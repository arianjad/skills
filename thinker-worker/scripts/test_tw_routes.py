"""Role policy comes from routes.json: Claude tier agents tw-<role>-<tier>, Codex model + effort tiers.
Run: python test_tw_routes.py"""
import json

import tw
from test_tw_receipt import AUTH, HDR, REV, W

R = tw.load_routes(tw.source_root() / "routes.json")  # explicit path: never a user override file


def narrowed(doc: dict) -> dict:
    """A test-local copy with narrower ladders (the pre-2026-11-01 shipped ones), so the logic that enforces a role's
    tiers and a model's `model_tiers` stays exercised now that the shipped roles admit every tier on every model."""
    d = json.loads(json.dumps(doc))
    for h in ("claude", "codex"):
        roles = d["harnesses"][h]["roles"]
        roles["worker"]["tiers"] = ["low", "medium", "high", "xhigh"]
        roles["leaf"]["tiers"] = ["low", "medium", "high"]
        roles["independent-review"]["tiers"] = ["medium", "high", "xhigh"]
    d["harnesses"]["claude"]["roles"]["worker"]["model_tiers"] = {"sonnet": ["high", "xhigh"]}
    return d


N = narrowed(R)
LEAF = "TW-Role: leaf\n" + HDR + "x"
IDEA = "TW-Role: ideation\n" + AUTH + HDR + "x"


def claude(brief, st, model=None, routes=None, **extra):
    inp = {"subagent_type": st, "prompt": brief, **extra}
    if model:
        inp["model"] = model
    return tw.decide("claude", {"tool_input": inp}, routes or R)


def codex(brief, model, effort=None, v2=False, routes=None):
    inp = {"message": brief, "model": model, "fork_turns": "none"}
    if effort:
        inp["reasoning_effort"] = effort
    return tw.decide("codex", {"tool_name": "collaborationspawn_agent" if v2 else "spawn_agent",
                               "tool_input": inp}, routes or R)


CASES = [
    ("claude worker tier agent, no model", claude(W, "tw-worker-low").admitted, True),
    ("claude tier recorded", claude(W, "tw-worker-xhigh").tier, "xhigh"),
    ("claude matching per-call model", claude(W, "tw-worker-high", "opus").admitted, True),
    ("claude per-call model mismatch", claude(W, "tw-worker-high", "not-a-model").admitted, False),
    ("sonnet worker high", claude(W, "tw-worker-high", "sonnet").admitted, True),
    ("sonnet worker xhigh", claude(W, "tw-worker-xhigh", "sonnet").admitted, True),
    ("sonnet worker medium (every model, every tier)", claude(W, "tw-worker-medium", "sonnet").admitted, True),
    ("sonnet worker low", claude(W, "tw-worker-low", "sonnet").admitted, True),
    ("sonnet worker max", claude(W, "tw-worker-max", "sonnet").admitted, True),
    ("narrowed: sonnet worker medium refused", claude(W, "tw-worker-medium", "sonnet", N).admitted, False),
    ("narrowed: sonnet worker low refused", claude(W, "tw-worker-low", "sonnet", N).reason,
     "tier low is outside worker's tiers ['high', 'xhigh'] on sonnet"),
    ("narrowed: opus keeps the role ladder", claude(W, "tw-worker-low", "opus", N).admitted, True),
    ("haiku worker", claude(W, "tw-worker-high", "haiku").admitted, True),
    ("haiku 5.5 review", claude(REV, "tw-independent-review-max", "claude-haiku-5-5").admitted, True),
    ("worker agent file stays opus", R["harnesses"]["claude"]["roles"]["worker"]["models"][0], "opus"),
    ("leaf sonnet 5.5 id", claude(LEAF, "tw-leaf-medium", "claude-sonnet-5-5").admitted, True),
    ("worker max", claude(W, "tw-worker-max").admitted, True),
    ("worker max tier recorded", claude(W, "tw-worker-max").tier, "max"),
    ("no tier beyond max", claude(W, "tw-worker-ultra").admitted, False),
    ("narrowed: worker max outside role", claude(W, "tw-worker-max", routes=N).admitted, False),
    ("role/agent mismatch", claude(W, "tw-leaf-low").admitted, False),
    ("leaf xhigh", claude(LEAF, "tw-leaf-xhigh").admitted, True),
    ("leaf max", claude(LEAF, "tw-leaf-max", "haiku").admitted, True),
    ("narrowed: leaf tier outside role", claude(LEAF, "tw-leaf-xhigh", routes=N).admitted, False),
    ("leaf high", claude(LEAF, "tw-leaf-high").admitted, True),
    ("leaf medium", claude(LEAF, "tw-leaf-medium").admitted, True),
    ("old hand-written agent refused", claude(W, "thinker-worker-opus", "opus").admitted, False),
    ("miners are not a route", claude(W, "effortmining:miner-high", "opus").admitted, False),
    ("review tier agent", claude(REV, "tw-independent-review-high").admitted, True),
    ("review medium allowed", claude(REV, "tw-independent-review-medium").admitted, True),
    ("review low", claude(REV, "tw-independent-review-low").admitted, True),
    ("review max", claude(REV, "tw-independent-review-max").admitted, True),
    ("narrowed: review low below floor", claude(REV, "tw-independent-review-low", routes=N).admitted, False),
    ("native review on astra refused (tw.py codex)", claude(REV, "tw-independent-review-high", "gpt-6-astra").admitted, False),
    ("native review on sol 6.1 refused (tw.py codex)", claude(REV, "tw-independent-review-high", "gpt-6.1-sol").admitted, False),
    ("sol 6.1 review pipeline", tw.decide("claude", {"tool_name": "codex", "tool_input": {
        "subagent_type": "tw-independent-review-high", "prompt": REV, "model": "gpt-6.1-sol"}}, R).admitted, True),
    ("native ideation on astra refused", claude(IDEA, "tw-ideation-medium", "gpt-6-astra").admitted, False),
    ("worker on astra refused", claude(W, "tw-worker-high", "gpt-6-astra").admitted, False),
    ("review default is astra", R["router"]["defaults"]["independent-review"], "gpt-6-astra"),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""), "tw-ideation-high").admitted, False),
    ("ideation on opus per call", claude(IDEA, "tw-ideation-high", "opus").admitted, True),
    ("ideation on sonnet refused", claude(IDEA, "tw-ideation-xhigh", "sonnet").admitted, False),
    ("review refuses opus", claude(REV, "tw-independent-review-high", "opus").admitted, False),
    ("ideation agent file stays fable", R["harnesses"]["claude"]["roles"]["ideation"]["models"][0], "fable"),
    ("denial names model and role", claude(W, "tw-worker-high", "not-a-model").reason, "model not-a-model is not allowed for worker"),
    ("fork refused", claude(W, "tw-worker-high", fork=True).admitted, False),
    ("role line split on \\n only", claude("TW-Role: worker " + HDR + "x", "tw-worker-high").admitted, False),
    ("codex worker sol high", codex(W, "gpt-6-sol", "high").admitted, True),
    ("codex worker terra", codex(W, "gpt-5.6-terra", "medium").admitted, True),
    ("codex worker max", codex(W, "gpt-6-sol", "max").admitted, True),
    ("codex worker terra 6.1 max", codex(W, "gpt-6.1-terra", "max").admitted, True),
    ("codex tier beyond max refused", codex(W, "gpt-6-sol", "ultra").admitted, False),
    ("narrowed: codex max refused", codex(W, "gpt-6-sol", "max", routes=N).admitted, False),
    ("codex worker effort required", codex(W, "gpt-6-sol").admitted, False),
    ("codex review effort required", codex(REV, "gpt-6-astra").admitted, False),
    ("codex review low", codex(REV, "gpt-6-astra", "low").admitted, True),
    ("codex review terra 6.1", codex(REV, "gpt-6.1-terra", "high").admitted, True),
    ("narrowed: codex review low below floor", codex(REV, "gpt-6-astra", "low", routes=N).admitted, False),
    ("narrowed: sol 6.1 review low refused", codex(REV, "gpt-6.1-sol", "low", routes=N).admitted, False),
    ("codex ideation medium", codex(IDEA, "gpt-6-astra", "medium").admitted, True),
    ("codex ideation on sol", codex(IDEA, "gpt-6-sol", "high").admitted, False),
    ("codex leaf luna low", codex(LEAF, "gpt-6-luna", "low").admitted, True),
    ("codex leaf luna high", codex(LEAF, "gpt-6-luna", "high").admitted, True),
    ("codex leaf luna xhigh", codex(LEAF, "gpt-6-luna", "xhigh").admitted, True),
    ("codex leaf terra 6.1 max", codex(LEAF, "gpt-6.1-terra", "max").admitted, True),
    ("narrowed: codex leaf luna xhigh refused", codex(LEAF, "gpt-6-luna", "xhigh", routes=N).admitted, False),
    ("v2 astra needs effort", codex("<cipher>", "gpt-6-astra", v2=True).admitted, False),
    ("v2 astra high, role null", codex("<cipher>", "gpt-6-astra", "high", v2=True)[:3:2], (True, None)),
    ("v2 sol 6.1 shared-model role inferred as worker", codex("<cipher>", "gpt-6.1-sol", "medium", v2=True).role, "worker"),
    ("v2 unknown model", codex("<cipher>", "gpt-9", "high", v2=True).admitted, False),
]

CASES += [(f"sol 6.1 review {tier}", codex(REV, "gpt-6.1-sol", tier).admitted, True)
          for tier in tw.TIERS]

if __name__ == "__main__":
    bad = [(name, got, want) for name, got, want in CASES if got != want]
    for b in bad:
        print("FAIL", b)
    assert not bad
    import tempfile
    from pathlib import Path
    good = {"priors": {"*": "medium"}}
    with tempfile.TemporaryDirectory() as tmp:
        for router, ok in [(good, True), (None, False), ([], False),
                           ({k: v for k, v in good.items() if k != "priors"}, False),                    # priors required
                           ({**good, "priors": {"C-coding": "high"}}, False),                            # "*" required
                           ({**good, "priors": {"*": "medium", "C-cooding": "high"}}, False),            # unknown class
                           ({**good, "priors": {"*": "ultra"}}, False)]:                                 # a real tier
            doc = {**R, "router": router}
            if router is None:
                del doc["router"]
            p = Path(tmp) / "routes.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            try:
                tw.load_routes(p)
                got = True
            except tw.Conflict as exc:
                got = False
                assert "bad router block" in str(exc), exc
            assert got == ok, router
    import os
    with tempfile.TemporaryDirectory() as tmp:           # TW_ROUTES (tests pin their routing); an explicit path wins
        env_file, arg_file = Path(tmp) / "env.json", Path(tmp) / "arg.json"
        for p, tier in ((env_file, "low"), (arg_file, "high")):
            p.write_text(json.dumps({**R, "router": {**R["router"], "priors": {"*": tier}}}), encoding="utf-8")
        old = os.environ.get("TW_ROUTES")
        os.environ["TW_ROUTES"] = str(env_file)
        try:
            assert tw.load_routes()["router"]["priors"] == {"*": "low"}
            assert tw.load_routes(arg_file)["router"]["priors"] == {"*": "high"}
        finally:
            os.environ.pop("TW_ROUTES") if old is None else os.environ.__setitem__("TW_ROUTES", old)
    # switch-on T4c: tier priors live in router.priors; no role carries a `default`
    assert R["router"]["priors"] == {"*": "medium", "T1-mechanical": "low", "T2-simple-transform": "low",
                                     "T3-moderate-reasoning": "medium", "T4-hard-reasoning": "high",
                                     "R-research": "medium", "C-coding": "high"}, R["router"]["priors"]
    assert not [(h, r) for h in R["harnesses"] for r, pol in R["harnesses"][h]["roles"].items() if "default" in pol]
    assert tw.prior(R, "claude", "worker", "C-coding") == "high"
    with tempfile.TemporaryDirectory() as tmp:  # every tier list is a ladder: non-empty, unique, in TIERS order
        for mt, ok in (({"sonnet": ["high", "xhigh"]}, True), ({"sonnet": ["xhigh", "high"]}, False),
                       ({"sonnet": ["high", "high"]}, False), ({"sonnet": []}, False), ({"sonnet": "high"}, False),
                       ({"sonnet": ["max"]}, False), ({"sonnet": ["ultra"]}, False), ({"not-a-model": ["high"]}, False),
                       ([], False)):
            doc = json.loads(json.dumps(R))
            doc["harnesses"]["claude"]["roles"]["worker"]["tiers"] = ["low", "medium", "high", "xhigh"]  # max: outside
            doc["harnesses"]["claude"]["roles"]["worker"]["model_tiers"] = mt
            p = Path(tmp) / "mt.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            try:
                tw.load_routes(p)
                got = True
            except tw.Conflict as exc:
                got = False
                assert "bad policy for claude/worker" in str(exc), exc
            assert got == ok, mt
        doc = json.loads(json.dumps(R))
        doc["harnesses"]["claude"]["roles"]["leaf"]["tiers"] = ["medium", "low"]
        p.write_text(json.dumps(doc), encoding="utf-8")
        try:
            tw.load_routes(p)
            raise AssertionError("reversed role tiers accepted")
        except tw.Conflict:
            pass
    assert tw.prior(R, "claude", "independent-review", "T1-mechanical") == "low"       # the shipped review ladder has low
    assert tw.prior(N, "claude", "independent-review", "T1-mechanical") == "medium"    # clamped to a narrowed ladder
    assert tw.prior(R, "codex", "ideation", "T1-mechanical") == "medium"

    from test_tw_hook import envelope, pinned_routes, run_main
    hdr = "TW-Class: {}\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"
    with pinned_routes(), tempfile.TemporaryDirectory() as tmp:     # activate/status print the priors
        code, out = run_main(["activate", "--home", tmp, "--harness", "claude", "--session", "s-priors"])
        assert code == 0 and "C-coding=high" in out and "T1-mechanical=low" in out, out
        assert "Tier priors (installed routes.json): *=medium," in out and "risk floors" not in out, out
        code, out = run_main(["status", "--home", tmp, "--harness", "claude", "--session", "s-priors"])
        assert code == 0 and "C-coding=high" in out and "T1-mechanical=low" in out, out

    # user override file: TW_ROUTES_OVERRIDE (else ~/.thinker-worker/routes.json), read only with no path/TW_ROUTES
    saved = {k: os.environ.pop(k, None) for k in ("TW_ROUTES", "TW_ROUTES_OVERRIDE")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ov = Path(tmp) / "override.json"
            os.environ["TW_ROUTES_OVERRIDE"] = str(ov)

            def loaded(text):
                ov.write_text(text, encoding="utf-8")
                return tw.load_routes()
            doc = loaded(json.dumps({"router": {"priors": {"C-coding": "medium"}}}))
            assert doc["router"]["priors"]["C-coding"] == "medium" and doc["router"]["priors"]["T1-mechanical"] == "low"
            assert doc["_override"] == str(ov) and "_override_error" not in doc, doc
            assert tw.prior(doc, "claude", "worker", "C-coding") == "medium"
            # retired router keys (an override written for the removed router) are ignored and named, not errors
            doc = loaded(json.dumps({"router": {"backends": [], "classes": {"*": {"mode": "active"}},
                                                "T4-hard-reasoning": {"explore": 0}, "priors": {"C-coding": "medium"}}}))
            assert "_override_error" not in doc, doc.get("_override_error")
            assert doc["router"]["priors"]["C-coding"] == "medium"
            assert doc["_override_ignored"] == ["T4-hard-reasoning", "backends", "classes"], doc["_override_ignored"]
            assert "ignored override keys: T4-hard-reasoning, backends, classes" in tw.priors_line(doc)
            assert set(doc["router"]) == {"priors", "model_priors", "defaults"}, set(doc["router"])
            # fails open: any bad override leaves the installed doc unchanged and says why
            for bad in (json.dumps({"harnesses": {}}), "{not json", json.dumps({"router": {"priors": "high"}}),
                        json.dumps({"router": {"priors": {"C-coding": "ultra"}}}),
                        json.dumps({"router": {"defaults": {"worker": "not-a-model"}}}), "[]"):
                doc = loaded(bad)
                assert doc.get("_override_error") and "_override" not in doc, (bad, doc)
                assert doc["router"] == R["router"] and doc["harnesses"] == R["harnesses"], bad
            os.environ["TW_ROUTES"] = str(tw.source_root() / "routes.json")   # a pin skips the override entirely
            doc = tw.load_routes()
            assert "_override_error" not in doc and "_override" not in doc, doc
            del os.environ["TW_ROUTES"]
            doc = tw.load_routes(tw.source_root() / "routes.json")                # so does an explicit path
            assert "_override_error" not in doc and "_override" not in doc, doc
            ov.unlink()
            assert "_override_error" not in tw.load_routes() and "_override" not in tw.load_routes()   # absent file

            # a bad override: the dispatch is admitted, one error row names it, status says it was ignored
            ov.write_text(json.dumps({"harnesses": {}}), encoding="utf-8")
            session = "s-override"
            code, out = run_main(["activate", "--home", tmp, "--harness", "claude", "--session", session])
            assert code == 0 and "Tier priors (override ignored: " in out, out
            code, out = run_main(["status", "--home", tmp, "--harness", "claude", "--session", session])
            assert code == 0 and "override ignored" in out, out
            brief = "TW-Role: worker\n" + hdr.format("C-coding")
            env = envelope(session, {"subagent_type": "tw-worker-high", "prompt": brief}, tool_use_id="t1")
            code, out = run_main(["hook", "--home", tmp, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))
            assert code == 0 and out == "", out
            rows = tw.read_rows(tw.receipts_path(Path(tmp), "claude", session))
            assert [r["kind"] for r in rows] == ["dispatch", "error"] and rows[0]["decision"] == "admit", rows
            assert rows[1]["where"] == "override" and "override" in rows[1]["error"], rows[1]
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    print(f"PASS {len(CASES)} route-policy cases; router block validated; priors, activate/status line, "
          "user override (merge, retired keys ignored, fail-open, pinned-out)")
