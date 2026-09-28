"""Promotion rule reproduces the design's count table (coordinator arm 850/1000 ~ known 0.85).
Run: python test_tw_promote.py"""
import tempfile
from pathlib import Path

import tw

S = "55555555-6666-7777-8888-999999999999"
OPUS = "claude-opus-5-5"  # an executed model id, as a Claude cost row records it


def ran(home, tid, model=OPUS, **extra):
    """The cost row: executed identity (Claude `model`, optional `agent_type`; codex `model` + `effort`)."""
    tw.append_receipt(home, "claude", S, {"kind": "cost", "tool_use_id": tid, "model": model, **extra})


def verdict(k, n=10, lost=0, advised=0):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for i in range(lost):  # rewrites that lost the race: rejected, but excluded from both arms
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"x{i}", "ticket": f"v{i}",
                                                  "class": "C-coding", "action": "rewrite",
                                                  "router_tier": "low", "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": f"x{i}", "lost": True})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"x{i}", "accepted": False})
        for i in range(n):  # router arm: active rewrites to a lower tier
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"r{i}", "ticket": f"t{i}",
                                                  "class": "C-coding", "action": "rewrite",
                                                  "router_tier": "low", "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": f"r{i}", "lost": False})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"r{i}", "accepted": i < k})
            ran(home, f"r{i}", **({"advisor_calls": 1} if i < advised else {}))  # advisor: tier + Fable, not the tier
        for i in range(5):  # rewrites never race-checked: unverified, in neither arm
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"q{i}", "ticket": f"z{i}",
                                                  "class": "C-coding", "action": "rewrite",
                                                  "router_tier": "low", "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"q{i}", "accepted": False})
        for i in range(1000):  # coordinator arm: table wanted low (and would have acted), ran at high
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"c{i}", "ticket": f"u{i}",
                                                  "class": "C-coding", "action": None, "source": "table",
                                                  "router_tier": "low", "coordinator_tier": "high", "eligible": True})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"c{i}", "accepted": i < 850})
            ran(home, f"c{i}")
        for i in range(200):  # table wanted low but would not have acted (under cutoff, unexplored): neither arm
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"e{i}", "ticket": f"y{i}",
                                                  "class": "C-coding", "action": None, "source": "table",
                                                  "router_tier": "low", "coordinator_tier": "high", "eligible": False})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"e{i}", "accepted": True})
        for i in range(50):  # agreement and coordinator-fallback rows: in neither arm
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"a{i}", "ticket": f"w{i}",
                                                  "class": "C-coding", "action": None,
                                                  "source": "table" if i % 2 else "coordinator",
                                                  "router_tier": "high" if i % 2 else "low",
                                                  "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"a{i}", "accepted": False})
        [v] = tw.promote(home, "claude", model=OPUS)   # the executed model; rows without a cost row group under None
        return v


if __name__ == "__main__":
    got = {k: verdict(k)["verdict"] for k in (9, 8, 6, 5)}
    assert got == {9: "promote", 8: "hold", 6: "hold", 5: "demote"}, got
    v = verdict(9, lost=5)
    assert (v["n_router"], v["n_coord"], v["verdict"]) == (10, 1000, "promote"), v   # lost races, agreement,
                                                    # coordinator-fallback and ineligible rows count for neither arm
    v = verdict(9, advised=3)
    assert (v["n_router"], v["n_advisor_excluded"]) == (7, 3), v     # advisor-assisted rows leave the arm
    with tempfile.TemporaryDirectory() as tmp:           # floored advise, then compliance at the floored tier
        home = Path(tmp)
        base = {"kind": "route", "ticket": "fl", "class": "C-coding", "router_tier": "low", "target_tier": "medium"}
        tw.append_receipt(home, "claude", S, {**base, "tool_use_id": "f0", "action": "advise", "source": "table",
                                              "coordinator_tier": "high", "eligible": True})
        tw.append_receipt(home, "claude", S, {**base, "tool_use_id": "f1", "action": None, "source": "cached:table",
                                              "coordinator_tier": "medium", "eligible": False})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "f1", "accepted": True})
        ran(home, "f1")
        [v] = tw.promote(home, "claude", model=OPUS)
        assert (v["n_router"], v["n_coord"]) == (1, 0), v    # complied at the floored tier: router arm
    with tempfile.TemporaryDirectory() as tmp:           # one verdict per (class, model); --model filters
        home = Path(tmp)
        for m, k in (("opus", 9), ("gpt-6-sol", 5)):
            for i in range(10):  # router arm; half the opus rows predate agent_model: the cost row's model groups them
                own = {"agent_model": m} if m != "opus" or i % 2 else {"router_agent": "tw-worker-low"}
                tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"{m}r{i}", "ticket": f"{m}t{i}",
                                                      "class": "C-coding", "action": "rewrite", "router_tier": "low",
                                                      "coordinator_tier": "high", **own})
                tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": f"{m}r{i}", "lost": False})
                tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"{m}r{i}", "accepted": i < k})
                ran(home, f"{m}r{i}", m)
            for i in range(1000):
                tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"{m}c{i}", "ticket": f"{m}u{i}",
                                                      "class": "C-coding", "action": None, "source": "table",
                                                      "router_tier": "low", "coordinator_tier": "high",
                                                      "eligible": True, "agent_model": m})
                tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"{m}c{i}", "accepted": i < 850})
                ran(home, f"{m}c{i}", m)
        for i in range(20):  # pinned by the user: the router never acted, so neither arm (else sol would promote)
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"p{i}", "ticket": f"p{i}",
                                                  "class": "C-coding", "action": "rewrite", "router_tier": "low",
                                                  "coordinator_tier": "high", "agent_model": "gpt-6-sol", "pinned": True})
            tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": f"p{i}", "lost": False})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"p{i}", "accepted": True})
        got = {(v["class"], v["model"]): (v["n_router"], v["verdict"]) for v in tw.promote(home, "claude")}
        assert got == {("C-coding", "opus"): (10, "promote"), ("C-coding", "gpt-6-sol"): (10, "demote")}, got
        assert [v["model"] for v in tw.promote(home, "claude", model="gpt-6-sol")] == ["gpt-6-sol"]
    with tempfile.TemporaryDirectory() as tmp:           # a TW-Check label outranks the coordinator's accept
        home = Path(tmp)
        for tid, accepted, checks in (("k1", True, ["fail"]),             # check fail beats accept: rejected
                                      ("k2", False, ["pass"]),            # check pass beats reject: accepted
                                      ("k3", True, ["unknown"]),          # unknown: excluded
                                      ("k4", True, ["fail", "pass"]),     # the latest check wins: accepted
                                      ("k5", None, ["pass"]),             # check only: accepted
                                      ("k6", True, []),                   # coordinator only: accepted
                                      ("k7", True, ["pass", "unknown"])):  # latest unknown: excluded
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": tid, "ticket": tid,
                                                  "class": "C-coding", "action": "rewrite", "router_tier": "low",
                                                  "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": tid, "lost": False})
            if accepted is not None:
                tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": tid, "accepted": accepted})
            for lab in checks:
                tw.append_receipt(home, "claude", S, {"kind": "check", "tool_use_id": tid, "label": lab})
            ran(home, tid)
        [v] = tw.promote(home, "claude", model=OPUS)
        assert (v["k_router"], v["n_router"], v["n_check"], v["n_coordinator"]) == (4, 5, 4, 1), v
    # R3 (Astra review finding 3): arms count the executed model/effort (the cost row), never the requested one
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        # Astra 1: a verified codex rewrite requested as gpt-6-sol that ran gpt-5.6-terra
        tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": "sub", "ticket": "sub", "class": "C-coding",
                                              "action": "rewrite", "router_tier": "low", "coordinator_tier": "high",
                                              "agent_model": "gpt-6-sol", "via": "codex-exec"})
        tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": "sub", "lost": False})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "sub", "accepted": True})
        ran(home, "sub", "gpt-5.6-terra", effort="low", via="codex-exec")
        # Astra 2: an advise to medium, then the cached retry at medium; the runtime ran high
        adv = {"kind": "route", "ticket": "cr", "class": "C-coding", "router_tier": "medium", "agent_model": "gpt-6-sol"}
        tw.append_receipt(home, "claude", S, {**adv, "tool_use_id": "cr0", "action": "advise", "source": "table",
                                              "coordinator_tier": "high", "eligible": True})
        tw.append_receipt(home, "claude", S, {**adv, "tool_use_id": "cr1", "action": None, "source": "cached:table",
                                              "coordinator_tier": "medium", "eligible": False})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "cr1", "accepted": True})
        ran(home, "cr1", "gpt-6-sol", effort="high", via="codex-exec")
        # a Claude coordinator-arm row whose child agent file was the low tier, not the coordinator's high
        tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": "ag", "ticket": "ag", "class": "C-coding",
                                              "action": None, "source": "table", "router_tier": "low",
                                              "coordinator_tier": "high", "eligible": True, "agent_model": "opus"})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "ag", "accepted": True})
        ran(home, "ag", agent_type="tw-worker-low")
        # no executed evidence: labeled, verified rewrite, no cost row; not back-filled from the role default (opus)
        tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": "nx", "ticket": "nx", "class": "C-coding",
                                              "action": "rewrite", "router_tier": "low", "coordinator_tier": "high",
                                              "router_agent": "tw-worker-low"})
        tw.append_receipt(home, "claude", S, {"kind": "race", "tool_use_id": "nx", "lost": False})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "nx", "accepted": True})
        got = {v["model"]: (v["n_router"], v["n_coord"], v.get("n_excluded_identity")) for v in tw.promote(home, "claude")}
        assert got.get("gpt-6-sol") == (0, 0, 1), got   # the substituted run left; the ignored effort excluded
        assert got.get("gpt-5.6-terra") == (1, 0, 0), got           # counted under the model that ran
        assert got.get(OPUS) == (0, 0, 1) and got.get(None) == (0, 0, 1) and "opus" not in got, got
    print("PASS R3 promote groups by executed model; contradicted or missing executed identity -> n_excluded_identity")
    print("PASS promotion rule matches design §5 table at n=10 (promote k>=9, demote k<=5); lost races, "
          "ineligible and advisor-assisted rows excluded; check labels outrank the coordinator's")
