"""tw.py's fast path must exit only where tw_core.hook would answer with nothing and write nothing, and must hand
everything else to tw_core with the same stdin bytes.
Run: python test_tw_launcher.py"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import tw
import tw_core
from test_tw_hook import W_MIN, pinned_routes

TW = str(Path(__file__).with_name("tw.py"))
SESSION = "launcher-session"


def argv(home, harness="claude", owner=tw.OWNER):
    return ["hook", "--home", str(home), "--harness", harness, "--owner", owner]


def core(home, harness, payload):
    """tw_core.hook's stdout and whether it wrote anything under ~/.thinker-worker beyond the activation records."""
    before = {p for p in (home / ".thinker-worker").rglob("*")}
    out, old = io.StringIO(), sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
    try:
        with contextlib.redirect_stdout(out):
            tw_core.hook(home, harness, tw.OWNER)
    finally:
        sys.stdin = old
    return out.getvalue(), {p for p in (home / ".thinker-worker").rglob("*")} != before


def env(tool="Agent", session=SESSION, prompt=W_MIN):
    return {"session_id": session, "tool_name": tool, "hook_event_name": "PreToolUse", "tool_use_id": "t1",
            "cwd": "/tmp", "tool_input": {"subagent_type": "tw-worker-high", "prompt": prompt}}


def check_owner():
    assert tw.OWNER == tw_core.OWNER
    print("PASS launcher: OWNER matches tw_core")


def check_fast_path_matches_core():
    with pinned_routes(), tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        tw_core.activate(home, "claude", "active-session")
        cases = [  # (harness, payload, exits early)
            ("claude", json.dumps(env(tool="Bash")).encode(), True),
            ("claude", json.dumps(env()).encode(), True),
            ("claude", b"\xef\xbb\xbf" + json.dumps(env()).encode(), True),
            ("codex", json.dumps(env(tool="spawn_agent")).encode(), True),
            ("claude", json.dumps(env(session="active-session")).encode(), False),
            ("claude", json.dumps(env(session="")).encode(), False),
            ("claude", json.dumps(env(session="a\nb")).encode(), False),
            ("claude", json.dumps({**env(), "session_id": None}).encode(), False),
            ("claude", b"[]", False),
        ]
        for harness, payload, early in cases:
            assert tw.inactive(argv(home, harness), payload) is early, (harness, payload)
            if early:
                assert core(home, harness, payload) == ("", False), (harness, payload)
        good = json.dumps(env()).encode()
        assert not tw.inactive(argv(home, owner="someone-else"), good)
        assert not tw.inactive(["hook", "--harness", "claude", "--home", str(home), "--owner", tw.OWNER], good)
        for bad in (b"{", b"\xff", b""):  # inactive() raises; main() then defers to tw_core
            try:
                tw.inactive(argv(home), bad)
            except Exception:
                pass
            else:
                raise AssertionError(bad)
    print("PASS launcher: exits early only where tw_core.hook is silent and writes nothing")


def check_subprocess():
    with pinned_routes(), tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        tw_core.activate(home, "claude", "active-session")

        def run(payload):
            r = subprocess.run([sys.executable, TW, *argv(home)], input=payload, capture_output=True)
            assert r.returncode == 0, r.stderr
            return r.stdout.decode("utf-8")

        assert run(json.dumps(env()).encode()) == ""
        assert not (home / ".thinker-worker" / "receipts").exists()
        good = json.dumps(env(session="active-session")).encode()
        for payload in (good, b"\xef\xbb\xbf" + good):  # stdin replayed to tw_core: admitted (shadow), receipts written
            assert run(payload) == ""
        rows = [json.loads(x) for p in (home / ".thinker-worker" / "receipts" / "claude").glob("*.jsonl")
                for x in p.read_text(encoding="utf-8").splitlines()]
        assert [(r["kind"], r.get("decision")) for r in rows] == [("dispatch", "admit"), ("route", None)] * 2, rows
        bad_header = json.dumps(env(session="active-session", prompt="TW-Role: worker\nx")).encode()
        for payload, why in ((bad_header, "routing header needs"), (b"{", "malformed hook JSON")):
            out = json.loads(run(payload))["hookSpecificOutput"]
            assert out["permissionDecision"] == "deny" and why in out["permissionDecisionReason"], out
        r = subprocess.run([sys.executable, TW, "check", "--home", str(home)], capture_output=True, text=True)
        assert r.returncode == 2 and "manifest" in r.stderr, r.stderr  # other commands go to tw_core
    print("PASS launcher: inactive exits silently; activated, BOM and malformed input reach tw_core")


if __name__ == "__main__":
    check_owner()
    check_fast_path_matches_core()
    check_subprocess()
