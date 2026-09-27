"""Role policy comes from routes.json: Claude tier agents tw-<role>-<tier>, Codex model + effort tiers.
Run: python test_tw_routes.py"""
import tw

R = tw.load_routes()
HDR = "TW-Class: C-coding\nTW-Deliverable: patch\nTW-Accept: tests pass\nTW-Risk: none\n"
AUTH = "TW-Authorization: t\nTW-Scope: t\n"
W = "TW-Role: worker\n" + HDR + "x"
LEAF = "TW-Role: leaf\n" + HDR + "x"
REV = "TW-Role: independent-review\n" + AUTH + HDR + "x"
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
    ("review below its floor", claude(REV, "tw-independent-review-medium").admitted, False),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""), "tw-ideation-high").admitted, False),
    ("ideation on opus refused", claude(IDEA, "tw-ideation-high", "opus").admitted, False),
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
    good = {"backends": [], "budget_s": 2.0, "classes": {"*": {"mode": "shadow"}}}
    with tempfile.TemporaryDirectory() as tmp:
        for router, ok in [(good, True), (None, False), ([], False), ({**good, "backends": "table"}, False),
                           ({**good, "budget_s": 0}, False), ({**good, "budget_s": "2"}, False),
                           ({**good, "budget_s": True}, False), ({**good, "classes": {}}, False),
                           ({**good, "classes": {"*": {}}}, False)]:
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
    print(f"PASS {len(CASES)} route-policy cases; router block validated")
