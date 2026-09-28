"""TW-Check: an optional brief header naming a shell command that checks the delivered artifact. The dispatch row
stores it in full with the dispatch cwd; `tw.py outcome` runs it and writes a pass/fail/unknown `check` row.
Run: python test_tw_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from test_tw_hook import pinned_routes, run_main
from test_tw_receipt import HDR, SESSION, receipts

PY = '"' + Path(sys.executable).as_posix() + '"'


def dispatch(home, brief, cwd, tid="toolu_x"):
    env = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION, "tool_use_id": tid,
           "cwd": cwd, "tool_input": {"subagent_type": "tw-worker-high", "prompt": brief}}
    return run_main(["hook", "--home", home, "--harness", "claude", "--owner", "thinker-worker-v1"], json.dumps(env))


def brief(check=None, extra=""):
    return "TW-Role: worker\n" + HDR + (f"TW-Check: {check}\n" if check is not None else "") + extra + "do it"


def denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


if __name__ == "__main__":
    pin = pinned_routes()
    pin.__enter__()
    # C1: the header key, stored on the dispatch row in full with the hook envelope's cwd
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        long = f"{PY} -c pass && " + "echo " + "y" * 600   # longer than the 256-char header cut
        code, out = dispatch(home, brief(long), home)
        assert code == 0 and not denied(out), out
        row = [r for r in receipts(home, "claude") if r["kind"] == "dispatch"][-1]
        assert row["decision"] == "admit" and row["check"] == long and row["cwd"] == home, row
        code, out = dispatch(home, brief(), home, "toolu_y")                   # optional: still admitted
        row = [r for r in receipts(home, "claude") if r["kind"] == "dispatch"][-1]
        assert not denied(out) and row["decision"] == "admit" and row["check"] is None, (out, row)
        for why, b in (("repeats TW-Check", brief("true", "TW-Check: false\n")),
                       ("TW-Check", brief("   ")),                            # empty value
                       ("over 1000", brief("x" * 1001))):
            code, out = dispatch(home, b, home, "toolu_z")
            assert denied(out) and why in out, (why, out)
        code, out = dispatch(home, brief("x" * 1000), home, "toolu_z")
        assert not denied(out), out
    print("PASS C1 TW-Check header: optional, once, non-empty, <= VALUE_MAX; stored in full with cwd")

    # C2: `tw.py outcome` runs the check once, in the recorded cwd, and writes a pass/fail/unknown row
    def outcome(home, tid, *extra):
        return run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                         "--tool-use-id", tid, *extra])

    def kinds(home, kind):
        return [r for r in receipts(home, "claude") if r["kind"] == kind]

    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        work = Path(home) / "work"
        work.mkdir()
        (work / "marker.txt").write_text("hi", encoding="utf-8")
        # pass: bash syntax (a for loop) in the dispatch cwd, on every OS
        dispatch(home, brief(f'for f in marker.txt; do test -f "$f" || exit 1; done && {PY} -c "print(42)"'),
                 str(work), "t_pass")
        code, out = outcome(home, "t_pass")
        c = kinds(home, "check")[-1]
        assert code == 0 and "pass" in out, (code, out)
        assert (c["tool_use_id"], c["label"], c["exit_code"], c["unknown_reason"]) == ("t_pass", "pass", 0, None), c
        assert "42" in c["tail"] and 0 <= c["seconds"] < 60, c
        assert not kinds(home, "outcome"), "no coordinator label without --accepted"
        # fail: nonzero exit; tail = last 400 chars of stdout + stderr
        dispatch(home, brief(f"{PY} -c \"import sys; print('a' * 1000, flush=True); "
                             f"sys.stderr.write('ERRTAIL'); sys.exit(3)\""), str(work), "t_fail")
        code, out = outcome(home, "t_fail")
        c = kinds(home, "check")[-1]
        assert code == 0 and "fail" in out and (c["label"], c["exit_code"]) == ("fail", 3), (out, c)
        assert len(c["tail"]) == 400 and c["tail"].endswith("ERRTAIL"), c["tail"][-40:]
        # --accepted with a check: the coordinator's (weak) row as before, plus a fresh check row
        assert outcome(home, "t_fail", "--accepted", "yes")[0] == 0
        assert kinds(home, "outcome")[-1]["accepted"] is True and len(kinds(home, "check")) == 3
        # --no-check: only the coordinator's row
        assert outcome(home, "t_fail", "--accepted", "no", "--cause", "brief", "--no-check")[0] == 0
        assert len(kinds(home, "check")) == 3 and kinds(home, "outcome")[-1]["cause"] == "brief"
        # nothing to record: exit 2, no rows
        dispatch(home, brief(), str(work), "t_none")
        n = len(receipts(home, "claude"))
        assert outcome(home, "t_none")[0] == 2                    # no --accepted and no TW-Check
        assert outcome(home, "t_fail", "--no-check")[0] == 2      # no --accepted and the check skipped
        assert outcome(home, "t_pass", "--cause", "tier")[0] == 2  # a cause still needs --accepted no
        assert len(receipts(home, "claude")) == n
        # unknown: timeout (the check's process tree is killed), missing cwd, no cwd, launch error
        pidf = (work / "pid.txt").as_posix()
        dispatch(home, brief(f"{PY} -c \"import os, time; open('{pidf}', 'w').write(str(os.getpid())); "
                             f"time.sleep(60)\""), str(work), "t_slow")
        t0 = time.monotonic()
        code, out = outcome(home, "t_slow", "--check-timeout", "3")
        c = kinds(home, "check")[-1]
        assert code == 0 and "unknown" in out and time.monotonic() - t0 < 30, (out, time.monotonic() - t0)
        assert (c["label"], c["unknown_reason"], c["exit_code"]) == ("unknown", "timeout", None), c
        pid = int(Path(pidf).read_text())
        if os.name == "nt":
            import subprocess
            alive = str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
                                               text=True).stdout
        else:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        assert not alive, f"timed-out check process {pid} survived"
        dispatch(home, brief("true"), str(Path(home) / "gone"), "t_gone")
        dispatch(home, brief("true"), None, "t_nocwd")
        for tid in ("t_gone", "t_nocwd"):
            assert outcome(home, tid)[0] == 0
            c = kinds(home, "check")[-1]
            assert (c["tool_use_id"], c["label"], c["unknown_reason"]) == (tid, "unknown", "cwd missing"), c
        import tw

        def boom(*_a, **_k):
            raise OSError("no shell")
        real, tw.subprocess.Popen = tw.subprocess.Popen, boom
        try:
            assert outcome(home, "t_pass")[0] == 0
        finally:
            tw.subprocess.Popen = real
        c = kinds(home, "check")[-1]
        assert c["label"] == "unknown" and c["unknown_reason"].startswith("launch error") and "no shell" in \
            c["unknown_reason"], c
    print("PASS C2 outcome runs TW-Check: pass/fail/unknown (timeout, cwd missing, launch error), tail, "
          "--accepted optional, --no-check, exit 2 when nothing to record")
