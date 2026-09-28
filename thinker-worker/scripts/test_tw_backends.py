"""Decision-model backends (design D11, D14). D1: backend_jev POSTs /v1/systemone to a local stub server (stdlib
http.server on 127.0.0.1, ephemeral port): state = routing header + body cut to body_chars, options = the role's
tiers with router.options wording, probabilities renormalized over the role's tiers, timeout = remaining budget;
a router name whose block has kind "jev" resolves to it.
Run: python test_tw_backends.py"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tw
from test_tw_hook import pinned_routes
from test_tw_receipt import HDR

BODY = "B" * 40 + "TAIL-NOT-SENT"
BRIEF = "TW-Role: worker\n" + HDR + "TW-Check: python -c pass\n" + BODY
SHIPPED = tw.load_routes(tw.source_root() / "routes.json")  # explicit path: never a user override file


class Stub:
    """A local decision-model server: records each request body, answers `reply` after `delay` seconds."""

    def __init__(self, reply, delay=0.0):
        self.reply, self.delay, self.seen = reply, delay, []
        stub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                stub.seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                time.sleep(stub.delay)
                data = json.dumps(stub.reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.handle_error = lambda *a: None  # the timeout case: the client hung up before the reply
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1/systemone"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def answer(probs, choice="low"):
    return {"answers": {"tier": {"type": "choice", "choice": choice, "confidence": 0.5, "probabilities": probs}}}


def routes_with(**router):
    r = json.loads(json.dumps(SHIPPED))
    r["router"].update({"classes": {"*": {"mode": "shadow", "explore": 0.0}}, **router})
    return r


if __name__ == "__main__":
    pin = pinned_routes()
    pin.__enter__()
    fields, _ = tw.header_fields(BRIEF)
    worker = SHIPPED["harnesses"]["claude"]["roles"]["worker"]
    leaf = SHIPPED["harnesses"]["claude"]["roles"]["leaf"]
    opts = SHIPPED["router"]["options"]
    assert set(opts) == set(tw.TIERS) and opts["low"].startswith("Direct execution"), opts

    # D1: request shape, body cut, renormalization over the role's tiers (a stray option is dropped)
    s = Stub(answer({"low": 0.2, "medium": 0.6, "high": 0.1, "xhigh": 0.0, "max": 0.3}, "medium"))
    try:
        out = tw.backend_jev({"url": s.url, "body_chars": 40, "options": opts, "timeout": 2.0}, worker, fields, BRIEF)
        path, req = s.seen[-1]
        assert path == "/v1/systemone", path
        q = req["questions"]["tier"]
        assert q["type"] == "choice" and q["instructions"] and q["criteria"] == {t: opts[t] for t in worker["tiers"]}, q
        assert req["state"].startswith("TW-Role: worker\n" + tw.header_text(fields)), req["state"]
        assert req["state"].endswith("B" * 40) and "TAIL-NOT-SENT" not in req["state"], req["state"]
        assert "TW-Check" not in req["state"], req["state"]              # not a routing header line
        assert tw.valid_route(out, worker["tiers"]), out
        assert out["tier"] == "medium" and abs(out["probs"]["medium"] - 0.6 / 0.9) < 1e-9, out
        assert out["body_chars_sent"] == 40 and "max" not in out["probs"], out
        tw.backend_jev({"url": s.url, "options": opts, "timeout": 2.0}, leaf, fields, BRIEF)  # default body_chars 1500
        q = s.seen[-1][1]["questions"]["tier"]
        assert list(q["criteria"]) == ["low", "medium"] and "TAIL-NOT-SENT" in s.seen[-1][1]["state"], q
    finally:
        s.close()
    s = Stub(answer({"high": 0.0, "xhigh": 0.0, "low": 0.0, "medium": 0.0}))   # no mass on the role's tiers
    try:
        try:
            tw.backend_jev({"url": s.url, "options": opts, "timeout": 2.0}, worker, fields, BRIEF)
            raise AssertionError("zero mass accepted")
        except ValueError:
            pass
    finally:
        s.close()
    s = Stub(answer({"low": 1.0}), delay=1.5)                                   # urllib timeout = the budget left
    try:
        t0 = time.monotonic()
        try:
            tw.backend_jev({"url": s.url, "options": opts, "timeout": 0.3}, worker, fields, BRIEF)
            raise AssertionError("no timeout")
        except OSError:
            pass
        assert time.monotonic() - t0 < 1.2, time.monotonic() - t0
    finally:
        s.close()

    # D1: a named block with kind "jev" resolves to backend_jev inside route()
    s = Stub(answer({"low": 0.9, "medium": 0.05, "high": 0.05, "xhigh": 0.0}))
    try:
        r = tw.route(routes_with(backends=["kev"], kev={"kind": "jev", "url": s.url, "body_chars": 100}),
                     "claude", "worker", fields, BRIEF, "high")
        assert r["tier"] == "low" and r["source"] != "coordinator" and s.seen, r
    finally:
        s.close()
    print("PASS backends D1: backend_jev request/renormalize/timeout, jev block resolution")

    # D2: every configured backend in parallel within budget_s; weighted geometric mean (w = 1/n unless
    # router.combine.weights; zeros floored at 1e-6); acts (source "bayes") only if top1 - top2 >= margin
    calls = []

    def stub(probs, delay=0.0, boom=False, name="?"):
        def fn(cfg, pol, fields, brief):
            calls.append(name)
            time.sleep(delay)
            if boom:
                raise RuntimeError("down")
            tier = max(probs, key=probs.get)
            return {"tier": tier, "probs": probs, "confidence": probs[tier], "body_chars_sent": 7}
        return fn

    def expect(answers, weights=None, tiers=("low", "medium", "high", "xhigh")):   # the rule, written out
        import math
        w = {k: (weights or {}).get(k, 1 / len(answers)) for k in answers}
        un = {t: math.exp(sum(w[k] * math.log(max(p.get(t, 0.0), 1e-6)) for k, p in answers.items())) for t in tiers}
        return {t: v / sum(un.values()) for t, v in un.items()}

    close = lambda a, b: set(a) == set(b) and all(abs(a[k] - b[k]) < 1e-5 for k in a)
    A, B = {"low": 0.7, "medium": 0.2, "high": 0.1}, {"low": 0.6, "medium": 0.3, "high": 0.1}
    tw.BACKENDS.update(a=stub(A, name="a"), b=stub(B, name="b"))
    r = tw.route(routes_with(backends=["a", "b"]), "claude", "worker", fields, BRIEF, "high")
    want = expect({"a": A, "b": B})
    assert (r["source"], r["tier"], r["gate"]) == ("bayes", "low", "pass"), r
    assert close(r["combined"], want) and close(r["probs"], want), (r["combined"], want)
    assert abs(r["confidence"] - want["low"]) < 1e-5 and r["confidence"] < SHIPPED["router"]["cutoff"], r
    assert set(r["backends"]) == {"a", "b"} and r["backends"]["a"]["tier"] == "low", r["backends"]
    assert r["backends"]["b"]["probs"] == B and isinstance(r["backends"]["b"]["ms"], int), r["backends"]
    C, D = {"low": 0.5, "medium": 0.5}, {"low": 0.4, "medium": 0.6}               # margin ~0.1 < 0.2
    tw.BACKENDS.update(c=stub(C), d=stub(D))
    r = tw.route(routes_with(backends=["c", "d"]), "claude", "worker", fields, BRIEF, "high")
    assert (r["source"], r["tier"], r["gate"]) == ("coordinator", "high", "margin"), r
    assert close(r["combined"], expect({"c": C, "d": D})) and set(r["backends"]) == {"c", "d"}, r
    r = tw.route(routes_with(backends=["c", "d"], combine={"rule": "bayes", "margin": 0.05}),
                 "claude", "worker", fields, BRIEF, "high")
    assert (r["source"], r["tier"], r["gate"]) == ("bayes", "medium", "pass"), r   # the margin is the knob
    E, F = {"low": 0.9, "medium": 0.1}, {"medium": 1.0}
    tw.BACKENDS.update(e=stub(E), f=stub(F))
    assert tw.route(routes_with(backends=["e", "f"]), "claude", "worker", fields, BRIEF, "high")["tier"] == "medium"
    r = tw.route(routes_with(backends=["e", "f"], combine={"rule": "bayes", "margin": 0.2, "weights": {"e": 1.0, "f": 0.0}}),
                 "claude", "worker", fields, BRIEF, "high")
    assert r["tier"] == "low" and close(r["combined"], expect({"e": E, "f": F}, {"e": 1.0, "f": 0.0})), r   # weights
    G, H = {"low": 1.0}, {"medium": 1.0}                                            # disjoint: floored, not log(0)
    tw.BACKENDS.update(g=stub(G), h=stub(H))
    r = tw.route(routes_with(backends=["g", "h"]), "claude", "worker", fields, BRIEF, "high")
    assert r["gate"] == "margin" and abs(r["combined"]["low"] - r["combined"]["medium"]) < 1e-9, r
    # failures are logged per backend; the one valid answer decides alone (n = 1)
    tw.BACKENDS.update(good=stub({"low": 0.2, "medium": 0.8}), boom=stub({}, boom=True), slow=stub({"low": 1.0}, delay=3),
                       bad=lambda *a: {"tier": "low", "probs": {"low": 0.7}, "confidence": 0.9})
    t0 = time.monotonic()
    r = tw.route(routes_with(backends=["good", "boom", "slow", "bad", "nope"], budget_s=0.5), "claude", "worker",
                 fields, BRIEF, "high")
    assert time.monotonic() - t0 < 1.0, time.monotonic() - t0
    bk = r["backends"]
    assert (r["source"], r["tier"]) == ("bayes", "medium") and close(r["combined"], expect({"good": bk["good"]["probs"]})), r
    assert bk["boom"]["error"] == "RuntimeError: down" and bk["slow"] == {"error": "timeout"}, bk
    assert bk["bad"]["error"] == "invalid answer" and bk["nope"]["error"] == "unknown backend", bk
    # parallel: two 0.4 s backends both answer inside a 0.7 s budget (serially the second would miss it)
    tw.BACKENDS.update(p1=stub(A, delay=0.4), p2=stub(B, delay=0.4))
    r = tw.route(routes_with(backends=["p1", "p2"], budget_s=0.7), "claude", "worker", fields, BRIEF, "high")
    assert set(k for k, v in r["backends"].items() if "tier" in v) == {"p1", "p2"} and r["source"] == "bayes", r
    r = tw.route(routes_with(backends=[]), "claude", "worker", fields, BRIEF, "high")
    assert (r["source"], r["backends"], r["combined"], r["gate"]) == ("coordinator", {}, None, None), r

    # D2 through the hook: advisory acts on a gated pick below the cutoff; a margin miss leaves the coordinator's
    # tier; the route row carries every backend, combined, gate; a re-dispatch reuses the decision (no calls)
    import tempfile
    from test_tw_hook import run_main
    from test_tw_receipt import SESSION, hook, receipts
    real_load = tw.load_routes
    plain = BRIEF.replace("TW-Risk: destructive", "TW-Risk: none")               # no risk floor on the pick
    try:
        for backends, gate in ((["a", "b"], "pass"), (["c", "d"], "margin")):
            rr = routes_with(backends=backends + ["nope"])
            rr["router"]["classes"]["*"]["mode"] = "advisory"
            tw.load_routes = lambda path=None: rr
            with tempfile.TemporaryDirectory() as home:
                run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
                code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": plain})
                row = receipts(home, "claude")[-1]
                assert row["kind"] == "route" and row["gate"] == gate and "errors" not in row, row
                assert set(row["backends"]) == set(backends) | {"nope"} and row["combined"], row
                if gate == "pass":
                    why = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
                    assert "router picks low (p=0.65)" in why and "tw-worker-low" in why, why
                    assert (row["source"], row["action"], row["eligible"]) == ("bayes", "advise", True), row
                    n = len(calls)
                    code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-low", "prompt": plain})
                    again = receipts(home, "claude")[-1]
                    assert out == "" and again["source"] == "cached:bayes" and len(calls) == n, (out, again)
                    assert again["backends"] == {} and again["gate"] is None, again
                else:
                    assert out == "" and (row["source"], row["action"], row["eligible"]) == ("coordinator", None, False), row
    finally:
        tw.load_routes = real_load
    print("PASS backends D2: parallel backends, Bayesian combination, weights, zero floor, margin gate, per-backend "
          "errors/timeout, hook row, cached decision")

    # D3 (design D14): exploration applies to the final pick, whichever source produced it: one tier below it on the
    # role's ladder (never below the cheapest), propensity eps / 1 - eps / 1.0 as before
    decay = {"c": 0.5, "power": 0.25, "floor": 0.05}
    coin = lambda b: int(tw.ticket(b, "opus")[0], 16) / 16 ** 12
    mid = next(b for b in (plain + f" d{i}" for i in range(500)) if 0.3 < coin(b) < 0.5)   # explored iff eps > coin
    tw.BACKENDS.update(med=stub({"low": 0.05, "medium": 0.9, "high": 0.05}), lo=stub({"low": 0.9, "medium": 0.1}),
                       top=stub({"high": 0.05, "xhigh": 0.95}))
    rx = lambda names, explore=decay: tw.route(routes_with(backends=names, classes={"*": {"mode": "advisory",
                                                                                         "explore": explore}}),
                                               "claude", "worker", fields, mid, "high", t=1)
    r = rx(["med"])                                             # eps 0.5 at t=1 > coin: one tier below the bayes pick
    assert (r["source"], r["tier"], r["eps"], r["propensity"], r["gate"]) == ("explore", "low", 0.5, 0.5, "pass"), r
    assert r["combined"] and r["combined"]["medium"] > 0.8, r                     # what the models said is kept
    r = tw.route(routes_with(backends=["med"], classes={"*": {"mode": "advisory", "explore": decay}}),
                 "claude", "worker", fields, mid, "high", t=16)                    # eps 0.25 < coin
    assert (r["source"], r["tier"], r["propensity"]) == ("bayes", "medium", 0.75), r
    r = rx(["lo"], 1.0)                                          # the pick is the cheapest tier: no draw
    assert (r["source"], r["tier"], r["propensity"]) == ("bayes", "low", 1.0), r
    r = rx(["top"], 1.0)                                         # above the coordinator: explored to xhigh - 1 = high
    assert (r["source"], r["tier"]) == ("explore", "high"), r
    tw.BACKENDS["rev"] = stub({"medium": 0.9, "high": 0.1})
    r = tw.route(routes_with(backends=["rev"], classes={"*": {"mode": "advisory", "explore": 1.0}}),
                 "claude", "independent-review", fields, mid, "high")   # medium is review's cheapest tier
    assert (r["source"], r["tier"]) == ("bayes", "medium"), r
    try:  # through the hook: an explored bayes pick is advised as exploration; a re-dispatch reuses it
        rr = routes_with(backends=["med"], classes={"*": {"mode": "advisory", "explore": decay}})
        tw.load_routes = lambda path=None: rr
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": mid})
            why = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
            assert "router picks low (exploration)" in why and "dispatch tw-worker-low " in why, why
            row = receipts(home, "claude")[-1]
            assert (row["source"], row["router_tier"], row["propensity"], row["eligible"]) == ("explore", "low", 0.5, True), row
            assert row["gate"] == "pass" and row["backends"]["med"]["tier"] == "medium", row
            hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": mid})   # rejected: no re-advice
            again = receipts(home, "claude")[-1]
            assert (again["source"], again["action"], again["eps"]) == ("cached:explore", None, 0.0), again
        rr["router"]["classes"]["*"]["explore"] = 1.0             # explored above the coordinator: acted on as picked
        rr["router"]["backends"] = ["top"]
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            code, out = hook(home, "claude", "Agent", {"subagent_type": "tw-worker-medium", "prompt": mid})
            why = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
            assert "router picks high (exploration)" in why, why
            assert receipts(home, "claude")[-1]["propensity"] == 1.0
    finally:
        tw.load_routes = real_load
    print("PASS backends D3: exploration around the final pick (bayes or coordinator), ladder floor, propensity, hook")

    # D4: the arithmetic mean of the valid answers is logged next to the acting (bayes) combination, never acted on
    mean = lambda *ps: {t: sum(p.get(t, 0.0) for p in ps) / len(ps) for t in ("low", "medium", "high", "xhigh")}
    r = tw.route(routes_with(backends=["a", "b", "nope"]), "claude", "worker", fields, BRIEF, "high")
    assert close(r["combined_mean"], mean(A, B)) and r["source"] == "bayes", r
    r = tw.route(routes_with(backends=["c", "d"]), "claude", "worker", fields, BRIEF, "high")   # margin miss: logged too
    assert close(r["combined_mean"], mean(C, D)) and r["source"] == "coordinator", r
    assert tw.route(routes_with(backends=[]), "claude", "worker", fields, BRIEF, "high")["combined_mean"] is None
    try:
        rr = routes_with(backends=["a", "b"])
        tw.load_routes = lambda path=None: rr
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": plain})
            hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": plain})
            first, again = [x for x in receipts(home, "claude") if x["kind"] == "route"]
            assert close(first["combined_mean"], mean(A, B)) and again["combined_mean"] is None, (first, again)
    finally:
        tw.load_routes = real_load
    print("PASS backends D4: combined_mean logged (gate pass and miss), None with no answer or cached")
