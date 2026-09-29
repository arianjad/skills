"""Adding a model: per-model priors (S1), their validation and override (S2).
Run: python test_tw_models.py"""
import json
import os
import tempfile
from pathlib import Path

import tw

R = tw.load_routes(tw.source_root() / "routes.json")


def with_model_priors(mp: dict) -> dict:
    doc = json.loads(json.dumps(R))
    doc["router"]["model_priors"] = mp
    return doc


def loads(doc: dict) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "routes.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        try:
            tw.load_routes(p)
            return True
        except tw.Conflict:
            return False


# S1: model_priors[model][class] > model_priors[model]["*"] > router.priors, clamped to the model's tiers
doc = with_model_priors({"gpt-6-sol": {"*": "low", "C-coding": "medium"}, "sonnet": {"*": "low"}})
assert tw.prior(doc, "claude", "worker", "C-coding", "gpt-6-sol") == "medium"          # class entry
assert tw.prior(doc, "claude", "worker", "T4-hard-reasoning", "gpt-6-sol") == "low"    # model "*" beats class prior
assert tw.prior(doc, "claude", "worker", "T4-hard-reasoning", "opus") == "high"        # no entry: class prior
assert tw.prior(doc, "claude", "worker", "C-coding", "sonnet") == "high"               # "*" low clamped to high
assert tw.prior(doc, "claude", "worker", "C-coding") == "high"                         # no model: role's first
print("PASS S1 per-model priors")

# S2: validation
assert loads(with_model_priors({"gpt-6-sol": {"*": "low"}}))
for bad in ({"not-a-model": {"*": "low"}}, {"gpt-6-sol": {"*": "max"}}, {"gpt-6-sol": {"Z-class": "low"}},
            {"gpt-6-sol": "low"}, []):
    assert not loads(with_model_priors(bad)), bad
print("PASS S2 model_priors validated")

# S2: the local override may set model_priors; a model's override table merges over its installed one
saved = {k: os.environ.pop(k, None) for k in ("TW_ROUTES", "TW_ROUTES_OVERRIDE")}
try:
    with tempfile.TemporaryDirectory() as tmp:
        ov = Path(tmp) / "ov.json"
        os.environ["TW_ROUTES_OVERRIDE"] = str(ov)
        ov.write_text(json.dumps({"router": {"model_priors": {"gpt-6-sol": {"C-coding": "xhigh"}}}}), encoding="utf-8")
        got = tw.load_routes()
        assert "_override_error" not in got, got.get("_override_error")
        installed = R["router"].get("model_priors", {}).get("gpt-6-sol", {})
        assert got["router"]["model_priors"]["gpt-6-sol"] == {**installed, "C-coding": "xhigh"}, got["router"]
        assert tw.prior(got, "claude", "worker", "C-coding", "gpt-6-sol") == "xhigh"
        ov.write_text(json.dumps({"router": {"model_priors": {"not-a-model": {"*": "low"}}}}), encoding="utf-8")
        assert "_override_error" in tw.load_routes()                                   # fails open, named
finally:
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v

# S2: routes.json says an override exists and lists exactly what it may set
note = R["$override"]
assert set(note["may_set"]) == {f"router.{k}" for k in tw.OVERRIDABLE} | {"router.<jev backend block>"}, note
assert "TW_ROUTES_OVERRIDE" in note["path"] and ".thinker-worker/routes.json" in note["path"], note
print("PASS S2 override may set model_priors; routes.json names the override")
