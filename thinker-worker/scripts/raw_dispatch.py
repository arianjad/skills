#!/usr/bin/env python3
"""Minimal vanilla multi-backend agent dispatcher (no role prompts, no route gates).

Lower transport layer beneath thinker-worker: sends an exact verbatim prompt to
codex, claude, agy, or omp with any requested model/effort, captures process
evidence and logs under ~/.thinker-worker/raw/<run_id>/, and prints one JSON line.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw  # noqa: E402


def _check_batch_metachars(exe: str, argv: list[str], name: str) -> None:
    if os.name == "nt" and Path(exe).suffix.lower() in {".cmd", ".bat"} and any(
        re.search(r'[\r\n"&|<>^%!]', arg) for arg in argv[1:] if arg
    ):
        raise tw.Conflict(f"{name} batch launcher cannot safely carry shell metacharacters")


def _claude_evidence(stdout: str) -> dict:
    """Parse `claude -p --output-format json` stdout (object or JSON-lines fallback)."""
    obj = None
    text = stdout.strip()
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                obj = parsed
        except ValueError:
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        cand = json.loads(line)
                        if isinstance(cand, dict) and cand.get("type") == "result":
                            obj = cand
                            break
                    except ValueError:
                        continue
    if not obj:
        return {"session_id": None, "model": None, "usage": None, "status": None, "is_error": True, "text": text}
    mu = obj.get("modelUsage") if isinstance(obj.get("modelUsage"), dict) else {}
    models = sorted(mu.keys()) if mu else []
    primary = max(mu.items(), key=lambda kv: (kv[1].get("outputTokens") or 0))[0] if mu else None
    return {
        "session_id": obj.get("session_id"),
        "model": primary,
        "models": models or None,
        "usage": obj.get("usage"),
        "cost_usd": obj.get("total_cost_usd"),
        "status": obj.get("subtype"),
        "is_error": bool(obj.get("is_error")),
        "text": obj.get("result") if isinstance(obj.get("result"), str) else "",
    }


def build_codex_argv(exe: str, model: str | None, effort: str | None, cd: Path, out: Path,
                     sandbox: str, approval_policy: str, search: bool = True) -> list[str]:
    argv = [exe]
    if search:
        argv.append("--search")
    argv.extend(["--ask-for-approval", approval_policy, "exec"])
    if model:
        argv.extend(["-m", model])
    if effort:
        argv.extend(["-c", f"model_reasoning_effort={effort}"])
    argv.extend(["-s", sandbox, "--json", "--skip-git-repo-check", "-C", str(cd), "-o", str(out), "-"])
    return argv


def build_claude_argv(exe: str, model: str | None, effort: str | None, permission_mode: str,
                      resume: str | None = None) -> list[str]:
    argv = [exe, "-p", "--output-format", "json", "--permission-mode", permission_mode]
    if model:
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    if resume:
        argv.extend(["--resume", resume])
    return argv


def build_agy_argv(exe: str, model: str | None, effort: str | None, mode: str | None,
                   resume: str | None = None) -> list[str]:
    argv = [exe, "--print", "", "--input-format", "stream-json", "--output-format", "stream-json"]
    for flag, val in (("--model", model), ("--effort", effort), ("--mode", mode), ("--conversation", resume)):
        if val is not None:
            argv.extend([flag, val])
    if mode is None:
        argv.append("--dangerously-skip-permissions")
    return argv


def build_omp_argv(exe: str, cd: Path, model: str | None, effort: str | None, approval_mode: str | None,
                   sessions: Path, resume: str | None = None) -> list[str]:
    argv = [exe, "--print", "--mode", "json", "--wait-async", "--no-title", "--cwd", str(cd)]
    for flag, val in (("--model", model), ("--thinking", effort), ("--approval-mode", approval_mode)):
        if val is not None:
            argv.extend([flag, val])
    argv.extend(["--resume", str(Path(resume).expanduser().resolve())] if resume else ["--session-dir", str(sessions)])
    return argv


def raw_run(backend: str, prompt_text: str, cd: Path, model: str | None = None, effort: str | None = None,
            timeout: float = 1800.0, home: Path | None = None, permission_mode: str | None = None,
            sandbox: str | None = None, approval_policy: str | None = None, resume: str | None = None,
            search: bool = True) -> tuple[int, dict]:
    home = (home or Path.home()).expanduser().resolve()
    cd = cd.expanduser().resolve()
    if not cd.is_dir():
        raise tw.Conflict(f"working directory does not exist: {cd}")
    if not 0 < timeout < float("inf"):
        raise tw.Conflict("timeout must be positive finite seconds")

    run_id = f"raw-{backend}-{uuid.uuid4().hex[:12]}"
    folder = tw.state_root(home) / "raw" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "prompt.md").write_text(prompt_text, encoding="utf-8")
    events_file, stderr_file, last_file = folder / "events.jsonl", folder / "stderr.log", folder / "last.md"

    effective_model = reported_model = effective_effort = session_id = usage = None
    completed = False

    if backend == "codex":
        if Path.home().resolve().is_relative_to(cd):
            raise tw.Conflict(f"--cd {cd} is the home directory or above it; pass a repo or scratch directory")
        exe = shutil.which("codex")
        if not exe:
            raise tw.Conflict("codex CLI not found on PATH")
        sb = sandbox or "danger-full-access"
        ap = approval_policy or "never"
        argv = build_codex_argv(exe, model, effort, cd, last_file, sb, ap, search=search)
        ran = tw.run_bounded(argv, None, prompt_text.encode("utf-8"), timeout)
        events_file.write_bytes(ran["out"].encode("utf-8"))
        stderr_file.write_bytes(ran["err"].encode("utf-8"))
        ev = tw.codex_evidence(home, ran["out"])
        effective_model, effective_effort, session_id = ev["model"], ev["effort"], ev["thread_id"]
        usage = {k: ev[k] for k in tw.CODEX_USAGE}
        completed = bool(ran["code"] == 0 and not ran["timed_out"] and last_file.is_file()
                         and last_file.read_text(encoding="utf-8").strip())

    elif backend == "claude":
        exe = shutil.which("claude")
        if not exe:
            raise tw.Conflict("claude CLI not found on PATH")
        pm = permission_mode or "bypassPermissions"
        argv = build_claude_argv(exe, model, effort, pm, resume=resume)
        ran = tw.run_bounded(argv, cd, prompt_text.encode("utf-8"), timeout)
        events_file.write_bytes(ran["out"].encode("utf-8"))
        stderr_file.write_bytes(ran["err"].encode("utf-8"))
        ev = _claude_evidence(ran["out"])
        last_file.write_text(ev["text"], encoding="utf-8")
        effective_model, session_id, usage = ev["model"], ev["session_id"], ev["usage"]
        completed = bool(ran["code"] == 0 and not ran["timed_out"] and not ev["is_error"] and ev["text"].strip())

    elif backend == "agy":
        exe = shutil.which("agy")
        if not exe:
            raise tw.Conflict("agy CLI not found on PATH")
        argv = build_agy_argv(exe, model, effort, permission_mode, resume=resume)
        _check_batch_metachars(exe, argv, "agy")
        stdin = json.dumps({"event": "user", "message": {"content": prompt_text}}) + "\n"
        ran = tw.run_bounded(argv, cd, stdin.encode("utf-8"), timeout)
        events_file.write_bytes(ran["out"].encode("utf-8"))
        stderr_file.write_bytes(ran["err"].encode("utf-8"))
        ev = tw.agy_evidence(ran["out"])
        last_file.write_text(ev.pop("text"), encoding="utf-8")
        reported_model, session_id, usage = ev["reported_model"], ev["conversation_id"], ev["usage"]
        completed = bool(ran["code"] == 0 and not ran["timed_out"] and ev["status"] == "SUCCESS"
                         and last_file.read_text(encoding="utf-8").strip())

    elif backend == "omp":
        exe = shutil.which("omp")
        if not exe:
            raise tw.Conflict("omp CLI not found on PATH")
        sessions = folder / "sessions"
        argv = build_omp_argv(exe, cd, model, effort, permission_mode, sessions, resume=resume)
        _check_batch_metachars(exe, argv, "omp")
        ran = tw.run_bounded(argv, cd, prompt_text.encode("utf-8"), timeout)
        events_file.write_bytes(ran["out"].encode("utf-8"))
        stderr_file.write_bytes(ran["err"].encode("utf-8"))
        ev = tw.omp_evidence(ran["out"], None)
        sfile = Path(resume).expanduser().resolve() if resume else None
        if not sfile and isinstance(ev["worker_session_id"], str):
            sfile = next((p for p in sessions.glob("*.jsonl") if p.stem.endswith("_" + ev["worker_session_id"])), None)
        ev = tw.omp_evidence(ran["out"], sfile)
        last_file.write_text(ev.pop("text"), encoding="utf-8")
        effective_model, effective_effort, session_id, usage = ev["model"], ev["effort"], ev["worker_session_id"], ev["usage"]
        completed = bool(ran["code"] == 0 and not ran["timed_out"] and ev["terminal"]
                         and ev["stop_reason"] == "stop" and last_file.read_text(encoding="utf-8").strip())
    else:
        raise tw.Conflict(f"unsupported backend: {backend}")

    result = {
        "run_id": run_id,
        "backend": backend,
        "requested_model": model,
        "requested_effort": effort,
        "effective_model": effective_model,
        "reported_model": reported_model,
        "effective_effort": effective_effort,
        "session_id": session_id,
        "exit_code": ran["code"],
        "completed": completed,
        "timed_out": ran["timed_out"],
        "kill_failed": ran["kill_failed"],
        "usage": usage,
        "last_message": str(last_file),
        "events": str(events_file),
        "stderr": str(stderr_file),
    }
    (folder / "result.json").write_bytes(tw.canonical_json(result))
    return (0 if completed else ran["code"] or 1), result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Minimal vanilla multi-backend agent dispatcher (verbatim prompt, no role gates).")
    p.add_argument("--backend", required=True, choices=("codex", "claude", "agy", "omp"))
    p.add_argument("--model", help="Backend-native model id/alias")
    p.add_argument("--effort", help="Effort / thinking level passed to backend")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt-file", type=Path, help="Path to verbatim prompt file (or '-' for stdin)")
    src.add_argument("--prompt", help="Inline verbatim prompt text")
    p.add_argument("--cd", type=Path, default=Path.cwd(), help="Working directory (default: cwd)")
    p.add_argument("--timeout", type=float, default=1800.0, help="Timeout in seconds (default: 1800)")
    p.add_argument("--permission-mode", help="Claude --permission-mode / agy --mode / omp --approval-mode")
    p.add_argument("--sandbox", help="Codex --sandbox (default: danger-full-access)")
    p.add_argument("--approval-policy", help="Codex --ask-for-approval (default: never)")
    p.add_argument("--no-search", action="store_true", help="Disable Codex --search")
    p.add_argument("--resume", help="Session / conversation id or OMP session path to resume")
    p.add_argument("--home", type=Path, help="Override home directory for state/evidence")
    args = p.parse_args(argv)

    if args.prompt is not None:
        prompt_text = args.prompt
    elif str(args.prompt_file) == "-":
        prompt_text = sys.stdin.read()
    else:
        prompt_text = args.prompt_file.expanduser().resolve().read_text(encoding="utf-8-sig")

    try:
        code, result = raw_run(
            backend=args.backend, prompt_text=prompt_text, cd=args.cd, model=args.model, effort=args.effort,
            timeout=args.timeout, home=args.home, permission_mode=args.permission_mode, sandbox=args.sandbox,
            approval_policy=args.approval_policy, resume=args.resume, search=not args.no_search,
        )
    except tw.Conflict as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
