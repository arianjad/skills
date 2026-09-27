"""The hook entry point (`tw.py hook`) must fail closed: any internal error yields a deny, never a
traceback (Claude Code treats a non-zero, non-2 exit as non-blocking, i.e. the dispatch would proceed).
Run: python test_tw_hook.py"""
import contextlib
import io
import json
import os
import sys
import tempfile

import tw


def run_main(argv, stdin=""):
    if argv[:1] and argv[0] in ("hook", "activate", "status", "route"):  # these read routes.json (+ user override)
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


def boom(*_a, **_k):
    raise RuntimeError("simulated guard bug")


if __name__ == "__main__":
    pin = pinned_routes()  # held for the whole run; exit restores the env and removes the temp copy
    pin.__enter__()
    tmp = tempfile.TemporaryDirectory()
    home = tmp.name
    session = "11111111-2222-3333-4444-555555555555"
    assert run_main(["activate", "--home", home, "--harness", "claude", "--session", session])[0] == 0
    envelope = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session,
                           "tool_input": {"subagent_type": "tw-worker-high",
                                          "prompt": "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"}})
    hook_argv = ["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER]

    code, out = run_main(hook_argv, envelope)  # sanity: a valid dispatch is admitted (no output)
    assert code == 0 and out == "", (code, out)

    tw.decide = boom
    code, out = run_main(hook_argv, envelope)
    assert code == 0, code
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
    print("PASS hook fails closed")
