#!/usr/bin/env python3
"""Session-scoped fresh-agent routing guard and reversible skill installer.

Receipts store the validated routing header (each value cut at 256 chars) and never the brief body or a secret. The hook is a guardrail for
native fresh dispatch; it cannot establish effective child model or permissions.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import NamedTuple
import uuid


OWNER = "thinker-worker-v1"
HARNESSES = ("codex", "claude")
SKILL_FILES = ("SKILL.md", "routes.json", "references/codex.md", "references/claude.md", "references/add-model.md",
               "references/omp.md", "references/agy.md", "scripts/tw.py")
TIERS = ("low", "medium", "high", "xhigh", "max")
AGENT_NAME = re.compile(r"tw-(worker|leaf|independent-review|ideation)-(low|medium|high|xhigh|max)(?:-opus55)?")
OPUS_REVIEW_MODEL = "claude-opus-5-5"
VALUE_MAX = 1000  # per header value at the gate; receipts truncate at 256
ROLE_LINE = re.compile(r"^TW-Role: (worker|leaf|independent-review|ideation)$")
# Routing header: the brief's class picks its tier prior; receipts keep it for tally. Classes are effortmining's vocabulary.
HEADER_KEYS = ("TW-Class", "TW-Deliverable", "TW-Accept", "TW-Risk")
CHECK_KEY = "TW-Check"  # optional: a shell command `tw.py outcome` runs in the dispatch cwd for a pass/fail label
OUTPUT_KEY = "TW-Output"  # optional: the one file path the child must write (the guard checks its basename)
OMP_HEADER_KEYS = ("TW-Scope", "TW-Checkpoint", "TW-Stop")  # optional continuity detail for OMP prompts/retries
OMP_DEFAULT_TIMEOUT = 7200.0
# Claude Code refuses a native subagent's Write to these basenames ("Subagents should return findings as text");
# probed 2026-09-28 on 15 real names, matches anthropics/claude-code#44657. Undocumented: the agent text's
# verbatim-return fallback covers a pattern change. Codex children are unaffected.
REFUSED_OUTPUT = re.compile(r"(?i)(report|summary|findings|analysis).*\.md")
TASK_CLASSES = {"T1-mechanical", "T2-simple-transform", "T3-moderate-reasoning",
                "T4-hard-reasoning", "R-research", "C-coding"}
RISKS = {"destructive", "external", "physics"}


class Conflict(Exception):
    pass


class Decision(NamedTuple):
    admitted: bool
    reason: str
    role: str | None = None
    model: str | None = None
    tier: str | None = None
    fields: dict | None = None


def agent_name(role: str, tier: str) -> str:
    return f"tw-{role}-{tier}"


# The router keys the user override file may set; any other key (a retired router setting) is ignored and named by
# activate/status, so an override written for the old router keeps working.
OVERRIDABLE = {"priors", "model_priors", "defaults"}


def load_routes(path: Path | None = None) -> dict:
    """An explicit path wins, then TW_ROUTES (tests pin their routing with it); either is used as is. Otherwise the
    skill's own routes.json (installer-owned, fails closed) with the user override file merged over it:
    TW_ROUTES_OVERRIDE, else ~/.thinker-worker/routes.json. The override fails open: any problem leaves the installed
    doc unchanged with `_override_error` set (the hook logs it per dispatch; activate/status print it)."""
    pinned = path or os.environ.get("TW_ROUTES")
    path = Path(pinned or source_root() / "routes.json")
    doc = read_json(path, None)
    check_routes(doc, path)
    if pinned:
        return doc
    ov_path = Path(os.environ.get("TW_ROUTES_OVERRIDE") or Path.home() / ".thinker-worker" / "routes.json")
    try:
        return merge_override(doc, ov_path) if ov_path.exists() else doc
    except Exception as exc:
        return {**doc, "_override_error": f"override {ov_path}: {exc}"[:300]}


def merge_override(doc: dict, ov_path: Path) -> dict:
    """Key by key over the installed router block: each OVERRIDABLE key is an object merged over the installed one
    (model_priors per model). The merged doc is validated like the installed one."""
    ov = read_json(ov_path, None)
    rt = ov.get("router") if isinstance(ov, dict) else None
    if (not isinstance(ov, dict) or set(ov) != {"router"} or not isinstance(rt, dict)
            or not all(isinstance(rt[k], dict) for k in OVERRIDABLE & set(rt))):
        raise Conflict("must be {\"router\": {...}} with router." + ", router.".join(sorted(OVERRIDABLE))
                       + " each an object if set")
    merged = json.loads(json.dumps(doc))
    mr = merged["router"]
    for k in sorted(OVERRIDABLE & set(rt)):
        v = rt[k]
        if k == "model_priors":  # per model: the override's table merges over the installed one
            mr[k] = {**mr.get(k, {}), **{m: {**mr.get(k, {}).get(m, {}), **t} for m, t in v.items()}}
        else:
            mr[k] = {**mr.get(k, {}), **v}
    check_routes(merged, ov_path)
    merged["_override"] = str(ov_path)
    merged["_override_ignored"] = sorted(set(rt) - OVERRIDABLE)
    merged["_override_model_priors"] = rt.get("model_priors", {})  # which prior values came from the override
    return merged


def is_codex_model(routes: dict, model: object) -> bool:
    """The model is in some Codex role's models: from Claude it runs only through `tw.py codex`."""
    return any(model in p["models"] for p in routes["harnesses"]["codex"]["roles"].values())


def model_tiers(pol: dict, model: str | None) -> list[str]:
    """The role's tiers for this model: its `model_tiers` entry (a subset of the role's tiers), else the role's."""
    return pol.get("model_tiers", {}).get(model, pol["tiers"])


def check_routes(doc: object, path: Path) -> None:
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise Conflict(f"routes.json missing or not schema 1: {path}")
    def ladder(ts: object, allowed: list) -> bool:  # non-empty, unique, in TIERS order
        return (isinstance(ts, list) and bool(ts) and all(t in allowed for t in ts)
                and [TIERS.index(t) for t in ts] == sorted({TIERS.index(t) for t in ts}))

    for harness in HARNESSES:
        for role, pol in doc["harnesses"][harness]["roles"].items():
            mt = pol.get("model_tiers", {})
            if (not pol.get("models") or not ladder(pol.get("tiers"), TIERS) or not isinstance(mt, dict)
                    or any(m not in pol["models"] or not ladder(ts, pol["tiers"]) for m, ts in mt.items())):
                raise Conflict(f"routes.json: bad policy for {harness}/{role}")

    rt = doc.get("router")
    priors = rt.get("priors") if isinstance(rt, dict) else None
    if (not isinstance(rt, dict) or not isinstance(priors, dict) or "*" not in priors
            or not set(priors) <= TASK_CLASSES | {"*"} or any(v not in TIERS for v in priors.values())):
        raise Conflict("routes.json: bad router block")
    admitted = {m for h in HARNESSES for p in doc["harnesses"][h]["roles"].values() for m in p["models"]}
    mp = rt.get("model_priors", {})
    if not isinstance(mp, dict) or any(m not in admitted or not isinstance(t, dict) or not set(t) <= TASK_CLASSES | {"*"}
                                       or any(v not in TIERS for v in t.values()) for m, t in mp.items()):
        raise Conflict("routes.json: router.model_priors must map an admitted model to {class or *: tier}")
    arch = doc.get("archived", {})  # dated records of models no longer offered; never admitted at the same time
    if not isinstance(arch, dict) or any(m in admitted or not isinstance(r, dict) for m, r in arch.items()):
        raise Conflict("routes.json: archived must map a model that is not admitted to its record")
    defaults = rt.get("defaults", {})  # per-role default model the coordinator dispatches; guidance, not enforced
    claude_roles = doc["harnesses"]["claude"]["roles"]
    if not isinstance(defaults, dict) or any(r not in claude_roles or m not in claude_roles[r]["models"]
                                             for r, m in defaults.items()):
        raise Conflict("routes.json: router.defaults must map a Claude role to one of its models")


def prior(routes: dict, harness: str, role: str, cls: str | None, model: str | None = None) -> str:
    """The tier prior for a class, clamped into the model's tiers: router.model_priors[model] (its class, else its
    "*"), else router.priors (the class, else "*"). No model: the role's first."""
    pol = routes["harnesses"][harness]["roles"][role]
    priors, own = routes["router"]["priors"], routes["router"].get("model_priors", {}).get(model or pol["models"][0], {})
    return clamp(own.get(cls, own.get("*", priors.get(cls, priors["*"]))), model_tiers(pol, model))


def models(harness: str) -> list[dict]:
    """One line per (role, model) admitted for the harness: its tiers, its model_priors entries (source "override" when
    the local override set that entry, else "installed"), whether it is the role's default (router.defaults, else the
    role's first model: the agent file's pin), and how to dispatch it from this harness."""
    routes = load_routes()
    rt, local = routes["router"], routes.get("_override_model_priors", {})
    out = []
    for role, pol in routes["harnesses"][harness]["roles"].items():
        for m in pol["models"]:
            own = rt.get("model_priors", {}).get(m, {})
            out.append({"harness": harness, "role": role, "model": m, "tiers": model_tiers(pol, m),
                        "priors": {c: {"tier": v, "source": "override" if c in local.get(m, {}) else "installed"}
                                   for c, v in own.items()},
                        "default": rt.get("defaults", {}).get(role, pol["models"][0]) == m,
                        "via": "tw.py codex" if harness == "claude" and is_codex_model(routes, m) else "native"})
    return out


def dump_routes(doc: dict) -> str:
    """The canonical routes.json text: 2-space blocks, a list of scalars on one line, a trailing newline.
    ponytail: not canonical_json (indent=2) because routes.json is read by people: one line per model/tier list keeps
    it ~110 lines instead of ~200. Switch to canonical_json if nobody reads the file by hand."""
    def fmt(v: object, pad: str) -> str:
        inner = pad + "  "
        if isinstance(v, dict) and v:
            return "{\n" + ",\n".join(f"{inner}{json.dumps(k)}: {fmt(x, inner)}" for k, x in v.items()) + f"\n{pad}}}"
        if isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v):
            return "[\n" + ",\n".join(inner + fmt(x, inner) for x in v) + f"\n{pad}]"
        return json.dumps(v, ensure_ascii=False)
    return fmt(doc, "") + "\n"


def model_set(path: Path, harness: str, role: str, model: str, tiers: str | None, priors: list[str],
              default: bool, role_tiers: str | None = None) -> str:
    """Admit (or update, or re-admit an archived) model for one harness role; validated before it writes."""
    doc = load_routes(path)
    roles = doc["harnesses"].get(harness, {}).get("roles", {})
    if role not in roles:
        raise Conflict(f"no role {role!r} for harness {harness!r}")
    pol, rt = roles[role], doc["router"]
    if role_tiers is not None:
        pol["tiers"] = role_tiers.split(",")
    if model not in pol["models"]:
        pol["models"].append(model)  # appended: the role's first model (the agent file's pin) never changes here
    if tiers is not None:
        ts = tiers.split(",")
        pol.setdefault("model_tiers", {}).pop(model, None)
        if ts != pol["tiers"]:
            pol["model_tiers"][model] = ts
        if not pol["model_tiers"]:
            del pol["model_tiers"]
    for kv in priors:
        cls, _, tier = kv.partition("=")
        rt.setdefault("model_priors", {}).setdefault(model, {})[cls] = tier
    if default:
        rt.setdefault("defaults", {})[role] = model
    doc.get("archived", {}).pop(model, None)
    if doc.get("archived") == {}:
        del doc["archived"]
    return write_routes(path, doc)


def model_archive(path: Path, model: str) -> str:
    """Remove a model no longer offered from every role, keeping a dated record under `archived`. A role's first model
    (its agent file's pin) is refused; a role it was the default for falls back to its first model."""
    doc = load_routes(path)
    rt, roles, pins = doc["router"], {}, []
    for h in HARNESSES:
        for role, pol in doc["harnesses"][h]["roles"].items():
            if model in pol["models"]:
                if pol["models"][0] == model:
                    pins.append(f"{h}/{role}")
                roles[f"{h}/{role}"] = model_tiers(pol, model)
                pol["models"].remove(model)
                pol.get("model_tiers", {}).pop(model, None)
                if pol.get("model_tiers") == {}:
                    del pol["model_tiers"]
    if not roles or pins:
        raise Conflict(f"{model} is not admitted" if not roles else
                       f"{model} is the first model (agent file pin) of {', '.join(pins)}; archive refused")
    was_default = sorted(r for r, m in rt.get("defaults", {}).items() if m == model)
    for r in was_default:
        del rt["defaults"][r]
    rec = {"date": datetime.now().date().isoformat(), "roles": roles,
           "model_priors": rt.get("model_priors", {}).pop(model, {}), "default_for": was_default}
    if rt.get("model_priors") == {}:
        del rt["model_priors"]
    doc.setdefault("archived", {})[model] = rec
    note = (f"note: {model} was the default for {', '.join(was_default)}; it now falls back to the role's first "
            "model (set another with `model set --default`)\n") if was_default else ""
    return note + write_routes(path, doc)


def write_routes(path: Path, doc: dict) -> str:
    """Validate, then write canonical text atomically; returns the diff (or "unchanged")."""
    import difflib  # cold path: kept off the hook's import time
    check_routes(doc, path)
    raw = path.read_bytes()  # atomic_write's changed-target check compares raw bytes (a Windows checkout may be CRLF)
    old, new = raw.decode("utf-8").replace("\r\n", "\n"), dump_routes(doc)
    if old == new:
        return f"unchanged: {path}"
    atomic_write(path, new.encode("utf-8"), raw)
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), str(path), str(path)))


def priors_line(routes: dict) -> str:
    rt = routes["router"]
    source = (f"override ignored: {routes['_override_error']}" if routes.get("_override_error")
              else "installed routes.json" + (f" + {routes['_override']}" if routes.get("_override") else ""))
    return (f"Tier priors ({source}): " + ", ".join(f"{k}={v}" for k, v in rt["priors"].items())
            + "; default models: " + (", ".join(f"{k}={v}" for k, v in rt.get("defaults", {}).items()) or "agent files")
            + "".join(f"; {m}: " + ", ".join(f"{k}={v}" for k, v in t.items())
                      for m, t in rt.get("model_priors", {}).items())
            + (f"; ignored override keys: {', '.join(routes['_override_ignored'])}" if routes.get("_override_ignored") else ""))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Conflict(f"Invalid JSON at {path}: {exc}") from exc


def state_root(home: Path) -> Path:
    return home / ".thinker-worker"


def record_path(home: Path, harness: str, session: str) -> Path:
    return state_root(home) / "state" / harness / f"{sha(session.encode('utf-8'))}.json"


def session_value(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or any(c in value for c in "\r\n\0"):
        raise Conflict("A nonempty exact session ID (at most 256 characters) is required")
    return value


def atomic_write(path: Path, data: bytes, expected: bytes | None) -> None:
    """Compare immediately before atomic replacement; refuse a changed target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        current = path.read_bytes() if path.exists() else None
        if current != expected:
            raise Conflict(f"Concurrent or unexpected change at {path}; no overwrite")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def activation(home: Path, harness: str, session: str) -> dict | None:
    path = record_path(home, harness, session)
    if not path.exists():
        return None
    obj = read_json(path, {})
    if (not isinstance(obj, dict) or obj.get("schema") != 1 or
            obj.get("harness") != harness or obj.get("session_id") != session):
        # Older records carry review/luna/sonnet/ideation flags or store_bodies; they are ignored.
        raise Conflict(f"Invalid activation record at {path}; deactivate and reactivate this session")
    return obj


def activate(home: Path, harness: str, session: str) -> str:
    path = record_path(home, harness, session)
    old = path.read_bytes() if path.exists() else None
    if old is not None:
        activation(home, harness, session)
    priors = priors_line(load_routes())
    obj = {"schema": 1, "harness": harness, "session_id": session, "activated_at": now()}
    atomic_write(path, canonical_json(obj), old)
    return (f"Activation requested for {harness} session {session}; hook trust/loading, interception, and effective "
            f"child model remain unverified.\n{priors}")


def deactivate(home: Path, harness: str, session: str) -> None:
    path = record_path(home, harness, session)
    if path.exists():
        path.unlink()
    print(f"Deactivated {harness} session {session} (if present).")


def status(home: Path, harness: str, session: str) -> None:
    try:
        record = activation(home, harness, session)
        value = {"activation": "requested" if record else "inactive",
                 "harness": harness, "session_id": session,
                 "hook_loaded": "unknown", "native_interception": "unknown",
                 "effective_child_model_effort": "unknown"}
    except Conflict as exc:
        value = {"activation": "invalid", "harness": harness, "session_id": session,
                 "error": str(exc), "hook_loaded": "unknown",
                 "native_interception": "unknown", "effective_child_model_effort": "unknown"}
    print(json.dumps(value, indent=2))
    print(priors_line(load_routes()))


def first_role(brief: object) -> tuple[str | None, str]:
    if not isinstance(brief, str) or not brief:
        return None, "missing brief"
    match = ROLE_LINE.fullmatch(brief.split("\n")[0])  # "\n" only: splitlines() splits on U+2028 etc.
    return (match.group(1), "") if match else (None, "first brief line must be exactly TW-Role: worker, leaf, independent-review, or ideation")


def review_details(brief: str) -> bool:
    return flagged(brief, "TW-Authorization") and flagged(brief, "TW-Scope")


def header_fields(brief: str) -> tuple[dict | None, str]:
    """Return ({key: value}, "") or (None, problem). Keys may sit anywhere in lines 2-12; TW-Check, TW-Output and
    the OMP continuity keys are optional."""
    found: dict[str, str] = {}
    for line in brief.split("\n")[1:12]:
        key, sep, value = line.partition(": ")
        if sep and key in HEADER_KEYS + (CHECK_KEY, OUTPUT_KEY) + OMP_HEADER_KEYS:
            if key in found:
                return None, f"routing header repeats {key}"
            found[key] = value.strip()
    missing = [k for k in HEADER_KEYS if not found.get(k)]
    if missing:
        return None, "routing header needs non-empty " + ", ".join(missing)
    if found["TW-Class"] not in TASK_CLASSES:
        return None, "routing header TW-Class is not an effortmining class"
    risks = [r.strip() for r in found["TW-Risk"].split(",")]
    if risks != ["none"] and not (set(risks) <= RISKS and len(set(risks)) == len(risks)):
        return None, "routing header TW-Risk must be none or distinct values from " + ", ".join(sorted(RISKS))
    if CHECK_KEY in found and not found[CHECK_KEY]:
        return None, f"routing header {CHECK_KEY} is empty; drop the line or name a command"
    if OUTPUT_KEY in found and not found[OUTPUT_KEY]:
        return None, f"routing header {OUTPUT_KEY} is empty; drop the line or name the file"
    long = [k for k in found if len(found[k]) > VALUE_MAX]
    if long:
        return None, f"routing header value over {VALUE_MAX} characters: " + ", ".join(long)
    return found, ""


def header_text(fields: dict, cap: int = 256) -> str:
    def cut(v: str) -> str:
        return v if len(v) <= cap else f"{v[:cap]}…[+{len(v) - cap}]"
    return "\n".join(f"{k}: {cut(fields[k])}" for k in HEADER_KEYS)


def flagged(brief: str, key: str) -> bool:
    """A non-empty `<key>: <value>` line in brief lines 2-12 (the header lines)."""
    return any(x.startswith(key + ": ") and x[len(key) + 2:].strip() for x in brief.split("\n")[1:12])


def valid_codex_fork(value: object) -> bool:
    return value == "none" or (isinstance(value, str) and
                               bool(re.fullmatch(r"[1-9][0-9]*", value)))


def decide(harness: str, envelope: dict, routes: dict) -> Decision:
    inp = envelope.get("tool_input")
    if not isinstance(inp, dict):
        return Decision(False, "missing tool_input")
    roles = routes["harnesses"][harness]["roles"]
    model = inp.get("model")
    model = model if isinstance(model, str) else None
    brief = inp.get("message" if harness == "codex" else "prompt")
    fields = None
    if harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent":
        # v2 brief is ciphertext: route from the visible model only; Astra = review or ideation, role unknown.
        route = next((r for r in ("worker", "leaf", "independent-review") if model in roles[r]["models"]), None)
        if route is None:
            return Decision(False, "model is not allowed for namespaced Codex dispatch", None, model)
        role = None if route == "independent-review" else route
    else:
        role, problem = first_role(brief)
        if not problem:
            fields, problem = header_fields(brief)
        if problem:
            return Decision(False, problem, role, model)
        route = role
        if role in ("independent-review", "ideation") and not review_details(brief):
            return Decision(False, f"{role} brief needs TW-Authorization and TW-Scope lines", role, model, fields=fields)
    pol = roles[route]
    if harness == "codex":
        if model is None:
            return Decision(False, "explicit model is required; inherited/omitted model is disallowed", role, fields=fields)
        if inp.get("agent_type") not in (None, "default"):
            return Decision(False, "custom agent_type is outside this route", role, model, fields=fields)
        if model not in pol["models"]:
            return Decision(False, f"model is not allowed for {route}", role, model, fields=fields)
        tier = inp.get("reasoning_effort")
        if tier not in model_tiers(pol, model):
            return Decision(False, f"reasoning_effort must be one of {', '.join(model_tiers(pol, model))} for {route}",
                            role, model, fields=fields)
        if not valid_codex_fork(inp.get("fork_turns")):
            return Decision(False, "fork_turns must be explicit 'none' or a bounded positive count", role, model, fields=fields)
    else:
        st = inp.get("subagent_type")
        match = AGENT_NAME.fullmatch(st) if isinstance(st, str) else None
        if not match or match.group(1) != role:
            return Decision(False, f"subagent_type must be tw-{role}-<tier>", role, model, fields=fields)
        tier = match.group(2)
        if st.endswith("-opus55"):
            if role != "independent-review" or model is not None:
                return Decision(False, "pinned Opus review agent requires independent-review and no per-call model override",
                                role, model, fields=fields)
            model = OPUS_REVIEW_MODEL  # immutable generated agent pin; alias 'opus' remains unadmitted
        if tier not in pol["tiers"]:
            return Decision(False, f"tier {tier} is outside {role}'s tiers {pol['tiers']}", role, model, fields=fields)
        if model is not None and model not in pol["models"]:
            return Decision(False, f"model {model} is not allowed for {role}", role, model, fields=fields)
        if tier not in model_tiers(pol, model):
            return Decision(False, f"tier {tier} is outside {role}'s tiers {model_tiers(pol, model)} on {model}",
                            role, model, fields=fields)
        if envelope.get("tool_name") != "codex" and is_codex_model(routes, model):  # not the pipeline's own call
            return Decision(False, f"model {model} is a Codex model; dispatch it with `tw.py codex --model {model}`",
                            role, model, fields=fields)
        if inp.get("fork_context") or inp.get("fork"):
            return Decision(False, "Claude inherited-model fork is outside fresh dispatch", role, model, fields=fields)
        output = (fields or {}).get(OUTPUT_KEY)
        if envelope.get("tool_name") != "codex" and output and REFUSED_OUTPUT.fullmatch(re.split(r"[\\/]", output)[-1]):
            return Decision(False, f"{OUTPUT_KEY} {output}: Claude Code refuses a native subagent's Write to a "
                            "report/summary/findings/analysis*.md basename; name it for its task, e.g. worker-notes.md",
                            role, model, fields=fields)
    return Decision(True, "admitted-request-only", role, model, tier, fields)


def denial(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                       "permissionDecision": "deny", "permissionDecisionReason": f"{OWNER}: {reason}"}}))


def reminder(harness: str, d: Decision, routes: dict, brief: str) -> dict | None:
    """Claude only: an additionalContext line when an admitted dispatch's tier differs from its class prior, unless the
    user pinned the tier (TW-Pin). ponytail: Codex's handling of additionalContext without a decision is unverified."""
    p = prior(routes, harness, d.role, d.fields["TW-Class"], d.model)
    if harness != "claude" or d.tier == p or flagged(brief, "TW-Pin"):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext":
            f"thinker-worker: prior for {d.fields['TW-Class']} is {p}; you dispatched {d.tier} (fine if deliberate)"}}


def receipt(home: Path, harness: str, session: str, envelope: dict, d: Decision) -> None:
    # Never store the brief body or any unknown input field; the validated routing header is kept for tally.
    def small(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        return value if len(value) <= 128 and not any(c in value for c in "\r\n\0") else "<invalid-field>"

    inp = envelope.get("tool_input") if isinstance(envelope.get("tool_input"), dict) else {}
    header = header_text(d.fields) if d.fields else None
    entry = {"kind": "dispatch", "at": now(), "harness": harness, "session_id": session,
             "subagent_type": small(inp.get("subagent_type")), "header": header,
             "tool_use_id": small(envelope.get("tool_use_id")),
             "tool_name": envelope.get("tool_name"), "decision": "admit" if d.admitted else "deny",
             "reason": d.reason, "role": d.role, "requested_model": small(d.model),
             "tier": d.tier, "effective_model": None, "effective_effort": None,
             # full TW-Check (not cut at 256) and where it runs; `outcome` executes it
             "check": (d.fields or {}).get(CHECK_KEY), "cwd": envelope["cwd"] if isinstance(envelope.get("cwd"), str) else None,
             "brief_checks": "unavailable-encrypted-v2" if harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent" else "plaintext-route"}
    if "permissions" in envelope:
        entry["permissions"] = envelope["permissions"]
    append_receipt(home, harness, session, entry)


def receipts_path(home: Path, harness: str, session: str) -> Path:
    return state_root(home) / "receipts" / harness / f"{sha(session.encode('utf-8'))}.jsonl"


def append_receipt(home: Path, harness: str, session: str, entry: dict) -> None:
    path = receipts_path(home, harness, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab+") as stream:  # append mode: writes land at EOF whatever the read position
        lead = b""
        if stream.seek(0, 2):
            stream.seek(-1, 2)
            lead = b"" if stream.read(1) == b"\n" else b"\n"  # don't glue this row onto a torn last line
        stream.write(lead + (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))


def read_rows(path: Path) -> list[dict]:
    """JSONL rows as dicts; blank lines and lines torn by a concurrent writer are skipped."""
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def kill_tree(proc: subprocess.Popen, wait: float = 10) -> bool:
    """Kill proc and its descendants; True only if the kill command succeeded and proc exited, all within `wait` s.
    Never blocks longer than that budget: the kill command and the exit wait share it. A denied kill (taskkill exit
    1, Access denied) or a kill command that overruns returns False; proc may live on."""
    deadline = time.monotonic() + wait
    ok = True
    if os.name == "nt":
        try:
            ok = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                                timeout=wait).returncode == 0
        except subprocess.TimeoutExpired:
            return False  # a stalled taskkill: termination not established
    else:
        try:
            os.killpg(proc.pid, 9)  # SIGKILL; the check runs in its own session
        except OSError:
            proc.kill()
    try:
        proc.wait(max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return False
    return ok


def run_bounded(argv: list[str], cwd: object, stdin_bytes: bytes | None, timeout: float, merge: bool = False) -> dict:
    """Run argv once for at most `timeout` s. stdout/stderr are temp files, not pipes (a surviving grandchild cannot
    hang the read); stdin is a pipe fed by a writer thread (Windows lost a temp-file stdin handle through npm's
    codex.CMD -> node shim, "No prompt provided via stdin", 2026-09-28; a pipe survived; the thread keeps a prompt
    larger than the pipe buffer from blocking before the child reads). On POSIX the child gets its own session so
    kill_tree kills the group. On timeout the tree is killed (kill_tree). Returns code (None on timeout), out, err
    ("" with merge: stderr goes to out, in order), timed_out, kill_failed, pid, exited (the process was gone at
    return). Popen's OSError propagates. stdin_bytes None: DEVNULL."""
    with tempfile.TemporaryFile() as fout, tempfile.TemporaryFile() as ferr:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL if stdin_bytes is None else subprocess.PIPE,
                                stdout=fout, stderr=subprocess.STDOUT if merge else ferr,
                                start_new_session=os.name != "nt")
        if stdin_bytes is not None:
            def feed() -> None:
                try:
                    proc.stdin.write(stdin_bytes)
                    proc.stdin.close()
                except OSError:  # the child exited or was killed before reading everything
                    pass
            threading.Thread(target=feed, daemon=True).start()
        code, timed_out, kill_failed = None, False, False
        try:
            code = proc.wait(timeout)
        except subprocess.TimeoutExpired:
            timed_out, kill_failed = True, not kill_tree(proc)
        fout.seek(0), ferr.seek(0)
        out, err = (f.read().decode("utf-8", errors="replace") for f in (fout, ferr))
    return {"code": code, "out": out, "err": err, "timed_out": timed_out, "kill_failed": kill_failed,
            "pid": proc.pid, "exited": proc.poll() is not None}


def check_shell() -> tuple[str | None, str | None]:
    """(shell path, None) or (None, unknown_reason). Modeled on GitHub Actions `shell: bash`: TW_CHECK_BASH if set;
    on Windows the bash of git's own install (never a PATH bash: WSL's bash.exe, or anything planted first);
    elsewhere bash, else sh, from PATH. Resolved once per process for each (TW_CHECK_BASH, PATH)."""
    return _check_shell(os.environ.get("TW_CHECK_BASH"), os.environ.get("PATH"))


@functools.lru_cache(maxsize=None)
def _check_shell(override: str | None, _path: str | None) -> tuple[str | None, str | None]:
    if override:
        return (override, None) if Path(override).is_file() else (None, f"TW_CHECK_BASH not a file: {override}"[:200])
    if os.name != "nt":
        return shutil.which("bash") or shutil.which("sh"), None
    try:
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        exec_path = ""
    for root in Path(exec_path).parents if exec_path else ():  # <root>/mingw64/libexec/git-core
        for rel in ("usr/bin/bash.exe", "bin/bash.exe"):
            if (root / rel).is_file():
                return str(root / rel), None
    return None, "no git bash"


@functools.lru_cache(maxsize=None)
def shell_version(shell: str) -> str | None:
    """First line of `<shell> --version`, else None; once per process per shell."""
    try:
        ver = subprocess.run([shell, "--version"], capture_output=True, text=True, errors="replace", timeout=30,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (ver.splitlines() or [None])[0]


def run_check(cmd: str, cwd: object, timeout: float) -> dict:
    """Run a TW-Check once in cwd under `bash --noprofile --norc -eo pipefail -c` (check_shell): label pass (exit 0) /
    fail (nonzero) / unknown (timeout, cwd missing, no shell, a shell whose `--version` is not GNU bash ("no pipefail
    shell": it is not run), launch error; unknown_reason says which), exit_code,
    seconds, tail (last 400 chars of stdout + stderr), shell, shell_version (first line of `--version`; shell and
    shell_version stay None when the cwd is missing: no shell is resolved), kill_failed
    (a timed-out check's tree was not verifiably killed; see kill_tree)."""
    start = time.monotonic()
    res: dict = {"label": "unknown", "exit_code": None, "unknown_reason": None, "tail": "", "shell": None,
                 "shell_version": None, "kill_failed": False}
    cwd_ok = isinstance(cwd, str) and Path(cwd).is_dir()
    shell, why = check_shell() if cwd_ok else (None, None)  # a check that cannot run resolves no shell
    if shell:
        res["shell"], res["shell_version"] = shell, shell_version(shell)
    if not cwd_ok:
        res["unknown_reason"] = "cwd missing"
    elif not shell:
        res["unknown_reason"] = why or "no shell"
    elif not (res["shell_version"] or "").startswith("GNU bash"):
        # without pipefail `failing | cat` exits 0 and would label pass; Git's sh.exe and macOS /bin/sh are bash
        res["unknown_reason"] = "no pipefail shell"
    else:
        try:
            ran = run_bounded([shell, "--noprofile", "--norc", "-eo", "pipefail", "-c", cmd], cwd, None, timeout,
                              merge=True)
        except OSError as exc:
            res["unknown_reason"] = f"launch error: {type(exc).__name__}: {exc}"[:200]
        else:
            if ran["timed_out"]:
                res["kill_failed"], res["unknown_reason"] = ran["kill_failed"], "timeout"
            else:
                res["exit_code"] = ran["code"]
                res["label"] = "pass" if ran["code"] == 0 else "fail"
            res["tail"] = ran["out"][-400:]
    res["seconds"] = round(time.monotonic() - start, 3)
    return res


def outcome(home: Path, harness: str, session: str, tool_use_id: str, accepted: bool | None,
            cause: str | None = None, run: bool = True, timeout: float = 900) -> None:
    """Label a guarded dispatch; the last outcome for a tool_use_id wins. accepted is the coordinator's (weak) label;
    the dispatch's TW-Check, unless run is False, is executed and writes a `check` row. Claude: one cost row.
    Only a dispatch that ran is labeled: its dispatch row says admit, and a `tw.py codex` dispatch has a cost row
    (codex ran). Otherwise Conflict, before anything is written."""
    rows = read_rows(receipts_path(home, harness, session))
    disp, state = dispatch_state(rows, tool_use_id)
    if state == "none":
        # The usual cause: the id came from a notification that followed a SendMessage to the child, which carries
        # that message's id. Name the dispatches still waiting for a label so the right id is one copy away.
        labeled = {r.get("tool_use_id") for r in rows if r.get("kind") == "outcome"}
        waiting = [f"{r.get('tool_use_id')} ({r.get('subagent_type') or r.get('tool_name')}, {str(r.get('at'))[:16]})"
                   for r in rows if r.get("kind") == "dispatch" and r.get("decision") == "admit"
                   and r.get("tool_use_id") not in labeled]
        hint = ("; admitted dispatches without a label: " + ", ".join(waiting) + ". Pass the id of the Agent call that "
                "launched the child (its meta.json toolUseId), not the id on a notification after a SendMessage"
                ) if waiting else ""
        raise Conflict(f"no dispatch receipt for tool_use_id {tool_use_id} in {harness} session {session}{hint}")
    if state == "deny":
        raise Conflict(f"{tool_use_id} was denied at the gate ({disp.get('reason')}); it never ran")
    if disp.get("tool_name") in {"codex", "omp", "agy"} and not any(
            r.get("kind") == "cost" and r.get("tool_use_id") == tool_use_id for r in rows):
        raise Conflict(f"{tool_use_id}: no cost row, so {disp['tool_name']} never ran for it")
    check = disp.get("check") if run else None
    if accepted is None and not check:
        raise Conflict("nothing to record: pass --accepted yes|no, or dispatch with a TW-Check line (without "
                       "--no-check)")
    if accepted is not None:
        append_receipt(home, harness, session, {"kind": "outcome", "at": now(), "harness": harness,
                                                "session_id": session, "tool_use_id": tool_use_id,
                                                "accepted": accepted, "cause": cause})
    if harness == "claude":  # the label above stands even if the child's files are unreadable
        record_cost(home, harness, session, tool_use_id, rows)
    if accepted is not None:
        print(f"Recorded {'accepted' if accepted else 'rejected'} for {tool_use_id}.")
    if check:
        res = run_check(check, disp.get("cwd"), timeout)
        append_receipt(home, harness, session, {"kind": "check", "at": now(), "harness": harness,
                                                "session_id": session, "tool_use_id": tool_use_id, **res})
        why = f" (exit {res['exit_code']})" if res["label"] != "unknown" else f" ({res['unknown_reason']})"
        print(f"Check {res['label']}{why} for {tool_use_id}.")


CODEX_USAGE = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def worker_permissions(backend: str, sandbox: str | None = None,
                       approval_policy: str | None = None, permission_mode: str | None = None) -> dict:
    """Backend-specific dispatch defaults, not a claim about enforced runtime permissions."""
    if backend == "codex":
        if sandbox is not None and sandbox not in ("read-only", "workspace-write", "danger-full-access"):
            raise Conflict("unsupported Codex sandbox")
        if approval_policy is not None and approval_policy not in ("never", "on-request"):
            raise Conflict("unsupported Codex approval policy")
        if permission_mode is not None:
            raise Conflict("Claude permission mode cannot be mapped implicitly to Codex")
        requested = {"sandbox": sandbox, "approval_policy": approval_policy}
        resolved = {"sandbox": "danger-full-access" if sandbox is None else sandbox,
                    "approval_policy": "never" if approval_policy is None else approval_policy}
    elif backend == "claude":
        if sandbox is not None or approval_policy is not None:
            raise Conflict("Codex permission controls cannot be mapped implicitly to Claude")
        if permission_mode is not None and permission_mode not in ("manual", "acceptEdits", "bypassPermissions", "plan", "auto", "dontAsk"):
            raise Conflict("unsupported Claude permission mode")
        requested = {"permission_mode": permission_mode}
        resolved = {"permission_mode": "bypassPermissions" if permission_mode is None else permission_mode}
    elif backend == "agy":
        if sandbox is not None or approval_policy is not None:
            raise Conflict("Codex permission controls cannot be mapped implicitly to agy")
        if permission_mode is not None and permission_mode not in ("accept-edits", "auto", "plan"):
            raise Conflict("unsupported agy mode")
        requested = {"mode": permission_mode}
        resolved = ({"permission": "dangerously-skip-permissions"} if permission_mode is None
                    else {"permission": "mode", "mode": permission_mode})
    else:
        raise Conflict("unknown worker permission backend")
    return {"backend": backend, "requested": requested, "resolved": resolved,
            "source": {key: "wrapper-default" if value is None else "explicit-override" for key,value in requested.items()},
            "effective": {"status": "unverified", "settings": None},
            "boundary": "host-enforced restrictions and separate model-use approvals remain in force"}


def codex_cmd(exe: str, model: str, tier: str, cd: Path, out: Path, sandbox: str = "danger-full-access",
              search: bool = True, approval_policy: str = "never") -> list[str]:
    # Full Access is this explicit pair of Codex controls, not a Claude permission-mode alias.
    permissions = worker_permissions("codex", sandbox, approval_policy)["resolved"]
    return [exe, *(["--search"] if search else []), "--ask-for-approval", permissions["approval_policy"],
            "exec", "-m", model, "-c", f"model_reasoning_effort={tier}",
            "-s", permissions["sandbox"], "--json", "--skip-git-repo-check", "-C", str(cd), "-o", str(out), "-"]


def codex_evidence(home: Path, events: str) -> dict:
    """Thread id and summed usage from `codex exec --json`; effective model/effort from the rollout's turn_context."""
    ev: dict = {"thread_id": None, "model": None, "effort": None, **{k: 0 for k in CODEX_USAGE}}
    for line in events.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "thread.started":
            ev["thread_id"] = row.get("thread_id")
        elif row.get("type") == "turn.completed":
            for k in CODEX_USAGE:
                ev[k] += (row.get("usage") or {}).get(k) or 0
    if ev["thread_id"]:
        rollout = next((home / ".codex" / "sessions").rglob(f"rollout-*{ev['thread_id']}.jsonl"), None)
        for row in read_rows(rollout) if rollout else []:
            if row.get("type") == "turn_context":  # last one wins
                ev["model"], ev["effort"] = row["payload"].get("model"), row["payload"].get("effort")
    return ev


def codex_run(home: Path, session: str, role: str, tier: str, model: str, brief_file: Path, cd: Path,
              sandbox: str | None = None, approval_policy: str | None = None) -> int:
    """Claude coordinator -> a Codex model via `codex exec`. Same gate as a native dispatch (decide() on a synthetic
    Agent call with the model), plus: the model must also be in some Codex role's models. Receipts get a dispatch row
    and a cost row with effective model/effort. `-o` (Codex's closing message) always goes to state, never to a
    caller path: pointed at the brief's deliverable it overwrote the child's report at exit (incident 2026-09-28)."""
    permissions = worker_permissions("codex", sandbox, approval_policy)
    resolved = permissions["resolved"]
    record = activation(home, "claude", session)
    if record is None:
        raise Conflict(f"claude session {session} is not activated for thinker-worker")
    if Path.home().resolve().is_relative_to(cd.expanduser().resolve()):
        # workspace-write makes Codex's Windows sandbox ACL-walk every top-level entry under --cd: at the home
        # directory that spun codex-windows-sandbox-setup for 90+ min (2026-09-28; 150 s probe vs 19 s in a small dir).
        raise Conflict(f"--cd {cd} is the home directory or above it; pass the repo or a scratch directory")
    brief = brief_file.read_text(encoding="utf-8")
    tool_use_id = f"codex-{os.urandom(6).hex()}"
    env = {"tool_name": "codex", "tool_use_id": tool_use_id, "cwd": str(cd),
           "tool_input": {"subagent_type": agent_name(role, tier), "model": model, "prompt": brief}}
    routes = load_routes()
    d = decide("claude", env, routes)
    if d.admitted and not is_codex_model(routes, model):
        d = d._replace(admitted=False, reason=f"model {model} is not a Codex model")
    env["permissions"] = permissions
    receipt(home, "claude", session, env, d)
    if not d.admitted:
        raise Conflict(d.reason)
    exe = shutil.which("codex")
    if not exe:
        raise Conflict("codex CLI not found on PATH")
    out = state_root(home) / "codex" / f"{tool_use_id}.last.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    timeout = env_timeout("TW_CODEX_TIMEOUT")
    # on timeout the whole tree is killed: codex.CMD -> node -> codex.exe -> sandbox helpers
    ran = run_bounded(codex_cmd(exe, model, tier, cd, out, resolved["sandbox"], approval_policy=resolved["approval_policy"]), None, (AGENT_TEXT[role][1] + "\n\n" + brief).encode("utf-8"),
                      timeout)
    code, timed_out, kill_failed, stdout, stderr = ran["code"], ran["timed_out"], ran["kill_failed"], ran["out"], ran["err"]
    if timed_out:
        stderr += (f"\ncodex timed out after {timeout:g} s (TW_CODEX_TIMEOUT); "
                   + (f"killing its process tree failed; pid {ran['pid']} "
                      + ("exited" if ran["exited"] else "may still be running") if kill_failed
                      else "process tree killed"))
    ev = codex_evidence(home, stdout)
    append_receipt(home, "claude", session, {"kind": "cost", "at": now(), "harness": "claude", "session_id": session,
                                             "tool_use_id": tool_use_id, "via": "codex-exec", "exit_code": code,
                                             "timed_out": timed_out, "kill_failed": kill_failed,
                                             "requested_effort": tier, "permissions": permissions, **ev})
    print(json.dumps({"tool_use_id": tool_use_id, "last_message": str(out), "exit_code": code, "timed_out": timed_out,
                      "effective_model": ev["model"], "effective_effort": ev["effort"], "thread_id": ev["thread_id"], "permissions": permissions}))
    if code != 0:
        print(stderr[-2000:], file=sys.stderr)
    return 1 if timed_out else code


def env_timeout(name: str, default: float = 3600.0) -> float:
    return float(os.environ.get(name, str(default)))


def omp_evidence(events: str, session_file: Path | None) -> dict:
    """OMP event metadata identifies the worker; prose is never model/setting evidence."""
    rows = []
    for line in events.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    sessions = [r for r in rows if r.get("type") == "session"]
    messages = [r["message"] for r in rows if r.get("type") == "message_end"
                and isinstance(r.get("message"), dict) and r["message"].get("role") == "assistant"]
    last = messages[-1] if messages else {}
    text = "\n".join(c["text"] for c in (last.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    ends = [r for r in rows if r.get("type") == "agent_end"]
    terminal = bool(ends and ends[-1].get("isTerminal", True) is True and ends[-1].get("yielded", True) is True)
    saved = read_rows(session_file) if session_file else []
    thinking = [r.get("thinkingLevel") for r in saved if r.get("type") == "thinking_level_change"]
    usage = [m["usage"] for m in messages if isinstance(m.get("usage"), dict)]
    return {"worker_session_id": sessions[-1].get("id") if sessions else None,
            "model": last.get("model"), "provider": last.get("provider"),
            "effort": thinking[-1] if thinking else None,
            "usage": {k: sum(u.get(k, 0) or 0 for u in usage)
                      for k in ("input", "output", "cacheRead", "cacheWrite")} if usage else None,
            "terminal": terminal, "stop_reason": last.get("stopReason"), "text": text}


def omp_contract(fields: dict) -> str:
    """A compact assignment frame for OMP. Legacy briefs get truthful fallbacks; optional details make it precise."""
    scope = fields.get("TW-Scope") or "Use only the ownership and boundaries stated in the assignment body."
    checkpoint = fields.get("TW-Checkpoint") or "Preserve useful partial artifacts before the time allowance ends."
    stop = fields.get("TW-Stop") or f"Stop when the deliverable satisfies TW-Accept: {fields['TW-Accept']}"
    return "\n".join(("Assignment contract:",
                      f"Deliverable: {fields['TW-Deliverable']}",
                      f"Acceptance: {fields['TW-Accept']}",
                      f"Scope: {scope}",
                      f"Checkpoint: {checkpoint}",
                      f"Stop: {stop}"))


def omp_retry_prompt(role: str, fields: dict, cd: Path) -> str:
    return (AGENT_TEXT[role][1] + f"\n\nWorking directory: {cd}\n\n" + omp_contract(fields)
            + "\n\nThe previous attempt reached its time allowance and its process tree exited. Continue the same "
              "bounded assignment in this saved session. Inspect the current files and saved progress before acting. "
              "Do not repeat completed edits, checks, external effects, or any operation whose outcome is uncertain. "
              "If an uncertain effect prevents safe continuation, stop and report it with the useful work already present.")


def omp_run(home: Path, role: str, brief_file: Path, cd: Path, model: str | None = None,
            thinking: str | None = None, resume: Path | None = None, timeout: float | None = None,
            approval_mode: str | None = None, *, total_timeout: float | None = None,
            retry_on_timeout: bool | None = None) -> tuple[int, dict]:
    """Any caller -> configured OMP worker; caller identity and fixed-model admissions are not inputs."""
    brief = brief_file.expanduser().resolve().read_text(encoding="utf-8-sig")
    found_role, problem = first_role(brief)
    fields, header_problem = header_fields(brief)
    if problem or header_problem or found_role != role:
        raise Conflict(problem or header_problem or "OMP role does not match the brief")
    if role in {"independent-review", "ideation"} and not review_details(brief):
        raise Conflict("review/ideation needs TW-Authorization and TW-Scope")
    cd = cd.expanduser().resolve()
    if not cd.is_dir():
        raise Conflict(f"working directory does not exist: {cd}")
    resume = resume.expanduser().resolve() if resume else None
    if resume and not resume.is_file():
        raise Conflict(f"OMP resume file does not exist: {resume}")
    explicit_timeout = timeout is not None or "TW_OMP_TIMEOUT" in os.environ
    try:
        timeout = env_timeout("TW_OMP_TIMEOUT", OMP_DEFAULT_TIMEOUT) if timeout is None else timeout
    except ValueError as exc:
        raise Conflict("TW_OMP_TIMEOUT must be positive finite seconds") from exc
    if not 0 < timeout < float("inf"):
        raise Conflict("OMP timeout must be positive finite seconds")
    if total_timeout is not None and not 0 < total_timeout < float("inf"):
        raise Conflict("OMP total timeout must be positive finite seconds")
    risks = {risk.strip() for risk in fields["TW-Risk"].split(",")}
    unsafe_retry = risks & {"external", "destructive"}
    if retry_on_timeout is True and unsafe_retry:
        raise Conflict("OMP timeout retry is unavailable for destructive or external work")
    retry_enabled = (retry_on_timeout if retry_on_timeout is not None
                     else (not explicit_timeout or total_timeout is not None)) and not unsafe_retry
    exe = shutil.which("omp")
    if not exe:
        raise Conflict("OMP executable not found on PATH")
    run_id = "omp-" + uuid.uuid4().hex
    folder = state_root(home) / "omp" / run_id
    folder.mkdir(parents=True)
    prompt = folder / "brief.md"
    prompt_text = (AGENT_TEXT[role][1] + f"\n\nWorking directory: {cd}\n\n" + omp_contract(fields)
                   + "\n\nAssignment:\n" + brief)
    prompt.write_text(prompt_text, encoding="utf-8")
    sessions = folder / "sessions"
    base_argv = [exe, "--print", "--mode", "json", "--wait-async", "--no-title", "--cwd", str(cd)]
    for flag, value in (("--model", model), ("--thinking", thinking), ("--approval-mode", approval_mode)):
        if value is not None:
            base_argv.extend([flag, value])
    first_argv = base_argv + (["--resume", str(resume)] if resume else ["--session-dir", str(sessions)])
    if os.name == "nt" and Path(exe).suffix.lower() in {".cmd", ".bat"} and any(
            re.search(r'[\r\n"&|<>^%!]', arg) for arg in first_argv[1:]):
        raise Conflict("OMP batch launcher cannot safely carry shell metacharacters; use the native OMP executable")
    envelope = {"tool_name": "omp", "tool_use_id": run_id, "cwd": str(cd), "tool_input": {}}
    receipt(home, "omp", run_id, envelope, Decision(True, "explicit-omp-subprocess", role, model, thinking, fields))
    started = time.monotonic()
    first_timeout = min(timeout, total_timeout) if total_timeout is not None else timeout
    first = run_bounded(first_argv, cd, prompt_text.encode("utf-8"), first_timeout)
    initial = omp_evidence(first["out"], None)
    session_file = resume
    if not resume and isinstance(initial["worker_session_id"], str):
        session_file = next((p for p in sessions.glob("*.jsonl")
                             if p.stem.endswith("_" + initial["worker_session_id"])), None)

    attempts = [{"attempt": 1, "timeout_seconds": first_timeout, "exit_code": first["code"],
                 "timed_out": first["timed_out"], "kill_failed": first["kill_failed"],
                 "pid": first["pid"], "exited": first["exited"]}]
    retry_used, retry_skipped_reason = False, None
    ran, combined_out, combined_err = first, first["out"], first["err"]
    if first["timed_out"]:
        if not retry_enabled:
            retry_skipped_reason = ("risk excludes automatic retry" if unsafe_retry else
                                    "retry was explicitly disabled" if retry_on_timeout is False else
                                    "explicit timeout keeps legacy single-attempt behavior")
        elif first["kill_failed"] or not first["exited"]:
            retry_skipped_reason = "first process tree did not verifiably exit"
        elif not session_file:
            retry_skipped_reason = "no saved OMP session was available for continuity"
        else:
            remaining = None if total_timeout is None else total_timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                retry_skipped_reason = "hard total timeout was exhausted"
            else:
                retry_timeout = timeout if remaining is None else min(timeout, remaining)
                retry_text = omp_retry_prompt(role, fields, cd)
                retry_argv = base_argv + ["--resume", str(session_file)]
                retry_used = True
                second = run_bounded(retry_argv, cd, retry_text.encode("utf-8"), retry_timeout)
                attempts.append({"attempt": 2, "timeout_seconds": retry_timeout, "exit_code": second["code"],
                                 "timed_out": second["timed_out"], "kill_failed": second["kill_failed"],
                                 "pid": second["pid"], "exited": second["exited"]})
                ran = second
                combined_out = first["out"] + ("\n" if first["out"] else "") + second["out"]
                combined_err = first["err"] + ("\n" if first["err"] else "") + second["err"]
    events, errors, last_file = folder / "events.jsonl", folder / "stderr.log", folder / "last.md"
    events.write_bytes(combined_out.encode("utf-8"))
    errors.write_bytes(combined_err.encode("utf-8"))
    if retry_used:
        for number, attempt in enumerate((first, ran), 1):
            attempt_events = folder / f"events-attempt-{number}.jsonl"
            attempt_errors = folder / f"stderr-attempt-{number}.log"
            attempt_events.write_bytes(attempt["out"].encode("utf-8"))
            attempt_errors.write_bytes(attempt["err"].encode("utf-8"))
            attempts[number - 1].update(events=str(attempt_events), stderr=str(attempt_errors))
    # Completion and the returned final answer come only from the last attempt. Combined logs remain available as evidence.
    ev = omp_evidence(ran["out"], session_file)
    if ev["worker_session_id"] is None:
        ev["worker_session_id"] = initial["worker_session_id"]
    last_file.write_text(ev.pop("text"), encoding="utf-8")
    complete = bool(ran["code"] == 0 and not ran["timed_out"] and ev["terminal"]
                    and ev["stop_reason"] == "stop" and last_file.read_text(encoding="utf-8").strip())
    append_receipt(home, "omp", run_id, {"kind": "cost", "at": now(), "harness": "omp",
                   "session_id": run_id, "tool_use_id": run_id, "via": "omp", "exit_code": ran["code"],
                   "timed_out": ran["timed_out"], "kill_failed": ran["kill_failed"],
                   "completed": complete, "timeout_seconds": timeout, "total_timeout_seconds": total_timeout,
                   "initial_timed_out": first["timed_out"], "retry_enabled": retry_enabled,
                   "retry_used": retry_used, "retry_skipped_reason": retry_skipped_reason,
                   "attempts": attempts, **ev})
    result = {"session_id": run_id, "tool_use_id": run_id, "worker_session_id": ev["worker_session_id"],
              "session_file": str(session_file) if session_file else None,
              "requested_model": model, "requested_thinking": thinking,
              "effective_model": ev["model"], "provider": ev["provider"],
              "observed_thinking": ev["effort"], "usage": ev["usage"],
              "exit_code": ran["code"], "completed": complete, "timed_out": ran["timed_out"],
              "kill_failed": ran["kill_failed"], "pid": ran["pid"], "exited": ran["exited"],
              "timeout_seconds": timeout, "total_timeout_seconds": total_timeout,
              "initial_timed_out": first["timed_out"], "retry_enabled": retry_enabled,
              "retry_used": retry_used, "retry_skipped_reason": retry_skipped_reason, "attempts": attempts,
              "events": str(events), "stderr": str(errors), "last_message": str(last_file)}
    (folder / "result.json").write_bytes(canonical_json(result))
    return (0 if complete else ran["code"] or 1), result


def agy_evidence(events: str) -> dict:
    """agy stream-json events carry the conversation, the model it reports, and the final result; prose is not evidence."""
    rows = []
    for line in events.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    init = next((r for r in rows if r.get("event") == "init"), {})
    results = [r["result"] for r in rows if r.get("event") == "result" and isinstance(r.get("result"), dict)]
    final = results[-1] if results else {}
    meta = init.get("init") if isinstance(init.get("init"), dict) else {}
    text = final.get("response") if isinstance(final.get("response"), str) else ""
    # init.model echoes the requested selector (absent for agy's default): a report, not executed-model evidence
    return {"conversation_id": init.get("conversation_id"), "reported_model": meta.get("model"),
            "usage": final.get("usage"), "status": final.get("status"),
            "finished_reason": final.get("finished_reason"), "text": text}


def agy_run(home: Path, role: str, brief_file: Path, cd: Path, model: str | None = None,
            effort: str | None = None, mode: str | None = None, resume: str | None = None,
            timeout: float | None = None) -> tuple[int, dict]:
    """Any caller -> Antigravity `agy` headless worker; agy owns the model catalogue, no native admission is involved."""
    brief = brief_file.expanduser().resolve().read_text(encoding="utf-8-sig")
    found_role, problem = first_role(brief)
    fields, header_problem = header_fields(brief)
    if problem or header_problem or found_role != role:
        raise Conflict(problem or header_problem or "agy role does not match the brief")
    if role in {"independent-review", "ideation"} and not review_details(brief):
        raise Conflict("review/ideation needs TW-Authorization and TW-Scope")
    cd = cd.expanduser().resolve()
    if not cd.is_dir():
        raise Conflict(f"working directory does not exist: {cd}")
    try:
        timeout = env_timeout("TW_AGY_TIMEOUT") if timeout is None else timeout
    except ValueError as exc:
        raise Conflict("TW_AGY_TIMEOUT must be positive finite seconds") from exc
    if not 0 < timeout < float("inf"):
        raise Conflict("agy timeout must be positive finite seconds")
    permissions = worker_permissions("agy", permission_mode=mode)
    exe = shutil.which("agy")
    if not exe:
        raise Conflict("agy executable not found on PATH")
    argv = [exe, "--print", "", "--input-format", "stream-json", "--output-format", "stream-json"]
    for flag, value in (("--model", model), ("--effort", effort), ("--mode", mode), ("--conversation", resume)):
        if value is not None:
            argv.extend([flag, value])
    if mode is None:
        argv.append("--dangerously-skip-permissions")
    if os.name == "nt" and Path(exe).suffix.lower() in {".cmd", ".bat"} and any(
            re.search(r'[\r\n"&|<>^%!]', arg) for arg in argv[1:] if arg):
        raise Conflict("agy batch launcher cannot safely carry shell metacharacters; use the native agy executable")
    run_id = "agy-" + uuid.uuid4().hex
    folder = state_root(home) / "agy" / run_id
    folder.mkdir(parents=True)
    prompt_text = AGENT_TEXT[role][1] + f"\n\nWorking directory: {cd}\n\n" + brief
    (folder / "brief.md").write_text(prompt_text, encoding="utf-8")
    stdin = json.dumps({"event": "user", "message": {"content": prompt_text}}) + "\n"
    envelope = {"tool_name": "agy", "tool_use_id": run_id, "cwd": str(cd), "tool_input": {}}
    receipt(home, "agy", run_id, envelope, Decision(True, "explicit-agy-subprocess", role, model, None, fields))
    ran = run_bounded(argv, cd, stdin.encode("utf-8"), timeout)
    events, errors, last_file = folder / "events.jsonl", folder / "stderr.log", folder / "last.md"
    events.write_bytes(ran["out"].encode("utf-8"))
    errors.write_bytes(ran["err"].encode("utf-8"))
    ev = agy_evidence(ran["out"])
    last_file.write_text(ev.pop("text"), encoding="utf-8")
    complete = bool(ran["code"] == 0 and not ran["timed_out"] and ev["status"] == "SUCCESS"
                    and last_file.read_text(encoding="utf-8").strip())
    append_receipt(home, "agy", run_id, {"kind": "cost", "at": now(), "harness": "agy",
                   "session_id": run_id, "tool_use_id": run_id, "via": "agy", "exit_code": ran["code"],
                   "timed_out": ran["timed_out"], "kill_failed": ran["kill_failed"], "completed": complete,
                   "requested_effort": effort, "permissions": permissions, **ev})  # agy reports no executed effort
    result = {"session_id": run_id, "tool_use_id": run_id, "conversation_id": ev["conversation_id"],
              "requested_model": model, "requested_effort": effort, "reported_model": ev["reported_model"],
              "usage": ev["usage"], "status": ev["status"], "finished_reason": ev["finished_reason"],
              "exit_code": ran["code"], "completed": complete, "timed_out": ran["timed_out"],
              "kill_failed": ran["kill_failed"], "pid": ran["pid"], "exited": ran["exited"],
              "events": str(events), "stderr": str(errors), "last_message": str(last_file),
              "permissions": permissions}
    (folder / "result.json").write_bytes(canonical_json(result))
    return (0 if complete else ran["code"] or 1), result


def dispatch_state(rows: list[dict], tool_use_id: str | None = None) -> tuple[dict | None, str]:
    """The dispatch row for tool_use_id (default: the last one) and its gate decision: none, deny or admit."""
    disp = [r for r in rows if r.get("kind") == "dispatch" and tool_use_id in (None, r.get("tool_use_id"))]
    if not disp:
        return None, "none"
    row = disp[-1]
    if row.get("decision") != "admit":
        return row, "deny"
    return row, "admit"


def record_cost(home: Path, harness: str, session: str, tool_use_id: str, rows: list[dict]) -> dict | None:
    """Append the dispatch's Claude cost row once (a cost-error row if the child's files are unreadable)."""
    if any(r.get("kind") == "cost" and r.get("tool_use_id") == tool_use_id for r in rows):
        return None
    try:
        row = cost_row(home, harness, session, tool_use_id)
    except Exception as exc:
        row = {"kind": "cost-error", "at": now(), "harness": harness, "session_id": session,
               "tool_use_id": tool_use_id, "error": f"{type(exc).__name__}: {exc}"[:200]}
    if row is not None:
        append_receipt(home, harness, session, row)
    return row


def claude_run(home: Path, role: str, tier: str, brief_file: Path, cd: Path, model: str | None = None,
               relay_model: str = "sonnet", permission_mode: str | None = None) -> tuple[int, dict]:
    """Any shell (Codex) -> a guarded native Claude dispatch. A fresh session is activated, then a `claude -p` relay
    makes exactly one native Agent call; the PreToolUse hook gates it and writes the receipts as for any dispatch.
    Returns (exit code, result): 0 ran, 1 failed run, 2 denied. The result carries executed evidence from
    the child's transcript, never the relay's or the child's self-report."""
    permissions = worker_permissions("claude", permission_mode=permission_mode)
    permission_mode = permissions["resolved"]["permission_mode"]
    brief = Path(brief_file).expanduser().resolve().read_text(encoding="utf-8")
    agent = agent_name(role, tier)
    routes = load_routes()
    pinned_opus = role == "independent-review" and model == OPUS_REVIEW_MODEL
    native_model = None if pinned_opus else model
    if pinned_opus:
        agent += "-opus55"
    pre = decide("claude", {"tool_name": "Agent", "tool_input": {"subagent_type": agent, "model": native_model,
                                                                "prompt": brief}}, routes)
    if not pre.admitted:  # fail before spending a relay session; the hook re-checks the real call
        raise Conflict(pre.reason)
    if pinned_opus:
        expected = agent_files(routes).get(f"{agent}.md")
        definition = home / ".claude" / "agents" / f"{agent}.md"
        if expected is None or not definition.is_file() or definition.read_bytes() != expected:
            raise Conflict("pinned Opus review definition missing or changed; use normal upgrade/check")
        for parent in (Path(cd).resolve(), *Path(cd).resolve().parents):
            if parent == home.resolve() or parent == Path.home().resolve():
                break
            if (parent / ".claude" / "agents" / f"{agent}.md").exists():
                raise Conflict("project-local agent shadows pinned Opus review definition")
    exe = shutil.which("claude")
    if not exe:
        raise Conflict("claude CLI not found on PATH")
    session = str(uuid.uuid4())
    activate(home, "claude", session)
    append_receipt(home, "claude", session, {"kind": "permissions", "at": now(), "harness": "claude",
        "session_id": session, "via": "claude-relay", "permissions": permissions})
    relay = "\n".join([
        "Relay only. Make exactly one foreground Agent tool call with these parameters and nothing else:",
        f"subagent_type: {agent}", *([f"model: {native_model}"] if native_model else []),
        "prompt: the text between the BRIEF-BEGIN and BRIEF-END lines below, verbatim.",
        "If the call is denied, print the denial verbatim and stop: no retry, no edits, no doing the work yourself.",
        "Otherwise print the subagent's final message verbatim and nothing else.",
        "BRIEF-BEGIN", brief, "BRIEF-END"])
    ran = run_bounded([exe, "-p", "--session-id", session, "--model", relay_model, "--effort", "low",
                       "--permission-mode", permission_mode], Path(cd).expanduser().resolve(), relay.encode("utf-8"),
                      env_timeout("TW_CLAUDE_TIMEOUT"))
    out = state_root(home) / "claude" / f"{session}.last.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ran["out"], encoding="utf-8")
    rows = read_rows(receipts_path(home, "claude", session))
    disp, state = dispatch_state(rows)
    tool_use_id = disp.get("tool_use_id") if disp else None
    cost = record_cost(home, "claude", session, tool_use_id, rows) if state == "admit" else None
    cost = cost if cost and cost.get("kind") == "cost" else {}
    result = {"session_id": session, "tool_use_id": tool_use_id, "decision": None if state == "none" else state,
              "reason": disp.get("reason") if disp else None, "agent_type": cost.get("agent_type"),
              "effective_model": cost.get("model"), "effective_effort": cost.get("effort"), "exit_code": ran["code"],
              "timed_out": ran["timed_out"], "kill_failed": ran["kill_failed"], "last_message": str(out), "permissions": permissions}
    if state == "deny":
        return 2, result
    if pinned_opus and (result["effective_model"] != OPUS_REVIEW_MODEL or result["effective_effort"] != tier):
        result["identity_error"] = "pinned Opus review model/effort not verified; result is not accepted"
        return 1, result
    return (0 if result["effective_model"] and ran["code"] == 0 else 1), result


SPOOL_KEYS = ("role", "tier", "brief_file", "cd", "model", "relay_model", "permission_mode")  # claude_run's own


def spool_once(home: Path) -> None:
    """For sandboxed Codex threads (no network): each `spool/inbox/<name>.json` job, keyed by claude_run's own
    parameters, becomes one claude_run outside the sandbox; `spool/done/<name>.result.json` gets its exit code and
    result. A job is claimed by an atomic rename into done/ before it runs, so it runs once. Writers drop
    `<name>.json.tmp`, then rename. ponytail: sequential, one job at a time; a worker pool if jobs ever queue up."""
    inbox, done = state_root(home) / "spool" / "inbox", state_root(home) / "spool" / "done"
    for job in sorted(inbox.glob("*.json")):  # a missing inbox globs nothing
        done.mkdir(parents=True, exist_ok=True)
        claimed = done / job.name
        try:
            job.replace(claimed)
        except OSError:
            continue  # another watcher claimed it
        res = {"job": job.name, "exit_code": 2, "result": None, "error": None}
        try:
            spec = read_json(claimed, None)
            if not isinstance(spec, dict) or set(spec) - set(SPOOL_KEYS):
                raise Conflict(f"job must be an object with keys from {list(SPOOL_KEYS)}")
            res["exit_code"], res["result"] = claude_run(home, **spec)
        except (Conflict, OSError, TypeError, ValueError) as exc:
            res["error"] = f"{type(exc).__name__}: {exc}"[:500]
        atomic_write(done / f"{claimed.stem}.result.json", canonical_json(res), None)


COST_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def subagents_dirs(home: Path, session: str, transcript_path: str | None = None) -> list[Path]:
    if transcript_path:
        return [Path(transcript_path).with_suffix("") / "subagents"]
    return list((home / ".claude" / "projects").glob(f"*/{session}/subagents"))


def child_files(dirs: list[Path], tool_use_id: str) -> tuple[dict, Path] | None:
    for folder in dirs:
        for meta_path in folder.glob("agent-*.meta.json"):
            try:  # one torn sibling meta must not hide this child
                meta = read_json(meta_path, {})
            except Conflict:
                continue
            if isinstance(meta, dict) and meta.get("toolUseId") == tool_use_id:
                return meta, meta_path.with_name(meta_path.name[: -len(".meta.json")] + ".jsonl")
    return None


def cost_row(home: Path, harness: str, session: str, tool_use_id: str) -> dict | None:
    found = child_files(subagents_dirs(home, session), tool_use_id)
    if found is None or not found[1].exists():
        return None
    meta, transcript = found
    usage, advisor_ids = {}, set()
    rows = read_rows(transcript)
    for obj in rows:
        msg = obj.get("message") or {}
        if obj.get("type") != "assistant":
            continue
        for b in msg.get("content") or []:  # an advisor call: a server_tool_use block, counted once per block id
            if isinstance(b, dict) and b.get("type") == "server_tool_use" and b.get("name") == "advisor":
                advisor_ids.add(b.get("id"))
        if msg.get("id") and msg.get("usage") and msg.get("model") != "<synthetic>":  # an error stub is no API call
            usage[msg["id"]] = msg["usage"]  # last row per message.id carries the final counts
    # advisor tokens appear only in usage.iterations (never top-level); subagent rows may lack iterations
    adv = [it for u in usage.values() for it in u.get("iterations") or [] if it.get("type") == "advisor_message"]
    ran = [m for m in ((o.get("message") or {}).get("model") for o in rows if o.get("type") == "assistant")
           if m and m != "<synthetic>"]  # an error stub names no model
    att = [o.get("attachment") or {} for o in rows if o.get("type") == "attachment"]
    eff = next((o["effort"] for o in reversed(rows) if o.get("type") == "assistant" and o.get("effort")), None)
    return {"kind": "cost", "at": now(), "harness": harness, "session_id": session, "tool_use_id": tool_use_id,
            # model: executed evidence only; meta.json's model is the request (an alias), never recorded as the model that ran
            "agent_type": meta.get("agentType"), "model": ran[-1] if ran else None, "requested_model": meta.get("model"),
            # offered at any point in the run; a later available:false removal does not clear it
            "advisor_available": any(a.get("type") == "advisor_tool" and a.get("available") is True for a in att),
            "api_calls": len(usage),
            # effort: the transcript's own per-turn field (executed); absent when the transcript lacks it, so
            # tally falls back to the agent_type tier
            **({"effort": eff} if eff else {}),
            **{k: sum(u.get(k, 0) for u in usage.values()) for k in COST_KEYS},
            "advisor_calls": len(advisor_ids), "advisor_model": next((it.get("model") for it in adv), None),
            "advisor_input_tokens": sum(it.get("input_tokens", 0) for it in adv),
            "advisor_output_tokens": sum(it.get("output_tokens", 0) for it in adv)}


def harness_rows(home: Path, harness: str) -> list[dict]:
    """Every receipt row of the harness, preserving session-file order (torn lines skipped).
    The receipt filename supplies the session join key, including rows without session_id."""
    return [{**r, "_session_file": p.stem}
            for p in (state_root(home) / "receipts" / harness).glob("*.jsonl") for r in read_rows(p)]


def dispatch_key(r: dict) -> tuple[str, str | None]:
    return r["_session_file"], r.get("tool_use_id")


def tally(home: Path, harness: str) -> list[dict]:
    """Accept counts per (class, executed model, executed tier) over labeled, admitted dispatches. Label: the latest
    check row (pass/fail; unknown ignored), else the coordinator's latest outcome. Executed model/tier: the cost row's
    model and effort, else the tier of its tw-* agent_type; a dispatch with neither is counted at its requested tier
    with model None. Historical exploration rewrites therefore count at the tier that actually ran."""
    rows = harness_rows(home, harness)

    def latest(kind: str) -> dict:  # the last row of a kind per dispatch
        return {dispatch_key(r): r for r in rows if r.get("kind") == kind}
    disp, cost, out, chk = latest("dispatch"), latest("cost"), latest("outcome"), latest("check")
    groups = {}
    for k, d in disp.items():
        # ponytail: a regex, not header_fields(): receipts hold the header without its role line and cut at 256 chars
        m = re.search(r"^TW-Class: (.+)$", d.get("header") or "", re.M)
        label = {"pass": True, "fail": False}.get((chk.get(k) or {}).get("label"))
        if label is None:
            label = (out.get(k) or {}).get("accepted")
        if d.get("decision") != "admit" or not m or label is None:
            continue
        c = cost.get(k) or {}
        agent = AGENT_NAME.fullmatch(c.get("agent_type") or "")
        tier = c.get("effort") or (agent.group(2) if agent else d.get("tier"))
        g = groups.setdefault((m.group(1), c.get("model"), tier), [0, 0])
        g[0] += 1
        g[1] += bool(label)
    return [{"class": cls, "model": mod, "tier": t, "n": n, "accepted": a, "rate": round(a / n, 3)}
            for (cls, mod, t), (n, a) in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]


def clamp(tier: str, tiers: list[str]) -> str:
    i = TIERS.index(tier)
    return min(tiers, key=lambda t: (abs(TIERS.index(t) - i), TIERS.index(t)))


def hook(home: Path, harness: str, owner: str) -> None:
    if owner != OWNER:
        denial("unknown installed hook owner")
        return
    try:
        # Hook transport is UTF-8, not the Windows locale. PowerShell may add a BOM.
        payload = getattr(sys.stdin, "buffer", sys.stdin).read()
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8-sig")
        envelope = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        denial("malformed hook JSON; routing state cannot be established")
        return
    if not isinstance(envelope, dict):
        denial("hook envelope must be an object")
        return
    tool = envelope.get("tool_name")
    if tool not in ({"spawn_agent", "collaborationspawn_agent", "Agent"} if harness == "codex" else {"Agent"}):
        return
    session = envelope.get("session_id")
    try:
        session = session_value(session)
    except Conflict:
        denial("missing or invalid session_id on native dispatch")
        return
    try:
        record = activation(home, harness, session)
    except Conflict as exc:
        denial(str(exc))
        receipt(home, harness, session, envelope, Decision(False, "invalid-state"))
        return
    if record is None:
        return
    if envelope.get("hook_event_name") != "PreToolUse":
        denial("unexpected hook_event_name on native dispatch")
        receipt(home, harness, session, envelope, Decision(False, "invalid-event"))
        return
    inp = envelope.get("tool_input")
    if isinstance(inp, dict) and any(k in inp for k in ("resume", "resume_id", "agent_id")):
        receipt(home, harness, session, envelope, Decision(False, "resume-key-on-fresh-dispatch"))
        denial("resume fields are outside fresh dispatch; coordinator must verify child identity before native continuation")
        return
    routes = load_routes()
    d = decide(harness, envelope, routes)
    receipt(home, harness, session, envelope, d)
    if routes.get("_override_error"):  # the override failed open: the installed routes decided; say so every dispatch
        append_receipt(home, harness, session, {"kind": "error", "at": now(), "harness": harness, "session_id": session,
                                                "tool_use_id": envelope.get("tool_use_id"), "where": "override",
                                                "error": routes["_override_error"]})
    if not d.admitted:
        denial(d.reason)
        return
    if d.role is None or tool == "collaborationspawn_agent":
        return  # ponytail: Codex v2 ciphertext; the task_name join is phase 2
    out = reminder(harness, d, routes, envelope["tool_input"].get("prompt"))
    if out:
        print(json.dumps(out))


def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def source_items(harnesses: tuple[str, ...] = HARNESSES) -> dict[str, bytes]:
    root = source_root()
    out = {}
    for harness in harnesses:
        for rel in SKILL_FILES:
            out[f".{harness}/skills/thinker-worker/{rel}"] = (root / rel).read_bytes()
    if "claude" in harnesses:
        for name, data in agent_files(load_routes(root / "routes.json")).items():
            out[f".claude/agents/{name}"] = data
    return out


AGENT_TEXT = {  # role -> (description, body); bodies carried over from the retired hand-written agents
    "worker": ("Bounded execution for thinker/worker mode; coordinator owns framing and acceptance.",
               "Execute the coordinator's bounded assignment. Preserve other agents' edits. Checkpoint meaningful "
               "progress, run proportional checks, and report exact artifacts, results, and uncertainties. Escalate a "
               "changed objective or consequential assumption to the coordinator. Do not dispatch children without "
               "explicit bounded authorization."),
    "leaf": ("Short, objectively checkable leaf for an opted-in thinker/worker session.",
             "Complete only the coordinator's bounded leaf assignment. Use supplied rules for extraction, inventory, or "
             "simple reconciliation; report exact artifacts and checks. Escalate ambiguity or judgment calls to the "
             "coordinator. Preserve other agents' edits and do not dispatch children."),
    "independent-review": ("Bounded independent review when the coordinator cites authorization.",
                           "Review the assigned artifact adversarially. Identify unsupported, incorrect, fragile, or "
                           "overbuilt parts with exact source references; run a check yourself when it settles a claim. "
                           "Report findings; do not edit the files under review. Stay within the bounded assignment. Do "
                           "not treat the request's model name as evidence of the effective runtime model. Do your own "
                           "pass against the acceptance criteria before reading any coordinator hypotheses; if the brief "
                           "lists claims to test, answer them after your findings, in their own section."),
    "ideation": ("Bounded ideation (divergent) when the coordinator cites authorization.",
                 "Propose at most the requested number of ranked directions. Label each speculative and state what "
                 "would confirm or kill it; cite prior art you find. Do not edit project files. Stay within the bounded "
                 "assignment."),
}


# Native Claude children only: Claude Code may refuse a subagent's Write of a report-like file (REFUSED_OUTPUT);
# if it does, the artifact must survive whole in the final message, not as a summary.
NATIVE_WRITE_FALLBACK = (" If a Write of your deliverable file is refused, return the complete artifact verbatim in "
                         "your final message, not a summary, and name the path it was meant for.")


def agent_files(routes: dict) -> dict[str, bytes]:
    out = {}
    for role, pol in routes["harnesses"]["claude"]["roles"].items():
        desc, body = AGENT_TEXT[role]
        for tier in pol["tiers"]:
            name = agent_name(role, tier)
            head = ["---", f"name: {name}", f"description: {desc} Effort {tier}.",
                    f"model: {pol['models'][0]}", f"effort: {tier}"]
            if pol.get("tools"):
                head.append("tools: " + ", ".join(pol["tools"]))
            out[f"{name}.md"] = ("\n".join(head + ["---", "", body + NATIVE_WRITE_FALLBACK, ""])).encode("utf-8")
            if role == "independent-review" and OPUS_REVIEW_MODEL in pol["models"] and tier in model_tiers(pol, OPUS_REVIEW_MODEL):
                pinned_name = name + "-opus55"
                pinned_head = [x.replace(f"name: {name}", f"name: {pinned_name}")
                               .replace(f"model: {pol['models'][0]}", f"model: {OPUS_REVIEW_MODEL}") for x in head]
                out[f"{pinned_name}.md"] = ("\n".join(pinned_head + ["---", "", body + NATIVE_WRITE_FALLBACK, ""])).encode("utf-8")
    return out


def installed_harnesses(manifest: dict) -> tuple[str, ...]:
    return tuple(manifest.get("harnesses", HARNESSES))  # manifests before --harness cover both


def portable_command(harness: str, python_cmd: str | None) -> str:
    """Home-relative bash hook for a settings.json synced across Windows and Mac: resolves the skill
    via $USERPROFILE (Windows) or $HOME, runs the first interpreter that starts, no-ops if absent."""
    run = f'"$tw" hook --home "$h" --harness {harness} --owner {OWNER}'
    candidates = ([python_cmd] if python_cmd else []) + ["python3", "python", "py -3"]
    # ponytail: probing costs one extra interpreter start per dispatch.
    probes = "".join(f'if {c} -c "" >/dev/null 2>&1; then exec {c} {run}; fi; ' for c in candidates)
    # No interpreter: block (exit 2) only if this machine holds activation state; inactive is a no-op.
    blocked = ('for f in "$h"/.thinker-worker/state/*/*.json; do if [ -f "$f" ]; then '
               f'echo "{OWNER}: guard could not run: no Python interpreter started. Put python3 or python on PATH, '
               'reinstall with --portable --python-cmd <interpreter>, or deactivate the session." >&2; exit 2; fi; done; ')
    return ('h="$HOME"; if [ "$OS" = Windows_NT ] && [ -n "$USERPROFILE" ]; then h="$USERPROFILE"; fi; '
            f'tw="$h/.{harness}/skills/thinker-worker/scripts/tw.py"; [ -f "$tw" ] || exit 0; ' + probes + blocked + "exit 0")


def portable_windows_command(harness: str) -> str:
    """PowerShell twin of portable_command for Codex's Windows runner (cmd /C, no bash guaranteed).
    --python-cmd is bash syntax, so it is not applied here; PATH python is searched instead."""
    ps = f"""$ProgressPreference = 'SilentlyContinue'
$h = $env:USERPROFILE; if (-not $h) {{ $h = $HOME }}
$tw = Join-Path $h '.{harness}/skills/thinker-worker/scripts/tw.py'
if (-not (Test-Path -LiteralPath $tw -PathType Leaf)) {{ exit 0 }}
$in = [Console]::In.ReadToEnd()
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
foreach ($c in 'python3', 'python', 'py -3') {{
  $p = $c.Split(' '); $exe = $p[0]; $pre = @($p | Select-Object -Skip 1)
  if (Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue) {{
    & $exe @pre -c 0 *> $null
    if ($LASTEXITCODE -eq 0) {{ $in | & $exe @pre $tw hook --home $h --harness {harness} --owner {OWNER}; exit $LASTEXITCODE }}
  }}
}}
if (Test-Path (Join-Path $h '.thinker-worker/state/*/*.json')) {{
  [Console]::Error.WriteLine('{OWNER}: guard could not run: no Python interpreter started. Put python on PATH or deactivate the session.'); exit 2
}}
exit 0
"""
    import base64
    return "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(ps.encode("utf-16le")).decode("ascii")


def hook_entry(harness: str, home: Path, python: Path, portable: bool = False,
               python_cmd: str | None = None) -> dict:
    installed = home / f".{harness}" / "skills" / "thinker-worker" / "scripts" / "tw.py"
    argv = [str(python), str(installed), "hook", "--home", str(home),
            "--harness", harness, "--owner", OWNER]
    if harness == "claude" and portable:
        handler = {"type": "command", "command": portable_command(harness, python_cmd), "timeout": 10}
    elif portable:
        handler = {"type": "command", "command": portable_command(harness, python_cmd),
                   "commandWindows": portable_windows_command(harness), "timeout": 10}
    elif harness == "claude":
        # Claude's exec form avoids Git Bash/PowerShell parsing on Windows.
        handler = {"type": "command", "command": str(python), "args": argv[1:], "timeout": 10}
    else:
        handler = {"type": "command", "command": shlex.join(argv),
                   "commandWindows": windows_codex_command(argv), "timeout": 10}
    return {"matcher": "^(Agent|spawn_agent|collaborationspawn_agent)$" if harness == "codex" else "^Agent$",
            "hooks": [handler]}


def windows_codex_command(argv: list[str]) -> str:
    # Codex's Windows hook runner uses cmd /C. Its current outer quoting can
    # mis-handle embedded quotes, so use a plain command for safe paths.
    if all(re.fullmatch(r"[A-Za-z0-9_./:\\-]+", part) for part in argv):
        return " ".join(argv)
    # Alternate homes with spaces still work without embedded quotes in the
    # cmd command line. The encoded payload calls only the fixed Python script.
    escaped = ["'" + part.replace("'", "''") + "'" for part in argv]
    ps = "& " + " ".join(escaped)
    import base64
    payload = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
    return "powershell.exe -NoProfile -EncodedCommand " + payload


def config_path(home: Path, harness: str) -> Path:
    return home / (".codex/hooks.json" if harness == "codex" else ".claude/settings.json")


def owned_entries(doc: dict) -> list[dict]:
    hooks = doc.get("hooks", {})
    if not isinstance(hooks, dict):
        raise Conflict("hooks must be an object")
    pre = hooks.get("PreToolUse", [])
    if not isinstance(pre, list):
        raise Conflict("hooks.PreToolUse must be an array")
    result = []
    for entry in pre:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise Conflict("Each PreToolUse entry needs an object with a hooks array")
        if any(isinstance(hook, dict) and OWNER in json.dumps(hook)
               for hook in entry["hooks"]):
            result.append(entry)
    return result


def config_doc(path: Path) -> tuple[dict, bytes | None]:
    raw = path.read_bytes() if path.exists() else None
    doc = read_json(path, {})
    if not isinstance(doc, dict):
        raise Conflict(f"Configuration root must be an object: {path}")
    return doc, raw


def add_entry(doc: dict, entry: dict) -> dict:
    result = json.loads(json.dumps(doc))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise Conflict("hooks must be an object")
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        raise Conflict("hooks.PreToolUse must be an array")
    pre.append(entry)
    return result


def remove_entry(doc: dict, entry: dict) -> dict:
    result = json.loads(json.dumps(doc))
    pre = result["hooks"]["PreToolUse"]
    matches = [i for i, existing in enumerate(pre) if existing == entry]
    if len(matches) != 1:
        raise Conflict("Owned hook entry changed or duplicated; refusing uninstall")
    pre.pop(matches[0])
    if not pre:
        del result["hooks"]["PreToolUse"]
    if not result["hooks"]:
        del result["hooks"]
    return result


def manifest_path(home: Path) -> Path:
    return state_root(home) / "manifest.json"


def machine_id() -> str:
    """Stable, non-secret machine label: TW_MACHINE_ID (tests, overrides) else OS + hostname."""
    raw = os.environ.get("TW_MACHINE_ID") or f"{platform.system()}-{socket.gethostname()}"
    return re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-") or "unknown"


def default_ledger_dir(home: Path) -> Path:
    return home / ".claude" / "thinker-worker-installs"  # inside the git-synced ~/.claude


def write_ledger(ledger_dir: Path, mid: str, status: str, flags: dict, hooks: dict) -> None:
    path = ledger_dir / f"{mid}.json"
    old = path.read_bytes() if path.exists() else None
    prior = read_json(path, {}) if old is not None else {}
    stamp = now()
    doc = {"machine_id": mid, "os": platform.system(), "status": status,
           "installed_at": prior.get("installed_at", stamp) if status == "installed" else prior.get("installed_at"),
           "updated_at": stamp,
           "tw_sha256": sha((source_root() / "scripts" / "tw.py").read_bytes()),
           "flags": flags, "hooks": hooks}
    atomic_write(path, canonical_json(doc), old)


def read_ledgers(ledger_dir: Path) -> list[dict]:
    docs = [read_json(p, {}) for p in sorted(ledger_dir.glob("*.json"))] if ledger_dir.is_dir() else []
    return [d for d in docs if isinstance(d, dict) and d.get("machine_id")]


UPGRADE_COMMAND = "python thinker-worker/scripts/tw.py upgrade"  # in place; the machine's manifest keeps its flags


def machines(home: Path, ledger_dir: Path | None) -> None:
    manifest = read_json(manifest_path(home), {})
    manifest = manifest if isinstance(manifest, dict) else {}
    ledger_dir = ledger_dir or Path(manifest.get("ledger_dir") or default_ledger_dir(home))
    me = manifest.get("machine_id") or machine_id()
    docs = read_ledgers(ledger_dir)
    live = [d for d in docs if d.get("status") == "installed"]
    newest = max(live, key=lambda d: d.get("updated_at", "")) if live else None
    if not docs:
        print(f"No install ledgers in {ledger_dir}")
    for d in docs:
        stale = newest is not None and d in live and d.get("tw_sha256") != newest.get("tw_sha256")
        note = ("STALE (newest tw.py is on " + newest["machine_id"] + ") -> run: " + UPGRADE_COMMAND
                if stale else "current" if d in live else "")
        print(" ".join(["*" if d["machine_id"] == me else " ", d["machine_id"], str(d.get("os")),
                        str(d.get("status")), "updated", str(d.get("updated_at")),
                        "tw.py", str(d.get("tw_sha256", ""))[:12], note]).rstrip())


def load_manifest(home: Path) -> dict:
    doc = read_json(manifest_path(home), None)
    if not isinstance(doc, dict) or doc.get("owner") != OWNER or doc.get("schema") != 1:
        raise Conflict("Missing or invalid thinker-worker installation manifest")
    return doc


def check(home: Path, quiet: bool = False) -> dict:
    manifest = load_manifest(home)
    problems = ["uninstall incomplete; rerun uninstall"] if manifest.get("uninstalling") else []
    for rel, digest in manifest["files"].items():
        path = home / rel
        if not path.is_file() or sha(path.read_bytes()) != digest:
            problems.append(f"owned file changed or missing: {path}")
    for harness in installed_harnesses(manifest):
        path = config_path(home, harness)
        try:
            doc, _ = config_doc(path)
            found = owned_entries(doc)
            if found != [manifest["hooks"][harness]]:
                problems.append(f"owned {harness} hook changed, missing, or duplicated")
        except Conflict as exc:
            problems.append(str(exc))
    value = {"installed": not problems, "problems": problems, "hook_trust_loaded": "unknown",
             "native_interception": "unknown", "effective_child_model_effort": "unknown"}
    if not quiet:
        print(json.dumps(value, indent=2))
    return value


def install(home: Path, python: Path, portable: bool = False, python_cmd: str | None = None,
            harnesses: tuple[str, ...] = HARNESSES, ledger_dir: Path | None = None) -> None:
    manifest_file = manifest_path(home)
    ledger_dir = ledger_dir or default_ledger_dir(home)
    mid = machine_id()
    flags = {"portable": portable, "harness": list(harnesses), "python_cmd": python_cmd}
    items = source_items(harnesses)
    if manifest_file.exists():
        manifest = load_manifest(home)
        if manifest["source"] != {rel: sha(data) for rel, data in items.items()}:
            raise Conflict("Source changed since installation; after reviewing the changes run `tw.py upgrade` "
                           "(in place, keeps hooks and activations)")
        state = check(home, quiet=True)
        if state["problems"]:
            raise Conflict("Existing installation conflict: " + "; ".join(state["problems"]))
        adopted = manifest.get("adopted", [])
        write_ledger(Path(manifest.get("ledger_dir") or ledger_dir), manifest.get("machine_id", mid), "installed",
                     manifest.get("flags", flags),
                     {h: {"entry": e, "mode": "adopted" if h in adopted else "written"}
                      for h, e in manifest["hooks"].items()})
        print("Already installed; owned files and hook entries match. Trust/loading and live routing remain unverified.")
        return
    paths = {rel: home / rel for rel in items}
    collisions = [str(path) for path in paths.values() if path.exists()]
    if collisions:
        raise Conflict("Unowned target collision; no overwrite: " + ", ".join(collisions))
    entries = {h: hook_entry(h, home, python, portable, python_cmd) for h in harnesses}
    originals = {}
    revisions = {}
    adopted = []
    for harness in harnesses:
        path = config_path(home, harness)
        doc, raw = config_doc(path)
        found = owned_entries(doc)
        originals[harness] = raw
        if found == [entries[harness]]:
            # A synced config already holds exactly this entry (written by another machine):
            # record it without writing; uninstall keeps it while another installed ledger claims it.
            adopted.append(harness)
        elif found:
            raise Conflict(f"Existing {OWNER} hook at {path} differs from what this install would write; "
                           "rerun install with the same --portable/--python-cmd as the machine that wrote it, "
                           "or remove that entry first")
        else:
            revisions[harness] = canonical_json(add_entry(doc, entries[harness]))
    # Recovery copies are evidence; normal uninstall removes only the owned entry.
    backups = {}
    root = state_root(home)
    if root.exists() and manifest_file.exists():
        raise Conflict("Installation state collision")
    for harness, raw in originals.items():
        if raw is not None:
            backup = root / "backups" / f"{harness}-config.before"
            if backup.exists():
                raise Conflict(f"Backup collision: {backup}")
            backups[harness] = str(backup.relative_to(home))
    created = []
    changed_configs = []
    try:
        for harness, rel in backups.items():
            backup = home / rel
            atomic_write(backup, originals[harness], None)
            created.append((backup, originals[harness]))
        for rel, data in items.items():
            path = home / rel
            atomic_write(path, data, None)
            created.append((path, data))
        for harness in revisions:
            path = config_path(home, harness)
            atomic_write(path, revisions[harness], originals[harness])
            changed_configs.append((path, revisions[harness], originals[harness]))
        manifest = {"schema": 1, "owner": OWNER, "installed_at": now(), "harnesses": list(harnesses),
                    "source": {rel: sha(data) for rel, data in items.items()},
                    "files": {rel: sha(data) for rel, data in items.items()},
                    "hooks": entries, "adopted": adopted, "backups": backups,
                    "config_existed": {h: originals[h] is not None for h in originals},
                    "machine_id": mid, "ledger_dir": str(ledger_dir), "flags": flags}
        atomic_write(manifest_file, canonical_json(manifest), None)
    except Exception:
        for path, replacement, original in reversed(changed_configs):
            if path.exists() and path.read_bytes() == replacement:
                if original is None:
                    path.unlink()
                else:
                    atomic_write(path, original, replacement)
        for path, written in reversed(created):
            if path.exists() and path.read_bytes() == written:
                path.unlink()
        raise
    write_ledger(ledger_dir, mid, "installed", flags,
                 {h: {"entry": entries[h], "mode": "adopted" if h in adopted else "written"} for h in harnesses})
    print("Installed owned skill copies, Claude agents, and one guard entry per harness. Review Codex /hooks trust; activation and live verification are separate.")


def upgrade(home: Path) -> None:
    """Bring an installation to the current source in place: every owned file is replaced (or removed, if the source
    no longer produces it) when it still matches the manifest or already matches the new source; missing current
    files are restored. Pre-existing edits, non-file collisions and changed hook entries refuse before the first
    write. A later concurrent conflict preserves that target but may follow earlier replacements; this is not a
    multi-file transaction. Resolve the conflict and rerun to reconcile the installation. Hook entries,
    activation records and receipts are kept, unlike uninstall + install."""
    manifest_file = manifest_path(home)
    manifest_before = manifest_file.read_bytes() if manifest_file.exists() else None
    manifest = load_manifest(home)
    if manifest_file.read_bytes() != manifest_before:
        raise Conflict(f"Concurrent change at {manifest_file}; no overwrite")
    if manifest.get("uninstalling"):
        raise Conflict("uninstall incomplete; rerun uninstall")
    for harness in installed_harnesses(manifest):
        doc, _ = config_doc(config_path(home, harness))
        if owned_entries(doc) != [manifest["hooks"][harness]]:
            raise Conflict(f"owned {harness} hook changed, missing, or duplicated; upgrade keeps hooks, fix that first")
    items = source_items(tuple(installed_harnesses(manifest)))
    problems, plan = [], []
    for rel in sorted(set(manifest["files"]) | set(items)):
        path = home / rel
        if (path.exists() or path.is_symlink()) and not path.is_file():
            problems.append(f"non-file target in the way: {path}")
            continue
        parent = next((p for p in path.parents if (p.exists() or p.is_symlink()) and not p.is_dir()), None)
        if parent is not None:
            problems.append(f"non-directory parent in the way: {parent}")
            continue
        before = path.read_bytes() if path.is_file() else None
        have = sha(before) if before is not None else None
        new = sha(items[rel]) if rel in items else None
        if have == new:
            continue
        if have is None or have == manifest["files"].get(rel):
            plan.append((rel, before))
        else:
            problems.append(f"owned file changed by hand: {path}" if rel in manifest["files"]
                            else f"unowned file in the way: {path}")
    if problems:
        raise Conflict("Upgrade conflict; nothing written: " + "; ".join(problems))
    for rel, before in plan:
        path = home / rel
        if rel in items:
            atomic_write(path, items[rel], before)
        else:
            current = path.read_bytes() if path.is_file() else None
            if current != before:
                raise Conflict(f"Concurrent or unexpected change at {path}; no removal")
            path.unlink()
    manifest = {**manifest, "source": {rel: sha(d) for rel, d in items.items()},
                "files": {rel: sha(d) for rel, d in items.items()}, "upgraded_at": now()}
    atomic_write(manifest_file, canonical_json(manifest), manifest_before)
    adopted = manifest.get("adopted", [])
    write_ledger(Path(manifest.get("ledger_dir") or default_ledger_dir(home)), manifest.get("machine_id", machine_id()),
                 "installed", manifest.get("flags", {}),
                 {h: {"entry": manifest["hooks"][h], "mode": "adopted" if h in adopted else "written"}
                  for h in installed_harnesses(manifest)})
    print(f"Upgraded {len(plan)} owned file(s) in place; hook entries and activation records kept.")


def uninstall(home: Path) -> None:
    manifest = load_manifest(home)
    if not manifest.get("uninstalling"):
        state = check(home, quiet=True)
        if state["problems"]:
            raise Conflict("Uninstall conflict: " + "; ".join(state["problems"]))
        path = manifest_path(home)
        before = path.read_bytes()
        manifest = {**manifest, "uninstalling": True}
        atomic_write(path, canonical_json(manifest), before)
    revisions = {}
    originals = {}
    mid = manifest.get("machine_id") or machine_id()
    ledger_dir = Path(manifest.get("ledger_dir") or default_ledger_dir(home))
    others = [d for d in read_ledgers(ledger_dir)
              if d["machine_id"] != mid and d.get("status") == "installed"]
    kept = []
    for harness in installed_harnesses(manifest):
        path = config_path(home, harness)
        doc, raw = config_doc(path)
        found = owned_entries(doc)
        if found and found != [manifest["hooks"][harness]]:
            raise Conflict(f"Owned {harness} hook changed or duplicated during uninstall")
        # The config syncs: keep a shared entry while another installed machine's ledger claims it.
        holders = [d["machine_id"] for d in others
                   if (d.get("hooks") or {}).get(harness, {}).get("entry") == manifest["hooks"][harness]]
        if found and holders:
            kept.append(f"{harness} (claimed by {', '.join(holders)})")
        elif found:
            originals[harness] = raw
            revisions[harness] = canonical_json(remove_entry(doc, manifest["hooks"][harness]))
    # Check all owned artifacts before the first removal, then re-read each config
    # immediately before replacement. Later unrelated entries remain in the doc.
    changed_configs = []
    try:
        for harness in ("codex", "claude"):
            if harness not in revisions:
                continue
            path = config_path(home, harness)
            updated = revisions[harness]
            if not manifest["config_existed"][harness] and updated == canonical_json({}):
                if path.read_bytes() != originals[harness]:
                    raise Conflict(f"Concurrent change at {path}")
                path.unlink()
                changed_configs.append((path, None, originals[harness]))
            else:
                atomic_write(path, updated, originals[harness])
                changed_configs.append((path, updated, originals[harness]))
    except Exception:
        for path, updated, original in reversed(changed_configs):
            current = path.read_bytes() if path.exists() else None
            if current == updated:
                atomic_write(path, original, updated)
        raise
    preserved = []
    for rel, digest in manifest["files"].items():
        path = home / rel
        if path.is_file() and sha(path.read_bytes()) == digest:
            path.unlink()
        elif path.exists():
            preserved.append(str(path))
    for harness in ("codex", "claude"):
        folder = home / f".{harness}" / "skills" / "thinker-worker"
        for child in (folder / "references", folder / "scripts", folder):
            if child.exists() and not any(child.iterdir()):
                child.rmdir()
    for rel in manifest["backups"].values():
        (home / rel).unlink(missing_ok=True)
    backup_dir = state_root(home) / "backups"
    if backup_dir.exists() and not any(backup_dir.iterdir()):
        backup_dir.rmdir()
    for harness in ("codex", "claude"):
        folder = state_root(home) / "state" / harness
        if folder.exists():
            for record in folder.glob("*.json"):
                record.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()
    state_dir = state_root(home) / "state"
    if state_dir.exists() and not any(state_dir.iterdir()):
        state_dir.rmdir()
    adopted = manifest.get("adopted", [])
    write_ledger(ledger_dir, mid, "uninstalled", manifest.get("flags", {}),
                 {h: {"entry": manifest["hooks"][h], "mode": "adopted" if h in adopted else "written"}
                  for h in installed_harnesses(manifest)})
    manifest_path(home).unlink()
    if kept:
        print("Kept shared hook entry for " + "; ".join(kept) + ": that machine still relies on it.")
    print("Removed unchanged owned files, hook entries, and activation records; later unrelated settings retained. Receipts remain as evidence.")
    if preserved:
        print("Preserved paths changed during uninstall: " + ", ".join(preserved))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "upgrade", "uninstall", "check", "activate", "deactivate", "status", "hook", "machines", "outcome",
                 "tally", "codex", "claude", "omp", "agy", "spool", "models", "model"):
        p = commands.add_parser(name)
        p.add_argument("--home", type=Path, default=Path.home())
        if name == "codex":  # Claude harness only; Codex dispatches its models natively
            p.add_argument("--session", required=True)
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--tier", choices=TIERS, required=True)
            p.add_argument("--model", required=True)
            p.add_argument("--brief-file", type=Path, required=True)
            p.add_argument("--cd", type=Path, default=Path.cwd(), help="the child's working root (default: cwd)")
            p.add_argument("--sandbox", choices=("read-only", "workspace-write", "danger-full-access"), default=None,
                           help="Codex sandbox (default danger-full-access); explicit narrower values are preserved")
            p.add_argument("--approval-policy", choices=("never", "on-request"), default=None,
                           help="Codex approval policy (default never); enforced host restrictions still apply")
        if name == "claude":  # any shell (Codex) -> guarded native Claude dispatch via a `claude -p` relay
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--tier", choices=TIERS, required=True)
            p.add_argument("--model", help="per-call native alias (default: the agent file's pin)")
            p.add_argument("--brief-file", type=Path, required=True)
            p.add_argument("--cd", type=Path, default=Path.cwd(), help="the relay's and child's working root")
            p.add_argument("--relay-model", default="sonnet", help="the relay session's model (it only relays)")
            # -p cannot answer a permission prompt, so anything not pre-approved is refused (reads outside --cd, most
            # Bash): default bypassPermissions (Arian's own defaultMode); auto lets a classifier refuse risky actions
            p.add_argument("--permission-mode", default=None,
                           help="claude -p --permission-mode for the relay and its child (default bypassPermissions; "
                                "auto, acceptEdits, ...)")
        if name == "spool":  # run outside the sandbox: executes jobs sandboxed Codex threads drop in spool/inbox
            mode = p.add_mutually_exclusive_group(required=True)
            mode.add_argument("--once", action="store_true", help="process the inbox once and exit")
            mode.add_argument("--watch", action="store_true", help="process the inbox every 2 s until killed")
        if name == "omp":
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--brief-file", type=Path, required=True)
            p.add_argument("--cd", type=Path, default=Path.cwd(), help="worker working directory")
            p.add_argument("--model", help="optional OMP model selector; omitted inherits OMP configuration/session")
            p.add_argument("--thinking", choices=("off", "minimal", "low", "medium", "high", "xhigh", "max", "auto"),
                           help="optional OMP thinking override; omitted inherits configuration/session")
            p.add_argument("--resume", type=Path, help="saved OMP worker session file")
            p.add_argument("--timeout", type=float,
                           help="seconds per attempt; default TW_OMP_TIMEOUT, else 7200. An explicit value keeps "
                                "legacy single-attempt behavior unless --retry-on-timeout is passed")
            p.add_argument("--total-timeout", type=float,
                           help="hard wall-clock seconds across both attempts; a retry receives only time remaining")
            retry = p.add_mutually_exclusive_group()
            retry.add_argument("--retry-on-timeout", dest="retry_on_timeout", action="store_true",
                               help="resume the same saved session once after a clean timeout")
            retry.add_argument("--no-retry-on-timeout", dest="retry_on_timeout", action="store_false",
                               help="disable the normal one-shot continuation retry")
            p.set_defaults(retry_on_timeout=None)
            p.add_argument("--approval-mode", choices=("always-ask", "always-ask-cached", "write", "yolo"),
                           help="optional per-run OMP approval override; omitted inherits configuration")
        if name == "agy":
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--brief-file", type=Path, required=True)
            p.add_argument("--cd", type=Path, default=Path.cwd(), help="worker working directory")
            p.add_argument("--model", help="optional agy model id (see `agy models`); omitted uses agy's default")
            p.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                           help="optional agy effort override")
            p.add_argument("--mode", choices=("accept-edits", "auto", "plan"),
                           help="agy permission mode; replaces the default --dangerously-skip-permissions")
            p.add_argument("--resume", help="agy conversation_id from an earlier run")
            p.add_argument("--timeout", type=float, help="seconds; default TW_AGY_TIMEOUT, else 3600")
        if name in {"activate", "deactivate", "status", "hook", "outcome", "tally", "models"}:
            p.add_argument("--harness", choices=(*HARNESSES, "omp", "agy") if name in {"outcome", "tally"} else HARNESSES,
                           required=True)
        if name == "model":  # edits the skill's source routes.json (validated before it writes); then `upgrade`
            p.add_argument("action", choices=("set", "archive"))
            p.add_argument("--harness")
            p.add_argument("--role")
            p.add_argument("--model", required=True)
            p.add_argument("--tiers", help="comma list in ascending order; the role's tiers when omitted on a new model")
            p.add_argument("--role-tiers", help="explicit role ladder, comma list in ascending order; validated before writing")
            p.add_argument("--prior", action="append", default=[], help="CLASS=TIER (or *=TIER); repeatable")
            p.add_argument("--default", action="store_true", help="router.defaults[role] = this model")
            p.add_argument("--routes", type=Path, help="default: the skill's own source routes.json")
        if name in {"activate", "deactivate", "status", "outcome"}:
            p.add_argument("--session", required=True)
        if name == "outcome":
            p.add_argument("--tool-use-id", required=True)
            p.add_argument("--accepted", choices=("yes", "no"), help="the coordinator's label (weak; a TW-Check "
                           "label outranks it); optional when the dispatch has a TW-Check")
            p.add_argument("--no-check", action="store_true", help="do not run the dispatch's TW-Check")
            p.add_argument("--check-timeout", type=float, default=900, help="seconds (default 900)")
            # No argparse `choices`: its SystemExit(2) escapes run_main, so main checks the closed vocabulary.
            p.add_argument("--cause", help="why a rejection happened: tier, brief or other (only with --accepted no)")
        if name == "machines":
            p.add_argument("--ledger-dir", type=Path, help="default: the one recorded at install, "
                           "else <home>/.claude/thinker-worker-installs")
        if name == "install":
            p.add_argument("--python", type=Path, default=Path(sys.executable))
            p.add_argument("--portable", action="store_true",
                           help="Claude hook as a home-relative bash command (settings synced across machines)")
            p.add_argument("--harness", choices=("claude", "codex", "both"), default="both")
            p.add_argument("--python-cmd", help="with --portable: interpreter command tried first, inserted verbatim")
            p.add_argument("--ledger-dir", type=Path, help="synced dir for per-machine install ledgers "
                           "(default <home>/.claude/thinker-worker-installs)")
        if name == "hook":
            p.add_argument("--owner", required=True)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    try:
        if args.command == "install":
            install(home, args.python.expanduser().resolve(), args.portable, args.python_cmd,
                    HARNESSES if args.harness == "both" else (args.harness,),
                    args.ledger_dir.expanduser().resolve() if args.ledger_dir else None)
        elif args.command == "upgrade":
            upgrade(home)
        elif args.command == "uninstall":
            uninstall(home)
        elif args.command == "machines":
            machines(home, args.ledger_dir.expanduser().resolve() if args.ledger_dir else None)
        elif args.command == "check":
            return 1 if check(home)["problems"] else 0
        elif args.command == "activate":
            print(activate(home, args.harness, session_value(args.session)))
        elif args.command == "deactivate":
            deactivate(home, args.harness, session_value(args.session))
        elif args.command == "status":
            status(home, args.harness, session_value(args.session))
        elif args.command == "outcome":
            if args.cause is not None and args.cause not in ("tier", "brief", "other"):
                raise Conflict(f"--cause must be tier, brief or other, not {args.cause!r}")
            if args.cause and args.accepted != "no":
                raise Conflict("--cause explains a rejection; use it only with --accepted no")
            outcome(home, args.harness, session_value(args.session), args.tool_use_id,
                    None if args.accepted is None else args.accepted == "yes", args.cause, not args.no_check,
                    args.check_timeout)
        elif args.command == "tally":  # read-only over receipts; one JSON line per (class, model, tier)
            for v in tally(home, args.harness):
                print(json.dumps(v))
        elif args.command == "codex":
            return codex_run(home, session_value(args.session), args.role, args.tier, args.model, args.brief_file,
                             args.cd.expanduser().resolve(), args.sandbox, args.approval_policy)
        elif args.command == "claude":
            code, result = claude_run(home, args.role, args.tier, args.brief_file, args.cd, args.model,
                                      args.relay_model, args.permission_mode)
            print(json.dumps(result))
            if code == 2:  # the relay printed the denial verbatim
                print(Path(result["last_message"]).read_text(encoding="utf-8")[-2000:], file=sys.stderr)
            return code
        elif args.command == "omp":
            code, result = omp_run(home, args.role, args.brief_file, args.cd, args.model, args.thinking,
                                   args.resume, args.timeout, args.approval_mode,
                                   total_timeout=args.total_timeout, retry_on_timeout=args.retry_on_timeout)
            print(json.dumps(result))
            return code
        elif args.command == "agy":
            code, result = agy_run(home, args.role, args.brief_file, args.cd, args.model, args.effort,
                                   args.mode, args.resume, args.timeout)
            print(json.dumps(result))
            return code
        elif args.command == "spool":
            while True:
                spool_once(home)
                if args.once:
                    break
                time.sleep(2)
        elif args.command == "model":
            args.routes = args.routes or source_root() / "routes.json"
            if args.action == "set":
                if not (args.harness and args.role):
                    raise Conflict("model set needs --harness and --role")
                print(model_set(args.routes, args.harness, args.role, args.model, args.tiers, args.prior, args.default,
                                args.role_tiers))
            else:
                print(model_archive(args.routes, args.model))
        elif args.command == "models":
            for line in models(args.harness):
                print(json.dumps(line))
        else:
            try:
                hook(home, args.harness, args.owner)
            except Exception as exc:  # fail closed: any guard bug denies the dispatch
                denial(f"guard error: {type(exc).__name__}: {exc}")
    except (Conflict, OSError, KeyError, TypeError) as exc:
        print(f"Conflict: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
