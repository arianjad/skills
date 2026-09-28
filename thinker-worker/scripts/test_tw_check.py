"""TW-Check: an optional brief header naming a shell command that checks the delivered artifact. The dispatch row
stores it in full with the dispatch cwd; `tw.py outcome` runs it and writes a pass/fail/unknown `check` row.
Run: python test_tw_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from test_tw_hook import denied_kill, pinned_routes, reap, run_main
from test_tw_receipt import HDR, SESSION, hook, receipts

PY = '"' + Path(sys.executable).as_posix() + '"'


def dispatch(home, brief, cwd, tid="toolu_x"):
    return hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": brief}, tid, cwd=cwd)


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
        assert c.get("kill_failed") is False, c
        dispatch(home, brief("true"), str(Path(home) / "gone"), "t_gone")
        dispatch(home, brief("true"), None, "t_nocwd")
        for tid in ("t_gone", "t_nocwd"):
            assert outcome(home, tid)[0] == 0
            c = kinds(home, "check")[-1]
            assert (c["tool_use_id"], c["label"], c["unknown_reason"]) == (tid, "unknown", "cwd missing"), c
        import tw

        def boom(argv, *a, **k):  # only the check's own launch fails; the --version probe runs
            if "-c" in argv:
                raise OSError("no shell")
            return real(argv, *a, **k)
        os.environ["TW_CHECK_BASH"] = tw.check_shell()[0]  # resolved before Popen breaks (git lookup uses it too)
        real, tw.subprocess.Popen = tw.subprocess.Popen, boom
        try:
            assert outcome(home, "t_pass")[0] == 0
        finally:
            tw.subprocess.Popen = real
            del os.environ["TW_CHECK_BASH"]
        c = kinds(home, "check")[-1]
        assert c["label"] == "unknown" and c["unknown_reason"].startswith("launch error") and "no shell" in \
            c["unknown_reason"], c
    print("PASS C2 outcome runs TW-Check: pass/fail/unknown (timeout, cwd missing, launch error), tail, "
          "--accepted optional, --no-check, exit 2 when nothing to record")

    # C5: shell policy (GitHub Actions `shell: bash`): bash --noprofile --norc -eo pipefail -c; on Windows the bash
    # of git's own install, never a PATH bash or cmd.exe; TW_CHECK_BASH overrides; the row records shell + version
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        work = Path(home) / "work"
        work.mkdir()
        # T1: pipefail — a failing command piped into cat is a fail, not masked by cat's exit 0
        dispatch(home, brief(f'{PY} -c "import sys; sys.exit(3)" | cat'), str(work), "t_pipe")
        assert outcome(home, "t_pipe")[0] == 0
        c = kinds(home, "check")[-1]
        assert (c["label"], c["exit_code"]) == ("fail", 3), c
        assert c["shell"] and c["shell_version"] and c["shell_version"].startswith("GNU bash"), c
        # T2: a bash planted first on PATH is not used on Windows
        fake = Path(home) / "fakebin"
        (fake / "src").mkdir(parents=True)
        marker = Path(home) / "fake_bash_ran.txt"
        src = fake / "src" / "bash"
        src.write_text("#!python\nimport os, sys\nopen(os.environ['FAKE_BASH_MARKER'], 'w').write(' '.join(sys.argv))\n",
                       encoding="utf-8")
        if os.name == "nt":
            from pip._vendor.distlib.scripts import ScriptMaker   # a real bash.exe (pip's script launcher)
            maker = ScriptMaker(str(fake / "src"), str(fake))
            maker.executable = sys.executable
            maker.make("bash")
            assert (fake / "bash.exe").is_file()
        dispatch(home, brief("true"), str(work), "t_path")
        old_path = os.environ["PATH"]
        os.environ["FAKE_BASH_MARKER"] = str(marker)
        os.environ["PATH"] = str(fake) + os.pathsep + old_path
        try:
            assert outcome(home, "t_path")[0] == 0
            c = kinds(home, "check")[-1]
            if os.name == "nt":
                assert not marker.exists(), "the PATH-planted fake bash ran"
                assert c["label"] == "pass" and c["shell"].lower().endswith(("usr\\bin\\bash.exe", "\\bin\\bash.exe")), c
                # no git on PATH: unknown, never cmd.exe or the PATH bash
                os.environ["PATH"] = str(fake)
                assert outcome(home, "t_path")[0] == 0
                c = kinds(home, "check")[-1]
                assert (c["label"], c["unknown_reason"]) == ("unknown", "no git bash"), c
                assert not marker.exists(), "the PATH-planted fake bash ran"
        finally:
            os.environ["PATH"] = old_path
        # TW_CHECK_BASH naming a missing file: unknown, no fallback
        os.environ["TW_CHECK_BASH"] = str(Path(home) / "nope" / "bash.exe")
        try:
            assert outcome(home, "t_path")[0] == 0
        finally:
            del os.environ["TW_CHECK_BASH"]
        c = kinds(home, "check")[-1]
        assert c["label"] == "unknown" and "TW_CHECK_BASH" in c["unknown_reason"], c
    print("PASS C5 check shell: -eo pipefail (piped exit 3 fails), git's bash not a PATH bash (Windows), "
          "no git -> unknown, TW_CHECK_BASH missing -> unknown, row shell + shell_version")

    # R6 (Astra review finding 6): a failed kill (taskkill exit 1, as under Access denied) still returns within the
    # bound, and the row says kill_failed instead of implying the tree died
    import tw
    with tempfile.TemporaryDirectory() as work:
        pidf = (Path(work) / "pid.txt").as_posix()
        t0 = time.monotonic()
        try:
            with denied_kill():
                c = tw.run_check(f"{PY} -c \"import os, time; open('{pidf}', 'w').write(str(os.getpid())); "
                                 f"time.sleep(60)\"", work, 1)
        finally:
            took = time.monotonic() - t0
            if Path(pidf).exists():  # the sleeper this test launched
                reap(int(Path(pidf).read_text()))
        assert took < 30, took
        assert (c["label"], c["unknown_reason"], c.get("kill_failed")) == ("unknown", "timeout", True), c
    print("PASS R6 failed kill: bounded return, kill_failed true")

    # R7 (Astra review finding 7): a shell without verified pipefail never labels. Git's sh.exe (Astra's
    # counterexample: `false | cat` recorded pass under `sh -e`) and a non-bash shell named sh
    bash = tw.check_shell()[0]
    with tempfile.TemporaryDirectory() as work:
        cases = []
        sibling = Path(bash).with_name("sh.exe" if os.name == "nt" else "sh")
        if sibling.is_file():
            cases.append(("git sh", str(sibling)))
        fake = Path(work) / "fakebin"
        (fake / "src").mkdir(parents=True)
        marker = Path(work) / "fake_sh_ran.txt"
        (fake / "src" / "sh").write_text("#!python\nimport sys\nif '-c' in sys.argv:\n    open(" + repr(str(marker))
                                         + ", 'w').write(' '.join(sys.argv))\nelse:\n    print('fake sh 0.1')\n",
                                         encoding="utf-8")
        from pip._vendor.distlib.scripts import ScriptMaker
        maker = ScriptMaker(str(fake / "src"), str(fake))
        maker.executable = sys.executable
        made = maker.make("sh")
        cases.append(("non-bash sh", made[0]))
        for name, shell in cases:
            os.environ["TW_CHECK_BASH"] = shell
            try:
                c = tw.run_check("false | cat", work, 30)
            finally:
                del os.environ["TW_CHECK_BASH"]
            assert c["label"] != "pass", (name, c)
            if name == "non-bash sh":
                assert (c["label"], c["unknown_reason"]) == ("unknown", "no pipefail shell"), (name, c)
                assert not marker.exists(), "the non-bash shell was run"
        assert len(cases) == 2 or os.name != "nt", cases   # Git for Windows ships usr/bin/sh.exe beside bash.exe
    print("PASS R7 no verified pipefail shell -> never pass; a non-bash shell -> unknown, not run")
