"""The hook entry point (`tw.py hook`) must fail closed: any internal error yields a deny, never a
traceback (Claude Code treats a non-zero, non-2 exit as non-blocking, i.e. the dispatch would proceed).
Run: python test_tw_hook.py"""
import contextlib
import io
import json
import sys
import tempfile

import tw


def run_main(argv, stdin=""):
    out = io.StringIO()
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv, sys.stdin = ["tw.py", *argv], io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out):
            code = tw.main()
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return code, out.getvalue()


def boom(*_a, **_k):
    raise RuntimeError("simulated guard bug")


if __name__ == "__main__":
    tmp = tempfile.TemporaryDirectory()
    home = tmp.name
    session = "11111111-2222-3333-4444-555555555555"
    assert run_main(["activate", "--home", home, "--harness", "claude", "--session", session])[0] == 0
    envelope = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session,
                           "tool_input": {"subagent_type": "thinker-worker-opus", "model": "opus",
                                          "prompt": "TW-Role: worker\nTW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"}})
    hook_argv = ["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER]

    code, out = run_main(hook_argv, envelope)  # sanity: a valid dispatch is admitted (no output)
    assert code == 0 and out == "", (code, out)

    tw.decide = boom
    code, out = run_main(hook_argv, envelope)
    assert code == 0, code
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
    print("PASS hook fails closed")
