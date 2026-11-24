"""No generated Claude agent files (retired 2026-11-24): install writes none, upgrade removes the ones an older install
wrote and leaves every other agent file alone; the role paragraphs that were their bodies live in tw.role_text.
Run: python test_tw_agents.py"""
import subprocess
import sys
import tempfile
from pathlib import Path

import tw

TW = str(Path(__file__).with_name("tw.py"))

if __name__ == "__main__":
    rev = tw.role_text("independent-review")
    assert ("Do your own pass against the acceptance criteria before reading any coordinator hypotheses; if the "
            "brief lists claims to test, answer them after your findings, in their own section.") in rev, rev
    assert all(tw.role_text(r).endswith(tw.NATIVE_WRITE_FALLBACK) for r in tw.ROLE_TEXT)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = subprocess.run([sys.executable, TW, "install", "--home", tmp, "--python", sys.executable,
                            "--harness", "claude"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert not (home / ".claude" / "agents").exists(), list((home / ".claude" / "agents").iterdir())
        assert not [rel for rel in tw.load_manifest(home)["files"] if "/agents/" in rel]

        # an older install: owned tw-*.md files in the manifest, next to an agent file the installer never wrote
        agents = home / ".claude" / "agents"
        agents.mkdir(parents=True)
        mine = b"---\nname: spectroscopy-reviewer\n---\nnot thinker-worker's\n"
        (agents / "spectroscopy-reviewer.md").write_bytes(mine)
        m = tw.load_manifest(home)
        for name in ("tw-worker-high.md", "tw-independent-review-high-opus55.md"):
            data = f"---\nname: {name[:-3]}\n---\nold body\n".encode()
            (agents / name).write_bytes(data)
            m["files"][f".claude/agents/{name}"] = m["source"][f".claude/agents/{name}"] = tw.sha(data)
        tw.manifest_path(home).write_bytes(tw.canonical_json(m))
        r = subprocess.run([sys.executable, TW, "upgrade", "--home", tmp], capture_output=True, text=True)
        assert r.returncode == 0 and "Upgraded 2 owned file(s)" in r.stdout, (r.stdout, r.stderr)
        assert sorted(p.name for p in agents.iterdir()) == ["spectroscopy-reviewer.md"]
        assert (agents / "spectroscopy-reviewer.md").read_bytes() == mine
        assert not [rel for rel in tw.load_manifest(home)["files"] if "/agents/" in rel]
        assert subprocess.run([sys.executable, TW, "check", "--home", tmp], capture_output=True).returncode == 0
        assert subprocess.run([sys.executable, TW, "uninstall", "--home", tmp], capture_output=True).returncode == 0
        assert (agents / "spectroscopy-reviewer.md").read_bytes() == mine
    print("PASS no agent files installed; upgrade removes owned tw-*.md, keeps other agent files; role paragraphs intact")
