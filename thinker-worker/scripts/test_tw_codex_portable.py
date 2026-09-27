"""`install --portable` also makes the Codex hooks.json entry home-relative: a POSIX `command` and a
PowerShell `commandWindows`. Round trip plus execution of both forms. Run: python test_tw_codex_portable.py"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_tw_hook import pinned_routes

TW = str(Path(__file__).with_name("tw.py"))
SESSION = "44444444-5555-6666-7777-888888888888"


def run_tw(*args):
    return subprocess.run([sys.executable, TW, *args], capture_output=True, text=True)


def codex_handler(home):
    pre = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    owned = [h for e in pre for h in e["hooks"] if "thinker-worker-v1" in json.dumps(h)]
    assert len(owned) == 1, owned
    return owned[0]


def envelope(model):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": SESSION,
                       "tool_input": {"message": "TW-Role: worker\nTW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx", "model": model,
                                      "reasoning_effort": "high", "fork_turns": "none"}})


def env_for(home, **extra):
    return {**os.environ, "HOME": home.as_posix(), "USERPROFILE": str(home), **extra}


def check_guard(run, label):
    r = run(envelope("gpt-4o"))
    assert r.returncode == 0 and r.stdout.strip(), (label, r.returncode, r.stdout, r.stderr)
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny", (label, r.stdout)
    r = run(envelope("gpt-6-sol"))
    assert r.returncode == 0 and r.stdout.strip() == "", (label, r.returncode, r.stdout, r.stderr)


def powershell_argv(command_windows, powershell):
    parts = command_windows.split()
    assert parts[0].lower() == "powershell.exe", command_windows
    return [powershell, *parts[1:]]


if __name__ == "__main__":
    pin = pinned_routes()  # TW_ROUTES in os.environ reaches every child hook process through its env
    pin.__enter__()
    bash = shutil.which("bash")
    powershell = shutil.which("powershell")
    prior = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}}
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as empty_bin:
        home = Path(tmp)
        (home / ".codex").mkdir()
        (home / ".codex" / "hooks.json").write_text(json.dumps(prior), encoding="utf-8")
        r = run_tw("install", "--portable", "--harness", "codex", "--home", str(home))
        assert r.returncode == 0, r.stderr
        h = codex_handler(home)
        payload = base64.b64decode(h["commandWindows"].split()[-1]).decode("utf-16le")
        for text in (h["command"], h["commandWindows"], payload):
            for form in {str(home), str(home.resolve()), home.as_posix(), home.resolve().as_posix()}:
                assert form not in text, (form, text)
        assert "$HOME" in h["command"] and "USERPROFILE" in payload, (h["command"], payload)
        assert run_tw("check", "--home", str(home)).returncode == 0
        assert run_tw("activate", "--home", str(home), "--harness", "codex", "--session", SESSION).returncode == 0

        # Mac/Linux form under sh-compatible bash; Windows form exactly as Codex runs it (cmd /C).
        check_guard(lambda inp: subprocess.run([bash, "-c", h["command"]], input=inp, capture_output=True,
                                               text=True, env=env_for(home, OS="")), "posix")
        check_guard(lambda inp: subprocess.run(["cmd", "/C", h["commandWindows"]], input=inp, capture_output=True,
                                               text=True, env=env_for(home)), "windows")

        # No interpreter with an activated session: both forms block with exit 2; inactive: exit 0.
        runs = {"posix": lambda: subprocess.run([bash, "-c", h["command"]], input=envelope("gpt-6-sol"),
                                                capture_output=True, text=True,
                                                env=env_for(home, OS="", PATH=empty_bin)),
                "windows": lambda: subprocess.run(powershell_argv(h["commandWindows"], powershell),
                                                  input=envelope("gpt-6-sol"), capture_output=True, text=True,
                                                  env=env_for(home, PATH=empty_bin))}
        for label, run in runs.items():
            r = run()
            assert r.returncode == 2 and "could not run" in r.stderr, (label, r.returncode, r.stderr)
        assert run_tw("deactivate", "--home", str(home), "--harness", "codex", "--session", SESSION).returncode == 0
        for label, run in runs.items():
            r = run()
            assert r.returncode == 0 and r.stdout.strip() == "", (label, r.returncode, r.stdout, r.stderr)

        assert run_tw("uninstall", "--home", str(home)).returncode == 0
        assert json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8")) == prior
    print("PASS codex portable: no absolute home paths; posix and cmd/PowerShell forms deny/admit; "
          "no-interpreter blocks only when activated; round trip restores hooks.json")
