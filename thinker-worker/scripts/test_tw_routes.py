"""Role policy comes from routes.json: Claude tier agents tw-<role>-<tier>, Codex model + effort tiers.
Run: python test_tw_routes.py"""
import tw
from test_tw_receipt import AUTH, HDR, REV, W

R = tw.load_routes(tw.source_root() / "routes.json")  # explicit path: never a user override file
LEAF = "TW-Role: leaf\n" + HDR + "x"
IDEA = "TW-Role: ideation\n" + AUTH + HDR + "x"


def claude(brief, st, model=None, **extra):
    inp = {"subagent_type": st, "prompt": brief, **extra}
    if model:
        inp["model"] = model
    return tw.decide("claude", {"tool_input": inp}, R)


def codex(brief, model, effort=None, v2=False):
    inp = {"message": brief, "model": model, "fork_turns": "none"}
    if effort:
        inp["reasoning_effort"] = effort
    return tw.decide("codex", {"tool_name": "collaborationspawn_agent" if v2 else "spawn_agent",
                               "tool_input": inp}, R)


CASES = [
    ("claude worker tier agent, no model", claude(W, "tw-worker-low").admitted, True),
    ("claude tier recorded", claude(W, "tw-worker-xhigh").tier, "xhigh"),
    ("claude matching per-call model", claude(W, "tw-worker-high", "opus").admitted, True),
    ("claude per-call model mismatch", claude(W, "tw-worker-high", "sonnet").admitted, False),
    ("no max tier", claude(W, "tw-worker-max").admitted, False),
    ("role/agent mismatch", claude(W, "tw-leaf-low").admitted, False),
    ("leaf tier outside role", claude(LEAF, "tw-leaf-high").admitted, False),
    ("leaf medium", claude(LEAF, "tw-leaf-medium").admitted, True),
    ("old hand-written agent refused", claude(W, "thinker-worker-opus", "opus").admitted, False),
    ("miners are not a route", claude(W, "effortmining:miner-high", "opus").admitted, False),
    ("review tier agent", claude(REV, "tw-independent-review-high").admitted, True),
    ("review medium allowed", claude(REV, "tw-independent-review-medium").admitted, True),
    ("review low below floor", claude(REV, "tw-independent-review-low").admitted, False),
    ("native review on astra refused (tw.py codex)", claude(REV, "tw-independent-review-high", "gpt-6-astra").admitted, False),
    ("native ideation on astra refused", claude(IDEA, "tw-ideation-medium", "gpt-6-astra").admitted, False),
    ("worker on astra refused", claude(W, "tw-worker-high", "gpt-6-astra").admitted, False),
    ("review default is astra", R["router"]["defaults"]["independent-review"], "gpt-6-astra"),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""), "tw-ideation-high").admitted, False),
    ("ideation on opus per call", claude(IDEA, "tw-ideation-high", "opus").admitted, True),
    ("ideation on sonnet refused", claude(IDEA, "tw-ideation-xhigh", "sonnet").admitted, False),
    ("review refuses opus", claude(REV, "tw-independent-review-high", "opus").admitted, False),
    ("ideation agent file stays fable", R["harnesses"]["claude"]["roles"]["ideation"]["models"][0], "fable"),
    ("denial names model and role", claude(W, "tw-worker-high", "sonnet").reason, "model sonnet is not allowed for worker"),
    ("fork refused", claude(W, "tw-worker-high", fork=True).admitted, False),
    ("role line split on \\n only", claude("TW-Role: worker " + HDR + "x", "tw-worker-high").admitted, False),
    ("codex worker sol high", codex(W, "gpt-6-sol", "high").admitted, True),
    ("codex worker terra", codex(W, "gpt-5.6-terra", "medium").admitted, True),
    ("codex max refused", codex(W, "gpt-6-sol", "max").admitted, False),
    ("codex worker effort required", codex(W, "gpt-6-sol").admitted, False),
    ("codex review effort required", codex(REV, "gpt-6-astra").admitted, False),
    ("codex review low below floor", codex(REV, "gpt-6-astra", "low").admitted, False),
    ("codex ideation medium", codex(IDEA, "gpt-6-astra", "medium").admitted, True),
    ("codex ideation on sol", codex(IDEA, "gpt-6-sol", "high").admitted, False),
    ("codex leaf luna low", codex(LEAF, "gpt-6-luna", "low").admitted, True),
    ("v2 astra needs effort", codex("<cipher>", "gpt-6-astra", v2=True).admitted, False),
    ("v2 astra high, role null", codex("<cipher>", "gpt-6-astra", "high", v2=True)[:3:2], (True, None)),
    ("v2 unknown model", codex("<cipher>", "gpt-9", "high", v2=True).admitted, False),
]

if __name__ == "__main__":
    bad = [(name, got, want) for name, got, want in CASES if got != want]
    for b in bad:
        print("FAIL", b)
    assert not bad
    import json, tempfile
    from pathlib import Path
    good = {"backends": [], "budget_s": 2.0, "classes": {"*": {"mode": "shadow"}},
            "risk_floor": {"physics": "high", "destructive": "medium", "external": "medium"},
            "priors": {"*": "medium"}, "combine": {"margin": 0.2}}
    dec = {"c": 0.5, "power": 0.25, "floor": 0.05}
    with tempfile.TemporaryDirectory() as tmp:
        for router, ok in [(good, True), (None, False), ([], False), ({**good, "backends": "table"}, False),
                           ({**good, "budget_s": 0}, False), ({**good, "budget_s": "2"}, False),
                           ({**good, "budget_s": True}, False), ({**good, "classes": {}}, False),
                           ({**good, "classes": {"*": {}}}, False),
                           ({**good, "risk_floor": {"physics": "high"}}, False),                         # every flag needs a floor
                           ({**good, "risk_floor": {**good["risk_floor"], "physics": "max"}}, False),    # a real tier
                           ({k: v for k, v in good.items() if k != "risk_floor"}, False),
                           ({k: v for k, v in good.items() if k != "priors"}, False),                    # priors required
                           ({**good, "priors": {"C-coding": "high"}}, False),                            # "*" required
                           ({**good, "priors": {"*": "medium", "C-cooding": "high"}}, False),            # unknown class
                           ({**good, "priors": {"*": "max"}}, False),                                    # a real tier
                           ({**good, "classes": {"*": {"mode": "bogus"}}}, False),                       # a real mode
                           ({**good, "classes": {"*": {"mode": "shadow"}, "X": {"mode": "shadow"}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": 1.5}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": dec}}}, True),     # decaying
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {**dec, "floor": 1.5}}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {**dec, "c": 0}}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {**dec, "power": -1}}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {**dec, "c": True}}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {"c": 0.5, "power": 0.25}}}}, False),
                           ({**good, "classes": {"*": {"mode": "shadow", "explore": {**dec, "x": 1}}}}, False),
                           # decision-model blocks (design D11): jev backends, combine margin/weights, option wording
                           ({**good, "backends": ["kev"], "kev": {"kind": "jev", "url": "http://x/v1/systemone",
                                                                  "body_chars": 1500}}, True),
                           ({**good, "kev": {"kind": "jev", "url": 8766}}, False),
                           ({**good, "kev": {"kind": "jev", "url": "http://x", "body_chars": 0}}, False),
                           ({**good, "kev": {"kind": "jev", "url": "http://x", "body_chars": True}}, False),
                           ({**good, "backends": [1]}, False),
                           ({**good, "combine": {"margin": 0.2, "weights": {"kev": 0.5}}}, True),
                           ({k: v for k, v in good.items() if k != "combine"}, False),                   # required
                           ({**good, "combine": {"margin": 1.5}}, False),
                           ({**good, "combine": {}}, False),
                           ({**good, "combine": {"margin": 0.2, "weights": {"kev": -1}}}, False),
                           ({**good, "options": {"low": "l", "medium": "m"}}, True),
                           ({**good, "options": {"max": "m"}}, False),
                           ({**good, "options": {"low": ""}}, False)]:
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
    with tempfile.TemporaryDirectory() as tmp:           # TW_ROUTES (tests pin shadow); an explicit path wins
        env_file, arg_file = Path(tmp) / "env.json", Path(tmp) / "arg.json"
        for p, mode in ((env_file, "shadow"), (arg_file, "active")):
            p.write_text(json.dumps({**R, "router": {**R["router"], "classes": {"*": {"mode": mode}}}}), encoding="utf-8")
        old = os.environ.get("TW_ROUTES")
        os.environ["TW_ROUTES"] = str(env_file)
        try:
            assert tw.load_routes()["router"]["classes"]["*"]["mode"] == "shadow"
            assert tw.load_routes(arg_file)["router"]["classes"]["*"]["mode"] == "active"
        finally:
            os.environ.pop("TW_ROUTES") if old is None else os.environ.__setitem__("TW_ROUTES", old)
    # switch-on T4c: tier priors live in router.priors; no role carries a `default`
    assert R["router"]["priors"] == {"*": "medium", "T1-mechanical": "low", "T2-simple-transform": "low",
                                     "T3-moderate-reasoning": "medium", "T4-hard-reasoning": "high",
                                     "R-research": "medium", "C-coding": "high"}, R["router"]["priors"]
    assert not [(h, r) for h in R["harnesses"] for r, pol in R["harnesses"][h]["roles"].items() if "default" in pol]
    assert tw.prior(R, "claude", "worker", "C-coding") == "high"
    assert tw.prior(R, "claude", "independent-review", "T1-mechanical") == "medium"    # clamped to the review ladder
    assert tw.prior(R, "codex", "ideation", "T1-mechanical") == "medium"

    from test_tw_hook import envelope, pinned_routes, run_main
    hdr = "TW-Class: {}\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"
    with pinned_routes(), tempfile.TemporaryDirectory() as tmp:     # route CLI: prior tier, exploration pinned off
        for cls, role, want in (("C-coding", "worker", "high"), ("T1-mechanical", "worker", "low"),
                                ("T1-mechanical", "independent-review", "medium")):
            f = Path(tmp) / "b.md"
            f.write_text(f"TW-Role: {role}\n" + hdr.format(cls), encoding="utf-8")
            code, out = run_main(["route", "--harness", "claude", "--role", role, "--brief-file", str(f)])
            assert code == 0 and json.loads(out)["tier"] == want, (cls, role, out)
        code, out = run_main(["activate", "--home", tmp, "--harness", "claude", "--session", "s-priors"])
        assert code == 0 and "C-coding=high" in out and "T1-mechanical=low" in out, out
        assert "Tier priors (installed routes.json): *=medium," in out and "risk floors: physics=medium" in out, out
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
            doc = loaded(json.dumps({"router": {"classes": {"C-coding": {"explore": 0.5}}}}))   # partial entry
            assert tw.class_mode(doc, "C-coding") == ("advisory", 0.5), doc["router"]["classes"]  # inherits "*" mode
            assert tw.class_mode(doc, "T1-mechanical") == ("advisory", dec)     # the shipped "*" schedule
            doc = loaded(json.dumps({"router": {"classes": {"*": {"mode": "shadow"}, "C-coding": {"explore": 0.5}}}}))
            assert tw.class_mode(doc, "C-coding") == ("shadow", 0.5), doc["router"]["classes"]
            doc = loaded(json.dumps({"router": {"risk_floor": {"physics": "xhigh"}}}))
            assert doc["router"]["risk_floor"] == {"physics": "xhigh", "destructive": "medium", "external": "medium"}
            # decision models (design D11): router.backends replaces; per-backend jev blocks, combine, options merge
            doc = loaded(json.dumps({"router": {"backends": ["kev"], "kev": {"url": "http://127.0.0.1:9/v1/systemone"},
                                                "combine": {"margin": 0.1}, "options": {"low": "terse"}}}))
            rt = doc["router"]
            assert "_override_error" not in doc and rt["backends"] == ["kev"], doc.get("_override_error")
            assert rt["kev"] == {**R["router"]["kev"], "url": "http://127.0.0.1:9/v1/systemone"}, rt["kev"]
            assert rt["combine"] == {"margin": 0.1} and rt["laya"] == R["router"]["laya"], rt
            assert rt["options"] == {**R["router"]["options"], "low": "terse"}, rt["options"]
            doc = loaded(json.dumps({"router": {"backends": ["mine"], "mine": {"kind": "jev", "url": "http://x"}}}))
            assert doc["router"]["mine"] == {"kind": "jev", "url": "http://x"} and "_override_error" not in doc, doc
            # fails open: any bad override leaves the installed doc unchanged and says why
            for bad in (json.dumps({"harnesses": {}}), json.dumps({"router": {"backends": "kev"}}), "{not json",
                        json.dumps({"router": {"table": {"path": "x"}}}), json.dumps({"router": {"budget_s": 5}}),
                        json.dumps({"router": {"cutoff": 0.5}}), json.dumps({"router": {"mine": {"url": "http://x"}}}),
                        json.dumps({"router": {"combine": {"margin": 2}}}), json.dumps({"router": {"kev": {"url": 1}}}),
                        json.dumps({"router": {"priors": {"C-coding": "max"}}}),
                        json.dumps({"router": {"classes": {"C-coding": {"mode": "bogus"}}}}), "[]"):
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
            coin = lambda b: tw.coin(tw.ticket(b)[0])
            brief = next(b for b in ("TW-Role: worker\n" + hdr.format("C-coding") + str(i) for i in range(50))
                         if coin(b) >= 0.5)                   # shipped eps at t=1 is 0.5: stay unexplored
            env = envelope(session, {"subagent_type": "tw-worker-high", "prompt": brief}, tool_use_id="t1")
            code, out = run_main(["hook", "--home", tmp, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))
            assert code == 0 and out == "", out
            rows = tw.read_rows(tw.receipts_path(Path(tmp), "claude", session))
            assert [r["kind"] for r in rows] == ["dispatch", "error", "route"] and rows[0]["decision"] == "admit", rows
            assert rows[1]["where"] == "override" and "override" in rows[1]["error"], rows[1]
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    print(f"PASS {len(CASES)} route-policy cases; router block validated; priors, route CLI, activate/status line, "
          "user override (merge, fail-open, pinned-out)")
