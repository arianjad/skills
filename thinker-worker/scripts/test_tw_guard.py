"""Guard: advisory whenever context-mode's Agent hook may be live in this session (design §4.6).
Run: python test_tw_guard.py"""
import json
import os
import tempfile
import time
from pathlib import Path

import tw

START = 1_790_000_000.0


def setup(home, enabled=True, agent=False, mtime=START - 100, installed=True):
    (home / ".claude" / "plugins").mkdir(parents=True)
    on = {} if enabled is None else {"context-mode@context-mode": enabled}
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": on}))
    cm = home / "cm"
    (cm / "hooks").mkdir(parents=True)
    pre = [{"matcher": "Bash", "hooks": []}] + ([{"matcher": "Agent", "hooks": []}] if agent else [])
    hj = cm / "hooks" / "hooks.json"
    hj.write_text(json.dumps({"hooks": {"PreToolUse": pre}}))
    os.utime(hj, (mtime, mtime))
    plugins = {"context-mode@context-mode": [{"installPath": str(cm)}]} if installed else {}
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": plugins}))


def verdict(start=START, **kw):
    tw.claude_process_start = lambda: start
    with tempfile.TemporaryDirectory() as tmp:
        setup(Path(tmp), **kw)
        return tw.competing_agent_writer(Path(tmp))


CASES = [
    ("plugin explicitly disabled", verdict(enabled=False, agent=True), None),
    ("key absent is not 'disabled'", verdict(enabled=None, agent=True) is not None, True),
    ("not installed", verdict(installed=False), None),
    ("clean and old", verdict(), None),
    ("Agent entry live", verdict(agent=True) is not None, True),
    ("patched after start (heal ran this session)", verdict(mtime=START + 1.5) is not None, True),
    ("patched within 1 s before start", verdict(mtime=START - 0.5) is not None, True),
    ("start unknown", verdict(start=None) is not None, True),
]

if __name__ == "__main__":
    bad = [(n, g, w) for n, g, w in CASES if g != w]
    for b in bad:
        print("FAIL", b)
    assert not bad
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        setup(home)
        (home / "cm" / "hooks" / "hooks.json").write_text("{not json")
        assert tw.competing_agent_writer(home).startswith("guard could not read"), "malformed -> advisory"
    print(f"PASS {len(CASES) + 1} guard cases")
