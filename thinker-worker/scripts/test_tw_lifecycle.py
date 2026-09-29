"""Lifecycle conflicts preserve user edits and rejected activation stays inactive.
Run: python test_tw_lifecycle.py. All mutations use disposable homes; no model calls.
"""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import tw


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def refused(fn, *args):
    try:
        quiet(fn, *args)
    except tw.Conflict:
        return
    raise AssertionError("expected Conflict")


def older(home, rel, data=b"older release\n"):
    path = home / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    manifest = tw.load_manifest(home)
    manifest["files"][rel] = manifest["source"][rel] = tw.sha(path.read_bytes())
    tw.manifest_path(home).write_bytes(tw.canonical_json(manifest))
    return path


def upgrade_conflicts(scenarios=("replace", "remove", "manifest", "directory", "parent-file")):
    for scenario in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            quiet(tw.install, home, Path(sys.executable), harnesses=("codex",))
            rel = ".codex/skills/thinker-worker/SKILL.md"
            target = older(home, rel)
            if scenario == "remove":
                target = older(home, ".codex/skills/thinker-worker/retired.md", b"older retired file\n")
            target_before = target.read_bytes()
            before = tw.manifest_path(home).read_bytes()
            if scenario in ("directory", "parent-file"):
                blocked = home / ".codex/skills/thinker-worker/scripts"
                if scenario == "directory":
                    blocked = blocked / "tw.py"
                    blocked.unlink()
                    blocked.mkdir()
                else:
                    (blocked / "tw.py").unlink()
                    blocked.rmdir()
                    blocked.write_bytes(b"user file\n")
                refused(tw.upgrade, home)
                assert target.read_bytes() == b"older release\n", "preflight must precede every write"
                assert tw.manifest_path(home).read_bytes() == before
            elif scenario == "manifest":
                original_now = tw.now
                edited = None
                def concurrent_manifest():
                    nonlocal edited
                    manifest = tw.load_manifest(home)
                    manifest["user_note"] = "concurrent edit"
                    edited = tw.canonical_json(manifest)
                    tw.manifest_path(home).write_bytes(edited)
                    return original_now()
                with patch.object(tw, "now", concurrent_manifest):
                    refused(tw.upgrade, home)
                assert tw.manifest_path(home).read_bytes() == edited, "manifest edit must survive"
            else:
                original_sha = tw.sha
                edited = False
                def concurrent_edit(data):
                    nonlocal edited
                    if data == target_before and not edited:
                        edited = True
                        target.write_bytes(b"user edit after snapshot\n")
                    return original_sha(data)
                with patch.object(tw, "sha", concurrent_edit):
                    refused(tw.upgrade, home)
                assert edited and target.read_bytes() == b"user edit after snapshot\n"
                assert tw.manifest_path(home).read_bytes() == before
            print(f"PASS upgrade conflict: {scenario}")


def rejected_activation():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        routes = home / "invalid-routes.json"
        routes.write_text("{}", encoding="utf-8")
        active = tw.record_path(home, "codex", "active")
        active.parent.mkdir(parents=True)
        prior = tw.canonical_json({"schema": 1, "harness": "codex", "session_id": "active",
                                   "store_bodies": True, "activated_at": "earlier"})
        active.write_bytes(prior)
        with patch.dict(os.environ, {"TW_ROUTES": str(routes)}):
            for session in ("inactive", "active"):
                refused(tw.activate, home, "codex", session)
        assert not tw.record_path(home, "codex", "inactive").exists()
        assert active.read_bytes() == prior
    print("PASS activation: invalid routes preserve inactive and existing session state")


if __name__ == "__main__":
    upgrade_conflicts()
    rejected_activation()
