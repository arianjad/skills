"""Hook stdin is UTF-8 JSON, including the BOM added by Windows PowerShell.

Run: python test_tw_hook_transport.py. Uses temporary homes, never real activations.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tw
from test_tw_hook import hook_env, pinned_routes


def check_transport():
    with tempfile.TemporaryDirectory() as tmp, pinned_routes():
        home = Path(tmp)
        session = "11111111-2222-3333-4444-555555555555"
        tw.activate(home, "codex", session, False)
        inp = {"hook_event_name": "PreToolUse", "tool_name": "collaborationspawn_agent",
               "session_id": session, "tool_input": {"model": "gpt-6-sol",
               "reasoning_effort": "xhigh", "fork_turns": "none", "agent_type": "default",
               "message": "opaque ciphertext", "task_name": "transport_probe"},
               "cwd": "C:/Users/test/\u03a3\u201d\U0001d44b"}
        raw = json.dumps(inp, ensure_ascii=False).encode("utf-8")
        argv = [sys.executable, str(Path(tw.__file__)), "hook", "--home", str(home),
                "--harness", "codex", "--owner", tw.OWNER]
        env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict"}

        def run(payload):
            r = subprocess.run(argv, input=payload, capture_output=True, env=env)
            assert r.returncode == 0, r.stderr
            return r.stdout.decode("utf-8")

        for payload in (raw, b"\xef\xbb\xbf" + raw):
            out = run(payload)
            assert not out.strip(), out
        for payload in (b"", b"{", b"\xff", b"[]"):
            out = run(payload)
            assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
        inp["tool_input"]["model"] = "gpt-4o"
        out = run(json.dumps(inp).encode("utf-8"))
        assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out

        # The generated Windows launcher, with the production stdin-forwarding path.
        if os.name == "nt" and shutil.which("powershell"):
            installed = home / ".codex/skills/thinker-worker/scripts/tw.py"
            installed.parent.mkdir(parents=True)
            shutil.copy2(tw.__file__, installed)
            r = subprocess.run(["cmd", "/C", tw.portable_windows_command("codex")],
                               input=raw, capture_output=True, env=hook_env(home, True))
            assert r.returncode == 0 and not r.stdout.strip(), (r.stdout, r.stderr)
    print("PASS: UTF-8/BOM and Windows forwarding admit; malformed inputs and bad model deny")


if __name__ == "__main__":
    check_transport()
