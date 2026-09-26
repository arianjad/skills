"""Ideation role (divergent, dreamer) beside independent review (convergent). Separate activation,
same authorization/scope lines. Claude: thinker-worker-dreamer on fable; opus only with a stated reason.
Codex: Astra for both; review/ideation effort may be omitted (inherited); v2 cannot tell them apart.
Run: python test_tw_ideation.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main

HDR = "TW-Class: R-research\nTW-Deliverable: ranked directions\nTW-Accept: each has a kill test\nTW-Risk: none\n"
AUTH = "TW-Authorization: t\nTW-Scope: t\n"
IDEA = "TW-Role: ideation\n" + AUTH + HDR + "task"
OLD = {"review": True, "luna": False, "sonnet": False}          # record written before ideation existed
ON = {"review": False, "luna": False, "sonnet": False, "ideation": True}


def claude(brief, st="thinker-worker-dreamer", model="fable", rec=ON):
    return tw.decide("claude", {"tool_input": {"subagent_type": st, "model": model, "prompt": brief}}, rec)


def codex(brief, model, effort=None, rec=ON, v2=False):
    inp = {"message": brief, "model": model, "fork_turns": "none"}
    if effort:
        inp["reasoning_effort"] = effort
    return tw.decide("codex", {"tool_name": "collaborationspawn_agent" if v2 else "spawn_agent",
                               "tool_input": inp}, rec)


CASES = [
    ("claude ideation admitted", claude(IDEA)[0], True),
    ("old record denies ideation", claude(IDEA, rec=OLD)[0], False),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""))[0], False),
    ("ideation must use dreamer", claude(IDEA, st="thinker-worker-fable-review")[0], False),
    ("ideation not via miner", claude(IDEA, st="effortmining:miner-high")[0], False),
    ("opus without reason", claude(IDEA, model="opus")[0], False),
    ("opus, fable exhausted", claude(IDEA.replace(HDR, HDR + "TW-Opus-Reason: fable-exhausted\n"), model="opus")[0], True),
    ("opus, user request", claude(IDEA.replace(HDR, HDR + "TW-Opus-Reason: user-request\n"), model="opus")[0], True),
    ("opus, other reason", claude(IDEA.replace(HDR, HDR + "TW-Opus-Reason: cheaper\n"), model="opus")[0], False),
    ("sonnet ideation", claude(IDEA, model="sonnet")[0], False),
    ("codex ideation astra, effort omitted", codex(IDEA, "gpt-6-astra")[0], True),
    ("codex ideation astra, effort given", codex(IDEA, "gpt-6-astra", "high")[0], True),
    ("codex ideation on sol", codex(IDEA, "gpt-6-sol", "high")[0], False),
    ("codex review astra, effort omitted",
     codex(IDEA.replace("ideation", "independent-review"), "gpt-6-astra", rec=OLD)[0], True),
    ("codex worker still needs effort",
     codex("TW-Role: worker\n" + HDR + "x", "gpt-6-sol")[0], False),
    ("v2 astra, ideation only", codex("<cipher>", "gpt-6-astra", v2=True)[:3:2], (True, None)),
    ("v2 astra, review only", codex("<cipher>", "gpt-6-astra", v2=True, rec=OLD)[:3:2], (True, None)),
    ("v2 astra, neither", codex("<cipher>", "gpt-6-astra", v2=True,
                                rec={"review": False, "luna": False, "ideation": False})[0], False),
]

if __name__ == "__main__":
    bad = [(name, got, want) for name, got, want in CASES if got != want]
    for b in bad:
        print("FAIL", b)
    assert not bad

    # CLI: --ideation lands in the activation record and status.
    session = "33333333-4444-5555-6666-777777777777"
    with tempfile.TemporaryDirectory() as home:
        code, _ = run_main(["activate", "--home", home, "--harness", "claude", "--session", session, "--ideation"])
        assert code == 0, code
        record = tw.activation(Path(home), "claude", session)
        assert record["ideation"] is True, record
        code, out = run_main(["status", "--home", home, "--harness", "claude", "--session", session])
        assert json.loads(out)["ideation"] is True, out
    print(f"PASS {len(CASES)} ideation cases + activate/status CLI")
