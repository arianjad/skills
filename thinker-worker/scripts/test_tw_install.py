"""install -> check -> uninstall round trip in a throwaway HOME, with and without a pre-existing
~/.claude/settings.json. Uninstall rewrites JSON canonically, so settings are compared parsed.
Run: python test_tw_install.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import tw

TW = str(Path(__file__).with_name("tw.py"))


def run_tw(*args):
    return subprocess.run([sys.executable, TW, *args], capture_output=True, text=True)


def round_trip(prior_settings, *extra):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".claude").mkdir()
        (home / ".codex").mkdir()
        settings = home / ".claude" / "settings.json"
        agent = home / ".claude" / "agents" / "thinker-worker-opus.md"
        if prior_settings is not None:
            settings.write_text(json.dumps(prior_settings), encoding="utf-8")

        r = run_tw("install", "--home", str(home), "--python", sys.executable, *extra)
        assert r.returncode == 0, r.stderr
        assert run_tw("check", "--home", str(home)).returncode == 0, "check after install"
        hooks = tw.read_json(settings, {})["hooks"]["PreToolUse"]
        assert any("thinker-worker" in json.dumps(h) for h in hooks), "guard hook installed"
        assert agent.exists()

        r = run_tw("uninstall", "--home", str(home))
        assert r.returncode == 0, r.stderr
        assert not agent.exists()
        assert not (home / ".claude" / "skills" / "thinker-worker").exists()
        assert tw.read_json(settings, {}) == (prior_settings or {})


if __name__ == "__main__":
    prior = {"env": {"X": "1"}, "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}}
    for extra in ((), ("--portable",)):
        round_trip(None, *extra)
        round_trip(prior, *extra)
    print("PASS install round trip (no prior settings, prior settings; exec and --portable)")
