"""tw.py claude: Codex (or any shell) -> a guarded native Claude dispatch through a `claude -p` relay session.
A fake `claude` on PATH plays Claude Code: it runs the real `tw.py hook` on the Agent call the relay prompt asks for,
and on admit writes the child's meta.json + transcript. Routing is pinned to a shadow copy of the shipped routes.json.
Run: python test_tw_claude.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from test_tw_codex import TW, run
HDR = "TW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\n"
WORK = "TW-Role: worker\n" + HDR + "print 42"
FAKE = r'''
import json, os, re, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ["FAKE_HOME"])
relay = sys.stdin.read()
(home / "call.json").write_text(json.dumps({"args": args, "stdin": relay}), encoding="utf-8")
session = args[args.index("--session-id") + 1]
agent = re.search(r"^subagent_type: (\S+)$", relay, re.M).group(1)
model = re.search(r"^model: (\S+)$", relay, re.M)
brief = re.search(r"^BRIEF-BEGIN\n(.*)\nBRIEF-END$", relay, re.M | re.S).group(1)
inp = {"subagent_type": agent, "prompt": brief, "description": "d"}
if model:
    inp["model"] = model.group(1)
env = {"session_id": session, "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_fake1",
       "cwd": os.getcwd(), "tool_input": inp}
hook = subprocess.run([sys.executable, os.environ["TW"], "hook", "--home", str(home), "--harness", "claude",
                       "--owner", "thinker-worker-v1"], input=json.dumps(env), capture_output=True, text=True)
out = json.loads(hook.stdout) if hook.stdout.strip() else {}
spec = out.get("hookSpecificOutput", {})
if spec.get("permissionDecision") == "deny":
    print("DENIED: " + spec["permissionDecisionReason"])
    sys.exit(0)
d = home / ".claude" / "projects" / "C--fake" / session / "subagents"
d.mkdir(parents=True, exist_ok=True)
(d / "agent-a1.meta.json").write_text(json.dumps({"agentType": agent, "toolUseId": "toolu_fake1"}), encoding="utf-8")
row = {"type": "assistant", "effort": agent.rsplit("-", 1)[1],
       "message": {"id": "m1", "model": os.environ.get("FAKE_MODEL", "claude-opus-5-5"),
                   "usage": {"input_tokens": 5, "output_tokens": 2}, "content": [{"type": "text", "text": "42"}]}}
(d / "agent-a1.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
print("42")
'''


def receipts(home: Path) -> list[dict]:
    files = list((home / ".thinker-worker" / "receipts" / "claude").glob("*.jsonl"))
    return [json.loads(x) for f in files for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        home, bin_ = Path(tmp), Path(tmp) / "bin"
        bin_.mkdir()
        (bin_ / "fake_claude.py").write_text(FAKE, encoding="utf-8")
        if os.name == "nt":
            (bin_ / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\n', encoding="utf-8")
        else:
            (bin_ / "claude").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_claude.py" "$@"\n')
            (bin_ / "claude").chmod(0o755)
        shipped = json.loads((Path(TW).parent.parent / "routes.json").read_text(encoding="utf-8"))
        shipped["router"]["classes"] = {"*": {"mode": "shadow", "explore": 0.0}}
        (home / "routes.json").write_text(json.dumps(shipped), encoding="utf-8")
        env = {**os.environ, "PATH": str(bin_) + os.pathsep + os.environ["PATH"], "FAKE_HOME": tmp, "TW": TW,
               "TW_ROUTES": str(home / "routes.json")}
        brief = home / "brief.md"

        def claude(text: str, tier: str = "low", role: str = "worker", *extra: str) -> subprocess.CompletedProcess:
            brief.write_text(text, encoding="utf-8")
            return run(home, env, "claude", "--role", role, "--tier", tier, "--brief-file", str(brief),
                       "--cd", tmp, *extra)

        # happy path: fresh activated session, relay argv, receipts, executed model/effort evidence
        r = claude(WORK)
        assert r.returncode == 0, r
        out = json.loads(r.stdout.strip().splitlines()[-1])
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        a = call["args"]
        assert a[0] == "-p" and a[a.index("--session-id") + 1] == out["session_id"], a
        assert a[a.index("--model") + 1] == "sonnet" and a[a.index("--effort") + 1] == "low", a
        assert a[a.index("--permission-mode") + 1] == "bypassPermissions", a  # -p cannot answer a prompt
        assert "subagent_type: tw-worker-low" in call["stdin"] and "\nmodel:" not in call["stdin"], call["stdin"]
        assert out["tool_use_id"] == "toolu_fake1" and out["decision"] == "admit", out
        assert (out["agent_type"], out["effective_model"], out["effective_effort"]) == \
            ("tw-worker-low", "claude-opus-5-5", "low"), out
        assert Path(out["last_message"]).read_text(encoding="utf-8").strip() == "42", out
        rows = [x for x in receipts(home) if x.get("session_id") == out["session_id"]]
        assert [x["kind"] for x in rows if x["kind"] in ("dispatch", "cost")] == ["dispatch", "cost"], rows
        print("PASS claude: relay argv, fresh activated session, dispatch + cost receipts, executed model/effort")

        # gate failures cost no relay session: bad brief, Codex model, tier outside the model's tiers
        for text, tier, extra, why in ((HDR + "no role line", "low", (), "first brief line"),
                                       (WORK, "low", ("--model", "gpt-6.1-sol"), "Codex model"),
                                       (WORK, "low", ("--model", "sonnet"), "tier low is outside")):
            (home / "call.json").unlink(missing_ok=True)
            r = claude(text, tier, "worker", *extra)
            assert r.returncode == 2 and why in r.stderr and not (home / "call.json").exists(), (why, r)
        print("PASS claude: pre-gate denials exit 2 without launching claude")

        # per-call model reaches the relay as its own line; the child's executed model is reported, not the alias
        env["FAKE_MODEL"] = "claude-sonnet-5-5"
        r = claude(WORK, "high", "worker", "--model", "sonnet")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert r.returncode == 0 and "\nmodel: sonnet\n" in json.loads((home / "call.json").read_text())["stdin"], r
        assert (out["effective_model"], out["effective_effort"]) == ("claude-sonnet-5-5", "high"), out
        print("PASS claude: per-call model forwarded; executed model reported")

        # a denial inside the relay (router advice in advisory mode) exits 2 and names it; nothing ran
        shipped["router"]["classes"] = {"*": {"mode": "advisory", "explore": 1.0}}
        (home / "advisory.json").write_text(json.dumps(shipped), encoding="utf-8")
        env["TW_ROUTES"] = str(home / "advisory.json")
        r = claude(WORK, "high")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert r.returncode == 2 and out["decision"] == "advise" and out["effective_model"] is None, r
        assert "DENIED" in r.stderr and "exploration" in r.stderr, r.stderr
        print("PASS claude: relay-side denial (router advice) exits 2 with the denial text")

        # spool: a sandboxed thread drops a job file; one pass outside the sandbox runs it and writes a result file
        env["TW_ROUTES"] = str(home / "routes.json")
        inbox, done = home / ".thinker-worker" / "spool" / "inbox", home / ".thinker-worker" / "spool" / "done"
        inbox.mkdir(parents=True)
        brief.write_text(WORK, encoding="utf-8")
        (inbox / "job1.json").write_text(json.dumps({"role": "worker", "tier": "low", "brief_file": str(brief),
                                                     "cd": tmp}), encoding="utf-8")
        (inbox / "bad.json").write_text("{not json", encoding="utf-8")
        (inbox / "job2.json.tmp").write_text("half-written", encoding="utf-8")       # not a job until renamed
        r = run(home, env, "spool", "--once")
        assert r.returncode == 0, r
        res = json.loads((done / "job1.result.json").read_text(encoding="utf-8"))
        assert res["exit_code"] == 0 and res["result"]["effective_model"] == "claude-sonnet-5-5", res
        assert res["result"]["agent_type"] == "tw-worker-low", res
        bad = json.loads((done / "bad.result.json").read_text(encoding="utf-8"))
        assert bad["exit_code"] == 2 and bad["result"] is None and bad["error"], bad
        assert sorted(p.name for p in inbox.iterdir()) == ["job2.json.tmp"], list(inbox.iterdir())
        (home / "call.json").unlink()
        r = run(home, env, "spool", "--once")                                          # consumed exactly once
        assert r.returncode == 0 and not (home / "call.json").exists(), r
        print("PASS spool: job -> result file, malformed job -> error result, .tmp ignored, each job runs once")
