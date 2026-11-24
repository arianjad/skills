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

# Antigravity (agy) model-effort tally: real agy model IDs parse base model + effort suffix or explicit requested_effort
H_T4 = "TW-Class: T4-hard-reasoning\nTW-Deliverable: x\nTW-Accept: x\nTW-Risk: none"
H_R = "TW-Class: R-research\nTW-Deliverable: x\nTW-Accept: x\nTW-Risk: none"
with tempfile.TemporaryDirectory() as home:
    home = Path(home)
    agy_cases = [
        ("agy-1", H_T4, "gemini-4-carbon-high", None, True),
        ("agy-2", H_T4, "gemini-4-carbon-high", None, False),
        ("agy-3", H, "gemini-4-neon-xhigh", None, True),
        ("agy-4", H_T4, "claude-opus-5-5-high", None, True),
        ("agy-5", H_R, "gemini-3.8-flash-medium", None, True),
        ("agy-6", H_R, "gemini-4-hydrogen-low", None, True),
        ("agy-7", H_T4, "gemini-pro-orchestrator", None, True),
        ("agy-8", H_T4, "gemini-pro-orchestrator", "high", True),
        ("agy-9", H_T4, "gemini-pro-orchestrator-neon", None, True),
        ("agy-10", H, "gemini-4-neon-low", "xhigh", True),       # explicit requested_effort overrides suffix
        ("agy-11", H, None, None, True),                         # default model (unreported)
    ]
    for rid, header, reported_model, req_effort, accepted in agy_cases:
        rp = tw.receipts_path(home, "agy", rid)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"kind": "dispatch", "tool_use_id": rid, "decision": "admit", "header": header,
             "requested_model": reported_model, "tier": None},
            {"kind": "cost", "tool_use_id": rid, "via": "agy",
             "reported_model": reported_model, "requested_effort": req_effort},
            {"kind": "outcome", "tool_use_id": rid, "accepted": accepted},
        ]
        rp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got_agy = tw.tally(home, "agy")
    expected_agy = [
        {"class": "C-coding", "model": None, "tier": None, "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "C-coding", "model": "gemini-4-neon", "tier": "xhigh", "n": 2, "accepted": 2, "rate": 1.0},
        {"class": "R-research", "model": "gemini-3.8-flash", "tier": "medium", "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "R-research", "model": "gemini-4-hydrogen", "tier": "low", "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "T4-hard-reasoning", "model": "claude-opus-5-5", "tier": "high", "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "T4-hard-reasoning", "model": "gemini-4-carbon", "tier": "high", "n": 2, "accepted": 1, "rate": 0.5},
        {"class": "T4-hard-reasoning", "model": "gemini-pro-orchestrator", "tier": None, "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "T4-hard-reasoning", "model": "gemini-pro-orchestrator", "tier": "high", "n": 1, "accepted": 1, "rate": 1.0},
        {"class": "T4-hard-reasoning", "model": "gemini-pro-orchestrator-neon", "tier": None, "n": 1, "accepted": 1, "rate": 1.0},
    ]
    assert got_agy == expected_agy, f"got:\n{json.dumps(got_agy, indent=2)}\nwant:\n{json.dumps(expected_agy, indent=2)}"
print("PASS tally: check outranks outcome, executed tier from cost, agy model-effort parsing, unlabeled/denied/headerless skipped")
