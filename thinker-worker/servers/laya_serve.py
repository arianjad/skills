"""Jev-compatible HTTP server around Laya typed-decisions (CPU).

POST /v1/systemone {"state", "questions"} -> {"answers", "latency_ms", "usage"}; GET /v1/models.
Run under Local-Agent/local_decisions/.venv python. `--selftest` checks the mapping with a stub, no weights.
"""
import argparse, json, math, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO, SUB = "convaiinnovations/laya", "typed-decisions"


class BadPrediction(ValueError):
    """The predictor's output is not a probability distribution: the server's fault, answered 502."""


def map_answer(raw: dict, qdef: dict) -> dict:
    """Map one Laya answer to the contract; choice probabilities renormalized over the given options, after checking
    every value is a finite, non-bool real >= 0 with some mass on an option (never coerced: Astra round-3 R3)."""
    if raw.get("type") != "choice":
        return raw
    opts, got = list(qdef["criteria"]), raw.get("probabilities")
    if not (isinstance(got, dict) and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
                                          and v >= 0 for v in got.values()) and any(got.get(o, 0) > 0 for o in opts)):
        raise BadPrediction(f"predictor probabilities are not a distribution: {got!r}"[:200])
    p = {o: float(got.get(o, 0.0)) for o in opts}
    s = sum(p.values())
    p = {o: v / s for o, v in p.items()}
    return {"type": "choice", "choice": max(p, key=p.get), "confidence": float(raw["confidence"]), "probabilities": p}


def handle(predict, body: dict) -> dict:
    qs = body["questions"]
    t = time.perf_counter()
    out = predict(body["state"], qs)
    ms = (time.perf_counter() - t) * 1000
    return {"answers": {k: map_answer(v, qs[k]) for k, v in out["answers"].items()},
            "latency_ms": round(ms, 2), "usage": out.get("usage", {})}


def make_handler(predict, model_id: str, lock: threading.Lock):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/v1/models":
                self._send(200, {"models": [{"id": model_id, "device": "cpu"}]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/systemone":
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                with lock:  # ponytail: one global model lock; batch requests if throughput ever matters
                    self._send(200, handle(predict, body))
            except BadPrediction as e:  # a bad upstream answer, not a bad request: the router logs a failed backend
                self._send(502, {"error": f"BadPrediction: {e}"})
            except Exception as e:
                self._send(400, {"error": f"{type(e).__name__}: {e}"})

        def log_message(self, *a):
            pass
    return H


def selftest():
    import urllib.request

    def stub(state, qs):
        assert isinstance(state, str)
        return {"answers": {"tier": {"type": "choice", "choice": "high", "confidence": 0.3, "action": {},
                                     "probabilities": {"low": 0.1, "medium": 0.2, "high": 0.5, "xhigh": 0.1}}},
                "usage": {"input_tokens": 5}}
    q = {"tier": {"type": "choice", "instructions": "pick", "criteria": {"low": "a", "medium": "b", "high": "c", "xhigh": "d"}}}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stub, "stub", threading.Lock()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        m = json.load(urllib.request.urlopen(base + "/v1/models"))
        assert m["models"][0]["device"] == "cpu", m
        req = urllib.request.Request(base + "/v1/systemone", json.dumps({"state": "x", "questions": q}).encode(),
                                     {"Content-Type": "application/json"})
        a = json.load(urllib.request.urlopen(req))
        t = a["answers"]["tier"]
        assert set(t) == {"type", "choice", "confidence", "probabilities"}, t
        assert t["choice"] == "high" and abs(sum(t["probabilities"].values()) - 1) < 1e-9, t
        assert abs(t["probabilities"]["high"] - 0.5 / 0.9) < 1e-9 and isinstance(a["latency_ms"], float), a
        for bad in ({"low": True}, {"low": -4, "high": 0}, {"low": 0}, {"low": float("nan")}, {"low": "0.9"}, [0.9]):
            try:
                map_answer({"type": "choice", "confidence": 0.3, "probabilities": bad}, q["tier"])
                raise AssertionError(f"accepted {bad!r}")
            except BadPrediction:
                pass
        try:  # malformed body -> 400, not a crash
            urllib.request.urlopen(urllib.request.Request(base + "/v1/systemone", b"{}"))
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch, laya
    torch.set_num_threads(a.threads)
    agent = laya.load(REPO, device="cpu", subfolder=SUB)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(agent.predict, f"{REPO}/{SUB}", threading.Lock()))
    print(f"laya_serve on 127.0.0.1:{a.port}, {a.threads} threads", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
