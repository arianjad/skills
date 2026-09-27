"""install generates one Claude agent per (role, tier) in routes.json, with matching effort and model.
Run: python test_tw_agents.py"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import tw

TW = str(Path(__file__).with_name("tw.py"))

if __name__ == "__main__":
    routes = tw.load_routes()
    want = {tw.agent_name(r, t) for r, p in routes["harnesses"]["claude"]["roles"].items() for t in p["tiers"]}
    assert len(want) == 10, want
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = subprocess.run([sys.executable, TW, "install", "--home", tmp, "--python", sys.executable,
                            "--harness", "claude"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        files = {p.stem for p in (home / ".claude" / "agents").glob("*.md")}
        assert files == want, files ^ want
        for name in want:
            text = (home / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            role, tier = tw.AGENT_NAME.fullmatch(name).groups()
            assert f"\neffort: {tier}\n" in text and f"\nname: {name}\n" in text, name
            assert f"\nmodel: {routes['harnesses']['claude']['roles'][role]['models'][0]}\n" in text, name
            assert "tools:" not in text, name               # tools: null = full access (Arian 2026-09-26)
            assert not re.search(r"effort: (max|ultra)", text), name
        rev = (home / ".claude" / "agents" / "tw-independent-review-high.md").read_text(encoding="utf-8")
        assert ("Do your own pass against the acceptance criteria before reading any coordinator hypotheses; if the "
                "brief lists claims to test, answer them after your findings, in their own section.") in rev, rev
        assert subprocess.run([sys.executable, TW, "uninstall", "--home", tmp], capture_output=True).returncode == 0
        assert not list((home / ".claude" / "agents").glob("tw-*.md"))
    print("PASS 10 generated tier agents; effort/model match routes.json; uninstall removes them")
