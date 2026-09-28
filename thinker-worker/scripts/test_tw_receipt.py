"""Every guarded dispatch leaves a receipt that is a labeled routing example: agent type + routing header,
never the brief body. Codex v2 ciphertext yields no header and no role.
Run: python test_tw_receipt.py"""
import json
import tempfile
from pathlib import Path

from test_tw_hook import envelope, pinned_routes, run_main

SESSION = "44444444-5555-6666-7777-888888888888"
HDR = "TW-Class: C-coding\nTW-Deliverable: patch\nTW-Accept: tests pass\nTW-Risk: destructive\n"
AUTH = "TW-Authorization: t\nTW-Scope: t\n"   # review and ideation briefs need both
W = "TW-Role: worker\n" + HDR + "x"
REV = "TW-Role: independent-review\n" + AUTH + HDR + "x"
BODY = "SECRET-BODY-TEXT do the thing"


def receipts(home, harness):
    files = list(Path(home).rglob(f"receipts/{harness}/*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(x) for x in files[0].read_text(encoding="utf-8").splitlines()]


def hook(home, harness, tool, inp, tool_use_id="toolu_x", **extra):
    env = envelope(SESSION, inp, tool, tool_use_id, **extra)
    return run_main(["hook", "--home", home, "--harness", harness, "--owner", "thinker-worker-v1"], json.dumps(env))


if __name__ == "__main__":
    pin = pinned_routes()  # shipped routing mode pinned out for the whole run
    pin.__enter__()
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-medium",
                                       "prompt": "TW-Role: worker\n" + HDR + BODY})
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high",
                                       "prompt": "TW-Role: worker\n" + BODY})
        admit, deny = [x for x in receipts(home, "claude") if x["kind"] == "dispatch"]  # T3 adds a route row
        assert admit["decision"] == "admit" and admit["kind"] == "dispatch", admit
        assert admit["subagent_type"] == "tw-worker-medium" and admit["tier"] == "medium", admit
        assert admit["header"] == ("TW-Class: C-coding\nTW-Deliverable: patch\n"
                                   "TW-Accept: tests pass\nTW-Risk: destructive"), admit
        assert deny["decision"] == "deny" and deny["header"] is None, deny
        assert deny["subagent_type"] == "tw-worker-high", deny
        raw = next(Path(home).rglob("receipts/claude/*.jsonl")).read_text(encoding="utf-8")
        assert "SECRET-BODY-TEXT" not in raw
        hook(home, "claude", "Agent", {"subagent_type": "tw-leaf-low",   # denied after the header parsed
                                       "prompt": "TW-Role: worker\n" + HDR + BODY})
        late = receipts(home, "claude")[-1]
        assert late["decision"] == "deny" and late["header"] == admit["header"], late

    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "codex", "--session", SESSION])
        hook(home, "codex", "collaborationspawn_agent", {"message": "<ciphertext>", "model": "gpt-6-astra",
                                                         "reasoning_effort": "high", "fork_turns": "none"})
        (rec,) = receipts(home, "codex")
        assert rec["decision"] == "admit" and rec["role"] is None and rec["header"] is None, rec
        assert rec["kind"] == "dispatch" and rec["subagent_type"] is None, rec
    with tempfile.TemporaryDirectory() as home:          # route rows: the model each dispatch asked for
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        idea = "TW-Role: ideation\n" + AUTH + HDR + BODY
        hook(home, "claude", "Agent", {"subagent_type": "tw-ideation-high", "model": "opus", "prompt": idea})
        hook(home, "claude", "Agent", {"subagent_type": "tw-ideation-high", "prompt": idea})
        rows = receipts(home, "claude")
        assert [r["decision"] for r in rows if r["kind"] == "dispatch"] == ["admit", "admit"], rows
        assert [r["agent_model"] for r in rows if r["kind"] == "route"] == ["opus", "fable"], rows
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "codex", "--session", SESSION])
        hook(home, "codex", "spawn_agent", {"message": "TW-Role: worker\n" + HDR + BODY, "model": "gpt-6-sol",
                                            "reasoning_effort": "high", "fork_turns": "none"})
        assert [r["agent_model"] for r in receipts(home, "codex") if r["kind"] == "route"] == ["gpt-6-sol"]
    print("PASS receipts carry kind, subagent_type, header; no body; v2 header/role null")
