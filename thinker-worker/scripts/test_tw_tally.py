"""tally: check outranks outcome; executed tier from cost; unlabeled, denied, headerless skipped.
Run: python test_tw_tally.py"""
import json
import tempfile
from pathlib import Path

import tw

H = "TW-Class: C-coding\nTW-Deliverable: x\nTW-Accept: x\nTW-Risk: none"
with tempfile.TemporaryDirectory() as home:
    home = Path(home)
    p = tw.receipts_path(home, "claude", "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"kind": "dispatch", "tool_use_id": "a", "decision": "admit", "header": H, "tier": "high"},
        {"kind": "cost", "tool_use_id": "a", "model": "claude-opus-5-5", "agent_type": "tw-worker-medium"},  # rewritten: ran medium
        {"kind": "outcome", "tool_use_id": "a", "accepted": True},
        {"kind": "dispatch", "tool_use_id": "b", "decision": "admit", "header": H, "tier": "high"},
        {"kind": "cost", "tool_use_id": "b", "model": "claude-opus-5-5", "agent_type": "tw-worker-high"},
        {"kind": "outcome", "tool_use_id": "b", "accepted": True},
        {"kind": "check", "tool_use_id": "b", "label": "fail"},                                          # check wins
        {"kind": "dispatch", "tool_use_id": "c", "decision": "admit", "header": H, "tier": "high"},       # unlabeled
        {"kind": "dispatch", "tool_use_id": "d", "decision": "deny", "header": H, "tier": "high"},
        {"kind": "outcome", "tool_use_id": "d", "accepted": True},                                       # denied
        {"kind": "dispatch", "tool_use_id": "e", "decision": "admit", "header": None, "tier": "high"},
        {"kind": "outcome", "tool_use_id": "e", "accepted": True},                                       # no header
        {"kind": "route", "tool_use_id": "a", "action": "rewrite"},                                      # old rows parse
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = tw.tally(home, "claude")
    assert got == [
        {"class": "C-coding", "model": "claude-opus-5-5", "tier": "high", "n": 1, "accepted": 0, "rate": 0.0},
        {"class": "C-coding", "model": "claude-opus-5-5", "tier": "medium", "n": 1, "accepted": 1, "rate": 1.0},
    ], got
print("PASS tally: check outranks outcome, executed tier from cost, unlabeled/denied/headerless skipped")
