"""Role policy comes from routes.json: Claude general-purpose + model + effort, Codex model + effort tiers.
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


def claude(brief, effort, model, routes=None, st="general-purpose", **extra):
    """A native Agent call: subagent_type (omitted when st is None), model and effort (each omitted when None)."""
    inp = {"prompt": brief, **extra}
    for k, v in (("subagent_type", st), ("model", model), ("effort", effort)):
        if v is not None:
            inp[k] = v
    return tw.decide("claude", {"tool_input": inp}, routes or R)


def codex(brief, model, effort=None, v2=False, routes=None):
    inp = {"message": brief, "model": model, "fork_turns": "none"}
    if effort:
        inp["reasoning_effort"] = effort
    return tw.decide("codex", {"tool_name": "collaborationspawn_agent" if v2 else "spawn_agent",
                               "tool_input": inp}, routes or R)


def pipeline(brief, model, effort="high"):
    """The synthetic call `tw.py codex` passes to decide()."""
    return tw.decide("claude", {"tool_name": "codex", "tool_input": {
        "subagent_type": "general-purpose", "prompt": brief, "model": model, "effort": effort}}, R)


RETIRED = ('subagent_type tw-worker-high is a retired thinker-worker agent (agent files removed 2026-11-24); retry '
           'with subagent_type: "general-purpose", model: "opus", effort: "high" and the same prompt')

CASES = [
    ("claude worker opus", claude(W, "low", "opus").admitted, True),
    ("claude tier is the effort", claude(W, "xhigh", "opus").tier, "xhigh"),
    ("claude model not admitted", claude(W, "high", "not-a-model").admitted, False),
    ("model required", claude(W, "high", None).reason,
     'explicit model is required; inherited/omitted model is disallowed: add model: "opus" or another native alias '
     'worker admits'),
    ("effort required", claude(W, None, "opus").reason,
     "explicit effort is required: one of worker's tiers ['low', 'medium', 'high', 'xhigh', 'max'] on opus"),
    ("sonnet worker high", claude(W, "high", "sonnet").admitted, True),
    ("sonnet worker xhigh", claude(W, "xhigh", "sonnet").admitted, True),
    ("sonnet worker medium (every model, every tier)", claude(W, "medium", "sonnet").admitted, True),
    ("sonnet worker low", claude(W, "low", "sonnet").admitted, True),
    ("sonnet worker max", claude(W, "max", "sonnet").admitted, True),
    ("narrowed: sonnet worker medium refused", claude(W, "medium", "sonnet", N).admitted, False),
    ("narrowed: sonnet worker low refused", claude(W, "low", "sonnet", N).reason,
     "effort low is outside worker's tiers ['high', 'xhigh'] on sonnet"),
    ("narrowed: opus keeps the role ladder", claude(W, "low", "opus", N).admitted, True),
    ("haiku worker", claude(W, "high", "haiku").admitted, True),
    ("haiku 5.5 review", claude(REV, "max", "claude-haiku-5-5").admitted, True),
    ("worker first model stays opus", R["harnesses"]["claude"]["roles"]["worker"]["models"][0], "opus"),
    ("leaf sonnet 5.5 id", claude(LEAF, "medium", "claude-sonnet-5-5").admitted, True),
    ("worker max", claude(W, "max", "opus").admitted, True),
    ("worker max tier recorded", claude(W, "max", "opus").tier, "max"),
    ("no tier beyond max", claude(W, "ultra", "opus").admitted, False),
    ("narrowed: worker max outside role", claude(W, "max", "opus", N).admitted, False),
    ("leaf on opus refused (not a leaf model)", claude(LEAF, "low", "opus").admitted, False),
    ("leaf xhigh", claude(LEAF, "xhigh", "sonnet").admitted, True),
    ("leaf max", claude(LEAF, "max", "haiku").admitted, True),
    ("narrowed: leaf tier outside role", claude(LEAF, "xhigh", "sonnet", N).admitted, False),
    ("leaf high", claude(LEAF, "high", "sonnet").admitted, True),
    ("leaf medium", claude(LEAF, "medium", "sonnet").admitted, True),
    ("retired tier agent: denial gives the exact new form", claude(W, None, None, st="tw-worker-high").reason, RETIRED),
    ("retired agent with a per-call model keeps it", 'model: "sonnet", effort: "low"' in
     claude(LEAF, None, "sonnet", st="tw-leaf-low").reason, True),
    ("retired agent, explicit effort wins over the name", 'effort: "max"' in
     claude(W, "max", "opus", st="tw-worker-high").reason, True),
    ("retired Opus 5.5 pin -> model opus", 'model: "opus", effort: "max"' in
     claude(REV, None, None, st="tw-independent-review-max-opus55").reason, True),
    ("retired agent on a Codex model -> tw.py codex",
     "run `tw.py codex --role worker --tier high --model gpt-6.2-sol` instead" in
     claude(W, None, "gpt-6.2-sol", st="tw-worker-high").reason, True),
    ("omitted subagent_type refused with the form", claude(W, "high", "opus", st=None).reason,
     'subagent_type is required; retry with subagent_type: "general-purpose", model: "opus", effort: "high" and the '
     'same prompt'),
    ("omitted type and effort: the form suggests the class prior", 'effort: "high"' in
     claude(W, None, "opus", st=None).reason, True),
    ("other built-in type refused", claude(W, "high", "opus", st="Explore").admitted, False),
    ("old hand-written agent refused", claude(W, "high", "opus", st="thinker-worker-opus").admitted, False),
    ("miners are not a route", claude(W, "high", "opus", st="effortmining:miner-high").admitted, False),
    ("review on fable", claude(REV, "high", "fable").admitted, True),
    ("review medium allowed", claude(REV, "medium", "fable").admitted, True),
    ("review low", claude(REV, "low", "fable").admitted, True),
    ("review max", claude(REV, "max", "fable").admitted, True),
    ("narrowed: review low below floor", claude(REV, "low", "fable", N).admitted, False),
    ("native review on astra refused (tw.py codex)", claude(REV, "high", "gpt-6-astra").admitted, False),
    ("native review on sol 6.1 refused (tw.py codex)", claude(REV, "high", "gpt-6.1-sol").admitted, False),
    ("sol 6.1 review pipeline", pipeline(REV, "gpt-6.1-sol").admitted, True),
    ("native ideation on astra refused", claude(IDEA, "medium", "gpt-6-astra").admitted, False),
    ("worker on legacy astra refused", claude(W, "high", "gpt-6-astra").admitted, False),
    ("native Claude worker on astra 6.2 refused", claude(W, "high", "gpt-6.2-astra").admitted, False),
    ("Codex redirect comes before the effort check", claude(W, None, "gpt-6.2-astra").reason,
     "model gpt-6.2-astra is a Codex model; dispatch it with `tw.py codex --model gpt-6.2-astra`"),
    ("Claude to Codex astra 6.2 worker", pipeline(W, "gpt-6.2-astra").admitted, True),
    ("codex astra 6.2 worker", codex(W, "gpt-6.2-astra", "high").admitted, True),
    ("codex sol 6.2 worker", codex(W, "gpt-6.2-sol", "high").admitted, True),
    ("codex astra 6.2 reviewer", codex(REV, "gpt-6.2-astra", "high").admitted, True),
    ("codex astra 6.2 ideation", codex(IDEA, "gpt-6.2-astra", "medium").admitted, True),
    ("codex astra 6.2 ideation below floor", codex(IDEA, "gpt-6.2-astra", "low").admitted, False),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""), "high", "fable").admitted, False),
    ("ideation on opus per call", claude(IDEA, "high", "opus").admitted, True),
    ("ideation on sonnet refused", claude(IDEA, "xhigh", "sonnet").admitted, False),
    ("ideation max outside its tiers", claude(IDEA, "max", "fable").admitted, False),
    ("review on alias opus requests Opus 5.5", claude(REV, "high", "opus")[:5],
     (True, "admitted-request-only", "independent-review", "claude-opus-5-5", "high")),
    ("ideation first model stays fable", R["harnesses"]["claude"]["roles"]["ideation"]["models"][0], "fable"),
    ("denial names model and role", claude(W, "high", "not-a-model").reason, "model not-a-model is not allowed for worker"),
    ("fork refused", claude(W, "high", "opus", fork=True).admitted, False),
    ("fork type refused", claude(W, "high", "opus", st="fork").admitted, False),
    ("role line split on \\n only", claude("TW-Role: worker " + HDR + "x", "high", "opus").admitted, False),
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
    ("v2 legacy astra high, role null", codex("<cipher>", "gpt-6-astra", "high", v2=True)[:3:2], (True, None)),
    ("v2 astra 6.2 high, inferred worker", codex("<cipher>", "gpt-6.2-astra", "high", v2=True)[:3:2],
     (True, "worker")),
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
            env = envelope(session, {"subagent_type": "general-purpose", "model": "opus", "effort": "high",
                                     "prompt": brief + "\n\n" + tw.role_text("worker")}, tool_use_id="t1")
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
