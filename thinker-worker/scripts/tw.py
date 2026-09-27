#!/usr/bin/env python3
"""Session-scoped fresh-agent routing guard and reversible skill installer.

Receipts store the validated routing header (each value cut at 256 chars) and never the brief body or a secret. The hook is a guardrail for
native fresh dispatch; it cannot establish effective child model or permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shlex
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import NamedTuple


OWNER = "thinker-worker-v1"
HARNESSES = ("codex", "claude")
SKILL_FILES = ("SKILL.md", "routes.json", "references/codex.md", "references/claude.md", "scripts/tw.py")
AGENT_FILES = ("thinker-worker-opus.md", "thinker-worker-fable-review.md", "thinker-worker-sonnet.md")
TIERS = ("low", "medium", "high", "xhigh")
AGENT_NAME = re.compile(r"tw-(worker|leaf|independent-review|ideation)-(low|medium|high|xhigh)")
VALUE_MAX = 1000  # per header value at the gate; receipts truncate at 256
ROLE_LINE = re.compile(r"^TW-Role: (worker|leaf|independent-review|ideation)$")
# Routing header: labeled input for the routing classifier. Classes are effortmining's vocabulary.
HEADER_KEYS = ("TW-Class", "TW-Deliverable", "TW-Accept", "TW-Risk")
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


def load_routes(path: Path | None = None) -> dict:
    path = path or source_root() / "routes.json"
    doc = read_json(path, None)
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise Conflict(f"routes.json missing or not schema 1: {path}")
    for harness in HARNESSES:
        for role, pol in doc["harnesses"][harness]["roles"].items():
            if (not pol.get("models") or not pol.get("tiers") or any(t not in TIERS for t in pol["tiers"])
                    or pol.get("default") not in pol["tiers"]):
                raise Conflict(f"routes.json: bad policy for {harness}/{role}")
    return doc


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


def first_role(brief: object) -> tuple[str | None, str]:
    if not isinstance(brief, str) or not brief:
        return None, "missing brief"
    match = ROLE_LINE.fullmatch(brief.split("\n")[0])  # "\n" only: splitlines() splits on U+2028 etc.
    return (match.group(1), "") if match else (None, "first brief line must be exactly TW-Role: worker, leaf, independent-review, or ideation")


def review_details(brief: str) -> bool:
    lines = brief.split("\n")[1:12]
    return (any(x.startswith("TW-Authorization: ") and x[18:].strip() for x in lines) and
            any(x.startswith("TW-Scope: ") and x[10:].strip() for x in lines))


def header_fields(brief: str) -> tuple[dict | None, str]:
    """Return ({key: value}, "") or (None, problem). Keys may sit anywhere in lines 2-12."""
    found: dict[str, str] = {}
    for line in brief.split("\n")[1:12]:
        key, sep, value = line.partition(": ")
        if sep and key in HEADER_KEYS:
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
    long = [k for k in HEADER_KEYS if len(found[k]) > VALUE_MAX]
    if long:
        return None, f"routing header value over {VALUE_MAX} characters: " + ", ".join(long)
    return found, ""


def header_text(fields: dict, cap: int = 256) -> str:
    def cut(v: str) -> str:
        return v if len(v) <= cap else f"{v[:cap]}…[+{len(v) - cap}]"
    return "\n".join(f"{k}: {cut(fields[k])}" for k in HEADER_KEYS)


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
            return Decision(False, f"{role} brief needs TW-Authorization and TW-Scope lines", role, model)
    pol = roles[route]
    if harness == "codex":
        if model is None:
            return Decision(False, "explicit model is required; inherited/omitted model is disallowed", role)
        if inp.get("agent_type") not in (None, "default"):
            return Decision(False, "custom agent_type is outside this route", role, model)
        if model not in pol["models"]:
            return Decision(False, f"model is not allowed for {route}", role, model)
        tier = inp.get("reasoning_effort")
        if tier not in pol["tiers"]:
            return Decision(False, f"reasoning_effort must be one of {', '.join(pol['tiers'])} for {route}", role, model)
        if not valid_codex_fork(inp.get("fork_turns")):
            return Decision(False, "fork_turns must be explicit 'none' or a bounded positive count", role, model)
    else:
        st = inp.get("subagent_type")
        match = AGENT_NAME.fullmatch(st) if isinstance(st, str) else None
        if not match or match.group(1) != role:
            return Decision(False, f"subagent_type must be tw-{role}-<tier>", role, model)
        tier = match.group(2)
        if tier not in pol["tiers"]:
            return Decision(False, f"tier {tier} is outside {role}'s tiers {pol['tiers']}", role, model)
        if model is not None and model not in pol["models"]:
            return Decision(False, f"per-call model {model} differs from the {role} agent's model", role, model)
        if inp.get("fork_context") or inp.get("fork"):
            return Decision(False, "Claude inherited-model fork is outside fresh dispatch", role, model)
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
             "brief_checks": "unavailable-encrypted-v2" if harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent" else "plaintext-route"}
    append_receipt(home, harness, session, entry)


def receipts_path(home: Path, harness: str, session: str) -> Path:
    return state_root(home) / "receipts" / harness / f"{sha(session.encode('utf-8'))}.jsonl"


def append_receipt(home: Path, harness: str, session: str, entry: dict) -> None:
    path = receipts_path(home, harness, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))


def outcome(home: Path, harness: str, session: str, tool_use_id: str, accepted: bool) -> None:
    """Label a guarded dispatch; the last outcome for a tool_use_id wins."""
    path = receipts_path(home, harness, session)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if not any(json.loads(x).get("tool_use_id") == tool_use_id for x in lines if x.strip()):
        raise Conflict(f"no receipt for tool_use_id {tool_use_id} in {harness} session {session}")
    append_receipt(home, harness, session, {"kind": "outcome", "at": now(), "harness": harness,
                                            "session_id": session, "tool_use_id": tool_use_id,
                                            "accepted": accepted})
    print(f"Recorded {'accepted' if accepted else 'rejected'} for {tool_use_id}.")


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
    d = decide(harness, envelope, load_routes())
    receipt(home, harness, session, envelope, d)
    if not d.admitted:
        denial(d.reason)


def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def source_items(harnesses: tuple[str, ...] = HARNESSES) -> dict[str, bytes]:
    root = source_root()
    out = {}
    for harness in harnesses:
        for rel in SKILL_FILES:
            out[f".{harness}/skills/thinker-worker/{rel}"] = (root / rel).read_bytes()
    if "claude" in harnesses:
        for name in AGENT_FILES:
            out[f".claude/agents/{name}"] = (root / "claude-agents" / name).read_bytes()
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
    for name in ("install", "uninstall", "check", "activate", "deactivate", "status", "hook", "machines", "outcome"):
        p = commands.add_parser(name)
        p.add_argument("--home", type=Path, default=Path.home())
        if name in {"activate", "deactivate", "status", "hook", "outcome"}:
            p.add_argument("--harness", choices=("codex", "claude"), required=True)
        if name in {"activate", "deactivate", "status", "outcome"}:
            p.add_argument("--session", required=True)
        if name == "outcome":
            p.add_argument("--tool-use-id", required=True)
            p.add_argument("--accepted", choices=("yes", "no"), required=True)
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
            outcome(home, args.harness, session_value(args.session), args.tool_use_id, args.accepted == "yes")
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
