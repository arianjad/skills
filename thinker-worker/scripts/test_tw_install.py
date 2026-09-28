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
        agent = home / ".claude" / "agents" / "tw-worker-high.md"
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


def behind(home, rel, old=b"older release\n"):
    """Make `rel` look installed from an older source: the file and its manifest digest are the old bytes."""
    (home / rel).write_bytes(old)
    m = tw.load_manifest(home)
    m["files"][rel] = m["source"][rel] = tw.sha(old)
    tw.manifest_path(home).write_bytes(tw.canonical_json(m))


def upgrade_in_place():
    """upgrade replaces owned files installed from an older source, keeps activation records and hooks, and refuses
    (writing nothing) when an owned file matches neither the manifest nor the new source (a hand edit)."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".claude").mkdir()
        (home / ".codex").mkdir()
        assert run_tw("install", "--home", str(home), "--python", sys.executable).returncode == 0
        assert run_tw("activate", "--home", str(home), "--harness", "claude", "--session", "s-1").returncode == 0
        tw_rel, agent_rel = ".claude/skills/thinker-worker/scripts/tw.py", ".claude/agents/tw-worker-high.md"
        current = {rel: (home / rel).read_bytes() for rel in (tw_rel, agent_rel)}
        settings = (home / ".claude" / "settings.json").read_bytes()
        behind(home, tw_rel)
        behind(home, agent_rel)
        ledger = next((home / ".claude" / "thinker-worker-installs").glob("*.json"))
        doc = json.loads(ledger.read_text(encoding="utf-8"))
        ledger.write_text(json.dumps({**doc, "tw_sha256": "0" * 64}), encoding="utf-8")   # this machine looks stale
        r = run_tw("install", "--home", str(home), "--python", sys.executable)
        assert r.returncode == 2 and "tw.py upgrade" in r.stderr, r.stderr                 # install points at upgrade
        r = run_tw("upgrade", "--home", str(home))
        assert r.returncode == 0, r.stderr
        assert all((home / rel).read_bytes() == data for rel, data in current.items()), "files now the new source"
        assert run_tw("check", "--home", str(home)).returncode == 0, "manifest matches the upgraded files"
        assert (home / ".claude" / "settings.json").read_bytes() == settings, "hook entries untouched"
        assert json.loads(ledger.read_text(encoding="utf-8"))["tw_sha256"] == tw.sha(Path(TW).read_bytes()), \
            "upgrade refreshes this machine's ledger"
        st = run_tw("status", "--home", str(home), "--harness", "claude", "--session", "s-1")
        assert st.returncode == 0 and "inactive" not in st.stdout.lower(), st.stdout      # activation kept

        # a file the source no longer produces (e.g. a dropped agent tier) is removed if unchanged since install
        gone = ".claude/agents/tw-worker-retired.md"
        (home / gone).write_bytes(b"old agent\n")
        m = tw.load_manifest(home)
        m["files"][gone] = m["source"][gone] = tw.sha(b"old agent\n")
        tw.manifest_path(home).write_bytes(tw.canonical_json(m))
        assert run_tw("upgrade", "--home", str(home)).returncode == 0
        assert not (home / gone).exists() and gone not in tw.load_manifest(home)["files"]

        # a hand edit refuses the whole upgrade: nothing written, the older file elsewhere left as it was
        behind(home, agent_rel)
        (home / tw_rel).write_bytes(b"hand edit\n")
        r = run_tw("upgrade", "--home", str(home))
        assert r.returncode == 2 and "nothing written" in r.stderr and "tw.py" in r.stderr, r.stderr
        assert (home / agent_rel).read_bytes() == b"older release\n" and (home / tw_rel).read_bytes() == b"hand edit\n"


if __name__ == "__main__":
    upgrade_in_place()
    print("PASS upgrade: older install replaced in place, check passes, hooks and activation kept")
    prior = {"env": {"X": "1"}, "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}}
    for extra in ((), ("--portable",)):
        round_trip(None, *extra)
        round_trip(prior, *extra)
    print("PASS install round trip (no prior settings, prior settings; exec and --portable)")
