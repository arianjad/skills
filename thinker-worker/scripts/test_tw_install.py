"""install -> check -> uninstall round trip in a throwaway HOME, with and without a pre-existing
~/.claude/settings.json. Uninstall rewrites JSON canonically, so settings are compared parsed.
Run: python test_tw_install.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TW = str(Path(__file__).with_name("tw.py"))


def tw(*args):
    return subprocess.run([sys.executable, TW, *args], capture_output=True, text=True)


def round_trip(prior_settings):
    home = Path(tempfile.mkdtemp())
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    settings = home / ".claude" / "settings.json"
    if prior_settings is not None:
        settings.write_text(json.dumps(prior_settings), encoding="utf-8")

    r = tw("install", "--home", str(home), "--python", sys.executable)
    assert r.returncode == 0, r.stderr
    assert tw("check", "--home", str(home)).returncode == 0, "check after install"
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert any("thinker-worker" in json.dumps(h) for h in hooks), "guard hook installed"
    assert (home / ".claude" / "agents" / "thinker-worker-opus.md").exists()

    r = tw("uninstall", "--home", str(home))
    assert r.returncode == 0, r.stderr
    assert not (home / ".claude" / "agents" / "thinker-worker-opus.md").exists()
    assert not (home / ".claude" / "skills" / "thinker-worker").exists()
    if prior_settings is None:
        assert not settings.exists() or json.loads(settings.read_text(encoding="utf-8")) in ({}, None), \
            settings.read_text(encoding="utf-8")
    else:
        assert json.loads(settings.read_text(encoding="utf-8")) == prior_settings


if __name__ == "__main__":
    round_trip(None)
    round_trip({"env": {"X": "1"}, "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}})
    print("PASS install round trip (no prior settings, prior settings)")
