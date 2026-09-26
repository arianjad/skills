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


def seam_b_machines_flags_stale():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as led:
        a, b, led = Path(a), Path(b), Path(led)
        assert run_tw("pc-a", "install", "--portable", "--harness", "claude", "--python-cmd", "python3",
                      "--home", str(a), "--ledger-dir", str(led)).returncode == 0
        assert run_tw("pc-b", "install", "--home", str(b), "--ledger-dir", str(led)).returncode == 0
        # pc-a ran an older tw.py: different sha, older timestamp.
        path = led / "pc-a.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.update(tw_sha256="0" * 64, updated_at="2026-01-01T00:00:00+00:00")
        path.write_text(json.dumps(doc), encoding="utf-8")
        before = sorted((p.name, p.read_bytes()) for p in led.iterdir())
        r = run_tw("pc-b", "machines", "--home", str(b), "--ledger-dir", str(led))
        assert r.returncode == 0, r.stderr
        lines = {l.split()[1] if l.startswith("*") else l.split()[0]: l for l in r.stdout.splitlines() if l.strip()}
        assert set(lines) == {"pc-a", "pc-b"}, r.stdout
        assert lines["pc-b"].startswith("*") and not lines["pc-a"].startswith("*"), r.stdout
        assert "STALE" not in lines["pc-b"], r.stdout
        want = ("python thinker-worker/scripts/tw.py uninstall && "
                "python thinker-worker/scripts/tw.py install --portable --harness claude --python-cmd python3")
        assert "STALE" in lines["pc-a"] and lines["pc-a"].endswith(want), r.stdout
        assert sorted((p.name, p.read_bytes()) for p in led.iterdir()) == before, "machines must be read-only"
        print(r.stdout)
    print("PASS seam b machines marks this machine and flags the stale one with its own install command")


def seam_c_uninstall_keeps_entry_claimed_by_other_machine():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as led:
        a, b, led = Path(a), Path(b), Path(led)
        flags = ("install", "--portable", "--harness", "claude", "--ledger-dir", str(led))
        def status(m):
            return json.loads((led / f"{m}.json").read_text(encoding="utf-8"))["status"]
        assert run_tw("pc-a", *flags, "--home", str(a)).returncode == 0
        [entry] = owned(a / ".claude" / "settings.json")
        (b / ".claude").mkdir()  # only ~/.claude travels between machines
        (b / ".claude" / "settings.json").write_bytes((a / ".claude" / "settings.json").read_bytes())
        assert run_tw("pc-b", *flags, "--home", str(b)).returncode == 0
        # B uninstalls while A's ledger says installed: the shared entry stays, naming pc-a.
        r = run_tw("pc-b", "uninstall", "--home", str(b))
        assert r.returncode == 0, r.stderr
        assert owned(b / ".claude" / "settings.json") == [entry] and "pc-a" in r.stdout, r.stdout
        assert status("pc-b") == "uninstalled" and status("pc-a") == "installed"
        assert not (b / ".claude" / "skills" / "thinker-worker").exists()
        # Symmetric: A uninstalls while B (reinstalled, adopting) claims it: A keeps it too.
        assert run_tw("pc-b", *flags, "--home", str(b)).returncode == 0
        r = run_tw("pc-a", "uninstall", "--home", str(a))
        assert r.returncode == 0, r.stderr
        assert owned(a / ".claude" / "settings.json") == [entry] and "pc-b" in r.stdout, r.stdout
        assert status("pc-a") == "uninstalled"
        # No other machine claims it now: B's uninstall removes it.
        r = run_tw("pc-b", "uninstall", "--home", str(b))
        assert r.returncode == 0, r.stderr
        assert owned(b / ".claude" / "settings.json") == [], r.stdout
        assert status("pc-b") == "uninstalled"
    print("PASS seam c uninstall keeps an entry another installed machine claims, removes it otherwise")


if __name__ == "__main__":
    seam_a_install_writes_ledger()
    seam_b_machines_flags_stale()
    seam_c_uninstall_keeps_entry_claimed_by_other_machine()
