#!/usr/bin/env python3
"""thinker-worker command line; the implementation is tw_core.py.

The PreToolUse hook runs this file on every native Agent call, in every session. Python compiles a __main__ script
on each start but caches an imported module's bytecode, so this file stays small and imports tw_core. A hook call
that tw_core.hook would answer with nothing (a tool it does not guard, or a session with no activation record)
exits here without importing tw_core.
"""

import hashlib
import io
import json
import os
import sys

# Copies of tw_core's, kept out of an import on the fast path; test_tw_launcher checks they match
OWNER = "thinker-worker-v1"
GUARDED_TOOLS = {"codex": {"spawn_agent", "collaborationspawn_agent", "Agent"}, "claude": {"Agent"}}


def record_path(home: str, harness: str, session: str) -> str:
    """tw_core.record_path, for main()'s resolved --home."""
    return os.path.join(os.path.realpath(os.path.expanduser(home)), ".thinker-worker", "state", harness,
                        hashlib.sha256(session.encode("utf-8")).hexdigest() + ".json")


def inactive(argv: list[str], payload: bytes) -> bool:
    """True only where tw_core.hook returns without output or a write. Anything else, including any argv other
    than the exact form hook_entry and the portable commands write, goes to tw_core."""
    if len(argv) != 7 or argv[0] != "hook" or argv[1::2] != ["--home", "--harness", "--owner"]:
        return False
    home, harness, owner = argv[2], argv[4], argv[6]
    if owner != OWNER or harness not in GUARDED_TOOLS:
        return False
    envelope = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(envelope, dict):
        return False
    if envelope.get("tool_name") not in GUARDED_TOOLS[harness]:
        return True
    session = envelope.get("session_id")
    if not isinstance(session, str) or not session or len(session) > 256 or any(c in session for c in "\r\n\0"):
        return False
    return not os.path.exists(record_path(home, harness, session))


def main() -> int:
    if sys.argv[1:2] == ["hook"]:
        try:  # on any failure tw_core decides, and fails closed
            payload = sys.stdin.buffer.read()
            sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")  # tw_core.hook reads the same bytes
            if inactive(sys.argv[1:], payload):
                return 0
        except Exception:
            pass
    import tw_core
    return tw_core.main()


if __name__ == "__main__":
    raise SystemExit(main())
