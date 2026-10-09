"""Adding a model: per-model priors (S1), their validation and override (S2).
Run: python test_tw_models.py"""
import contextlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

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

@contextlib.contextmanager
def override(doc: dict):
    """The user override file set to doc (TW_ROUTES_OVERRIDE, TW_ROUTES unset); the environment restored on exit."""
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
        os.environ.pop("TW_ROUTES", None)
        ov = Path(tmp) / "ov.json"
        ov.write_text(json.dumps(doc), encoding="utf-8")
        os.environ["TW_ROUTES_OVERRIDE"] = str(ov)
        yield


# S2: the local override may set model_priors; a model's override table merges over its installed one
OV = {"router": {"model_priors": {"gpt-6-sol": {"C-coding": "xhigh"}}}}
with override(OV):
    got = tw.load_routes()
    assert "_override_error" not in got, got.get("_override_error")
    installed = R["router"].get("model_priors", {}).get("gpt-6-sol", {})
    assert got["router"]["model_priors"]["gpt-6-sol"] == {**installed, "C-coding": "xhigh"}, got["router"]
    assert tw.prior(got, "claude", "worker", "C-coding", "gpt-6-sol") == "xhigh"
with override({"router": {"model_priors": {"not-a-model": {"*": "low"}}}}):
    assert "_override_error" in tw.load_routes()                                       # fails open, named

# S2: routes.json says an override exists and lists exactly what it may set
note = R["$override"]
assert set(note["may_set"]) == {f"router.{k}" for k in tw.OVERRIDABLE} | {"router.<jev backend block>"}, note
assert "TW_ROUTES_OVERRIDE" in note["path"] and ".thinker-worker/routes.json" in note["path"], note
print("PASS S2 override may set model_priors; routes.json names the override")

# S3: `tw.py models` lists one JSON line per (role, model), with prior sources and how to dispatch it
from test_tw_hook import run_main
with override(OV):
    code, out = run_main(["models", "--harness", "claude"])
    assert code == 0, out
    lines = {(x["role"], x["model"]): x for x in map(json.loads, out.splitlines())}
    assert lines[("worker", "gpt-6-sol")] == {
        "harness": "claude", "role": "worker", "model": "gpt-6-sol", "tiers": ["low", "medium", "high", "xhigh"],
        "priors": {"C-coding": {"tier": "xhigh", "source": "override"}}, "default": False, "via": "tw.py codex"}
    assert {k: v for k, v in lines[("worker", "sonnet")].items() if k != "priors"} == {  # shipped priors may change
        "harness": "claude", "role": "worker", "model": "sonnet", "tiers": ["high", "xhigh"],
        "default": False, "via": "native"}
    assert lines[("worker", "opus")]["default"] is True                      # the agent file's pin
    assert lines[("independent-review", "gpt-6-astra")]["default"] is True   # router.defaults
    assert lines[("leaf", "sonnet")]["tiers"] == ["low", "medium", "high"]
print("PASS S3 models listing")

# S5: the shipped routes.json is in canonical form, so script edits and hand edits cannot drift apart
text = (tw.source_root() / "routes.json").read_text(encoding="utf-8")
assert text == tw.dump_routes(json.loads(text)), "routes.json is not canonical: run tw.dump_routes over it"
assert '"sonnet": ["high", "xhigh"]' in text                                 # scalar lists stay on one line
print("PASS S5 canonical routes.json")


# S4: `tw.py model set|archive --routes <path>` edits a routes file, validated before it writes
def model_cmd(path, *argv):
    code, out = run_main(["model", *argv, "--routes", str(path)])
    return code, out, json.loads(path.read_text(encoding="utf-8"))


with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "routes.json"
    p.write_text(tw.dump_routes(R), encoding="utf-8")
    base = json.loads(p.read_text(encoding="utf-8"))
    code, out, doc = model_cmd(p, "set", "--harness", "claude", "--role", "worker", "--model", "gpt-9-test",
                               "--tiers", "medium,high", "--prior", "*=medium", "--prior", "C-coding=high")
    assert code == 0, out
    want = json.loads(json.dumps(base))
    w = want["harnesses"]["claude"]["roles"]["worker"]
    w["models"].append("gpt-9-test")
    w["model_tiers"]["gpt-9-test"] = ["medium", "high"]
    want["router"].setdefault("model_priors", {})["gpt-9-test"] = {"*": "medium", "C-coding": "high"}
    assert doc == want, doc
    assert p.read_text(encoding="utf-8") == tw.dump_routes(want)              # written canonical
    before = p.read_text(encoding="utf-8")
    code, out, _ = model_cmd(p, "set", "--harness", "claude", "--role", "worker", "--model", "gpt-9-test",
                             "--tiers", "medium,high", "--prior", "*=medium", "--prior", "C-coding=high")
    assert code == 0 and p.read_text(encoding="utf-8") == before and "unchanged" in out, out   # idempotent
    for bad in (["--tiers", "high,medium"], ["--tiers", "max"], ["--prior", "C-coding=max"], ["--prior", "Z=low"],
                ["--role", "nope"]):
        args = ["set", "--harness", "claude", "--role", "worker", "--model", "gpt-9-test", *bad]
        code, out, _ = model_cmd(p, *args)
        assert code == 2 and p.read_text(encoding="utf-8") == before, (bad, out)                # nothing written
print("PASS S4 model set: add, idempotent, invalid writes nothing")

# S6: role ladder changes are explicit, validated before write, and exercised through the dispatch guard.
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "routes.json"
    base = json.loads(json.dumps(R))
    for h in ("claude", "codex"):
        base["harnesses"][h]["roles"]["leaf"]["tiers"] = ["low", "medium"]
    p.write_text(tw.dump_routes(base), encoding="utf-8")
    brief = "TW-Role: leaf\nTW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"
    claude = {"tool_name": "Agent", "tool_input": {"subagent_type": "tw-leaf-high", "prompt": brief}}
    codex = {"tool_name": "spawn_agent", "tool_input": {"model": "gpt-6-luna", "reasoning_effort": "high",
                                                        "fork_turns": "none", "message": brief}}
    assert not tw.decide("claude", claude, base).admitted
    assert not tw.decide("codex", codex, base).admitted
    for h, model in (("claude", "sonnet"), ("codex", "gpt-6-luna")):
        args = ("set", "--harness", h, "--role", "leaf", "--model", model,
                "--role-tiers", "low,medium,high", "--tiers", "low,medium,high")
        code, out, doc = model_cmd(p, *args)
        assert code == 0, out
        before = p.read_bytes()
        code, out, _ = model_cmd(p, *args)
        assert code == 0 and p.read_bytes() == before and "unchanged" in out, out
    for model in ("sonnet", "claude-sonnet-5-5"):
        claude["tool_input"]["model"] = model
        assert tw.decide("claude", claude, doc).admitted, model
    assert tw.model_tiers(doc["harnesses"]["claude"]["roles"]["leaf"], "gpt-6-luna") == ["low", "medium", "high"]
    claude["tool_input"]["model"] = "gpt-6-luna"
    assert tw.decide("claude", {**claude, "tool_name": "codex"}, doc).admitted
    assert not tw.decide("claude", claude, doc).admitted  # Codex models still require the pipeline.
    assert tw.decide("codex", codex, doc).admitted
    for h in ("claude", "codex"):
        assert doc["harnesses"][h]["roles"]["worker"] == base["harnesses"][h]["roles"]["worker"]
    assert tw.model_tiers(doc["harnesses"]["claude"]["roles"]["worker"], "sonnet") == ["high", "xhigh"]
    for bad in ("high,medium", "low,max", "low,low", ""):
        code, out, _ = model_cmd(p, "set", "--harness", "claude", "--role", "leaf", "--model", "sonnet",
                                 "--role-tiers", bad)
        assert code == 2 and p.read_bytes() == before, (bad, out)
print("PASS S6 explicit role tiers: high leaves admitted, workers unchanged, idempotent, invalid writes nothing")

# S4: archive removes a model from dispatch and keeps a dated record; set restores it
import re
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "routes.json"
    p.write_text(tw.dump_routes(R), encoding="utf-8")
    base = json.loads(p.read_text(encoding="utf-8"))
    for h in ("claude", "codex"):
        assert model_cmd(p, "set", "--harness", h, "--role", "worker", "--model", "gpt-9-test", "--tiers", "high,xhigh",
                         "--prior", "C-coding=high")[0] == 0
    assert model_cmd(p, "set", "--harness", "claude", "--role", "independent-review", "--model", "gpt-9-test",
                     "--default")[0] == 0
    code, out, doc = model_cmd(p, "archive", "--model", "gpt-9-test")
    assert code == 0, out
    rec = doc["archived"]["gpt-9-test"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["date"]), rec
    assert rec == {"date": rec["date"],
                   "roles": {"claude/worker": ["high", "xhigh"], "codex/worker": ["high", "xhigh"],
                             "claude/independent-review": ["medium", "high", "xhigh"]},
                   "model_priors": {"C-coding": "high"}, "default_for": ["independent-review"]}, rec
    del doc["archived"]
    want = json.loads(json.dumps(base))
    del want["router"]["defaults"]["independent-review"]      # a default archived: the role falls back to its first
    assert doc == want, "archive left traces or changed other entries"
    assert "default" in out and "independent-review" in out, out           # and says so
    code, out, doc = model_cmd(p, "set", "--harness", "claude", "--role", "worker", "--model", "gpt-9-test")
    assert code == 0 and "archived" not in doc and "gpt-9-test" in doc["harnesses"]["claude"]["roles"]["worker"]["models"]
    before = p.read_text(encoding="utf-8")
    for m in ("opus", "never-admitted"):                                   # a role's agent-file pin; unknown model
        code, out, _ = model_cmd(p, "archive", "--model", m)
        assert code == 2 and p.read_text(encoding="utf-8") == before, (m, out)
print("PASS S4 model archive: dated record, clean removal, restore, refusals")
