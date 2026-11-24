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
from pathlib import Path

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
    """TW_ROUTES -> a temp copy of the shipped routes.json, so a hook test ignores any user override file. Set in
    os.environ, so subprocesses (portable tests) inherit it."""
    with tempfile.TemporaryDirectory() as tmp:
        doc = json.loads((tw.source_root() / "routes.json").read_text(encoding="utf-8"))
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


def reminder_cases():
    routes = tw.load_routes()
    d = tw.Decision(True, "admitted-request-only", "worker", None, "high",
                    {"TW-Class": "T1-mechanical", "TW-Deliverable": "x", "TW-Accept": "x", "TW-Risk": "none"})
    out = tw.reminder("claude", d, routes, "TW-Role: worker\nTW-Class: T1-mechanical")
    assert "prior for T1-mechanical is low; you dispatched high" in out["hookSpecificOutput"]["additionalContext"]
    assert tw.reminder("claude", d._replace(tier="low"), routes, "") is None            # at the prior
    assert tw.reminder("codex", d, routes, "") is None                                  # Codex: none
    assert tw.reminder("claude", d, routes, "TW-Role: worker\nTW-Pin: user high") is None  # pinned


def boom(*_a, **_k):
    raise RuntimeError("simulated guard bug")


if __name__ == "__main__":
    pin = pinned_routes()  # held for the whole run; exit restores the env and removes the temp copy
    pin.__enter__()
    tmp = tempfile.TemporaryDirectory()
    home = tmp.name
    session = "11111111-2222-3333-4444-555555555555"
    assert run_main(["activate", "--home", home, "--harness", "claude", "--session", session])[0] == 0
    W_ROLE = W_MIN + "\n\n" + tw.role_text("worker")
    call = {"subagent_type": "general-purpose", "model": "opus", "effort": "high", "prompt": W_ROLE}
    env = json.dumps(envelope(session, call))
    hook_argv = ["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER]

    code, out = run_main(hook_argv, env)  # sanity: a valid dispatch that holds its role paragraph: no output
    assert code == 0 and out == "", (code, out)

    reminder_cases()
    low = json.dumps(envelope(session, {**call, "effort": "low"}))
    code, out = run_main(hook_argv, low)  # through the hook: below the prior, admitted with one reminder line
    assert code == 0 and "you dispatched low" in json.loads(out)["hookSpecificOutput"]["additionalContext"], out
    print("PASS prior reminder (off-prior tier only; not at the prior, not Codex, not pinned)")

    # the role paragraph (once the tw-*.md agent body): appended through updatedInput, every other field kept
    bare = {**call, "prompt": W_MIN, "name": "n1", "isolation": "worktree", "description": "d"}
    code, out = run_main(hook_argv, json.dumps(envelope(session, bare)))
    spec = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and "permissionDecision" not in spec and spec["hookEventName"] == "PreToolUse", out
    assert spec["updatedInput"] == {**bare, "prompt": W_MIN + "\n\n" + tw.role_text("worker")}, spec
    assert tw.has_role_text(spec["updatedInput"]["prompt"], "worker") and not tw.has_role_text(W_MIN, "worker")
    both = json.loads(run_main(hook_argv, json.dumps(envelope(session, {**bare, "effort": "low"})))[1])
    assert "updatedInput" in both["hookSpecificOutput"] and "additionalContext" in both["hookSpecificOutput"], both
    # auto mode denies a hook-changed Agent call (hooks docs), so there the guard denies with the paragraph to add
    code, out = run_main(hook_argv, json.dumps(envelope(session, bare, permission_mode="auto")))
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny" and tw.role_text("worker") in spec["permissionDecisionReason"], out
    code, out = run_main(hook_argv, json.dumps(envelope(session, call, permission_mode="auto")))
    assert code == 0 and out == "", out                                   # auto mode, paragraph present: admitted
    rows = tw.read_rows(tw.receipts_path(Path(home), "claude", session))
    assert [r["role_text"] for r in rows if r["kind"] == "dispatch"][-4:] == ["appended", "appended", "missing", "present"]
    print("PASS role paragraph: appended via updatedInput (fields kept, no permissionDecision); auto mode denies "
          "with it; present -> unchanged")

    # retired agent names, missing/out-of-tier effort, Codex models: each denied with what to do instead
    for inp, want in (({"subagent_type": "tw-worker-high", "prompt": W_MIN},
                       'retry with subagent_type: "general-purpose", model: "opus", effort: "high"'),
                      ({**call, "effort": None}, "explicit effort is required"),
                      ({**call, "effort": "ultra"}, "effort ultra is outside worker's tiers"),
                      ({**call, "model": "gpt-6.2-sol"}, "dispatch it with `tw.py codex --model gpt-6.2-sol`")):
        code, out = run_main(hook_argv, json.dumps(envelope(session, {k: v for k, v in inp.items() if v is not None})))
        spec = json.loads(out)["hookSpecificOutput"]
        assert spec["permissionDecision"] == "deny" and want in spec["permissionDecisionReason"], (want, out)
    print("PASS denials: retired tw-* name (exact new form), missing/out-of-tier effort, Codex model redirect")

    tw.decide = boom
    code, out = run_main(hook_argv, env)
    assert code == 0, code
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
    print("PASS hook fails closed")
