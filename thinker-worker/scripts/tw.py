#!/usr/bin/env python3
"""Session-scoped fresh-agent routing guard and reversible skill installer.

No complete prompt or secret is written to receipts. The hook is a guardrail for
native fresh dispatch; it cannot establish effective child model or permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
from datetime import datetime, timezone


OWNER = "thinker-worker-v1"
HARNESSES = ("codex", "claude")
SKILL_FILES = ("SKILL.md", "references/codex.md", "references/claude.md", "scripts/tw.py")
AGENT_FILES = ("thinker-worker-opus.md", "thinker-worker-fable-review.md", "thinker-worker-sonnet.md")
CODEX_WORKERS = {"gpt-6-sol", "gpt-5.6-sol"}
CODEX_REVIEW = {"gpt-6-astra"}
CODEX_LEAF = {"gpt-6-luna"}
CLAUDE_WORKERS = {"opus", "claude-opus-5", "claude-opus-5-5"}
CLAUDE_REVIEW = {"fable", "claude-fable-5", "claude-fable-5-1"}
CLAUDE_LEAF = {"sonnet", "claude-sonnet-5"}
# role -> (owned agent type, allowed models, effortmining miners allowed). Miners pin effort only.
CLAUDE_ROLES = {"worker": ("thinker-worker-opus", CLAUDE_WORKERS, True),
                "leaf": ("thinker-worker-sonnet", CLAUDE_LEAF, True),
                "independent-review": ("thinker-worker-fable-review", CLAUDE_REVIEW, False)}
MINER_TYPE = re.compile(r"effortmining:miner-(low|medium|high|xhigh|max)")
CODEX_EFFORTS = {
    "gpt-6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-luna": {"low", "medium", "high", "xhigh", "max"},
}
ROLE_LINE = re.compile(r"^TW-Role: (worker|leaf|independent-review)$")


class Conflict(Exception):
    pass


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
            type(obj.get("review")) is not bool or type(obj.get("luna")) is not bool or
            type(obj.get("sonnet", False)) is not bool):
        raise Conflict(f"Invalid activation record at {path}; deactivate and reactivate this session")
    return obj


def activate(home: Path, harness: str, session: str, review: bool, luna: bool, sonnet: bool = False) -> None:
    if harness == "claude" and luna:
        raise Conflict("Luna is Codex-only")
    if harness == "codex" and sonnet:
        raise Conflict("Sonnet leaf is Claude-only")
    path = record_path(home, harness, session)
    old = path.read_bytes() if path.exists() else None
    if old is not None:
        activation(home, harness, session)
    obj = {"schema": 1, "harness": harness, "session_id": session,
           "review": review, "luna": luna if harness == "codex" else False,
           "sonnet": sonnet if harness == "claude" else False, "activated_at": now()}
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
                 "review": record["review"] if record else False,
                 "luna": record["luna"] if record else False,
                 "sonnet": record.get("sonnet", False) if record else False,
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
    match = ROLE_LINE.fullmatch(brief.splitlines()[0])
    return (match.group(1), "") if match else (None, "first brief line must be exactly TW-Role: worker, leaf, or independent-review")


def review_details(brief: str) -> bool:
    lines = brief.splitlines()[1:12]
    return (any(x.startswith("TW-Authorization: ") and x[18:].strip() for x in lines) and
            any(x.startswith("TW-Scope: ") and x[10:].strip() for x in lines))


def valid_codex_fork(value: object) -> bool:
    return value == "none" or (isinstance(value, str) and
                               bool(re.fullmatch(r"[1-9][0-9]*", value)))


def decide(harness: str, envelope: dict, record: dict) -> tuple[bool, str, str | None, str | None, str | None]:
    inp = envelope.get("tool_input")
    if not isinstance(inp, dict):
        return False, "missing tool_input", None, None, None
    v2 = harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent"
    brief = inp.get("message" if harness == "codex" else "prompt")
    model = inp.get("model")
    raw_effort = inp.get("reasoning_effort") if harness == "codex" else None
    effort = raw_effort if isinstance(raw_effort, str) else None
    if v2:
        # MultiAgentV2 exposes the brief as ciphertext at PreToolUse. Infer the
        # route only from visible native model metadata; never parse ciphertext.
        role = ("worker" if isinstance(model, str) and model in CODEX_WORKERS else
                "leaf" if isinstance(model, str) and model in CODEX_LEAF else
                "independent-review" if isinstance(model, str) and model in CODEX_REVIEW else None)
        if role is None:
            return False, "model is not allowed for namespaced Codex dispatch", None, model if isinstance(model, str) else None, effort
    else:
        role, problem = first_role(brief)
        if problem:
            return False, problem, role, model if isinstance(model, str) else None, effort
    if role == "independent-review" and not record["review"]:
        return False, "independent review is not activated for this session", role, model, effort
    if role == "independent-review" and not v2 and not review_details(brief):
        return False, "review brief needs TW-Authorization and TW-Scope lines", role, model, effort
    if role == "leaf" and harness == "codex" and not record["luna"]:
        return False, "Luna leaf is not activated for this Codex session", role, model, effort
    if role == "leaf" and harness == "claude" and not record.get("sonnet", False):
        return False, "Sonnet leaf is not activated for this Claude session", role, model, effort
    if not isinstance(model, str):
        return False, "explicit model is required; inherited/omitted model is disallowed", role, None, effort
    if harness == "codex":
        if inp.get("agent_type") not in (None, "default"):
            return False, "custom agent_type is outside this route", role, model, effort
        allowed = {"worker": CODEX_WORKERS, "leaf": CODEX_LEAF,
                   "independent-review": CODEX_REVIEW}[role]
        if model not in allowed:
            return False, f"model is not allowed for {role}", role, model, effort
        if effort not in CODEX_EFFORTS[model]:
            return False, f"explicit supported reasoning_effort is required for {model}", role, model, effort
        if not valid_codex_fork(inp.get("fork_turns")):
            return False, "fork_turns must be explicit 'none' or a bounded positive count", role, model, effort
    else:
        expected_type, allowed, miner_ok = CLAUDE_ROLES[role]
        st = inp.get("subagent_type")
        miner = miner_ok and isinstance(st, str) and MINER_TYPE.fullmatch(st)
        if st != expected_type and not miner:
            alt = " or effortmining:miner-<tier>" if miner_ok else ""
            return False, f"subagent_type must be {expected_type}{alt}", role, model, None
        if model not in allowed:
            return False, f"model is not allowed for {role}", role, model, None
        if inp.get("fork_context") or inp.get("fork"):
            return False, "Claude inherited-model fork is outside fresh dispatch", role, model, None
    return True, "admitted-request-only", role, model, effort


def denial(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                       "permissionDecision": "deny", "permissionDecisionReason": f"{OWNER}: {reason}"}}))


def receipt(home: Path, harness: str, session: str, envelope: dict,
            decision: str, reason: str, role: str | None, model: str | None,
            effort: str | None) -> None:
    # Never store the brief or any unknown input field.
    def small(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        return value if len(value) <= 128 and not any(c in value for c in "\r\n\0") else "<invalid-field>"

    entry = {"at": now(), "harness": harness, "session_id": session,
             "tool_use_id": small(envelope.get("tool_use_id")),
             "tool_name": envelope.get("tool_name"), "decision": decision,
             "reason": reason, "role": role, "requested_model": small(model),
             "requested_effort": small(effort), "effective_model": None, "effective_effort": None,
             "brief_checks": "unavailable-encrypted-v2" if harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent" else "plaintext-route"}
    path = state_root(home) / "receipts" / harness / f"{sha(session.encode('utf-8'))}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))


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
        receipt(home, harness, session, envelope, "deny", "invalid-state", None, None, None)
        return
    if record is None:
        return
    if envelope.get("hook_event_name") != "PreToolUse":
        denial("unexpected hook_event_name on native dispatch")
        receipt(home, harness, session, envelope, "deny", "invalid-event", None, None, None)
        return
    inp = envelope.get("tool_input")
    if isinstance(inp, dict) and any(k in inp for k in ("resume", "resume_id", "agent_id")):
        receipt(home, harness, session, envelope, "deny", "resume-key-on-fresh-dispatch", None, None, None)
        denial("resume fields are outside fresh dispatch; coordinator must verify child identity before native continuation")
        return
    admitted, reason, role, model, effort = decide(harness, envelope, record)
    receipt(home, harness, session, envelope, "admit" if admitted else "deny", reason, role, model, effort)
    if not admitted:
        denial(reason)


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


def portable_command(python_cmd: str | None) -> str:
    """Home-relative bash hook for a settings.json synced across Windows and Mac: resolves the skill
    via $USERPROFILE (Windows) or $HOME, runs the first interpreter that starts, no-ops if absent."""
    run = f'"$tw" hook --home "$h" --harness claude --owner {OWNER}'
    candidates = ([python_cmd] if python_cmd else []) + ["python3", "python", "py -3"]
    # ponytail: probing costs one extra interpreter start per dispatch.
    probes = "".join(f'if {c} -c "" >/dev/null 2>&1; then exec {c} {run}; fi; ' for c in candidates)
    # No interpreter: block (exit 2) only if this machine holds activation state; inactive is a no-op.
    blocked = ('for f in "$h"/.thinker-worker/state/*/*.json; do if [ -f "$f" ]; then '
               f'echo "{OWNER}: guard could not run: no Python interpreter started. Put python3 or python on PATH, '
               'reinstall with --portable --python-cmd <interpreter>, or deactivate the session." >&2; exit 2; fi; done; ')
    return ('h="$HOME"; if [ "$OS" = Windows_NT ] && [ -n "$USERPROFILE" ]; then h="$USERPROFILE"; fi; '
            'tw="$h/.claude/skills/thinker-worker/scripts/tw.py"; [ -f "$tw" ] || exit 0; ' + probes + blocked + "exit 0")


def hook_entry(harness: str, home: Path, python: Path, portable: bool = False,
               python_cmd: str | None = None) -> dict:
    installed = home / f".{harness}" / "skills" / "thinker-worker" / "scripts" / "tw.py"
    argv = [str(python), str(installed), "hook", "--home", str(home),
            "--harness", harness, "--owner", OWNER]
    if harness == "claude" and portable:
        handler = {"type": "command", "command": portable_command(python_cmd), "timeout": 10}
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
            harnesses: tuple[str, ...] = HARNESSES) -> None:
    manifest_file = manifest_path(home)
    items = source_items(harnesses)
    if manifest_file.exists():
        manifest = load_manifest(home)
        if manifest["source"] != {rel: sha(data) for rel, data in items.items()}:
            raise Conflict("Source changed since installation; uninstall and reinstall after reviewing changes")
        state = check(home, quiet=True)
        if state["problems"]:
            raise Conflict("Existing installation conflict: " + "; ".join(state["problems"]))
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
                    "config_existed": {h: originals[h] is not None for h in originals}}
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
    for harness in installed_harnesses(manifest):
        path = config_path(home, harness)
        doc, raw = config_doc(path)
        found = owned_entries(doc)
        if found and found != [manifest["hooks"][harness]]:
            raise Conflict(f"Owned {harness} hook changed or duplicated during uninstall")
        if found and harness not in manifest.get("adopted", []):
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
    manifest_path(home).unlink()
    print("Removed unchanged owned files, hook entries, and activation records; later unrelated settings retained. Receipts remain as evidence.")
    if preserved:
        print("Preserved paths changed during uninstall: " + ", ".join(preserved))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "uninstall", "check", "activate", "deactivate", "status", "hook"):
        p = commands.add_parser(name)
        p.add_argument("--home", type=Path, default=Path.home())
        if name in {"activate", "deactivate", "status", "hook"}:
            p.add_argument("--harness", choices=("codex", "claude"), required=True)
        if name in {"activate", "deactivate", "status"}:
            p.add_argument("--session", required=True)
        if name == "activate":
            p.add_argument("--review", action="store_true")
            p.add_argument("--luna", action="store_true")
            p.add_argument("--sonnet", action="store_true")
        if name == "install":
            p.add_argument("--python", type=Path, default=Path(sys.executable))
            p.add_argument("--portable", action="store_true",
                           help="Claude hook as a home-relative bash command (settings synced across machines)")
            p.add_argument("--harness", choices=("claude", "codex", "both"), default="both")
            p.add_argument("--python-cmd", help="with --portable: interpreter command tried first, inserted verbatim")
        if name == "hook":
            p.add_argument("--owner", required=True)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    try:
        if args.command == "install":
            install(home, args.python.expanduser().resolve(), args.portable, args.python_cmd,
                    HARNESSES if args.harness == "both" else (args.harness,))
        elif args.command == "uninstall":
            uninstall(home)
        elif args.command == "check":
            return 1 if check(home)["problems"] else 0
        elif args.command == "activate":
            activate(home, args.harness, session_value(args.session), args.review, args.luna, args.sonnet)
        elif args.command == "deactivate":
            deactivate(home, args.harness, session_value(args.session))
        elif args.command == "status":
            status(home, args.harness, session_value(args.session))
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
