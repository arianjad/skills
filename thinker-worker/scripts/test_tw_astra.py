"""tw.py astra: gate reuse, codex exec flags, receipts with effective model/effort (fake codex on PATH)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TW = str(Path(__file__).with_name("tw.py"))
HDR = "TW-Class: T3-moderate-reasoning\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\n"
REV = "TW-Role: independent-review\nTW-Authorization: t\nTW-Scope: t\n" + HDR + "review the thing"
FAKE = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ["FAKE_HOME"])
(home / "call.json").write_text(json.dumps({"args": args, "stdin": sys.stdin.read()}), encoding="utf-8")
tid = "0000-thread-1"
d = home / ".codex" / "sessions" / "2026" / "09" / "27"
d.mkdir(parents=True, exist_ok=True)
eff = args[args.index("-c") + 1].split("=")[1]
(d / f"rollout-2026-09-27T00-00-00-{tid}.jsonl").write_text(
    json.dumps({"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": eff}}) + "\n", encoding="utf-8")
Path(args[args.index("-o") + 1]).write_text("REPORT", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": tid}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}))
'''


def run(home: Path, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, TW, *extra, "--home", str(home)], capture_output=True, text=True, env=env)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        home, bin_ = Path(tmp), Path(tmp) / "bin"
        bin_.mkdir()
        (bin_ / "fake_codex.py").write_text(FAKE, encoding="utf-8")
        if os.name == "nt":
            (bin_ / "codex.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_codex.py" %*\n', encoding="utf-8")
        else:
            (bin_ / "codex").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_codex.py" "$@"\n')
            (bin_ / "codex").chmod(0o755)
        env = {**os.environ, "PATH": str(bin_) + os.pathsep + os.environ["PATH"], "FAKE_HOME": tmp}
        env.pop("TW_ROUTES", None)
        brief = home / "brief.md"

        def astra(text: str, tier: str = "high", session: str = "s1") -> subprocess.CompletedProcess:
            brief.write_text(text, encoding="utf-8")
            return run(home, env, "astra", "--session", session, "--role", "independent-review", "--tier", tier,
                       "--brief-file", str(brief), "--cd", tmp)

        r = astra(REV)
        assert r.returncode == 2 and "not activated" in r.stderr, r
        assert run(home, env, "activate", "--harness", "claude", "--session", "s1").returncode == 0

        r = astra(REV, "medium")
        assert r.returncode == 0, r
        out = json.loads(r.stdout)
        assert (out["effective_model"], out["effective_effort"]) == ("gpt-6-astra", "medium"), out
        assert Path(out["report"]).read_text(encoding="utf-8") == "REPORT"
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        a = call["args"]
        assert a[:2] == ["--search", "exec"] and a[a.index("-m") + 1] == "gpt-6-astra", a
        assert "model_reasoning_effort=medium" in a and a[a.index("-s") + 1] == "workspace-write", a
        assert call["stdin"].startswith("Review the assigned artifact") and call["stdin"].endswith(REV), call["stdin"][:80]

        rows = [json.loads(x) for x in next((home / ".thinker-worker" / "receipts" / "claude").glob("*.jsonl"))
                .read_text(encoding="utf-8").splitlines()]
        disp = [x for x in rows if x["kind"] == "dispatch"]
        cost = [x for x in rows if x["kind"] == "cost"]
        assert [x["decision"] for x in disp] == ["admit"] and disp[0]["requested_model"] == "gpt-6-astra", disp
        assert cost[0]["tool_use_id"] == out["tool_use_id"] and cost[0]["input_tokens"] == 10, cost
        lab = run(home, env, "outcome", "--harness", "claude", "--session", "s1", "--tool-use-id", out["tool_use_id"],
                  "--accepted", "yes")
        assert lab.returncode == 0, lab

        (home / "call.json").unlink()
        for text, tier, why in ((REV, "low", "outside"),
                                ("TW-Role: worker\n" + HDR + "x", "high", "subagent_type must be tw-worker"),
                                (REV.replace("TW-Scope: t\n", ""), "high", "TW-Authorization and TW-Scope")):
            r = astra(text, tier)
            assert r.returncode == 2 and why in r.stderr, (why, r.stderr)
        assert not (home / "call.json").exists(), "codex ran on a denied dispatch"
    print("PASS astra: activation gate, decide() reuse (tier/role/scope), codex flags + stdin, receipts, outcome label")
