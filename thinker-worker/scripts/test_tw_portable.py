"""`install --portable` writes a home-relative Claude hook that syncs across Windows and Mac.
Run: python test_tw_portable.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import tw
from test_tw_hook import pinned_routes

TW = str(Path(__file__).with_name("tw.py"))


def run_tw(*args):
    return subprocess.run([sys.executable, TW, *args], capture_output=True, text=True)


def claude_command(home):
    pre = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    owned = [h for e in pre for h in e["hooks"] if "thinker-worker-v1" in json.dumps(h)]
    assert len(owned) == 1, owned
    return owned[0]


def seam1_no_absolute_home_paths():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run_tw("install", "--portable", "--home", str(home))
        assert r.returncode == 0, r.stderr
        handler = claude_command(home)
        cmd = handler["command"]
        assert "args" not in handler, handler
        for form in {str(home), str(home.resolve()), home.as_posix(), home.resolve().as_posix()}:
            assert form not in cmd, (form, cmd)
        assert "$HOME" in cmd and "$USERPROFILE" in cmd, cmd
        assert "anaconda" not in cmd, cmd
        r = run_tw("check", "--home", str(home))
        assert r.returncode == 0, r.stdout + r.stderr
    print("PASS seam1 portable command has no absolute home path; check passes")


def run_hook_command(cmd, home, envelope, windows_branch):
    import os
    import shutil
    bash = shutil.which("bash")
    assert bash and "system32" not in bash.lower(), bash  # WSL bash would not see this HOME
    env = {**os.environ, "HOME": home.as_posix(), "USERPROFILE": str(home),
           "OS": "Windows_NT" if windows_branch else ""}
    r = subprocess.run([bash, "-c", cmd], input=json.dumps(envelope), capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.returncode, r.stderr)
    return r.stdout.strip()


def seam2_command_runs_guard():
    session = "22222222-3333-4444-5555-666666666666"
    def envelope(subagent_type):
        return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session,
                "tool_input": {"subagent_type": subagent_type, "model": "opus", "prompt": "TW-Role: worker\nTW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"}}
    # A bogus first-choice interpreter must fall back to the PATH search.
    for extra in ([], ["--python-cmd", '"$USERPROFILE/no-such/python.exe"']):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            assert run_tw("install", "--portable", "--home", str(home), *extra).returncode == 0
            assert run_tw("activate", "--home", str(home), "--harness", "claude", "--session", session).returncode == 0
            cmd = claude_command(home)["command"]
            for windows_branch in (True, False):
                out = run_hook_command(cmd, home, envelope("general-purpose"), windows_branch)
                assert out, "no output: the guard did not run"
                assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
                assert run_hook_command(cmd, home, envelope("tw-worker-high"), windows_branch) == ""
            receipts = list((home / ".thinker-worker" / "receipts" / "claude").glob("*.jsonl"))
            assert len(receipts) == 1 and len(receipts[0].read_text().splitlines()) == 6, receipts
    print("PASS seam2 portable command runs the guard (deny bad, admit good; both OS branches; fallback)")


def seam4_claude_only_leaves_no_codex():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run_tw("install", "--portable", "--harness", "claude", "--home", str(home))
        assert r.returncode == 0, r.stderr
        assert not (home / ".codex").exists(), list((home / ".codex").rglob("*"))
        assert (home / ".claude" / "skills" / "thinker-worker" / "scripts" / "tw.py").is_file()
        r = run_tw("check", "--home", str(home))
        assert r.returncode == 0, r.stdout + r.stderr
        r = run_tw("uninstall", "--home", str(home))
        assert r.returncode == 0, r.stderr
        assert not (home / ".codex").exists()
        assert not (home / ".claude" / "skills" / "thinker-worker").exists()
        assert not (home / ".claude" / "settings.json").exists()
    print("PASS seam4 --harness claude creates no ~/.codex; check and uninstall pass")


def seam5_second_machine_adopts_synced_entry():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as c:
        a, b, c = Path(a), Path(b), Path(c)
        assert run_tw("install", "--portable", "--home", str(a)).returncode == 0
        synced = (a / ".claude" / "settings.json").read_bytes()
        for other in (b, c):  # only settings.json travels between machines
            (other / ".claude").mkdir()
            (other / ".claude" / "settings.json").write_bytes(synced)
        r = run_tw("install", "--portable", "--harness", "claude", "--home", str(b))
        assert r.returncode == 0, r.stderr
        claude_command(b)  # asserts exactly one owned entry
        r = run_tw("check", "--home", str(b))
        assert r.returncode == 0, r.stdout + r.stderr
        # No other machine's ledger is visible from B here (only settings.json was copied), so B's
        # uninstall removes the adopted entry; keeping it for a claiming machine is test_tw_ledger seam c.
        r = run_tw("uninstall", "--home", str(b))
        assert r.returncode == 0, r.stderr
        assert "thinker-worker-v1" not in (b / ".claude" / "settings.json").read_text(encoding="utf-8")
        assert not (b / ".claude" / "skills" / "thinker-worker").exists()
        # A differing owned entry still refuses, naming the fix.
        r = run_tw("install", "--portable", "--harness", "claude", "--python-cmd", "python3.99", "--home", str(c))
        assert r.returncode == 2 and "differs" in r.stderr and "--python-cmd" in r.stderr, r.stderr
        assert (c / ".claude" / "settings.json").read_bytes() == synced
    print("PASS seam5 second machine adopts identical synced entry; unclaimed uninstall removes it; differing entry refuses")


def seam6_no_interpreter_blocks_only_when_activated():
    import os
    import shutil
    bash = shutil.which("bash")
    session = "33333333-4444-5555-6666-777777777777"
    envelope = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session,
                           "tool_input": {"subagent_type": "tw-worker-high", "model": "opus",
                                          "prompt": "TW-Role: worker\nTW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"}})
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as empty_bin:
        home = Path(tmp)
        assert run_tw("install", "--portable", "--harness", "claude", "--home", str(home)).returncode == 0
        cmd = claude_command(home)["command"]
        for windows_branch in (True, False):
            env = {**os.environ, "PATH": empty_bin, "HOME": home.as_posix(), "USERPROFILE": str(home),
                   "OS": "Windows_NT" if windows_branch else ""}
            def run():
                return subprocess.run([bash, "-c", cmd], input=envelope, capture_output=True, text=True, env=env)
            r = run()  # no activation state: inactive sessions are unaffected
            assert r.returncode == 0 and r.stdout == "" and r.stderr == "", (r.returncode, r.stdout, r.stderr)
            assert run_tw("activate", "--home", str(home), "--harness", "claude", "--session", session).returncode == 0
            r = run()
            assert r.returncode == 2, (r.returncode, r.stderr)
            assert "could not run" in r.stderr and "--python-cmd" in r.stderr, r.stderr
            assert run_tw("deactivate", "--home", str(home), "--harness", "claude", "--session", session).returncode == 0
    print("PASS seam6 no interpreter: exit 2 with activation state, exit 0 without")


if __name__ == "__main__":
    pin = pinned_routes()  # TW_ROUTES in os.environ reaches every child hook process through its env
    pin.__enter__()
    seam1_no_absolute_home_paths()
    seam2_command_runs_guard()
    seam4_claude_only_leaves_no_codex()
    seam5_second_machine_adopts_synced_entry()
    seam6_no_interpreter_blocks_only_when_activated()
