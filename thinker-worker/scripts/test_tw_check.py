"""TW-Check: an optional brief header naming a shell command that checks the delivered artifact. The dispatch row
stores it in full with the dispatch cwd; `tw.py outcome` runs it and writes a pass/fail/unknown `check` row.
Run: python test_tw_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from test_tw_hook import pinned_routes, run_main
from test_tw_receipt import HDR, SESSION, receipts

PY = '"' + Path(sys.executable).as_posix() + '"'


def dispatch(home, brief, cwd, tid="toolu_x"):
    env = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION, "tool_use_id": tid,
           "cwd": cwd, "tool_input": {"subagent_type": "tw-worker-high", "prompt": brief}}
    return run_main(["hook", "--home", home, "--harness", "claude", "--owner", "thinker-worker-v1"], json.dumps(env))


def brief(check=None, extra=""):
    return "TW-Role: worker\n" + HDR + (f"TW-Check: {check}\n" if check is not None else "") + extra + "do it"


def denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


if __name__ == "__main__":
    pin = pinned_routes()
    pin.__enter__()
    # C1: the header key, stored on the dispatch row in full with the hook envelope's cwd
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        long = f"{PY} -c pass && " + "echo " + "y" * 600   # longer than the 256-char header cut
        code, out = dispatch(home, brief(long), home)
        assert code == 0 and not denied(out), out
        row = [r for r in receipts(home, "claude") if r["kind"] == "dispatch"][-1]
        assert row["decision"] == "admit" and row["check"] == long and row["cwd"] == home, row
        code, out = dispatch(home, brief(), home, "toolu_y")                   # optional: still admitted
        row = [r for r in receipts(home, "claude") if r["kind"] == "dispatch"][-1]
        assert not denied(out) and row["decision"] == "admit" and row["check"] is None, (out, row)
        for why, b in (("repeats TW-Check", brief("true", "TW-Check: false\n")),
                       ("TW-Check", brief("   ")),                            # empty value
                       ("over 1000", brief("x" * 1001))):
            code, out = dispatch(home, b, home, "toolu_z")
            assert denied(out) and why in out, (why, out)
        code, out = dispatch(home, brief("x" * 1000), home, "toolu_z")
        assert not denied(out), out
    print("PASS C1 TW-Check header: optional, once, non-empty, <= VALUE_MAX; stored in full with cwd")

