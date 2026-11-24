#!/usr/bin/env python3
"""thinker-worker runners and reader.

codex | claude | omp | agy: start that tool on a brief file with the model and effort you name, wait, print one JSON
line (the model that ran where the tool reports it, the session id for resuming, the path of the last message) and
append the same line to ~/.thinker-worker/log.jsonl. Each run keeps its files in ~/.thinker-worker/<tool>/<run_id>/.

ran: for each native Claude child of a session, its role, the model and effort on every turn, and token totals, read
from Claude Code's own transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

# Two hours per attempt for every runner: Arian set it for OMP (2026-11-22); a one-hour Codex cap killed a worker
# mid-task (2026-11-13, ~/.claude/lessons.md).
TIMEOUT = 7200.0
CODEX_USAGE = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
CLAUDE_USAGE = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
OMP_CONTINUE = ("The previous attempt reached its time allowance and its process tree exited. Continue the same "
                "bounded assignment in this saved session. Inspect the current files and saved progress before "
                "acting. Do not repeat completed edits, checks, external effects, or any operation whose outcome "
                "is uncertain. If an uncertain effect prevents safe continuation, stop and report it with the "
                "useful work already present.")


def rows(text: str) -> list[dict]:
    """JSON-lines text as dicts; blank, non-JSON and torn lines are skipped."""
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def file_rows(path: Path | None) -> list[dict]:
    return rows(path.read_text(encoding="utf-8", errors="replace")) if path and path.is_file() else []


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
            os.killpg(proc.pid, 9)  # SIGKILL; the child runs in its own session
        except OSError:
            proc.kill()
    try:
        proc.wait(max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return False
    return ok


def run_bounded(argv: list[str], cwd: object, stdin_bytes: bytes, timeout: float) -> dict:
    """Run argv once for at most `timeout` s. stdout/stderr are temp files, not pipes (a surviving grandchild cannot
    hang the read); stdin is a pipe fed by a writer thread (Windows lost a temp-file stdin handle through npm's
    codex.CMD -> node shim, "No prompt provided via stdin", 2026-09-28; a pipe survived; the thread keeps a prompt
    larger than the pipe buffer from blocking before the child reads). On POSIX the child gets its own session so
    kill_tree kills the group. On timeout the tree is killed. Returns code (None on timeout), out, err, timed_out,
    kill_failed, pid, exited (the process was gone at return)."""
    with tempfile.TemporaryFile() as fout, tempfile.TemporaryFile() as ferr:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=fout, stderr=ferr,
                                start_new_session=os.name != "nt")

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


def codex_evidence(home: Path, events: str) -> dict:
    """Thread id and summed usage from `codex exec --json`; the model and effort that ran from the rollout's
    turn_context."""
    ev: dict = {"thread_id": None, "model": None, "effort": None, "usage": {k: 0 for k in CODEX_USAGE}}
    for row in rows(events):
        if row.get("type") == "thread.started":
            ev["thread_id"] = row.get("thread_id")
        elif row.get("type") == "turn.completed":
            for k in CODEX_USAGE:
                ev["usage"][k] += (row.get("usage") or {}).get(k) or 0
    if ev["thread_id"]:
        rollout = next((home / ".codex" / "sessions").rglob(f"rollout-*{ev['thread_id']}.jsonl"), None)
        for row in file_rows(rollout):
            if row.get("type") == "turn_context":  # last one wins
                ev["model"], ev["effort"] = row["payload"].get("model"), row["payload"].get("effort")
    return ev


def claude_evidence(stdout: str) -> dict:
    """`claude -p --output-format json` prints one result object; modelUsage names the models that ran."""
    try:
        obj = json.loads(stdout)
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        return {"session_id": None, "model": None, "models": None, "usage": None, "ok": False, "text": ""}
    mu = obj.get("modelUsage") if isinstance(obj.get("modelUsage"), dict) else {}
    return {"session_id": obj.get("session_id"),
            # the model with the most output is the worker; others (e.g. a small helper model) are listed in models
            "model": max(mu, key=lambda m: mu[m].get("outputTokens") or 0) if mu else None,
            "models": sorted(mu) or None, "usage": obj.get("usage"), "cost_usd": obj.get("total_cost_usd"),
            "ok": not obj.get("is_error"), "text": obj.get("result") if isinstance(obj.get("result"), str) else ""}


def agy_evidence(events: str) -> dict:
    """agy stream-json events carry the conversation, the model it reports, and the final result."""
    rs = rows(events)
    init = next((r for r in rs if r.get("event") == "init"), {})
    results = [r["result"] for r in rs if r.get("event") == "result" and isinstance(r.get("result"), dict)]
    final = results[-1] if results else {}
    meta = init.get("init") if isinstance(init.get("init"), dict) else {}
    # init.model echoes the requested id (absent for agy's default); agy reports no executed model or effort
    return {"conversation_id": init.get("conversation_id"), "reported_model": meta.get("model"),
            "usage": final.get("usage"), "status": final.get("status"),
            "text": final.get("response") if isinstance(final.get("response"), str) else ""}


def omp_models_text() -> str | None:
    """OMP's models.yml, from the agent directory OMP itself resolves (oh-my-pi packages/utils/src/dirs.ts)."""
    # shortcut: Linux XDG redirection and variables set by OMP's own .env files are not followed
    agent = os.environ.get("PI_CODING_AGENT_DIR")
    if not agent:
        root = Path.home() / (os.environ.get("PI_CONFIG_DIR") or ".omp")
        profile = os.environ.get("OMP_PROFILE", os.environ.get("PI_PROFILE"))
        agent = (root / "profiles" / profile if profile else root) / "agent"
    try:
        return (Path(agent) / "models.yml").read_text(encoding="utf-8")
    except OSError:
        return None


def yaml_scalar(text: str) -> str:
    """One plain or quoted YAML scalar, trailing comment removed."""
    text = text.strip()
    if text[:1] == "'":
        m = re.match(r"'((?:[^']|'')*)'", text)
        return m.group(1).replace("''", "'") if m else text
    if text[:1] == '"':
        m = re.match(r'"((?:[^"\\]|\\.)*)"', text)
        if not m:
            return text
        try:
            return json.loads(f'"{m.group(1)}"')
        except ValueError:
            return m.group(1)
    return re.split(r"\s#", text, maxsplit=1)[0].strip()


def omp_model_name(model: str | None, text: str | None) -> str | None:
    """The `name:` OMP shows for served id `model` in models.yml `text`. A local server keeps one served id and
    provider key across model switches; Local-Agent's switch-model.sh rewrites this name on each switch."""
    if not model or not text:
        return None
    # shortcut: first list entry with this id wins; look up per provider if two providers serve one id under two names
    entries, entry, dash_col, key_col = [], None, -1, -1
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        col = len(line) - len(line.lstrip())
        if s.startswith("- ") and (entry is None or col <= dash_col):  # a new list item, not a list nested in one
            rest = line.lstrip()[1:]
            entry, dash_col, key_col = {}, col, col + 1 + len(rest) - len(rest.lstrip())
            entries.append(entry)
            s = rest.strip()
        elif entry is not None and col <= dash_col:
            entry = None
            continue
        elif entry is None or col != key_col:
            continue
        key, sep, value = s.partition(":")
        if sep and key.strip() in ("id", "name"):
            entry.setdefault(key.strip(), yaml_scalar(value))
    return next((e.get("name") or None for e in entries if e.get("id") == model), None)


def omp_evidence(events: str, session_file: Path | None) -> dict:
    """OMP event metadata identifies the worker; the thinking level comes from the saved session."""
    rs = rows(events)
    sessions = [r for r in rs if r.get("type") == "session"]
    messages = [r["message"] for r in rs if r.get("type") == "message_end"
                and isinstance(r.get("message"), dict) and r["message"].get("role") == "assistant"]
    last = messages[-1] if messages else {}
    text = "\n".join(c["text"] for c in (last.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    ends = [r for r in rs if r.get("type") == "agent_end"]
    terminal = bool(ends and ends[-1].get("isTerminal", True) is True and ends[-1].get("yielded", True) is True)
    thinking = [r.get("thinkingLevel") for r in file_rows(session_file) if r.get("type") == "thinking_level_change"]
    usage = [m["usage"] for m in messages if isinstance(m.get("usage"), dict)]
    return {"worker_session_id": sessions[-1].get("id") if sessions else None,
            "model": last.get("model"), "provider": last.get("provider"), "effort": thinking[-1] if thinking else None,
            "usage": {k: sum(u.get(k, 0) or 0 for u in usage)
                      for k in ("input", "output", "cacheRead", "cacheWrite")} if usage else None,
            "ok": terminal and last.get("stopReason") == "stop", "text": text}


def opt(flag: str, value: str | None) -> list[str]:
    return [flag, value] if value is not None else []


def run(tool: str, brief_file: Path, cd: Path, model: str | None = None, effort: str | None = None,
        timeout: float = TIMEOUT, mode: str | None = None, resume: str | None = None,
        home: Path | None = None) -> tuple[int, dict]:
    """Start `tool` on the brief, wait, and return (exit code, result). The brief goes on stdin, verbatim."""
    home = (home or Path.home()).expanduser().resolve()
    cd = Path(cd).expanduser().resolve()
    brief = Path(brief_file).expanduser().read_text(encoding="utf-8-sig")
    run_id = f"{tool}-{uuid.uuid4().hex[:12]}"
    folder = home / ".thinker-worker" / tool / run_id
    folder.mkdir(parents=True)
    last = folder / "last.md"
    exe = shutil.which(tool) or tool
    result: dict = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run_id, "tool": tool,
                    "cd": str(cd), "brief": str(Path(brief_file).expanduser().resolve()),
                    "requested_model": model, "requested_effort": effort}

    if tool == "codex":  # full access by default (Arian 2026-10-25); --mode passes another --sandbox value
        argv = [exe, "--search", "--ask-for-approval", "never", "exec", *opt("-m", model),
                *opt("-c", effort and f"model_reasoning_effort={effort}"), "-s", mode or "danger-full-access",
                "--json", "--skip-git-repo-check", "-C", str(cd), "-o", str(last), "-"]
        ran = run_bounded(argv, cd, brief.encode("utf-8"), timeout)
        out, err = ran["out"], ran["err"]
        ev = codex_evidence(home, out)
        result.update(model=ev["model"], effort=ev["effort"], session_id=ev["thread_id"], usage=ev["usage"])
        ok = last.is_file() and last.read_text(encoding="utf-8").strip() != ""

    elif tool == "claude":  # bypassPermissions by default: `claude -p` cannot answer a permission prompt
        argv = [exe, "-p", "--output-format", "json", "--permission-mode", mode or "bypassPermissions",
                *opt("--model", model), *opt("--effort", effort), *opt("--resume", resume)]
        ran = run_bounded(argv, cd, brief.encode("utf-8"), timeout)
        out, err = ran["out"], ran["err"]
        ev = claude_evidence(out)
        last.write_text(ev["text"], encoding="utf-8")
        result.update(model=ev["model"], models=ev["models"], session_id=ev["session_id"], usage=ev["usage"],
                      cost_usd=ev.get("cost_usd"))
        ok = ev["ok"] and ev["text"].strip() != ""

    elif tool == "agy":  # --dangerously-skip-permissions by default (Arian 2026-11-15); --mode replaces it
        argv = [exe, "--print", "", "--input-format", "stream-json", "--output-format", "stream-json",
                *opt("--model", model), *opt("--effort", effort), *opt("--mode", mode), *opt("--conversation", resume),
                *([] if mode else ["--dangerously-skip-permissions"])]
        stdin = json.dumps({"event": "user", "message": {"content": brief}}) + "\n"
        ran = run_bounded(argv, cd, stdin.encode("utf-8"), timeout)
        out, err = ran["out"], ran["err"]
        ev = agy_evidence(out)
        last.write_text(ev["text"], encoding="utf-8")
        result.update(reported_model=ev["reported_model"], session_id=ev["conversation_id"], usage=ev["usage"],
                      status=ev["status"])
        ok = ev["status"] == "SUCCESS" and ev["text"].strip() != ""

    elif tool == "omp":
        sessions = folder / "sessions"
        base = [exe, "--print", "--mode", "json", "--wait-async", "--no-title", "--cwd", str(cd),
                *opt("--model", model), *opt("--thinking", effort), *opt("--approval-mode", mode)]
        session_file = Path(resume).expanduser().resolve() if resume else None
        names_at_launch = omp_models_text()
        first = run_bounded(base + (["--resume", str(session_file)] if session_file else ["--session-dir", str(sessions)]),
                            cd, brief.encode("utf-8"), timeout)
        first_id = omp_evidence(first["out"], None)["worker_session_id"]
        if not session_file and isinstance(first_id, str):
            session_file = next((p for p in sessions.glob("*.jsonl") if p.stem.endswith("_" + first_id)), None)
        ran, out, err, continued = first, first["out"], first["err"], False
        # After a timeout, continue the saved session once (Arian 2026-11-22), and only once the first process tree
        # is gone: otherwise two processes could write the same files.
        if first["timed_out"] and first["exited"] and not first["kill_failed"] and session_file:
            ran = run_bounded(base + ["--resume", str(session_file)], cd, OMP_CONTINUE.encode("utf-8"), timeout)
            out, err, continued = out + "\n" + ran["out"], err + "\n" + ran["err"], True
        ev = omp_evidence(ran["out"], session_file)
        last.write_text(ev["text"], encoding="utf-8")
        name = omp_model_name(ev["model"], names_at_launch)
        name_at_end = omp_model_name(ev["model"], omp_models_text())  # differs only after a model switch mid-run
        result.update(model=ev["model"], model_name=name,
                      **({"model_name_at_end": name_at_end} if name_at_end != name else {}),
                      provider=ev["provider"], effort=ev["effort"],
                      session_id=ev["worker_session_id"] or first_id,
                      session_file=str(session_file) if session_file else None,
                      usage=omp_evidence(out, None)["usage"], continued=continued)  # usage: every attempt's tokens
        ok = ev["ok"] and ev["text"].strip() != ""
        if ran["timed_out"] and session_file and ran["exited"] and not ran["kill_failed"]:
            (folder / "continue.md").write_text(OMP_CONTINUE + "\n", encoding="utf-8")
            q = lambda p: f'"{Path(p).resolve().as_posix()}"'  # forward slashes: a drive root cannot escape its quote
            parts = [q(sys.executable), q(__file__), "omp", "--brief-file", q(folder / "continue.md"), "--cd", q(cd),
                     "--resume", q(session_file), "--home", q(home), "--timeout", f"{timeout:g}"]
            for flag, value in (("--model", model), ("--effort", effort), ("--mode", mode)):
                parts += [flag, f'"{value}"'] if value is not None else []
            result["resume_command"] = " ".join(parts)
    else:
        raise SystemExit(f"unknown tool {tool}")

    (folder / "events.jsonl").write_text(out, encoding="utf-8")
    (folder / "stderr.log").write_text(err, encoding="utf-8")
    completed = bool(ok and ran["code"] == 0 and not ran["timed_out"])
    result.update(exit_code=ran["code"], completed=completed, timed_out=ran["timed_out"], kill_failed=ran["kill_failed"],
                  last_message=str(last), events=str(folder / "events.jsonl"), stderr=str(folder / "stderr.log"))
    with open(home / ".thinker-worker" / "log.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(result, ensure_ascii=False) + "\n")
    return (0 if completed else ran["code"] or 1), result


def message_text(row: dict) -> str:
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else ""


def ran_children(home: Path, session: str | None = None) -> list[dict]:
    """Every native child of `session` (default: the session whose children changed last), read from
    <config dir>/projects/<project>/<session>/subagents/ under ~/.claude and $CLAUDE_CONFIG_DIR. That layout and the
    per-turn `effort` field are undocumented: if they change, this returns nothing rather than a wrong label."""
    configs = {home / ".claude", *([Path(os.environ["CLAUDE_CONFIG_DIR"])] if os.environ.get("CLAUDE_CONFIG_DIR") else [])}
    folders = [f for c in configs for f in (c / "projects").glob(f"*/{session or '*'}/subagents")]
    if not session and folders:
        folders = [max(folders, key=lambda f: f.stat().st_mtime)]
    children = []
    for folder in folders:
        for meta_path in sorted(folder.glob("agent-*.meta.json"), key=lambda p: p.stat().st_mtime):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            rs = file_rows(meta_path.with_name(meta_path.name[: -len(".meta.json")] + ".jsonl"))
            first = next((message_text(r) for r in rs if r.get("type") == "user"), "")
            role = re.match(r"\s*TW-Role:\s*(\S+)", first)
            turns, usage = [], {}
            for r in rs:
                msg = r.get("message") or {}
                if r.get("type") != "assistant" or not msg.get("model") or msg["model"] == "<synthetic>":
                    continue
                seen = msg.get("id") in usage  # one API turn can span several rows with the same message id
                if msg.get("id") and isinstance(msg.get("usage"), dict):
                    usage[msg["id"]] = msg["usage"]  # the last row per message id carries the final counts
                if seen:
                    continue
                pair = [msg["model"], r.get("effort")]
                if turns and turns[-1][:2] == pair:
                    turns[-1][2] += 1
                else:
                    turns.append(pair + [1])
            children.append({"session": folder.parent.name, "agent": meta_path.name[6: -len(".meta.json")],
                             "name": meta.get("name") or meta.get("description"), "agent_type": meta.get("agentType"),
                             "requested": [meta.get("model"), meta.get("effort")],
                             "role": role.group(1) if role else None,
                             "turns": turns,  # [model, effort, consecutive turns]
                             **{k: sum(u.get(k) or 0 for u in usage.values()) for k in CLAUDE_USAGE}})
    return children


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        # Migration shim: settings that still call `tw.py hook` must get exit 0 and no output, else every Agent call
        # is blocked (an unknown subcommand exits 2). Delete once the Mac's settings no longer carry the entry.
        return 0
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for tool in ("codex", "claude", "omp", "agy"):
        s = sub.add_parser(tool)
        s.add_argument("--brief-file", type=Path, required=True)
        s.add_argument("--cd", type=Path, default=Path.cwd(), help="the worker's working directory")
        s.add_argument("--model", help="the tool's own model id or alias; omitted: the tool's default")
        s.add_argument("--effort", help="low, medium, high, xhigh or max (OMP: its --thinking level)")
        s.add_argument("--timeout", type=float, default=TIMEOUT, help="seconds per attempt (default 7200)")
        s.add_argument("--mode", help="codex --sandbox / claude --permission-mode / agy --mode / omp --approval-mode")
        if tool != "codex":
            s.add_argument("--resume", help="session id to continue (agy: conversation id; omp: session file)")
        s.add_argument("--home", type=Path, help=argparse.SUPPRESS)
    r = sub.add_parser("ran", help="model and effort each native Claude child of a session ran")
    r.add_argument("session", nargs="?", help="session id (default: the session whose children changed last)")
    r.add_argument("--home", type=Path, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    home = (args.home or Path.home()).expanduser()
    if args.cmd == "ran":
        for child in ran_children(home, args.session):
            print(json.dumps(child, ensure_ascii=False))
        return 0
    code, result = run(args.cmd, args.brief_file, args.cd, args.model, args.effort, args.timeout, args.mode,
                       getattr(args, "resume", None), home)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
