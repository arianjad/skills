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
import math
import os
from pathlib import Path
import platform
import random
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


OWNER = "thinker-worker-v1"
HARNESSES = ("codex", "claude")
SKILL_FILES = ("SKILL.md", "routes.json", "references/codex.md", "references/claude.md", "scripts/tw.py")
TIERS = ("low", "medium", "high", "xhigh")
AGENT_NAME = re.compile(r"tw-(worker|leaf|independent-review|ideation)-(low|medium|high|xhigh)")
VALUE_MAX = 1000  # per header value at the gate; receipts truncate at 256
ROLE_LINE = re.compile(r"^TW-Role: (worker|leaf|independent-review|ideation)$")
# Routing header: labeled input for the routing classifier. Classes are effortmining's vocabulary.
HEADER_KEYS = ("TW-Class", "TW-Deliverable", "TW-Accept", "TW-Risk")
CHECK_KEY = "TW-Check"  # optional: a shell command `tw.py outcome` runs in the dispatch cwd for a pass/fail label
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


MODES = ("shadow", "advisory", "active")
# The router keys the user override file may set, plus any per-backend block of kind "jev" (see merge_override)
OVERRIDABLE = {"priors", "classes", "risk_floor", "defaults", "backends", "combine", "options"}


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
    """Key by key over the installed router block: `backends` (a list) replaces; every other key is an object merged
    over the installed one (a per-backend block is allowed if it, or the installed block of that name, has kind
    "jev"); a class entry inherits the merged "*" entry. The merged doc is validated like the installed one."""
    ov = read_json(ov_path, None)
    rt = ov.get("router") if isinstance(ov, dict) else None
    if (not isinstance(ov, dict) or set(ov) != {"router"} or not isinstance(rt, dict)
            or not all(k in OVERRIDABLE or is_jev(v) or is_jev(doc["router"].get(k)) for k, v in rt.items())
            or not all(isinstance(v, list if k == "backends" else dict) for k, v in rt.items())
            or not all(isinstance(v, dict) for v in rt.get("classes", {}).values())):
        raise Conflict("may set only router.priors, classes, risk_floor, defaults, combine, options and jev backend "
                       "blocks (each an object) and router.backends (a list)")
    merged = json.loads(json.dumps(doc))
    mr = merged["router"]
    for k, v in rt.items():
        if k != "classes":
            mr[k] = v if k == "backends" else {**mr.get(k, {}), **v}
    star = {**mr["classes"]["*"], **rt.get("classes", {}).get("*", {})}
    for cls, entry in rt.get("classes", {}).items():
        mr["classes"][cls] = star if cls == "*" else {**star, **mr["classes"].get(cls, {}), **entry}
    check_routes(merged, ov_path)
    merged["_override"] = str(ov_path)
    return merged


def is_jev(block: object) -> bool:
    """A router block for a decision model behind /v1/systemone (backend_jev)."""
    return isinstance(block, dict) and block.get("kind") == "jev"


def is_codex_model(routes: dict, model: object) -> bool:
    """The model is in some Codex role's models: from Claude it runs only through `tw.py codex`."""
    return any(model in p["models"] for p in routes["harnesses"]["codex"]["roles"].values())


def check_routes(doc: object, path: Path) -> None:
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise Conflict(f"routes.json missing or not schema 1: {path}")
    for harness in HARNESSES:
        for role, pol in doc["harnesses"][harness]["roles"].items():
            if not pol.get("models") or not pol.get("tiers") or any(t not in TIERS for t in pol["tiers"]):
                raise Conflict(f"routes.json: bad policy for {harness}/{role}")

    def num(v: object) -> bool:
        return not isinstance(v, bool) and isinstance(v, (int, float))

    def good_explore(ex: object) -> bool:  # a constant in [0, 1], or a decaying schedule (see epsilon)
        if isinstance(ex, dict):
            return (set(ex) == {"c", "power", "floor"} and all(num(v) for v in ex.values())
                    and ex["c"] > 0 and ex["power"] >= 0 and 0 <= ex["floor"] <= 1)
        return num(ex) and 0 <= ex <= 1

    def good_class(name: object, entry: object) -> bool:
        return ((name == "*" or name in TASK_CLASSES) and isinstance(entry, dict) and entry.get("mode") in MODES
                and good_explore(entry.get("explore", 0.0)))
    def good_jev(b: dict) -> bool:
        chars = b.get("body_chars", 1)
        return isinstance(b.get("url"), str) and num(chars) and isinstance(chars, int) and chars > 0

    def good_models(rt: dict) -> bool:  # decision-model blocks: jev backends, router.combine, router.options
        comb, opts = rt.get("combine"), rt.get("options", {})
        return (all(isinstance(n, str) for n in rt["backends"]) and all(good_jev(b) for b in rt.values() if is_jev(b))
                and isinstance(comb, dict) and num(comb.get("margin"))
                and 0 <= comb["margin"] <= 1 and isinstance(comb.get("weights", {}), dict)
                and all(num(w) and w >= 0 for w in comb.get("weights", {}).values())
                and isinstance(opts, dict) and set(opts) <= set(TIERS)
                and all(isinstance(v, str) and v for v in opts.values()))
    rt = doc.get("router")
    budget = rt.get("budget_s") if isinstance(rt, dict) else None
    classes = rt.get("classes") if isinstance(rt, dict) else None
    floors = rt.get("risk_floor") if isinstance(rt, dict) else None
    priors = rt.get("priors") if isinstance(rt, dict) else None
    if (not isinstance(rt, dict) or not isinstance(rt.get("backends"), list) or not good_models(rt)
            or not num(budget) or budget <= 0
            or not isinstance(classes, dict) or "*" not in classes or not all(good_class(k, v) for k, v in classes.items())
            or not isinstance(floors, dict) or set(floors) != RISKS or any(v not in TIERS for v in floors.values())
            or not isinstance(priors, dict) or "*" not in priors or not set(priors) <= TASK_CLASSES | {"*"}
            or any(v not in TIERS for v in priors.values())):
        raise Conflict("routes.json: bad router block")
    defaults = rt.get("defaults", {})  # per-role default model the coordinator dispatches; guidance, not enforced
    claude_roles = doc["harnesses"]["claude"]["roles"]
    if not isinstance(defaults, dict) or any(r not in claude_roles or m not in claude_roles[r]["models"]
                                             for r, m in defaults.items()):
        raise Conflict("routes.json: router.defaults must map a Claude role to one of its models")


def prior(routes: dict, harness: str, role: str, cls: str | None) -> str:
    """The tier prior for a class (router.priors, "*" when the class has none), clamped into the role's tiers."""
    priors = routes["router"]["priors"]
    return clamp(priors.get(cls, priors["*"]), routes["harnesses"][harness]["roles"][role]["tiers"])


def priors_line(routes: dict) -> str:
    rt = routes["router"]
    source = (f"override ignored: {routes['_override_error']}" if routes.get("_override_error")
              else "installed routes.json" + (f" + {routes['_override']}" if routes.get("_override") else ""))
    return (f"Tier priors ({source}): " + ", ".join(f"{k}={v}" for k, v in rt["priors"].items())
            + "; risk floors: " + ", ".join(f"{k}={v}" for k, v in rt["risk_floor"].items())
            + "; default models: " + (", ".join(f"{k}={v}" for k, v in rt.get("defaults", {}).items()) or "agent files"))


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
            obj.get("harness") != harness or obj.get("session_id") != session or
            type(obj.get("store_bodies", False)) is not bool):
        # Pre-routes.json records carry review/luna/sonnet/ideation flags; they are ignored.
        raise Conflict(f"Invalid activation record at {path}; deactivate and reactivate this session")
    return obj


def activate(home: Path, harness: str, session: str, store_bodies: bool = False) -> None:
    path = record_path(home, harness, session)
    old = path.read_bytes() if path.exists() else None
    if old is not None:
        activation(home, harness, session)
    obj = {"schema": 1, "harness": harness, "session_id": session,
           "store_bodies": store_bodies, "activated_at": now()}
    atomic_write(path, canonical_json(obj), old)
    print(f"Activation requested for {harness} session {session}; hook trust/loading, interception, and effective child model remain unverified.")
    print(priors_line(load_routes()))


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
                 "store_bodies": record.get("store_bodies", False) if record else False,
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
    """Return ({key: value}, "") or (None, problem). Keys may sit anywhere in lines 2-12; TW-Check is optional."""
    found: dict[str, str] = {}
    for line in brief.split("\n")[1:12]:
        key, sep, value = line.partition(": ")
        if sep and key in HEADER_KEYS + (CHECK_KEY,):
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
        if tier not in pol["tiers"]:
            return Decision(False, f"reasoning_effort must be one of {', '.join(pol['tiers'])} for {route}", role, model, fields=fields)
        if not valid_codex_fork(inp.get("fork_turns")):
            return Decision(False, "fork_turns must be explicit 'none' or a bounded positive count", role, model, fields=fields)
    else:
        st = inp.get("subagent_type")
        match = AGENT_NAME.fullmatch(st) if isinstance(st, str) else None
        if not match or match.group(1) != role:
            return Decision(False, f"subagent_type must be tw-{role}-<tier>", role, model, fields=fields)
        tier = match.group(2)
        if tier not in pol["tiers"]:
            return Decision(False, f"tier {tier} is outside {role}'s tiers {pol['tiers']}", role, model, fields=fields)
        if model is not None and model not in pol["models"]:
            return Decision(False, f"model {model} is not allowed for {role}", role, model, fields=fields)
        if envelope.get("tool_name") != "codex" and is_codex_model(routes, model):  # not the pipeline's own call
            return Decision(False, f"model {model} is a Codex model; dispatch it with `tw.py codex --model {model}`",
                            role, model, fields=fields)
        if inp.get("fork_context") or inp.get("fork"):
            return Decision(False, "Claude inherited-model fork is outside fresh dispatch", role, model, fields=fields)
    return Decision(True, "admitted-request-only", role, model, tier, fields)


def denial(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                       "permissionDecision": "deny", "permissionDecisionReason": f"{OWNER}: {reason}"}}))


def receipt(home: Path, harness: str, session: str, envelope: dict, d: Decision) -> None:
    # Never store the brief body or any unknown input field; the validated routing header is the
    # labeled input for the routing classifier (Arian 2026-09-26).
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
    """Kill proc and its descendants; True only if the kill command succeeded and proc exited within `wait` s.
    Never blocks longer than that: a denied kill (taskkill exit 1, Access denied) returns False, proc may live on."""
    ok = True
    if os.name == "nt":
        ok = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True).returncode == 0
    else:
        try:
            os.killpg(proc.pid, 9)  # SIGKILL; the check runs in its own session
        except OSError:
            proc.kill()
    try:
        proc.wait(wait)
    except subprocess.TimeoutExpired:
        return False
    return ok


def run_bounded(argv: list[str], cwd: object, stdin_bytes: bytes | None, timeout: float, merge: bool = False) -> dict:
    """Run argv once for at most `timeout` s. stdio are temp files, not pipes (a surviving grandchild cannot hang the
    read); on POSIX the child gets its own session so kill_tree kills the group. On timeout the tree is killed
    (kill_tree). Returns code (None on timeout), out, err ("" with merge: stderr goes to out, in order), timed_out,
    kill_failed, pid, exited (the process was gone at return). Popen's OSError propagates. stdin_bytes None: DEVNULL."""
    with tempfile.TemporaryFile() as fin, tempfile.TemporaryFile() as fout, tempfile.TemporaryFile() as ferr:
        if stdin_bytes is not None:
            fin.write(stdin_bytes)
            fin.seek(0)
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL if stdin_bytes is None else fin, stdout=fout,
                                stderr=subprocess.STDOUT if merge else ferr, start_new_session=os.name != "nt")
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
    Only a dispatch that ran is labeled: its dispatch row says admit, its route row (if any) is not an advise (a
    denial), and a `tw.py codex` dispatch has a cost row (codex ran). Otherwise Conflict, before anything is written."""
    rows = read_rows(receipts_path(home, harness, session))
    mine = [r for r in rows if r.get("tool_use_id") == tool_use_id]
    disp = [r for r in mine if r.get("kind") == "dispatch"]
    route_rows = [r for r in mine if r.get("kind") == "route"]
    if not disp:
        raise Conflict(f"no dispatch receipt for tool_use_id {tool_use_id} in {harness} session {session}")
    if disp[-1].get("decision") != "admit":
        raise Conflict(f"{tool_use_id} was denied at the gate ({disp[-1].get('reason')}); it never ran")
    if route_rows and route_rows[-1].get("action") == "advise":
        raise Conflict(f"{tool_use_id} was advised (denied) by the router; it never ran")
    if disp[-1].get("tool_name") == "codex" and not any(r.get("kind") == "cost" for r in mine):
        raise Conflict(f"{tool_use_id}: no cost row, so codex never ran for it")
    check = disp[-1].get("check") if run else None
    if accepted is None and not check:
        raise Conflict("nothing to record: pass --accepted yes|no, or dispatch with a TW-Check line (without "
                       "--no-check)")
    if harness == "claude":
        race_check(home, harness, session, None)  # verify the session's last rewrite before it is labeled; never raises
    if accepted is not None:
        append_receipt(home, harness, session, {"kind": "outcome", "at": now(), "harness": harness,
                                                "session_id": session, "tool_use_id": tool_use_id,
                                                "accepted": accepted, "cause": cause})
    if harness == "claude" and not any(r.get("kind") == "cost" and r.get("tool_use_id") == tool_use_id for r in rows):
        try:  # the label above stands even if the child's files are unreadable
            row = cost_row(home, harness, session, tool_use_id)
        except Exception as exc:
            row = {"kind": "cost-error", "at": now(), "harness": harness, "session_id": session,
                   "tool_use_id": tool_use_id, "error": f"{type(exc).__name__}: {exc}"[:200]}
        if row is not None:
            append_receipt(home, harness, session, row)
    if accepted is not None:
        print(f"Recorded {'accepted' if accepted else 'rejected'} for {tool_use_id}.")
    if check:
        res = run_check(check, disp[-1].get("cwd"), timeout)
        append_receipt(home, harness, session, {"kind": "check", "at": now(), "harness": harness,
                                                "session_id": session, "tool_use_id": tool_use_id, **res})
        why = f" (exit {res['exit_code']})" if res["label"] != "unknown" else f" ({res['unknown_reason']})"
        print(f"Check {res['label']}{why} for {tool_use_id}.")


CODEX_USAGE = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def codex_cmd(exe: str, model: str, tier: str, cd: Path, out: Path, sandbox: str = "workspace-write",
              search: bool = True) -> list[str]:
    # Defaults (tw.py codex): same reach as a Claude child, may write (temp files, scripts) and search the web.
    return [exe, *(["--search"] if search else []), "exec", "-m", model, "-c", f"model_reasoning_effort={tier}",
            "-s", sandbox, "--json", "--skip-git-repo-check", "-C", str(cd), "-o", str(out), "-"]


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


def codex_run(home: Path, session: str, role: str, tier: str, model: str, brief_file: Path, cd: Path) -> int:
    """Claude coordinator -> a Codex model via `codex exec`. Same gate as a native dispatch (decide() on a synthetic
    Agent call with the model), plus: the model must also be in some Codex role's models. Receipts get a dispatch row
    and a cost row with effective model/effort. `-o` (Codex's closing message) always goes to state, never to a
    caller path: pointed at the brief's deliverable it overwrote the child's report at exit (incident 2026-09-28)."""
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
    receipt(home, "claude", session, env, d)
    if not d.admitted:
        raise Conflict(d.reason)
    hint, row = routed(home, "claude", session, env, d, routes, record, via="codex-exec")  # fails open: row None
    if row and row["action"] == "advise":
        raise Conflict(hint["hookSpecificOutput"]["permissionDecisionReason"])
    if row and row["action"] == "rewrite":
        tier = row["target_tier"]
        print(hint["hookSpecificOutput"]["additionalContext"])
    exe = shutil.which("codex")
    if not exe:
        raise Conflict("codex CLI not found on PATH")
    out = state_root(home) / "codex" / f"{tool_use_id}.last.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("TW_CODEX_TIMEOUT", "3600"))
    # on timeout the whole tree is killed: codex.CMD -> node -> codex.exe -> sandbox helpers
    ran = run_bounded(codex_cmd(exe, model, tier, cd, out), None, (AGENT_TEXT[role][1] + "\n\n" + brief).encode("utf-8"),
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
                                             "requested_effort": tier, **ev})
    if row and row["action"] == "rewrite":  # verified like race_check: did the child run the router's pick?
        append_receipt(home, "claude", session, {"kind": "race", "at": now(), "harness": "claude",
                                                 "session_id": session, "tool_use_id": tool_use_id,
                                                 "lost": ev["effort"] != tier, "agent_type": None, "via": "codex-exec",
                                                 "effective_effort": ev["effort"]})  # unknown effort counts as lost
    print(json.dumps({"tool_use_id": tool_use_id, "last_message": str(out), "exit_code": code, "timed_out": timed_out,
                      "effective_model": ev["model"], "effective_effort": ev["effort"], "thread_id": ev["thread_id"]}))
    if code != 0:
        print(stderr[-2000:], file=sys.stderr)
    return 1 if timed_out else code


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


def race_check(home: Path, harness: str, session: str, transcript_path: str | None,
               rows: list[dict] | None = None) -> None:
    """For earlier rewrites not yet checked: the child's actual agent (meta.json, written at spawn) must be the
    router's pick; only when meta.json lacks agentType, its prompt must not carry context-mode's block instead.
    Otherwise the race was lost. Runs at each dispatch and at outcome.
    Never raises: a failure becomes a race-error row, and the dispatch is decided normally. rows: the session's
    receipt rows if the caller already read them."""
    try:
        if harness != "claude":
            return
        if rows is None:
            path = receipts_path(home, harness, session)
            rows = read_rows(path) if path.exists() else []
        if not rows:
            return
        checked = {r.get("tool_use_id") for r in rows if r.get("kind") == "race"}
        dirs = subagents_dirs(home, session, transcript_path)
        for r in rows:
            if r.get("kind") != "route" or r.get("action") != "rewrite" or r.get("tool_use_id") in checked:
                continue
            found = child_files(dirs, r["tool_use_id"])
            if found is None or not found[1].exists():
                continue  # not spawned yet; next dispatch checks again
            meta, transcript = found
            if meta.get("agentType"):  # sole criterion: briefs may legitimately quote context-mode's block
                lost = meta["agentType"] != r.get("router_agent")
            else:
                lost = False
                with transcript.open(encoding="utf-8", errors="replace") as stream:
                    for line in stream:  # streamed to the first user row; torn lines skipped as in read_rows
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(obj, dict) and obj.get("type") == "user":
                            content = json.dumps((obj.get("message") or {}).get("content"), ensure_ascii=False)
                            lost = "<context_window_protection>" in content
                            break
            append_receipt(home, harness, session, {"kind": "race", "at": now(), "harness": harness,
                                                    "session_id": session, "tool_use_id": r["tool_use_id"],
                                                    "lost": lost, "agent_type": meta.get("agentType")})
            if lost:
                advisory_flag(home, harness, session).write_text(now(), encoding="utf-8")
    except Exception as exc:  # a tripwire failure is recorded, never silent, and never blocks a dispatch
        try:
            append_receipt(home, harness, session, {"kind": "race-error", "at": now(), "harness": harness,
                                                    "session_id": session,
                                                    "error": f"{type(exc).__name__}: {exc}"[:200]})
        except Exception:
            pass  # ponytail: unwritable receipts dir; the dispatch receipt fails right after anyway


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
           if m and m != "<synthetic>"]  # an error stub names no model; tw-* meta.json carries no model
    att = [o.get("attachment") or {} for o in rows if o.get("type") == "attachment"]
    return {"kind": "cost", "at": now(), "harness": harness, "session_id": session, "tool_use_id": tool_use_id,
            "agent_type": meta.get("agentType"), "model": ran[-1] if ran else meta.get("model"),
            # offered at any point in the run; a later available:false removal does not clear it
            "advisor_available": any(a.get("type") == "advisor_tool" and a.get("available") is True for a in att),
            "api_calls": len(usage),
            **{k: sum(u.get(k, 0) for u in usage.values()) for k in COST_KEYS},
            "advisor_calls": len(advisor_ids), "advisor_model": next((it.get("model") for it in adv), None),
            "advisor_input_tokens": sum(it.get("input_tokens", 0) for it in adv),
            "advisor_output_tokens": sum(it.get("output_tokens", 0) for it in adv)}


def promote(home: Path, harness: str, cls: str | None = None, model: str | None = None, margin: float = 0.15,
            draws: int = 200_000, seed: int = 7) -> list[dict]:
    """One verdict per (class, model) group of route rows, filtered by cls/model. The model is the executed one, the
    dispatch's latest `cost` row `model` (never the requested `agent_model`, never a role default), else None.
    An arm counts a dispatch only on executed evidence that agrees with it: a cost row with a model and positive
    effort evidence (codex `effort`; else the tier of a Claude `tw-*` `agent_type`) equal to the arm's tier (the
    floored target for a rewrite, the coordinator's tier otherwise). A dispatch failing this, missing or unknown
    effort included, leaves both arms and is counted in n_excluded_identity.
    Design §5: Beta posteriors for the router arm (verified lower-tier runs) and the coordinator arm
    (backend wanted lower and the row is `eligible`, child ran at the coordinator tier); promote/demote/hold on
    P(diff >= -margin). "Lower" and "complied" compare the floored `target_tier` (`router_tier` on rows written
    before it existed). A dispatch whose cost row shows advisor calls measured tier + advisor, not the tier: it
    leaves both arms and is counted in n_advisor_excluded. A dispatch's label is its latest `check` row (pass accepted,
    fail rejected, unknown excluded), else the coordinator's `outcome`; n_check / n_coordinator count each source."""
    rows = harness_rows(home, harness)
    routes = [r for r in rows if r.get("kind") == "route"]
    maps = {"cost": {r.get("tool_use_id"): r for r in rows if r.get("kind") == "cost"},  # the latest wins
            "label": {r["tool_use_id"]: r["accepted"] for r in rows if r.get("kind") == "outcome"},
            "checked": {r["tool_use_id"]: r.get("label") for r in rows if r.get("kind") == "check"},  # latest wins
            "race": {r["tool_use_id"]: r.get("lost") for r in rows if r.get("kind") == "race"},  # outcome runs race_check
            "advisor": {r["tool_use_id"] for r in rows if r.get("kind") == "cost" and r.get("advisor_calls")},
            "advised": {r["ticket"]: tgt(r) for r in routes if r.get("action") == "advise"
                        and TIERS.index(tgt(r)) < TIERS.index(r["coordinator_tier"])}}
    groups = {}
    for r in routes:
        if r.get("pinned"):
            continue  # the user pinned model/effort: the router never acted, so neither arm
        key = (r.get("class"), (maps["cost"].get(r.get("tool_use_id")) or {}).get("model"))
        if (cls is None or key[0] == cls) and (model is None or key[1] == model):
            groups.setdefault(key, []).append(r)
    return [{"class": c, "model": m, **arms(maps, g, margin, draws, seed)} for (c, m), g in groups.items()]


def harness_rows(home: Path, harness: str) -> list[dict]:
    """Every receipt row of the harness, across all session files (torn lines skipped)."""
    return [r for p in (state_root(home) / "receipts" / harness).glob("*.jsonl") for r in read_rows(p)]


def tgt(r: dict) -> str:
    """A route row's floored pick; rows before switch-on T3 lack target_tier."""
    return r.get("target_tier") or r["router_tier"]


def arms(maps: dict, group: list[dict], margin: float, draws: int, seed: int) -> dict:
    """The promote verdict for one group of route rows (see promote); maps: the per-tool_use_id indexes promote
    builds once over every row."""
    cost, label, checked, race = maps["cost"], maps["label"], maps["checked"], maps["race"]
    advised_by, advised = maps["advisor"], maps["advised"]

    def ran_as(tid: str | None, tier: str) -> bool:  # executed identity agrees with the arm's tier (see promote)
        c = cost.get(tid) or {}
        m = AGENT_NAME.fullmatch(c.get("agent_type") or "")
        eff = c.get("effort") if "effort" in c else m.group(2) if m else None
        return bool(c.get("model")) and eff == tier  # no effort evidence: unknown tier, in neither arm
    router, coord, n_adv, n_id, src = [], [], 0, 0, {"check": 0, "coordinator": 0}
    for r in group:
        if r.get("tool_use_id") in advised_by:
            n_adv += 1
            continue
        tid = r.get("tool_use_id")  # an executed TW-Check outranks the coordinator's accept (design D6)
        by = "check" if tid in checked else "coordinator"
        ok = {"pass": True, "fail": False}.get(checked[tid]) if by == "check" else label.get(tid)
        if ok is None or race.get(tid) is True:
            continue  # unlabeled, or lost race: ran at neither arm's tier
        rewrite_lower = (r.get("action") == "rewrite" and race.get(r.get("tool_use_id")) is False  # verified only
                         and TIERS.index(tgt(r)) < TIERS.index(r["coordinator_tier"]))
        complied = (r.get("action") is None and (r.get("source") or "").startswith("cached:")
                    and advised.get(r["ticket"]) == r["coordinator_tier"])
        to_coord = (not (rewrite_lower or complied) and r.get("action") is None
                    and not (r.get("source") or "coordinator").endswith("coordinator")
                    and r.get("eligible") and TIERS.index(tgt(r)) < TIERS.index(r["coordinator_tier"]))
        if not (rewrite_lower or complied or to_coord):
            continue
        if not ran_as(tid, tgt(r) if rewrite_lower else r["coordinator_tier"]):
            n_id += 1  # no executed evidence, or it contradicts the arm
            continue
        # router arm, or coordinator arm: the router wanted lower and would have acted; child ran at the coordinator tier
        (router if rewrite_lower or complied else coord).append(ok)
        src[by] += 1
    k, n, kc, nc = sum(router), len(router), sum(coord), len(coord)
    rng = random.Random(seed)
    hit = sum(rng.betavariate(1 + k, 1 + n - k) - rng.betavariate(1 + kc, 1 + nc - kc) >= -margin
              for _ in range(draws))
    p = hit / draws
    return {"k_router": k, "n_router": n, "k_coord": kc, "n_coord": nc, "p": round(p, 3),
            "n_advisor_excluded": n_adv, "n_excluded_identity": n_id, "n_check": src["check"], "n_coordinator": src["coordinator"], "verdict": "promote" if p > 0.8 else "demote" if p < 0.2 else "hold"}


def ticket(brief: str, model: str) -> tuple[str, str]:
    """(12-hex ticket, full digest) of the brief without TW-Route/TW-Override lines, keyed by the requested model."""
    norm = "\n".join(x.rstrip() for x in brief.split("\n")
                     if not x.startswith(("TW-Route:", "TW-Override:"))).strip()
    digest = sha(f"{model}\n{norm}".encode("utf-8"))
    return digest[:12], digest


def coin(tick: str) -> float:
    """A ticket's exploration draw in [0, 1): the dispatch is explored when it falls below eps."""
    return int(tick, 16) / 16 ** 12


def clamp(tier: str, tiers: list[str]) -> str:
    i = TIERS.index(tier)
    return min(tiers, key=lambda t: (abs(TIERS.index(t) - i), TIERS.index(t)))


def backend_table(cfg: dict, pol: dict, fields: dict, brief: str) -> dict:
    cal = json.loads(Path(os.path.expanduser(cfg["path"])).read_text(encoding="utf-8"))
    tier = clamp(cal["classes"][fields["TW-Class"]]["recommended_tier"], pol["tiers"])
    return {"tier": tier, "probs": {t: float(t == tier) for t in pol["tiers"]}, "confidence": 0.0,
            "body_chars_sent": 0, "provenance": f"calibration {cal.get('model')} {cal.get('fitted_date')}"}


# The option wording sent to decision models is routes.json router.options (tier -> behavioral effort description):
# provisional, from Astra ideation 2026-09-28, until candidate cards (design D5) replace it.
JEV_INSTRUCTIONS = ("Pick the lowest reasoning-effort tier at which a capable model completes this delegated task "
                    "correctly.")  # provisional, like router.options


def backend_jev(cfg: dict, pol: dict, fields: dict, brief: str) -> dict:
    """A decision model behind Jev/TypeSafe `POST /v1/systemone` (kev.serve, Laya). cfg is the router's block for
    this backend plus `options` (router.options unless the block has its own) and `timeout` (the budget left), both
    added by route(). state = TW-Role + routing header + the brief body (lines 2-12 starting `TW-` dropped) cut to
    body_chars; probabilities renormalized over the role's tiers."""
    import urllib.request
    lines = brief.split("\n")
    body = "\n".join(x for i, x in enumerate(lines) if i and not (i < 12 and x.startswith("TW-")))
    body = body[:cfg.get("body_chars", 1500)]
    req = {"state": f"{lines[0]}\n{header_text(fields)}\n\n{body}",
           "questions": {"tier": {"type": "choice", "instructions": JEV_INSTRUCTIONS,
                                  "criteria": {t: cfg["options"][t] for t in pol["tiers"]}}}}
    http = urllib.request.Request(cfg["url"], data=json.dumps(req).encode("utf-8"),
                                  headers={"Content-Type": "application/json"})
    # ProxyHandler({}): a local server, never through a system proxy
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(http, timeout=cfg["timeout"]) as resp:
        got = json.loads(resp.read().decode("utf-8"))["answers"]["tier"]["probabilities"]
    raw = {t: float(got.get(t, 0.0)) for t in pol["tiers"]}
    total = sum(raw.values())
    if any(v < 0 for v in raw.values()) or not total > 0:
        raise ValueError("no probability mass on the role's tiers")
    probs = {t: v / total for t, v in raw.items()}
    tier = max(pol["tiers"], key=probs.get)
    return {"tier": tier, "probs": probs, "confidence": probs[tier], "body_chars_sent": len(body),
            "provenance": f"jev {cfg['url']}"}


BACKENDS = {"table": backend_table}  # a router name not here resolves to backend_jev if its block has kind "jev"


def backend_fn(cfg: dict, name: str):
    return BACKENDS.get(name) or (backend_jev if is_jev(cfg.get(name)) else None)


def valid_route(out: object, tiers: list[str]) -> bool:
    if not isinstance(out, dict) or out.get("tier") not in tiers or not isinstance(out.get("probs"), dict):
        return False
    probs = out["probs"]
    return (set(probs) <= set(tiers) and all(isinstance(v, (int, float)) and v >= 0 for v in probs.values())
            and abs(sum(probs.values()) - 1) < 1e-6
            and isinstance(out.get("confidence"), (int, float)) and 0 <= out["confidence"] <= 1)


def class_mode(routes: dict, cls: str | None) -> tuple[str, float | dict]:
    """(mode, explore as configured: a number or a {c, power, floor} schedule) for a class, "*" if it has none."""
    classes = routes["router"]["classes"]
    c = classes.get(cls) or classes["*"]
    return c["mode"], c.get("explore", 0.0)


def epsilon(explore: float | dict, t: int) -> float:
    """Exploration probability at the t-th routed dispatch of a class. A schedule decays as SLARouter's forced
    exploration (arXiv 2606.19376, p_t = min(1, c / t^(1/4))) with a floor: max(floor, min(1, c / t**power))."""
    if isinstance(explore, dict):
        return max(explore["floor"], min(1.0, explore["c"] / t ** explore["power"]))
    return float(explore)


def class_count(home: Path, harness: str, cls: str, routes: dict) -> int:
    """Non-pinned route rows of a class across every receipt file of the harness; 0 without a scan when the class's
    explore is a plain number (epsilon ignores t then)."""
    if not isinstance(class_mode(routes, cls)[1], dict):
        return 0
    # ponytail: rereads all receipts per dispatch; a per-class counter file if this ever gets slow
    return sum(1 for r in harness_rows(home, harness)
               if r.get("kind") == "route" and r.get("class") == cls and not r.get("pinned"))


def prior_route(home: Path, harness: str, session: str, tick: str, rows: list[dict] | None = None) -> dict | None:
    for row in read_rows(receipts_path(home, harness, session)) if rows is None else rows:
        if (row.get("kind") == "route" and row.get("ticket") == tick
                and row.get("source") not in ("coordinator", "cached:coordinator")):
            return row  # the first bayes or exploration decision for this brief; coordinator picks are recomputed
    return None


def ask_backends(cfg: dict, pol: dict, fields: dict, brief: str) -> dict:
    """Every name in router.backends, one thread each, within budget_s: {name: answer + ms} for a valid answer,
    {"error": ...} otherwise ("timeout" for a thread still running at the deadline)."""
    got: dict = {}
    deadline = time.monotonic() + cfg["budget_s"]

    def one(name: str) -> None:
        t0 = time.monotonic()
        try:
            fn = backend_fn(cfg, name)
            if fn is None:
                raise LookupError
            out = fn({"options": cfg.get("options", {}), **cfg.get(name, {}),
                      "timeout": max(0.01, deadline - time.monotonic())}, pol, fields, brief)
            rec = {**out} if valid_route(out, pol["tiers"]) else {"error": "invalid answer"}
        except LookupError:
            rec = {"error": "unknown backend"}
        except Exception as exc:
            rec = {"error": f"{type(exc).__name__}: {exc}"[:160]}
        got[name] = {**rec, "ms": round((time.monotonic() - t0) * 1000)}

    threads = [threading.Thread(target=one, args=(n,), daemon=True) for n in dict.fromkeys(cfg["backends"])]
    for th in threads:
        th.start()
    for th in threads:
        th.join(max(0.0, deadline - time.monotonic()))
    return {n: got.get(n, {"error": "timeout"}) for n in dict.fromkeys(cfg["backends"])}  # a snapshot


def combine(answers: dict, tiers: list[str], weights: dict) -> dict:
    """Weighted geometric mean over tiers (design D11): p(t) ∝ Π p_i(t)^w_i, w_i = weights[i] else 1/n, each
    probability floored at 1e-6 before the log."""
    w = {k: weights.get(k, 1 / len(answers)) for k in answers}
    logp = {t: sum(w[k] * math.log(max(a["probs"].get(t, 0.0), 1e-6)) for k, a in answers.items()) for t in tiers}
    top = max(logp.values())
    un = {t: math.exp(v - top) for t, v in logp.items()}
    return {t: v / sum(un.values()) for t, v in un.items()}


def route(routes: dict, harness: str, role: str, fields: dict, brief: str, coord_tier: str,
          prior: dict | None = None, model: str | None = None, t: int = 1, pinned: bool | None = None) -> dict:
    """Fail-open router (design D11, D14): every backend is asked in parallel (ask_backends); the valid answers are
    combined (combine) and the combined pick decides (source "bayes") if its top1 - top2 >= router.combine.margin
    (gate "pass"), else the coordinator's tier stands (gate "margin"; None when no backend answered). A ticket whose
    coin falls below eps goes one tier below that pick (source "explore"). eps is the class's explore at the class's
    t-th routed dispatch (epsilon), 0 when cached or pinned. model: the requested model (default the role's
    models[0]); it keys the ticket. pinned: the brief's TW-Pin flag, computed here unless the caller passes it."""
    cfg = routes["router"]
    pol = routes["harnesses"][harness]["roles"][role]
    tick, digest = ticket(brief, model or pol["models"][0])
    mode, explore = class_mode(routes, fields["TW-Class"])
    pinned = flagged(brief, "TW-Pin") if pinned is None else pinned
    eps = 0.0 if pinned else epsilon(explore, t)  # a user pin is never explored
    if prior is not None:  # one decision per ticket: re-dispatches of the same brief reuse it, never re-explore
        return {"tier": prior["router_tier"], "probs": prior["probs"], "confidence": prior["confidence"],
                "provenance": prior.get("provenance"),
                "source": "cached:" + prior["source"].split(":")[-1], "body_chars_sent": 0, "ms": 0,
                "ticket": tick, "digest": digest, "mode": mode, "explore": explore, "eps": 0.0, "propensity": 1.0,
                "backends": {}, "combined": None, "combined_mean": None, "gate": None}
    start = time.monotonic()
    backends = ask_backends(cfg, pol, fields, brief)
    ok = {n: b for n, b in backends.items() if "tier" in b}
    backends = {n: ({k: b[k] for k in ("tier", "probs", "ms")} if n in ok else b) for n, b in backends.items()}
    found = {"tier": coord_tier, "probs": {coord_tier: 1.0}, "confidence": 0.0, "source": "coordinator",
             "body_chars_sent": 0}
    combined = mean = gate = None
    if ok:
        comb = cfg["combine"]
        combined = combine(ok, pol["tiers"], comb.get("weights", {}))
        # design D11: logged only, so other pooling rules can be scored offline against labels
        mean = {t: sum(b["probs"].get(t, 0.0) for b in ok.values()) / len(ok) for t in pol["tiers"]}
        pick = max(pol["tiers"], key=combined.get)  # a tie goes to the cheaper tier (and fails any margin > 0)
        top = sorted(combined.values(), reverse=True) + [0.0]
        gate = "pass" if top[0] - top[1] >= comb["margin"] else "margin"
        if gate == "pass":
            found = {"tier": pick, "probs": combined, "confidence": combined[pick], "source": "bayes",
                     "body_chars_sent": max(b.get("body_chars_sent", 0) for b in ok.values()),
                     "provenance": "; ".join(f"{n}: {b['provenance']}" for n, b in ok.items()
                                             if b.get("provenance")) or None}
    # Exploration around the final pick, bayes or coordinator (design D14): eligible when eps > 0 and the role has a
    # tier below the pick. The coin decides, and the row's propensity is the probability of the logged action: eps
    # if explored, 1 - eps if not, 1.0 with no draw.
    ladder = pol["tiers"]
    drawn = eps > 0 and found["tier"] in ladder and ladder.index(found["tier"]) > 0
    explored = drawn and coin(tick) < eps
    if explored:
        below = ladder[ladder.index(found["tier"]) - 1]  # one tier below the pick, on the role's own ladder
        found = {**found, "tier": below, "probs": {below: 1.0}, "confidence": 0.0, "source": "explore"}
    return {**found, "ms": round((time.monotonic() - start) * 1000), "ticket": tick, "digest": digest,
            "mode": mode, "explore": explore, "eps": eps,
            "propensity": eps if explored else 1 - eps if drawn else 1.0,
            "backends": backends, "combined": combined, "combined_mean": mean, "gate": gate}


def _win_claude_start() -> float | None:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class Entry(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("ppid", wintypes.DWORD), ("prio", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", ctypes.c_wchar * 260)]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    e = Entry()
    e.dwSize = ctypes.sizeof(Entry)
    procs = {}
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        procs[e.pid] = (e.ppid, e.exe.lower())
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    pid = os.getpid()
    for _ in range(12):
        ppid, exe = procs.get(pid, (0, ""))
        if exe == "claude.exe":
            handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            times = [wintypes.FILETIME() for _ in range(4)]
            k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
            k32.CloseHandle(handle)
            ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return (ft - 116444736000000000) / 1e7 if ft else None  # FILETIME (1601, 100 ns) -> epoch s
        if not ppid:
            return None
        pid = ppid
    return None


def _posix_claude_start() -> float | None:
    # ponytail: Mac CLI shows as "claude" or "node"; unverified on the Mac until the T9 live check there.
    import subprocess
    pid = os.getpid()
    for _ in range(12):
        parts = subprocess.run(["ps", "-o", "ppid=,etime=,comm=", "-p", str(pid)],
                               capture_output=True, text=True, timeout=2).stdout.split(None, 2)
        if len(parts) < 3:
            return None
        ppid, etime, comm = parts
        if os.path.basename(comm.strip()) in ("claude", "node"):
            d, _, hms = etime.rpartition("-")
            secs = sum(int(x) * m for x, m in zip(reversed(hms.split(":")), (1, 60, 3600)))
            return time.time() - secs - int(d or 0) * 86400
        pid = int(ppid)
    return None


def claude_process_start() -> float | None:
    """Epoch seconds at which the nearest claude(.exe) ancestor started, or None."""
    try:
        return _win_claude_start() if os.name == "nt" else _posix_claude_start()
    except Exception:
        return None


def competing_agent_writer(home: Path) -> str | None:
    """A reason the router must not return updatedInput on Agent this session, or None (design §4.6)."""
    try:
        enabled = None  # fail safe: only an explicit false skips the guard (Fable review, finding 5)
        for name in ("settings.json", "settings.local.json"):  # local overrides user
            plugins_on = read_json(home / ".claude" / name, {}).get("enabledPlugins") or {}
            if "context-mode@context-mode" in plugins_on:
                enabled = plugins_on["context-mode@context-mode"]
        if enabled is False:
            return None
        plugins = read_json(home / ".claude" / "plugins" / "installed_plugins.json", {}).get("plugins") or {}
        entries = plugins.get("context-mode@context-mode") or []
        if not entries:
            return None
        hooks_json = Path(entries[0]["installPath"]) / "hooks" / "hooks.json"
        pre = (read_json(hooks_json, {}).get("hooks") or {}).get("PreToolUse") or []
        for entry in pre:
            matcher = entry.get("matcher") or ""
            # Claude Code: ""/"*" match all; a plain [A-Za-z0-9_|] matcher is split on | and compared exactly
            # after legacy-name mapping (Task -> Agent); anything else is JS RegExp.test (a search).
            if matcher in ("", "*"):
                hit = True
            elif re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
                hit = "Agent" in {{"Task": "Agent"}.get(x, x) for x in matcher.split("|")}
            else:
                try:
                    hit = re.search(matcher, "Agent") is not None
                except re.error:
                    hit = matcher == "Agent"
            if hit:
                return "context-mode PreToolUse Agent hook is registered"
        start = claude_process_start()
        if start is None:
            return "Claude Code process start unknown"
        if hooks_json.stat().st_mtime >= start - 1:
            return "context-mode hooks.json changed after this session loaded its hooks"
        return None
    except Exception as exc:  # unreadable state: stay advisory, never race
        return f"guard could not read context-mode state: {type(exc).__name__}"


def advisory_flag(home: Path, harness: str, session: str) -> Path:
    return state_root(home) / "state" / harness / f"{sha(session.encode('utf-8'))}.advisory"


def act(home: Path, harness: str, session: str, envelope: dict, d: Decision, r: dict, routes: dict, pinned: bool,
        via: str | None = None):
    """(hook output | None, action None/"advise"/"rewrite", guard | None, eligible, target) for an admitted,
    routed dispatch; pinned: the brief's TW-Pin flag; via (the `tw.py codex` path) skips the competing-writer/race
    guard, names picks as --tier, and its rewrite output carries only additionalContext (no updatedInput).
    target: the router's pick raised to the highest routes.json risk_floor among the brief's
    TW-Risk flags (the coordinator's tier on a coordinator-source row). eligible: the router's pick differs from the
    coordinator's tier (a gated `bayes` pick or an explored one, fresh or a cached bayes decision), whatever the
    mode, and the floor did not lift a pick below the coordinator's tier to it or above; promote's coordinator arm
    keeps only such rows so it matches the dispatches the router would have acted on."""
    raw = r["tier"]
    flags = [] if d.fields["TW-Risk"] == "none" else [x.strip() for x in d.fields["TW-Risk"].split(",")]
    floor = 0 if r["source"] == "coordinator" else max(   # the floor lifts the router's pick only
        (TIERS.index(routes["router"]["risk_floor"][f]) for f in flags), default=0)
    target = TIERS[max(TIERS.index(raw), floor)]
    floored = target != raw
    lower = TIERS.index(target) < TIERS.index(d.tier)
    # A combined pick already cleared the margin gate and an explored pick is the exploration itself (design D14).
    # A re-dispatch of an explored brief is not re-advised.
    disagree = target != d.tier and r["source"] in ("bayes", "cached:bayes", "explore")
    eligible = r["source"] != "coordinator" and disagree and not (floored and not lower)
    inp = envelope["tool_input"]
    brief = inp.get("message" if harness == "codex" else "prompt")
    # No action when ineligible (a coordinator row, agreement, or a floor lifted the pick), in shadow, or kept by
    # the user: TW-Override is checked before the cached decision is used (the ticket ignores it, so an override
    # re-dispatch of an advised brief reuses the decision that advised it); TW-Pin: the user asked for this tier.
    if not eligible or r["mode"] == "shadow" or pinned or flagged(brief, "TW-Override"):
        return None, None, None, eligible, target
    guard = None
    pick = ("--tier " + target if via else agent_name(d.role, target) if harness == "claude"
            else "reasoning_effort=" + target)
    if r["mode"] == "active" and harness == "claude":
        if not via:  # the codex path owns its subprocess: no competing writer, no race to lose
            guard = competing_agent_writer(home)
            if guard is None and advisory_flag(home, harness, session).exists():
                guard = "lost race recorded earlier this session"
        if guard is None:
            note = (f"thinker-worker: dispatched as {pick} instead of {'--tier ' + d.tier if via else inp['subagent_type']} "
                    f"(router p={r['confidence']:.2f}); judge the result at that tier")
            out = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
            if not via:  # the whole tool_input, one key changed
                out["updatedInput"] = {**inp, "subagent_type": agent_name(d.role, target)}
            out["additionalContext"] = note
            return {"hookSpecificOutput": out}, "rewrite", None, eligible, target
    why = "exploration" if r["source"] == "explore" else f"p={r['confidence']:.2f}"
    reason = (f"router picks {target} ({why}); dispatch {pick} or add `TW-Override: <reason>` to keep {d.tier}"
              + (f" [active held: {guard}]" if guard else ""))
    return ({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": f"{OWNER}: {reason}"}}, "advise", guard, eligible,
            target)


def hook(home: Path, harness: str, owner: str) -> None:
    if owner != OWNER:
        denial("unknown installed hook owner")
        return
    try:
        envelope = json.load(sys.stdin)
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
    try:  # read once for race_check and prior_route; on failure each reads (and fails open) as before
        rows = read_rows(receipts_path(home, harness, session))
    except Exception:
        rows = None
    race_check(home, harness, session, envelope.get("transcript_path"), rows)  # never raises; see its docstring
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
    out, row = routed(home, harness, session, envelope, d, routes, record, rows=rows)
    if out:  # printed only after the route row is recorded; any earlier failure leaves the admit standing
        print(json.dumps(out))
    elif (row and harness == "claude" and d.tier != row["prior_tier"] and not row["pinned"]  # no router action:
          and not (row["source"].startswith("cached:") and d.tier == row["target_tier"])):  # prior reminder, unless
        # the user pinned the tier, or it obeys an earlier advise/exploration of this same brief (live check
        # 2026-09-27: the reminder contradicted it)
        # ponytail: Claude only; Codex's handling of additionalContext without a decision is unverified.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext":
                          f"thinker-worker: prior for {row['class']} is {row['prior_tier']}; "
                          f"you dispatched {d.tier} (fine if deliberate)"}}))


def routed(home: Path, harness: str, session: str, envelope: dict, d: Decision, routes: dict, record: dict,
           via: str | None = None, rows: list[dict] | None = None) -> tuple[dict | None, dict | None]:
    """Post-admission routing shared by the hook and `tw.py codex` (via="codex-exec"): route(), act(), and the route
    row. Returns (hook output | None, row). Fails open: the dispatch receipt already says admit, so any failure
    writes an `error` row (where "route") and returns (None, None)."""
    try:
        inp = envelope["tool_input"]
        brief = inp.get("message" if harness == "codex" else "prompt")
        model = d.model or routes["harnesses"][harness]["roles"][d.role]["models"][0]  # requested
        pinned = flagged(brief, "TW-Pin")
        cached = prior_route(home, harness, session, ticket(brief, model)[0], rows)
        r = route(routes, harness, d.role, d.fields, brief, d.tier, cached, model,
                  1 + class_count(home, harness, d.fields["TW-Class"], routes), pinned)
        row = {"kind": "route", "at": now(), "harness": harness, "session_id": session,
               "tool_use_id": envelope.get("tool_use_id"), "class": d.fields["TW-Class"],
               "coordinator_tier": d.tier, "router_tier": r["tier"],
               "prior_tier": prior(routes, harness, d.role, d.fields["TW-Class"]),
               "agent_model": model,
               "probs": r["probs"],
               "confidence": r["confidence"], "source": r["source"], "mode": r["mode"], "explore": r["explore"], "eps": r["eps"],
               "propensity": r["propensity"], "ms": r["ms"],
               "body_chars_sent": r["body_chars_sent"], "ticket": r["ticket"], "digest": r["digest"],
               "provenance": r.get("provenance"),  # which table/checkpoint produced the pick; None = coordinator
               "action": None, "guard": None, "eligible": None,  # eligible stays None if act() fails
               "pinned": pinned,
               # every configured backend's answer ({tier, probs, ms}) or {error}, logged whether or not the gate
               # passed; {} on a cached row
               "backends": r["backends"], "combined": r["combined"], "combined_mean": r["combined_mean"],
               "gate": r["gate"]}
        if via:
            row["via"] = via
        try:  # an act() bug still records the router's decision
            out, row["action"], row["guard"], row["eligible"], target = act(home, harness, session, envelope, d, r,
                                                                            routes, pinned, via)
        except Exception as exc:
            out, row["action"], row["guard"] = None, None, f"act error: {type(exc).__name__}"
            target = r["tier"]
        row["target_tier"] = target  # floored pick; router_tier stays the raw backend/explore pick
        row["router_agent"] = agent_name(d.role, target) if harness == "claude" else None  # race_check compares it
        if record.get("store_bodies"):
            body = state_root(home) / "bodies" / sha(session.encode("utf-8")) / f"{r['ticket']}.md"
            body.parent.mkdir(parents=True, exist_ok=True)
            body.write_text(brief, encoding="utf-8")
        append_receipt(home, harness, session, row)
        return out, row
    except Exception as exc:
        try:
            append_receipt(home, harness, session, {"kind": "error", "at": now(), "harness": harness,
                                                    "session_id": session, "tool_use_id": envelope.get("tool_use_id"),
                                                    "where": "route", "error": type(exc).__name__})
        except Exception:
            pass  # ponytail: best effort; an unwritable receipts dir already failed above
        return None, None


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
            out[f"{name}.md"] = ("\n".join(head + ["---", "", body, ""])).encode("utf-8")
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


def install_command(flags: dict) -> str:
    tw_cmd = "python thinker-worker/scripts/tw.py"
    args = [tw_cmd, "install"]
    if flags.get("portable"):
        args.append("--portable")
    if flags.get("harness") and len(flags["harness"]) == 1:
        args += ["--harness", flags["harness"][0]]
    if flags.get("python_cmd"):
        args += ["--python-cmd", shlex.quote(flags["python_cmd"])]
    # A changed tw.py makes install refuse an existing install, so the fix is uninstall then install.
    return f"{tw_cmd} uninstall && " + " ".join(args)


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
        note = ("STALE (newest tw.py is on " + newest["machine_id"] + ") -> run: " + install_command(d.get("flags", {}))
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
            raise Conflict("Source changed since installation; uninstall and reinstall after reviewing changes")
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
            # record it without writing; uninstall leaves it for the machine that wrote it.
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
    for name in ("install", "uninstall", "check", "activate", "deactivate", "status", "hook", "machines", "outcome",
                 "route", "promote", "codex"):
        p = commands.add_parser(name)
        p.add_argument("--home", type=Path, default=Path.home())
        if name == "codex":  # Claude harness only; Codex dispatches its models natively
            p.add_argument("--session", required=True)
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--tier", choices=TIERS, required=True)
            p.add_argument("--model", required=True)
            p.add_argument("--brief-file", type=Path, required=True)
            p.add_argument("--cd", type=Path, default=Path.cwd(), help="the child's working root (default: cwd)")
        if name in {"activate", "deactivate", "status", "hook", "outcome", "route", "promote"}:
            p.add_argument("--harness", choices=("codex", "claude"), required=True)
        if name == "route":  # ponytail: writes no receipt; the Codex v2 join by task_name is phase 2
            p.add_argument("--role", choices=("worker", "leaf", "independent-review", "ideation"), required=True)
            p.add_argument("--brief-file", type=Path, required=True)
        if name == "promote":  # read-only over receipts
            p.add_argument("--class", dest="cls")
            p.add_argument("--model")
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
        if name == "activate":
            p.add_argument("--store-bodies", action="store_true")
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
        elif args.command == "uninstall":
            uninstall(home)
        elif args.command == "machines":
            machines(home, args.ledger_dir.expanduser().resolve() if args.ledger_dir else None)
        elif args.command == "check":
            return 1 if check(home)["problems"] else 0
        elif args.command == "activate":
            activate(home, args.harness, session_value(args.session), args.store_bodies)
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
        elif args.command == "promote":
            for v in promote(home, args.harness, args.cls, args.model):  # one JSON line per (class, model)
                print(json.dumps(v))
        elif args.command == "codex":
            return codex_run(home, session_value(args.session), args.role, args.tier, args.model, args.brief_file,
                             args.cd.expanduser().resolve())
        elif args.command == "route":
            routes = load_routes()
            brief = args.brief_file.read_text(encoding="utf-8")
            fields, problem = header_fields(brief)
            if problem:
                raise Conflict(problem)
            r = route(routes, args.harness, args.role, fields, brief,
                      prior(routes, args.harness, args.role, fields["TW-Class"]),
                      t=1 + class_count(home, args.harness, fields["TW-Class"], routes))
            print(json.dumps({k: r[k] for k in ("tier", "probs", "confidence", "source", "ticket", "mode")}))
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
