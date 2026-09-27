"""Act modes: shadow silent; advisory denies with the router's pick; active rewrites subagent_type unless the
guard or a lost-race flag holds it to advisory; override (header lines only), per-flag risk floor (the pick is
raised to the highest flag's floor, recorded as target_tier; no action at or above the coordinator's tier), cutoff,
exploration; a failure inside act() leaves the dispatch admitted and the route row recorded with guard
"act error: <Exc>" and target_tier the raw pick.
Run: python test_tw_act.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import HDR, SESSION, receipts

BASE = tw.load_routes()


def run(mode, pick="low", conf=0.95, explore=0.0, brief_extra="", guard=None, flag=False, risk="none",
        st="tw-worker-high", then=None, backends=("stub",)):
    """One dispatch in a fresh temp home (plus `then=(st, brief_extra)`, a re-dispatch in the same home).
    Returns (hookSpecificOutput | None, last non-dispatch row). The real guard is never consulted."""
    routes = json.loads(json.dumps(BASE))
    routes["router"].update(backends=list(backends), classes={"*": {"mode": mode, "explore": explore}})
    tw.BACKENDS["stub"] = lambda *a: {"tier": pick, "probs": {pick: 1.0}, "confidence": conf, "body_chars_sent": 0}
    tw.load_routes = lambda path=None: routes
    tw.competing_agent_writer = guard if callable(guard) else (lambda home: guard)
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        if flag:
            tw.advisory_flag(Path(home), "claude", SESSION).write_text("", encoding="utf-8")
        for s, extra in [(st, brief_extra)] + ([then] if then else []):
            brief = "TW-Role: worker\n" + HDR.replace("TW-Risk: destructive", f"TW-Risk: {risk}") + extra + "x"
            env = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION,
                   "tool_use_id": "toolu_x", "tool_input": {"subagent_type": s, "prompt": brief}}
            _, out = run_main(["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))
        rows = receipts(home, "claude")
        assert rows[-2]["kind"] == "dispatch" and rows[-2]["decision"] == "admit", rows
        return (json.loads(out)["hookSpecificOutput"] if out else None), rows[-1]


def boom(home):
    raise RuntimeError("simulated act bug")


if __name__ == "__main__":
    out, row = run("shadow")
    assert out is None and row["action"] is None and row["router_tier"] == "low"
    # eligible (would the router act?) is recorded in shadow too: the promote coordinator arm matches on it
    assert row["eligible"] is True, row                                         # confident and lower
    assert run("shadow", conf=0.5)[1]["eligible"] is False                      # under cutoff
    assert run("shadow", conf=0.1, explore=1.0)[1]["eligible"] is True          # explored lower
    assert run("shadow", pick="high")[1]["eligible"] is False                   # agrees with the coordinator
    row = run("shadow", pick="bogus")[1]                                        # invalid -> coordinator fallback
    assert row["source"] == "coordinator" and row["eligible"] is False, row
    out, row = run("advisory")
    assert out["permissionDecision"] == "deny" and "tw-worker-low" in out["permissionDecisionReason"]
    assert row["action"] == "advise"
    assert run("advisory", brief_extra="TW-Override: needs high\n")[0] is None
    late = "pad\n" * 15 + "TW-Override: in the body\n"                  # brief line 20: not a header line
    assert run("advisory", brief_extra=late)[0]["permissionDecision"] == "deny"
    assert run("advisory", conf=0.5)[0] is None                          # under cutoff
    assert run("advisory", risk="physics")[0] is None                    # floor high = coordinator's high
    out, row = run("advisory", risk="external")                          # floor medium: advised to medium
    assert "tw-worker-medium" in out["permissionDecisionReason"] and row["router_tier"] == "low", (out, row)
    assert (row["target_tier"], row["router_agent"]) == ("medium", "tw-worker-medium"), row   # floored target
    assert run("advisory", risk="destructive,physics")[0] is None        # the highest flag wins
    assert run("advisory", pick="medium", risk="physics")[0] is None     # a pick below the floor is raised
    assert run("advisory", risk="physics")[1]["eligible"] is False       # floored rows stay out of promote
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-xhigh", risk="physics")[0]["permissionDecisionReason"].count("tw-worker-high") == 1
    # re-dispatch of an advised brief hits the cached decision: override or taking the pick both admit
    out, row = run("advisory", then=("tw-worker-high", "TW-Override: needs high\n"))
    assert out is None and row["source"] == "cached:stub" and row["action"] is None
    out, row = run("advisory", then=("tw-worker-low", ""))
    assert out is None and row["source"] == "cached:stub" and row["action"] is None
    out, row = run("active")
    assert out["permissionDecision"] == "allow" and out["updatedInput"]["subagent_type"] == "tw-worker-low"
    assert out["updatedInput"]["prompt"].startswith("TW-Role: worker") and row["action"] == "rewrite"
    assert out["additionalContext"] == ("thinker-worker: dispatched as tw-worker-low instead of tw-worker-high "
                                        "(router p=0.95); judge the result at that tier"), out
    assert row["eligible"] is True, row
    out, row = run("active", guard="context-mode PreToolUse Agent hook is registered")
    assert out["permissionDecision"] == "deny" and row["action"] == "advise" and row["guard"].startswith("context-mode")
    out, row = run("active", flag=True)
    assert out["permissionDecision"] == "deny" and "lost race" in row["guard"]
    assert run("advisory", conf=0.1, explore=1.0)[0]["permissionDecisionReason"].count("exploration") == 1
    assert run("advisory", conf=0.1, explore=0.0)[0] is None
    assert run("advisory", pick="xhigh", conf=0.1, explore=1.0)[0] is None   # exploration only goes lower
    out, row = run("active", guard=boom)          # act() raises: fail open, the route row is kept, no error row
    assert out is None and row["kind"] == "route" and row["action"] is None, row
    assert row["guard"] == "act error: RuntimeError" and row["router_tier"] == "low" and row["target_tier"] == "low", row
    out, row = run("advisory", explore=1.0, backends=())            # no backend: explore one tier below
    assert "tw-worker-medium" in out["permissionDecisionReason"] and "exploration" in out["permissionDecisionReason"]
    assert row["source"] == "explore" and row["router_tier"] == "medium" and row["eligible"] is True, row
    assert row["explore"] == 1.0, row                                                      # ε recorded
    out, row = run("advisory", explore=1e-9, backends=())           # coin >= ε: the phase-2 control shape
    assert out is None and row["source"] == "coordinator" and row["explore"] == 1e-9, row
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-medium", ""))   # take the pick
    assert out is None and row["source"] == "cached:explore" and row["explore"] == 0.0, row
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-high", ""))     # rejected, back to high
    assert out is None and row["source"] == "cached:explore", row
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-low")[0] is None       # nothing below low
    out, row = run("shadow", explore=1.0, backends=())              # computed in shadow, not acted on
    assert out is None and row["source"] == "explore" and row["action"] is None, row
    print("PASS act: shadow, advisory, override, cutoff, risk floor, cached re-dispatch, active rewrite, "
          "guard/flag hold, exploration, fail-open")
