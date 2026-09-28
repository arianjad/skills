"""tw.py codex: gate reuse, Codex-model admission per Claude role, codex exec flags, receipts with effective
model/effort (fake codex on PATH). Routing is pinned to a shadow copy of the shipped routes.json.
Run: python test_tw_codex.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TW = str(Path(__file__).with_name("tw.py"))
HDR = "TW-Class: T3-moderate-reasoning\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\n"
REV = "TW-Role: independent-review\nTW-Authorization: t\nTW-Scope: t\n" + HDR + "review the thing"
WORK = "TW-Role: worker\n" + HDR + "build the thing"
LEAF = "TW-Role: leaf\n" + HDR + "list the things"
FAKE = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ["FAKE_HOME"])
(home / "call.json").write_text(json.dumps({"args": args, "stdin": sys.stdin.read()}), encoding="utf-8")
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


def rows_of(home: Path) -> list:
    return [json.loads(x) for x in next((home / ".thinker-worker" / "receipts" / "claude").glob("*.jsonl"))
            .read_text(encoding="utf-8").splitlines()]


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
        assert Path(out["report"]).read_text(encoding="utf-8") == "REPORT"
        call = json.loads((home / "call.json").read_text(encoding="utf-8"))
        a = call["args"]
        assert a[:2] == ["--search", "exec"] and a[a.index("-m") + 1] == "gpt-6-astra", a
        assert "model_reasoning_effort=medium" in a and a[a.index("-s") + 1] == "workspace-write", a
        assert call["stdin"].startswith("Review the assigned artifact") and call["stdin"].endswith(REV), call["stdin"][:80]

        rows = rows_of(home)
        disp = [x for x in rows if x["kind"] == "dispatch"]
        cost = [x for x in rows if x["kind"] == "cost"]
        assert [x["decision"] for x in disp] == ["admit"] and disp[0]["requested_model"] == "gpt-6-astra", disp
        assert disp[0]["tool_name"] == "codex", disp
        assert cost[0]["tool_use_id"] == out["tool_use_id"] and cost[0]["input_tokens"] == 10, cost
        lab = run(home, env, "outcome", "--harness", "claude", "--session", "s1", "--tool-use-id", out["tool_use_id"],
                  "--accepted", "yes")
        assert lab.returncode == 0, lab
        assert [(x["tool_use_id"], x["accepted"]) for x in rows_of(home) if x["kind"] == "outcome"] == \
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
        assert [x["decision"] for x in rows_of(home) if x["kind"] == "dispatch"][-2:] == ["deny", "deny"]
    print("PASS codex: activation gate, decide() reuse (tier/role/scope), Codex-model admission per Claude role "
          "(Sol worker/review, Luna leaf; Luna worker and Sonnet denied), codex flags + stdin, receipts, outcome label")
