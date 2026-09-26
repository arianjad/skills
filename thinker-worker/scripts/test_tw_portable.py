"""`install --portable` writes a home-relative Claude hook that syncs across Windows and Mac.
Run: python test_tw_portable.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import tw

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


if __name__ == "__main__":
    seam1_no_absolute_home_paths()
