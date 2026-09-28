"""route(): table backend clamps to the role's tiers, falls back to the coordinator on any failure or overrun;
the hook appends a route row (no body) after an admitted dispatch; opt-in body store; ticket ignores TW-Route;
with no backend, a ticket under the class's explore goes one tier below the coordinator on the role's ladder.
Run: python test_tw_route.py"""
import json
import os
import tempfile
import time
from pathlib import Path

import tw
from test_tw_hook import pinned_routes, run_main
from test_tw_receipt import HDR, SESSION, hook, receipts

BRIEF = "TW-Role: worker\n" + HDR + "SECRET-BODY do it"


REAL_LOAD = tw.load_routes


def routes_with(cal_path, backends=("table",), budget=2.0):
    r = REAL_LOAD()
    r["router"] = {**r["router"], "backends": list(backends), "budget_s": budget, "table": {"path": str(cal_path)},
                   "classes": {"*": {"mode": "shadow"}}}  # independent of the shipped mode
    return r


if __name__ == "__main__":
    pin = pinned_routes()  # every block but the last runs on a shadow copy of the shipped file
    pin.__enter__()
    fields, _ = tw.header_fields(BRIEF)
    with tempfile.TemporaryDirectory() as tmp:
        cal = Path(tmp) / "calibration.json"
        cal.write_text(json.dumps({"classes": {"C-coding": {"recommended_tier": "xhigh"}}}), encoding="utf-8")
        r = tw.route(routes_with(cal), "claude", "worker", fields, BRIEF, "high")
        assert (r["source"], r["tier"], r["confidence"], r["mode"]) == ("table", "xhigh", 0.0, "shadow"), r
        assert r["provenance"].startswith("calibration "), r
        r = tw.route(routes_with(cal), "claude", "leaf", fields, BRIEF, "low")
        assert r["tier"] == "medium", r                                   # clamped into leaf tiers
        r = tw.route(routes_with(Path(tmp) / "missing.json"), "claude", "worker", fields, BRIEF, "high")
        assert (r["source"], r["tier"], r["confidence"]) == ("coordinator", "high", 0.0), r
        tw.BACKENDS["bad"] = lambda *a: {"tier": "low", "probs": {"low": 0.7}, "confidence": 0.9}
        assert tw.route(routes_with(cal, ("bad",)), "claude", "worker", fields, BRIEF, "high")["source"] == "coordinator"
        tw.BACKENDS["slow"] = lambda *a: time.sleep(3) or {"tier": "low", "probs": {"low": 1.0}, "confidence": 1.0}
        t0 = time.monotonic()
        r = tw.route(routes_with(cal, ("slow",), budget=0.2), "claude", "worker", fields, BRIEF, "high")
        assert r["source"] == "coordinator" and time.monotonic() - t0 < 1.0, r
    assert tw.ticket(BRIEF, "opus") == tw.ticket(BRIEF.replace(HDR, HDR + "TW-Route: abc\n"), "opus")
    assert tw.ticket(BRIEF, "opus") == tw.ticket(BRIEF.replace(HDR, HDR + "TW-Override: keep high\n"), "opus")

    with tempfile.TemporaryDirectory() as tmp:
        cal = Path(tmp) / "calibration.json"
        cal.write_text(json.dumps({"classes": {"C-coding": {"recommended_tier": "xhigh"}}}), encoding="utf-8")
        tw.load_routes = lambda path=None: routes_with(cal)          # hook sees a table backend
        try:
            for store in (False, True):
                with tempfile.TemporaryDirectory() as home:
                    run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION]
                             + (["--store-bodies"] if store else []))
                    assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF}) == (0, "")
                    hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": "TW-Role: worker\nno header"})
                    rows = receipts(home, "claude")
                    assert [x["kind"] for x in rows] == ["dispatch", "route", "dispatch"], rows   # no route row on deny
                    assert rows[1]["coordinator_tier"] == "high" and rows[1]["action"] is None, rows[1]
                    assert rows[1]["router_agent"] == tw.agent_name("worker", rows[1]["router_tier"]), rows[1]
                    assert rows[1]["source"] == "table" and "errors" not in rows[1], rows[1]
                    code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-low", "prompt": BRIEF})  # same ticket
                    assert code == 0 and "you dispatched low" in out, out            # admitted; only the prior reminder
                    again = receipts(home, "claude")[-1]
                    assert again["source"] == "cached:table", again
                    assert again["router_tier"] == "xhigh" and again["coordinator_tier"] == "low", again
                    raw = next(Path(home).rglob("receipts/claude/*.jsonl")).read_text(encoding="utf-8")
                    assert "SECRET-BODY" not in raw
                    bodies = list(Path(home).rglob("bodies/*/*.md"))
                    assert (len(bodies) == 1 and "SECRET-BODY" in bodies[0].read_text(encoding="utf-8")) if store else not bodies

            # backend error is recorded on the route row; the pick falls back to the coordinator
            cal.write_text(json.dumps({"classes": {"C-coding": {"recommended_tier": "max"}}}), encoding="utf-8")
            with tempfile.TemporaryDirectory() as home:
                run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
                assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF}) == (0, "")
                row = receipts(home, "claude")[-1]
                assert row["kind"] == "route" and row["source"] == "coordinator", row
                assert row.get("errors") and row["errors"][0].startswith("table: "), row
        finally:
            tw.load_routes = REAL_LOAD

    # real routes.json, exploration pinned off: backends [] -> coordinator rows, never cached
    tw.load_routes = lambda path=None: {**REAL_LOAD(), "router": {**REAL_LOAD()["router"], "classes": {"*": {"mode": "shadow"}}}}
    try:
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF}) == (0, "")  # = prior
            code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-low", "prompt": BRIEF})
            assert code == 0 and json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                "additionalContext": "thinker-worker: prior for C-coding is high; you dispatched low (fine if deliberate)"}}, out
            a, b = [x for x in receipts(home, "claude") if x["kind"] == "route"]
            assert a["source"] == b["source"] == "coordinator" and b["router_tier"] == "low", (a, b)
            assert a["prior_tier"] == b["prior_tier"] == "high", (a, b)                    # C-coding worker prior
    finally:
        tw.load_routes = REAL_LOAD

    with tempfile.TemporaryDirectory() as home:  # torn last line from a concurrent hook is skipped
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF}) == (0, "")
        path = next(Path(home).rglob("receipts/claude/*.jsonl"))
        with path.open("ab") as s:
            s.write(b'{"kind": "route", "tick')
        code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF + " v2"})
        assert code == 0 and out == "", out
        last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])  # the torn fragment swallows the next row
        assert last["kind"] == "route" and last["ticket"] == tw.ticket(BRIEF + " v2", "opus")[0], last

    with tempfile.TemporaryDirectory() as home:  # post-admission failure: admit stands, error row logged
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION, "--store-bodies"])
        (Path(home) / ".thinker-worker" / "bodies").write_text("", encoding="utf-8")  # body dir unwritable
        code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
        assert code == 0 and out == "", out
        rows = receipts(home, "claude")
        assert [x["kind"] for x in rows] == ["dispatch", "error"] and rows[0]["decision"] == "admit", rows
        assert rows[1]["where"] == "route" and rows[1]["tool_use_id"] == "toolu_x", rows
        assert rows[1]["error"] in ("FileExistsError", "NotADirectoryError"), rows

    long = "TW-Role: worker\n" + HDR.replace("TW-Deliverable: patch", "TW-Deliverable: " + "p" * 300) + "x"
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": long}) == (0, "")
        assert "…[+44]" in receipts(home, "claude")[0]["header"]
        f = Path(home) / "b.md"
        f.write_text(BRIEF, encoding="utf-8")
        code, out = run_main(["route", "--harness", "claude", "--role", "worker", "--brief-file", str(f)])
        assert code == 0 and json.loads(out)["ticket"] == tw.ticket(BRIEF, "opus")[0], out

    r0 = json.loads(json.dumps(tw.load_routes()))  # no backend: explore one tier below the coordinator
    r0["router"].update(backends=[], classes={"*": {"mode": "advisory", "explore": 1.0}})
    f = {"TW-Class": "C-coding", "TW-Deliverable": "d", "TW-Accept": "a", "TW-Risk": "none"}
    r = tw.route(r0, "claude", "worker", f, "x", "high")
    assert (r["source"], r["tier"], r["confidence"]) == ("explore", "medium", 0.0), r
    assert tw.route(r0, "claude", "worker", f, "x", "low")["source"] == "coordinator"       # cheapest: never explored
    assert tw.route(r0, "claude", "independent-review", f, "x", "xhigh")["tier"] == "high"  # the role's own ladder
    assert tw.route(r0, "claude", "leaf", f, "x", "medium")["tier"] == "low"
    r0["router"]["classes"]["*"]["explore"] = 0.0
    assert tw.route(r0, "claude", "worker", f, "x", "high")["source"] == "coordinator"

    # the ticket includes the model (per-call, else the role's models[0]): cached decisions are per (brief, model)
    tw.load_routes = lambda path=None: r0
    r0["router"]["classes"]["*"]["explore"] = 1.0
    try:
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            deny = lambda o: json.loads(o)["hookSpecificOutput"]["permissionDecision"] == "deny"
            assert deny(hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})[1])
            assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF,
                                                  "model": "opus"}) == (0, "")          # = the default: cached
            assert deny(hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF,
                                                       "model": "claude-opus-5-5"})[1])  # another model: fresh decision
            a, b, c = [x for x in receipts(home, "claude") if x["kind"] == "route"]
            assert a["ticket"] == b["ticket"] != c["ticket"] and b["source"] == "cached:explore", (a, b, c)
        pinned = BRIEF.replace(HDR, HDR + "TW-Pin: user asked for Opus high\n")
        for mode in ("advisory", "active"):  # TW-Pin: the router never advises, rewrites, or explores
            r0["router"]["classes"]["*"]["mode"] = mode
            with tempfile.TemporaryDirectory() as home:
                run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
                code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": pinned})
                assert code == 0 and "permissionDecision" not in out and "updatedInput" not in out, out
                row = receipts(home, "claude")[-1]
                assert (row["pinned"], row["source"], row["action"]) == (True, "coordinator", None), row
                hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
                assert receipts(home, "claude")[-1]["pinned"] is False                     # unpinned rows say so
    finally:
        tw.load_routes = REAL_LOAD

    # decaying forced exploration: eps_t = max(floor, min(1, c / t**power)), t = 1 + prior non-pinned class rows
    decay = {"c": 0.5, "power": 0.25, "floor": 0.05}
    r1 = json.loads(json.dumps(REAL_LOAD()))
    r1["router"].update(backends=[], classes={"*": {"mode": "advisory", "explore": decay}})
    coin = lambda b: int(tw.ticket(b, "opus")[0], 16) / 16 ** 12
    mid = next(b for b in (BRIEF + f" d{i}" for i in range(500)) if 0.3 < coin(b) < 0.5)   # explored iff eps > coin
    r = tw.route(r1, "claude", "worker", fields, mid, "high", t=1)
    assert (r["source"], r["eps"], r["explore"]) == ("explore", 0.5, decay), r
    r = tw.route(r1, "claude", "worker", fields, mid, "high", t=16)
    assert (r["source"], r["eps"]) == ("coordinator", 0.25), r
    assert tw.route(r1, "claude", "worker", fields, mid, "high", t=10 ** 8)["eps"] == 0.05       # the floor
    # propensity of the logged action: explored eps_t, eligible but unexplored 1 - eps_t, otherwise 1.0
    prop = lambda brief=mid, tier="high", t=1, prior=None: tw.route(r1, "claude", "worker", fields, brief, tier,
                                                                    prior, t=t)["propensity"]
    assert (prop(), prop(t=16)) == (0.5, 0.75), (prop(), prop(t=16))
    assert prop(tier="low") == 1.0                                                   # nothing below: not eligible
    assert prop(mid.replace(HDR, HDR + "TW-Pin: user asked for high\n")) == 1.0      # pinned
    cached = {"router_tier": "medium", "probs": {"medium": 1.0}, "confidence": 0.0, "source": "explore"}
    assert prop(prior=cached) == 1.0                                                  # cached: no draw
    tw.BACKENDS["stub"] = lambda *a: {"tier": "low", "probs": {"low": 1.0}, "confidence": 1.0}
    r1["router"]["backends"] = ["stub"]
    assert prop() == 1.0                                                              # a backend answered: no draw
    r1["router"]["backends"] = []
    tw.load_routes = lambda path=None: r1
    try:
        for n_class, want in ((15, "coordinator"), (0, "explore")):  # t counts every session file of the harness
            with tempfile.TemporaryDirectory() as home:
                for i in range(n_class):
                    tw.append_receipt(Path(home), "claude", "other", {"kind": "route", "class": "C-coding"})
                for i in range(100):  # pinned rows and other classes never count
                    tw.append_receipt(Path(home), "claude", "other", {"kind": "route", "class": "C-coding", "pinned": True})
                    tw.append_receipt(Path(home), "claude", "other", {"kind": "route", "class": "T1-mechanical"})
                run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
                hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": mid})
                row = tw.read_rows(tw.receipts_path(Path(home), "claude", SESSION))[-1]
                assert (row["source"], row["eps"]) == (want, 0.25 if n_class else 0.5), (n_class, row)
                assert row["propensity"] == (0.75 if n_class else 0.5), row
    finally:
        tw.load_routes = REAL_LOAD

    pin.__exit__(None, None, None)  # the one deliberate test of the SHIPPED routes.json: TW_ROUTES names it, so
    os.environ["TW_ROUTES"] = str(tw.source_root() / "routes.json")  # a real-home override file is never read
    shipped = tw.load_routes()  # no backend, every class advisory with decaying exploration (eps 0.5 at t=1)
    assert shipped["router"]["backends"] == [] and shipped["router"]["classes"]["*"] == {"mode": "advisory", "explore": decay}
    coin = lambda b: int(tw.ticket(b, "opus")[0], 16) / 16 ** 12      # the draw route() and act() use
    briefs = ["TW-Role: worker\n" + HDR.replace("destructive", "none") + f"shipped {i}" for i in range(200)]
    under, over = next(b for b in briefs if coin(b) < 0.2), next(b for b in briefs if coin(b) >= 0.5)  # t=1, t=2
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": under})
        why = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        assert code == 0 and "(exploration)" in why and "dispatch tw-worker-medium " in why, out   # next tier down
        assert hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": over}) == (0, "")
        phys = next(b.replace("TW-Risk: none", "TW-Risk: physics") for b in briefs
                    if coin(b.replace("TW-Risk: none", "TW-Risk: physics")) < 0.2)
        code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": phys})
        why = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]    # physics floor is medium, not high
        assert "dispatch tw-worker-medium " in why, out
    print("PASS route: table clamp, coordinator fallback (missing/invalid/overrun), route rows, no body, body store, "
          "header truncation, CLI, backend-only cache, TW-Override ticket, backend errors, torn line, fail-open error row")
