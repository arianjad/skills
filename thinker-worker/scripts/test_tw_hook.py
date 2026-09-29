"""The hook entry point (`tw.py hook`) must fail closed: any internal error yields a deny, never a
traceback (Claude Code treats a non-zero, non-2 exit as non-blocking, i.e. the dispatch would proceed).
Run: python test_tw_hook.py"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

import tw

W_MIN = "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"  # admitted worker brief


def run_main(argv, stdin=""):
    if argv[:1] and argv[0] in ("hook", "activate", "status", "route", "models"):  # these read routes.json (+ user override)
        assert os.environ.get("TW_ROUTES") or os.environ.get("TW_ROUTES_OVERRIDE"), \
            "tests must pin routing: TW_ROUTES (pinned_routes) or TW_ROUTES_OVERRIDE, never the real home override"
    out = io.StringIO()
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv, sys.stdin = ["tw.py", *argv], io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out):
            code = tw.main()
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return code, out.getvalue()


@contextlib.contextmanager
def pinned_routes():
    """TW_ROUTES -> a temp copy of the shipped routes.json with every class shadow, explore 0, so a hook test is
    independent of the shipped mode. Set in os.environ, so subprocesses (portable tests) inherit it."""
    with tempfile.TemporaryDirectory() as tmp:
        doc = json.loads((tw.source_root() / "routes.json").read_text(encoding="utf-8"))
        doc["router"]["classes"] = {"*": {"mode": "shadow", "explore": 0.0}}
        path = os.path.join(tmp, "routes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        old = os.environ.get("TW_ROUTES")
        os.environ["TW_ROUTES"] = path
        try:
            yield path
        finally:
            os.environ.pop("TW_ROUTES") if old is None else os.environ.__setitem__("TW_ROUTES", old)


def hook_env(home, windows, **extra):
    """Env for running a portable hook command under bash with `home` as the user's home. On Windows the
    $HOME branch (OS="") runs with a Windows Python, so Git Bash must convert its /tmp/... home path:
    MSYS_NO_PATHCONV is dropped."""
    env = {k: v for k, v in os.environ.items() if k != "MSYS_NO_PATHCONV"}
    return {**env, "HOME": home.as_posix(), "USERPROFILE": str(home),
            "OS": "Windows_NT" if windows else "", **extra}


def envelope(session, inp, tool="Agent", tool_use_id=None, **extra):
    """A PreToolUse hook envelope; tool_use_id and extra keys (cwd, transcript_path) only when given."""
    env = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": session, "tool_input": inp, **extra}
    if tool_use_id is not None:
        env["tool_use_id"] = tool_use_id
    return env


@contextlib.contextmanager
def denied_kill():
    """tw.kill_tree's kill fails as under Access denied: taskkill exits 1 (Windows), os.killpg does nothing (POSIX)."""
    real_run, real_killpg = tw.subprocess.run, getattr(tw.os, "killpg", None)

    def no_taskkill(argv, *a, **k):
        if argv[0] == "taskkill":
            return tw.subprocess.CompletedProcess(argv, 1, b"", b"ERROR: Access denied")
        return real_run(argv, *a, **k)
    tw.subprocess.run = no_taskkill
    if real_killpg:
        tw.os.killpg = lambda *_a: None
    try:
        yield
    finally:
        tw.subprocess.run = real_run
        if real_killpg:
            tw.os.killpg = real_killpg


def reap(pid):
    """Kill the process (tree) `pid` that a test launched; already gone is fine."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def boom(*_a, **_k):
    raise RuntimeError("simulated guard bug")


if __name__ == "__main__":
    pin = pinned_routes()  # held for the whole run; exit restores the env and removes the temp copy
    pin.__enter__()
    tmp = tempfile.TemporaryDirectory()
    home = tmp.name
    session = "11111111-2222-3333-4444-555555555555"
    assert run_main(["activate", "--home", home, "--harness", "claude", "--session", session])[0] == 0
    env = json.dumps(envelope(session, {"subagent_type": "tw-worker-high", "prompt": W_MIN}))
    hook_argv = ["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER]

    code, out = run_main(hook_argv, env)  # sanity: a valid dispatch is admitted (no output)
    assert code == 0 and out == "", (code, out)

    tw.decide = boom
    code, out = run_main(hook_argv, env)
    assert code == 0, code
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
    print("PASS hook fails closed")
