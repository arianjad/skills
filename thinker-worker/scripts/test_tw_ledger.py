"""Per-machine install ledgers in a synced dir: two machines simulated as two temp homes sharing one
ledger dir and a copied settings.json; identity injected via TW_MACHINE_ID.
Run: python test_tw_ledger.py"""
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TW = Path(__file__).with_name("tw.py")


def run_tw(machine, *args):
    env = {**os.environ, "TW_MACHINE_ID": machine}
    return subprocess.run([sys.executable, str(TW), *args], capture_output=True, text=True, env=env)


def owned(settings):
    pre = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {}).get("PreToolUse", [])
    return [e for e in pre if "thinker-worker-v1" in json.dumps(e)]


def seam_a_install_writes_ledger():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as led:
        home, led = Path(tmp), Path(led)
        t0 = datetime.now(timezone.utc)
        r = run_tw("pc-a", "install", "--portable", "--harness", "claude", "--python-cmd", "python3",
                   "--home", str(home), "--ledger-dir", str(led))
        assert r.returncode == 0, r.stderr
        t1 = datetime.now(timezone.utc)
        files = sorted(p.name for p in led.iterdir())
        assert files == ["pc-a.json"], files
        doc = json.loads((led / "pc-a.json").read_text(encoding="utf-8"))
        assert doc["machine_id"] == "pc-a" and doc["status"] == "installed", doc
        assert doc["os"] == platform.system(), doc["os"]
        assert doc["tw_sha256"] == hashlib.sha256(TW.read_bytes()).hexdigest()
        assert doc["flags"] == {"portable": True, "harness": ["claude"], "python_cmd": "python3"}, doc["flags"]
        [entry] = owned(home / ".claude" / "settings.json")
        assert doc["hooks"] == {"claude": {"entry": entry, "mode": "written"}}, doc["hooks"]
        for key in ("installed_at", "updated_at"):
            assert t0 <= datetime.fromisoformat(doc[key]) <= t1, (key, doc[key])
        # Ledger publishes no home path.
        text = (led / "pc-a.json").read_text(encoding="utf-8")
        for form in (json.dumps(str(home))[1:-1], home.as_posix(), json.dumps(str(led))[1:-1], led.as_posix()):
            assert form not in text, form
        # Rerunning install on an existing install (e.g. one that predates ledgers) refreshes it.
        (led / "pc-a.json").unlink()
        r = run_tw("pc-a", "install", "--portable", "--harness", "claude", "--python-cmd", "python3",
                   "--home", str(home), "--ledger-dir", str(led))
        assert r.returncode == 0 and "Already installed" in r.stdout, r.stdout + r.stderr
        again = json.loads((led / "pc-a.json").read_text(encoding="utf-8"))
        assert again["hooks"] == doc["hooks"] and again["flags"] == doc["flags"], again
    print("PASS seam a install writes this machine's ledger with the listed fields")


if __name__ == "__main__":
    seam_a_install_writes_ledger()
