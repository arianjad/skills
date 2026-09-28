"""tw.py codex: gate reuse, Codex-model admission per Claude role, codex exec flags, receipts with effective
model/effort (fake codex on PATH). Routing is pinned to a shadow copy of the shipped routes.json.
Run: python test_tw_codex.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from test_tw_hook import denied_kill, reap, run_main
from test_tw_receipt import AUTH, receipts

TW = str(Path(__file__).with_name("tw.py"))
HDR = "TW-Class: T3-moderate-reasoning\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\n"
REV = "TW-Role: independent-review\n" + AUTH + HDR + "review the thing"
WORK = "TW-Role: worker\n" + HDR + "build the thing"
LEAF = "TW-Role: leaf\n" + HDR + "list the things"
FAKE = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ["FAKE_HOME"])
(home / "call.json").write_text(json.dumps({"args": args, "stdin": sys.stdin.read()}), encoding="utf-8")
(home / "codex.pid").write_text(str(os.getpid()), encoding="utf-8")
import time; time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))  # a wedged codex (sandbox setup spinning)
tid = "0000-thread-1"
d = home / ".codex" / "sessions" / "2026" / "09" / "27"
d.mkdir(parents=True, exist_ok=True)
eff = os.environ.get("FAKE_EFFORT") or args[args.index("-c") + 1].split("=")[1]  # runtime may differ from request
(d / f"rollout-2026-09-27T00-00-00-{tid}.jsonl").write_text(
    json.dumps({"type": "turn_context", "payload": {"model": args[args.index("-m") + 1], "effort": eff}}) + "\n",
    encoding="utf-8")
Path(args[args.index("-o") + 1]).write_text("REPORT", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": tid}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


def run(home: Path, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, TW, *extra, "--home", str(home)], capture_output=True, text=True, env=env)


if __name__ == "__main__":
    # run_bounded feeds stdin through a pipe, not a temp-file handle: on Windows a file handle was lost through npm's
    # codex.CMD -> node shim ("No prompt provided via stdin", RaX session 2026-09-28) while a pipe survived. 1 MiB
    # exceeds any pipe buffer, so a writer that blocks before the child reads would hang here instead of passing.
    import tw
    probe = ("import os, stat, sys; d = sys.stdin.buffer.read(); "
             "print(stat.S_ISFIFO(os.fstat(0).st_mode), len(d), d[:3] == b'abc')")
    ran = tw.run_bounded([sys.executable, "-c", probe], None, b"abc" + b"x" * (1 << 20), 30)
    assert ran["code"] == 0 and ran["out"].split() == ["True", str(3 + (1 << 20)), "True"], ran
    ran = tw.run_bounded([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], None, None, 30)
    assert ran["out"].strip() == "''", ran                                            # None: still DEVNULL
    print("PASS codex stdin: pipe, 1 MiB without deadlock, None -> DEVNULL")
    with tempfile.TemporaryDirectory() as tmp:
        home, bin_ = Path(tmp), Path(tmp) / "bin"
        bin_.mkdir()
        (bin_ / "fake_codex.py").write_text(FAKE, encoding="utf-8")
        if os.name == "nt":
            (bin_ / "codex.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_codex.py" %*\n', encoding="utf-8")
        else:
            (bin_ / "codex").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_codex.py" "$@"\n')
            (bin_ / "codex").chmod(0o755)
        shipped = json.loads((Path(TW).parent.parent / "routes.json").read_text(encoding="utf-8"))
        shipped["router"]["classes"] = {"*": {"mode": "shadow", "explore": 0.0}}
        (home / "routes.json").write_text(json.dumps(shipped), encoding="utf-8")
        env = {**os.environ, "PATH": str(bin_) + os.pathsep + os.environ["PATH"], "FAKE_HOME": tmp,
               "TW_ROUTES": str(home / "routes.json")}
        brief = home / "brief.md"

        def codex(text: str, tier: str = "high", model: str = "gpt-6-astra", role: str = "independent-review",
                  session: str = "s1") -> subprocess.CompletedProcess:
            brief.write_text(text, encoding="utf-8")
            return run(home, env, "codex", "--session", session, "--role", role, "--tier", tier, "--model", model,
                       "--brief-file", str(brief), "--cd", tmp)

        r = codex(REV)
        assert r.returncode == 2 and "not activated" in r.stderr, r
        assert run(home, env, "activate", "--harness", "claude", "--session", "s1").returncode == 0

        env["FAKE_EFFORT"] = "xhigh"  # effective effort must come from the rollout, not echo the request
        r = codex(REV, "medium")
        env.pop("FAKE_EFFORT")
        assert r.returncode == 0, r
        out = json.loads(r.stdout.splitlines()[-1])
        assert out["tool_use_id"].startswith("codex-"), out
        assert (out["effective_model"], out["effective_effort"]) == ("gpt-6-astra", "xhigh"), out
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        a = call["args"]
        # -o is Codex's closing message only, always in state: a brief's deliverable path can never be clobbered
        last = Path(a[a.index("-o") + 1])
        assert last == home / ".thinker-worker" / "codex" / f"{out['tool_use_id']}.last.md", last
        assert "report" not in out and Path(out["last_message"]) == last and last.read_text(encoding="utf-8") == "REPORT"
        r = run(home, env, "codex", "--session", "s1", "--role", "independent-review", "--tier", "high", "--model",
                "gpt-6-astra", "--brief-file", str(brief), "--cd", tmp, "--out", str(home / "x.md"))
        assert r.returncode != 0 and "--out" in r.stderr, r                               # no --out option
        assert a[:2] == ["--search", "exec"] and a[a.index("-m") + 1] == "gpt-6-astra", a
        assert "model_reasoning_effort=medium" in a and a[a.index("-s") + 1] == "workspace-write", a
        assert call["stdin"].startswith("Review the assigned artifact") and call["stdin"].endswith(REV), call["stdin"][:80]

        rows = receipts(home, "claude")
        disp = [x for x in rows if x["kind"] == "dispatch"]
        cost = [x for x in rows if x["kind"] == "cost"]
        assert [x["decision"] for x in disp] == ["admit"] and disp[0]["requested_model"] == "gpt-6-astra", disp
        assert disp[0]["tool_name"] == "codex", disp
        assert cost[0]["tool_use_id"] == out["tool_use_id"] and cost[0]["input_tokens"] == 10, cost
        lab = run(home, env, "outcome", "--harness", "claude", "--session", "s1", "--tool-use-id", out["tool_use_id"],
                  "--accepted", "yes")
        assert lab.returncode == 0, lab
        assert [(x["tool_use_id"], x["accepted"]) for x in receipts(home, "claude") if x["kind"] == "outcome"] == \
            [(out["tool_use_id"], True)]
        env["FAKE_EXIT"] = "3"
        r = codex(REV)
        env.pop("FAKE_EXIT")
        assert r.returncode == 3 and json.loads(r.stdout.splitlines()[-1])["exit_code"] == 3, r  # failure propagates

        # Codex models reachable from Claude roles: in the Claude role's models AND in some Codex role's models
        for text, role, tier, model, head in ((WORK, "worker", "high", "gpt-6-sol", "Execute the coordinator's"),
                                              (LEAF, "leaf", "low", "gpt-6-luna", "Complete only the coordinator's"),
                                              (REV, "independent-review", "high", "gpt-6-sol", "Review the assigned")):
            r = codex(text, tier, model, role)
            assert r.returncode == 0, (model, role, r.stderr)
            out = json.loads(r.stdout.splitlines()[-1])
            call = json.loads((home / "call.json").read_text(encoding="utf-8"))
            assert call["args"][call["args"].index("-m") + 1] == model and out["effective_model"] == model, call
            assert f"model_reasoning_effort={tier}" in call["args"] and call["stdin"].startswith(head), call

        # TW-Check: stored on the dispatch row with --cd as its cwd; `outcome` alone runs it there
        r = codex(WORK.replace(HDR, HDR + "TW-Check: test -f call.json\n"), "high", "gpt-6-sol", "worker")
        assert r.returncode == 0, r.stderr
        disp = [x for x in receipts(home, "claude") if x["kind"] == "dispatch"][-1]
        assert (disp["check"], disp["cwd"]) == ("test -f call.json", str(Path(tmp).resolve())), disp
        lab = run(home, env, "outcome", "--harness", "claude", "--session", "s1", "--tool-use-id",
                  json.loads(r.stdout.splitlines()[-1])["tool_use_id"])
        assert lab.returncode == 0 and "pass" in lab.stdout, lab
        assert [x["label"] for x in receipts(home, "claude") if x["kind"] == "check"] == ["pass"], receipts(home, "claude")

        (home / "call.json").unlink()
        for text, tier, model, role, why in (
                (REV, "low", "gpt-6-astra", "independent-review", "outside"),
                (WORK, "high", "gpt-6-astra", "independent-review", "subagent_type must be tw-worker"),
                (REV.replace("TW-Scope: t\n", ""), "high", "gpt-6-astra", "independent-review",
                 "TW-Authorization and TW-Scope"),
                (WORK, "high", "gpt-6-luna", "worker", "model gpt-6-luna is not allowed for worker"),
                (LEAF, "low", "sonnet", "leaf", "model sonnet is not a Codex model")):
            r = codex(text, tier, model, role)
            assert r.returncode == 2 and why in r.stderr, (why, r.stderr)
        assert not (home / "call.json").exists(), "codex ran on a denied dispatch"
        assert [x["decision"] for x in receipts(home, "claude") if x["kind"] == "dispatch"][-2:] == ["deny", "deny"]

        # the router on the Codex path: no backend, explore 1.0, so a high dispatch is explored to medium
        def mode(m):
            doc = {**shipped, "router": {**shipped["router"], "backends": [], "classes": {"*": {"mode": m, "explore": 1.0}}}}
            (home / "routes.json").write_text(json.dumps(doc), encoding="utf-8")

        def last_route():
            return [x for x in receipts(home, "claude") if x["kind"] == "route"][-1]
        mode("shadow")
        r = codex(WORK + " shadow", "high", "gpt-6-sol", "worker")
        assert r.returncode == 0, r.stderr
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        row = last_route()
        assert "model_reasoning_effort=high" in call["args"], call["args"]                # shadow: coordinator tier
        assert (row["source"], row["mode"], row["action"], row["tool_use_id"]) == \
            ("explore", "shadow", None, json.loads(r.stdout.splitlines()[-1])["tool_use_id"]), row
        mode("advisory")
        (home / "call.json").unlink()
        r = codex(WORK + " advisory", "high", "gpt-6-sol", "worker")
        assert r.returncode == 2 and "--tier medium" in r.stderr, r.stderr                # advised: codex not run
        assert not (home / "call.json").exists() and last_route()["action"] == "advise", last_route()
        r = codex(WORK.replace(HDR, HDR + "TW-Override: keep high\n") + " override", "high", "gpt-6-sol", "worker")
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        assert r.returncode == 0 and "model_reasoning_effort=high" in call["args"], (r.stderr, call["args"])
        assert last_route()["action"] is None and last_route()["eligible"] is True, last_route()
        r = codex(WORK.replace(HDR, HDR + "TW-Pin: user asked for Sol high\n"), "high", "gpt-6-sol", "worker")
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        assert r.returncode == 0 and "model_reasoning_effort=high" in call["args"], (r.stderr, call["args"])
        assert last_route()["pinned"] is True and last_route()["source"] == "coordinator", last_route()
        mode("active")
        r = codex(WORK + " active", "high", "gpt-6-sol", "worker")
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        assert r.returncode == 0 and "model_reasoning_effort=medium" in call["args"], (r.stderr, call["args"])
        assert len(r.stdout.splitlines()) == 2 and "medium" in r.stdout.splitlines()[0], r.stdout   # one line says so
        assert last_route()["action"] == "rewrite" and last_route()["target_tier"] == "medium", last_route()
        # a codex-path rewrite is labeled by the rollout's effective effort: only a verified one joins promote's
        # router arm (the fake rollout echoes the requested effort unless FAKE_EFFORT says otherwise)
        ok_id = json.loads(r.stdout.splitlines()[-1])["tool_use_id"]
        env["FAKE_EFFORT"] = "high"
        r = codex(WORK + " active, runtime ignored the tier", "high", "gpt-6-sol", "worker")
        env.pop("FAKE_EFFORT")
        bad_id = json.loads(r.stdout.splitlines()[-1])["tool_use_id"]
        assert {x["tool_use_id"]: x["lost"] for x in receipts(home, "claude") if x["kind"] == "race"} == \
            {ok_id: False, bad_id: True}, receipts(home, "claude")
        for tid in (ok_id, bad_id):
            assert run(home, env, "outcome", "--harness", "claude", "--session", "s1", "--tool-use-id", tid,
                       "--accepted", "yes").returncode == 0
        p = run(home, env, "promote", "--harness", "claude", "--model", "gpt-6-sol")
        assert p.returncode == 0 and [json.loads(x)["n_router"] for x in p.stdout.splitlines()] == [1], p

        # review 2 F7 (design D14): the documented enable override (SKILL.md, verbatim; claude.md carries the same)
        # over the shipped routes.json lists the backend AND runs classes active (explore kept), so a gated pick
        # rewrites on the Codex path. The kev url is pointed at a local stub, never the real server.
        import re
        import tw
        from test_tw_backends import Stub, answer
        root = Path(TW).parent.parent
        enable = re.search(r"enable one with the user override, e\.g\. `([^`]+)`",
                           (root / "SKILL.md").read_text(encoding="utf-8")).group(1)
        assert f"`{enable}`" in (root / "references" / "claude.md").read_text(encoding="utf-8"), enable
        installed = tw.load_routes(root / "routes.json")
        ov = json.loads(enable)
        (home / "enable.json").write_text(enable, encoding="utf-8")
        merged = tw.merge_override(installed, home / "enable.json")
        assert merged["router"]["backends"] and tw.class_mode(merged, "C-coding") == \
            ("active", installed["router"]["classes"]["*"]["explore"]), (enable, merged["router"]["classes"])
        s = Stub(answer({"low": 0.05, "medium": 0.9, "high": 0.05, "xhigh": 0.0}, "medium"))
        try:
            for name in ov["router"]["backends"]:
                ov["router"][name] = {"url": s.url}
            (home / "enable.json").write_text(json.dumps(ov), encoding="utf-8")
            env2 = {k: v for k, v in env.items() if k != "TW_ROUTES"}
            env2["TW_ROUTES_OVERRIDE"] = str(home / "enable.json")
            coin = lambda b: tw.coin(tw.ticket(b)[0])
            text = next(b for b in (WORK + f" enabled {i}" for i in range(200)) if coin(b) >= 0.5)   # not explored
            brief.write_text(text, encoding="utf-8")
            (home / "call.json").unlink(missing_ok=True)
            r = run(home, env2, "codex", "--session", "s1", "--role", "worker", "--tier", "high", "--model",
                    "gpt-6-sol", "--brief-file", str(brief), "--cd", tmp)
            call = json.loads((home / "call.json").read_text(encoding="utf-8"))
            assert r.returncode == 0 and "model_reasoning_effort=medium" in call["args"], (r.stderr, call["args"])
            row = last_route()
            assert (row["source"], row["mode"], row["action"], row["target_tier"]) == \
                ("bayes", "active", "rewrite", "medium"), row
        finally:
            s.close()
        print("PASS F7 documented enable override: backend listed, classes active (explore kept), codex-path rewrite")

        # --cd at the user's home: Codex's Windows workspace-write sandbox ACL-walks every top-level home entry
        # (spun 90+ min, 2026-09-28). Refused before codex runs.
        (home / "call.json").unlink(missing_ok=True)
        brief.write_text(REV + " at home", encoding="utf-8")
        r = run(home, env, "codex", "--session", "s1", "--role", "independent-review", "--tier", "high", "--model",
                "gpt-6-astra", "--brief-file", str(brief), "--cd", str(Path.home()))
        assert r.returncode == 2 and "home directory" in r.stderr, r
        assert not (home / "call.json").exists(), "codex ran with --cd at home"

        # a wedged codex is killed at TW_CODEX_TIMEOUT: bounded return, nonzero, a cost row that says so
        import time
        env.update(FAKE_SLEEP="120", TW_CODEX_TIMEOUT="3")
        t0 = time.monotonic()
        r = codex(REV + " wedged")
        took = time.monotonic() - t0
        env.pop("FAKE_SLEEP"); env.pop("TW_CODEX_TIMEOUT")
        assert took < 30 and r.returncode != 0 and "timed out" in r.stderr, (took, r)
        cost = [x for x in receipts(home, "claude") if x["kind"] == "cost"][-1]
        assert cost["timed_out"] is True and cost["exit_code"] is None and cost["kill_failed"] is False, cost

        # R6 (Astra review finding 6): the kill fails (taskkill exit 1, as under Access denied). In process, so the
        # kill can be patched: bounded return, cost row kill_failed, and no "process tree killed" claim
        import contextlib
        import io
        saved = dict(os.environ)
        os.environ.update({k: env[k] for k in ("PATH", "FAKE_HOME", "TW_ROUTES")}, FAKE_SLEEP="60",
                          TW_CODEX_TIMEOUT="3")
        brief.write_text(REV + " wedged, kill denied", encoding="utf-8")
        err = io.StringIO()
        t0 = time.monotonic()
        try:
            with denied_kill(), contextlib.redirect_stderr(err):
                code, _ = run_main(["codex", "--home", str(home), "--session", "s1", "--role", "independent-review",
                                    "--tier", "high", "--model", "gpt-6-astra", "--brief-file", str(brief),
                                    "--cd", tmp])
        finally:
            took = time.monotonic() - t0
            os.environ.clear()
            os.environ.update(saved)
            reap(int((home / "codex.pid").read_text()))  # the fake codex this test launched
        cost = [x for x in receipts(home, "claude") if x["kind"] == "cost"][-1]
        assert took < 30 and code != 0, (took, code)
        assert cost["timed_out"] is True and cost["kill_failed"] is True, cost
        assert "timed out" in err.getvalue() and "process tree killed" not in err.getvalue(), err.getvalue()
    print("PASS R6 codex: a failed kill returns within the bound, cost row kill_failed, no 'process tree killed'")
    print("PASS codex: activation gate, decide() reuse (tier/role/scope), Codex-model admission per Claude role "
          "(Sol worker/review, Luna leaf; Luna worker and Sonnet denied), codex flags + stdin, receipts, outcome label")
