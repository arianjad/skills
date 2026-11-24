"""Every guarded dispatch leaves a receipt that is a labeled routing example: model, effort + routing header,
never the brief body. Codex v2 ciphertext yields no header and no role.
Run: python test_tw_receipt.py"""
import json
import tempfile
from pathlib import Path

import tw
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
        hook(home, "claude", "Agent", {"subagent_type": "general-purpose", "model": "opus", "effort": "medium",
                                       "prompt": "TW-Role: worker\n" + HDR + BODY})
        hook(home, "claude", "Agent", {"subagent_type": "general-purpose", "model": "opus", "effort": "high",
                                       "prompt": "TW-Role: worker\n" + BODY})
        admit, deny = [x for x in receipts(home, "claude") if x["kind"] == "dispatch"]
        assert admit["decision"] == "admit" and admit["kind"] == "dispatch", admit
        assert admit["subagent_type"] == "general-purpose" and admit["tier"] == "medium", admit
        assert admit["requested_effort"] == "medium" and admit["role_text"] == "appended", admit
        assert admit["header"] == ("TW-Class: C-coding\nTW-Deliverable: patch\n"
                                   "TW-Accept: tests pass\nTW-Risk: destructive"), admit
        assert deny["decision"] == "deny" and deny["header"] is None, deny
        assert deny["requested_effort"] == "high" and deny["tier"] is None and deny["role_text"] is None, deny
        raw = next(Path(home).rglob("receipts/claude/*.jsonl")).read_text(encoding="utf-8")
        assert "SECRET-BODY-TEXT" not in raw
        hook(home, "claude", "Agent", {"subagent_type": "tw-leaf-low",   # denied after the header parsed
                                       "prompt": "TW-Role: worker\n" + HDR + BODY})
        late = receipts(home, "claude")[-1]
        assert late["decision"] == "deny" and late["header"] == admit["header"], late
        assert late["subagent_type"] == "tw-leaf-low" and "retired" in late["reason"], late   # the old name, as sent

    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "codex", "--session", SESSION])
        hook(home, "codex", "collaborationspawn_agent", {"message": "<ciphertext>", "model": "gpt-6-astra",
                                                         "reasoning_effort": "high", "fork_turns": "none"})
        (rec,) = receipts(home, "codex")
        assert rec["decision"] == "admit" and rec["role"] is None and rec["header"] is None, rec
        assert rec["kind"] == "dispatch" and rec["subagent_type"] is None, rec
    with tempfile.TemporaryDirectory() as home:          # dispatch rows: the model each dispatch asked for
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        idea = "TW-Role: ideation\n" + AUTH + HDR + BODY
        hook(home, "claude", "Agent", {"subagent_type": "general-purpose", "model": "opus", "effort": "high",
                                       "prompt": idea + "\n\n" + tw.role_text("ideation")})
        hook(home, "claude", "Agent", {"subagent_type": "general-purpose", "effort": "high", "prompt": idea})
        rows = receipts(home, "claude")
        assert [r["decision"] for r in rows if r["kind"] == "dispatch"] == ["admit", "deny"], rows   # model required
        assert rows[0]["role_text"] == "present", rows[0]
        assert [r["requested_model"] for r in rows] == ["opus", None], rows
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "codex", "--session", SESSION])
        hook(home, "codex", "spawn_agent", {"message": "TW-Role: worker\n" + HDR + BODY, "model": "gpt-6-sol",
                                            "reasoning_effort": "high", "fork_turns": "none"})
        assert [r["requested_model"] for r in receipts(home, "codex")] == ["gpt-6-sol"]
    print("PASS receipts carry kind, subagent_type, requested effort, role_text, header; no body; v2 header/role null")
