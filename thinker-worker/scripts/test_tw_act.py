"""Act modes: shadow silent; advisory denies with the router's pick; active rewrites subagent_type unless the
guard or a lost-race flag holds it to advisory; override, risk floor, cutoff, exploration; a failure inside
act() leaves the dispatch admitted with an error row.
Run: python test_tw_act.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import HDR, SESSION, receipts

BASE = tw.load_routes()


def run(mode, pick="low", conf=0.95, explore=0.0, brief_extra="", guard=None, flag=False, risk="none",
        st="tw-worker-high", then=None):
    """One dispatch in a fresh temp home (plus `then=(st, brief_extra)`, a re-dispatch in the same home).
    Returns (hookSpecificOutput | None, last non-dispatch row). The real guard is never consulted."""
    routes = json.loads(json.dumps(BASE))
    routes["router"].update(backends=["stub"], classes={"*": {"mode": mode, "explore": explore}})
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
    out, row = run("advisory")
    assert out["permissionDecision"] == "deny" and "tw-worker-low" in out["permissionDecisionReason"]
    assert row["action"] == "advise"
    assert run("advisory", brief_extra="TW-Override: needs high\n")[0] is None
    assert run("advisory", conf=0.5)[0] is None                          # under cutoff
    assert run("advisory", risk="physics")[0] is None                    # never the cheapest tier
    assert run("advisory", risk="external")[0] is None                   # any risk flag, not just two
    assert run("advisory", pick="medium", risk="physics")[0]["permissionDecision"] == "deny"
    # re-dispatch of an advised brief hits the cached decision: override or taking the pick both admit
    out, row = run("advisory", then=("tw-worker-high", "TW-Override: needs high\n"))
    assert out is None and row["source"] == "cached:stub" and row["action"] is None
    out, row = run("advisory", then=("tw-worker-low", ""))
    assert out is None and row["source"] == "cached:stub" and row["action"] is None
    out, row = run("active")
    assert out["permissionDecision"] == "allow" and out["updatedInput"]["subagent_type"] == "tw-worker-low"
    assert out["updatedInput"]["prompt"].startswith("TW-Role: worker") and row["action"] == "rewrite"
    out, row = run("active", guard="context-mode PreToolUse Agent hook is registered")
    assert out["permissionDecision"] == "deny" and row["action"] == "advise" and row["guard"].startswith("context-mode")
    out, row = run("active", flag=True)
    assert out["permissionDecision"] == "deny" and "lost race" in row["guard"]
    assert run("advisory", conf=0.1, explore=1.0)[0]["permissionDecisionReason"].count("exploration") == 1
    assert run("advisory", conf=0.1, explore=0.0)[0] is None
    assert run("advisory", pick="xhigh", conf=0.1, explore=1.0)[0] is None   # exploration only goes lower
    out, row = run("active", guard=boom)                                  # act() raises: fail open
    assert out is None and row["kind"] == "error" and row["error"] == "RuntimeError"
    print("PASS act: shadow, advisory, override, cutoff, risk floor, cached re-dispatch, active rewrite, "
          "guard/flag hold, exploration, fail-open")
