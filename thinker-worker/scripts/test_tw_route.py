"""route(): table backend clamps to the role's tiers, falls back to the coordinator on any failure or overrun;
the hook appends a route row (no body) after an admitted dispatch; opt-in body store; ticket ignores TW-Route;
with no backend, a ticket under the class's explore goes one tier below the coordinator on the role's ladder.
Run: python test_tw_route.py"""
import json
import tempfile
import time
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import HDR, SESSION, hook, receipts

BRIEF = "TW-Role: worker\n" + HDR + "SECRET-BODY do it"


REAL_LOAD = tw.load_routes


def routes_with(cal_path, backends=("table",), budget=2.0):
    r = REAL_LOAD()
    r["router"] = {**r["router"], "backends": list(backends), "budget_s": budget, "table": {"path": str(cal_path)}}
    return r


if __name__ == "__main__":
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
    assert tw.ticket(BRIEF) == tw.ticket(BRIEF.replace(HDR, HDR + "TW-Route: abc\n"))
    assert tw.ticket(BRIEF) == tw.ticket(BRIEF.replace(HDR, HDR + "TW-Override: keep high\n"))

    with tempfile.TemporaryDirectory() as tmp:
        cal = Path(tmp) / "calibration.json"
        cal.write_text(json.dumps({"classes": {"C-coding": {"recommended_tier": "xhigh"}}}), encoding="utf-8")
        tw.load_routes = lambda path=None: routes_with(cal)          # hook sees a table backend
        try:
            for store in (False, True):
                with tempfile.TemporaryDirectory() as home:
                    run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION]
                             + (["--store-bodies"] if store else []))
                    hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
                    hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": "TW-Role: worker\nno header"})
                    rows = receipts(home, "claude")
                    assert [x["kind"] for x in rows] == ["dispatch", "route", "dispatch"], rows   # no route row on deny
                    assert rows[1]["coordinator_tier"] == "high" and rows[1]["action"] is None, rows[1]
                    assert rows[1]["router_agent"] == tw.agent_name("worker", rows[1]["router_tier"]), rows[1]
                    assert rows[1]["source"] == "table" and "errors" not in rows[1], rows[1]
                    hook(home, "claude", "Agent", {"subagent_type": "tw-worker-low", "prompt": BRIEF})  # same ticket
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
                hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
                row = receipts(home, "claude")[-1]
                assert row["kind"] == "route" and row["source"] == "coordinator", row
                assert row.get("errors") and row["errors"][0].startswith("table: "), row
        finally:
            tw.load_routes = REAL_LOAD

    with tempfile.TemporaryDirectory() as home:  # real routes.json: backends [] -> coordinator rows, never cached
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-low", "prompt": BRIEF})
        a, b = [x for x in receipts(home, "claude") if x["kind"] == "route"]
        assert a["source"] == b["source"] == "coordinator" and b["router_tier"] == "low", (a, b)

    with tempfile.TemporaryDirectory() as home:  # torn last line from a concurrent hook is skipped
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
        path = next(Path(home).rglob("receipts/claude/*.jsonl"))
        with path.open("ab") as s:
            s.write(b'{"kind": "route", "tick')
        code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF + " v2"})
        assert code == 0 and out == "", out
        last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])  # the torn fragment swallows the next row
        assert last["kind"] == "route" and last["ticket"] == tw.ticket(BRIEF + " v2")[0], last

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
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": long})
        assert "…[+44]" in receipts(home, "claude")[0]["header"]
        f = Path(home) / "b.md"
        f.write_text(BRIEF, encoding="utf-8")
        code, out = run_main(["route", "--harness", "claude", "--role", "worker", "--brief-file", str(f)])
        assert code == 0 and json.loads(out)["ticket"] == tw.ticket(BRIEF)[0], out

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
    print("PASS route: table clamp, coordinator fallback (missing/invalid/overrun), route rows, no body, body store, "
          "header truncation, CLI, backend-only cache, TW-Override ticket, backend errors, torn line, fail-open error row")
