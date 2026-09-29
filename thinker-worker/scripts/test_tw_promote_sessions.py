"""Promotion joins stay within a session and use only advice preceding a retry.
Run: python test_tw_promote_sessions.py
"""
import tempfile
from pathlib import Path

import tw

MODEL = "claude-opus-5-5"


def append(home, session, rows, legacy=False):
    for row in rows:
        tw.append_receipt(home, "claude", session, row if legacy else {**row, "session_id": session})


def route(tid, ticket="brief", **extra):
    return {"kind": "route", "tool_use_id": tid, "ticket": ticket, "class": "C-coding",
            "router_tier": "medium", "target_tier": "medium", "coordinator_tier": "medium",
            "action": None, "source": "cached:explore", "eligible": False, **extra}


def run(tid, tier="medium"):
    return [dict(kind="cost", tool_use_id=tid, model=MODEL, agent_type=f"tw-worker-{tier}"),
            dict(kind="outcome", tool_use_id=tid, accepted=True)]


def counts(home):
    # Only file enumeration is fixed, never order within a session's append-only receipts.
    original = tw.harness_rows
    tw.harness_rows = lambda h, harness: sorted(original(h, harness),
        key=lambda r: r.get("session_id") or ("b" if r.get("tool_use_id") == "other" else "a"))
    try:
        [v] = tw.promote(home, "claude", model=MODEL, draws=100)
        return tuple(v[k] for k in ("k_router", "n_router", "n_advisor_excluded", "n_check"))
    finally:
        tw.harness_rows = original


def advice_sessions(legacy=False):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        append(home, "a", [route("advice", action="advise", source="explore", coordinator_tier="high"),
                           route("run"), *run("run")], legacy)
        before = counts(home)
        append(home, "b", [route("other", action="advise", source="explore", coordinator_tier="medium",
                                router_tier="low", target_tier="low")], legacy)
        after = counts(home)
        assert before == after == (1, 1, 0, 0), (legacy, before, after)


def advice_order():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        append(home, "a", [route("unadvised"), *run("unadvised")])
        assert counts(home) == (0, 0, 0, 0)
        append(home, "a", [route("advice", action="advise", source="explore", coordinator_tier="high")])
        assert counts(home) == (0, 0, 0, 0), "later advice must not classify an earlier run"
        append(home, "a", [route("medium"), *run("medium"),
                           route("new-advice", action="advise", source="explore", coordinator_tier="medium",
                                 router_tier="low", target_tier="low"),
                           route("low", router_tier="low", target_tier="low", coordinator_tier="low"),
                           *run("low", "low")])
        assert counts(home) == (2, 2, 0, 0), "each run must keep its preceding advice"


def mixed_session_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        append(home, "a", [route("advice", action="advise", source="explore", coordinator_tier="high"), route("run")])
        append(home, "a", run("run"), legacy=True)
        assert counts(home) == (1, 1, 0, 0), "one receipt file remains one session with mixed legacy rows"


def execution_sessions(collision=None):
    collisions = [collision] if collision else [dict(kind="cost", tool_use_id="run", model="other-model", agent_type="tw-worker-high"),
                  dict(kind="outcome", tool_use_id="run", accepted=False),
                  dict(kind="check", tool_use_id="run", label="fail"),
                  dict(kind="race", tool_use_id="run", lost=True),
                  dict(kind="cost", tool_use_id="run", model=MODEL, agent_type="tw-worker-medium", advisor_calls=1)]
    for collision in collisions:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            append(home, "a", [route("run", action="rewrite", source="explore", coordinator_tier="high"),
                               dict(kind="race", tool_use_id="run", lost=False), *run("run")])
            before = counts(home)
            append(home, "b", [collision])
            after = counts(home)
            assert before == after == (1, 1, 0, 0), (collision, before, after)


if __name__ == "__main__":
    advice_sessions()
    advice_sessions(legacy=True)
    advice_order()
    mixed_session_metadata()
    execution_sessions()
    print("PASS promotion uses preceding session-local advice and session-local execution evidence")
