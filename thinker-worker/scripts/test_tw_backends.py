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
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1/systemone"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def answer(probs, choice="low"):
    return {"answers": {"tier": {"type": "choice", "choice": choice, "confidence": 0.5, "probabilities": probs}}}


def routes_with(**router):
    r = json.loads(json.dumps(SHIPPED))
    r["router"].update(classes={"*": {"mode": "shadow", "explore": 0.0}}, **router)
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

