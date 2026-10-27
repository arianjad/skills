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
import sys
from pathlib import Path

OWNER = "thinker-worker-v1"  # tw_core.OWNER (test_tw_launcher checks they match)


def inactive(argv: list[str], payload: bytes) -> bool:
    """True only where tw_core.hook returns without output or a write. Anything else, including any argv other
    than the exact form hook_entry and the portable commands write, goes to tw_core."""
    if len(argv) != 7 or argv[0] != "hook" or argv[1::2] != ["--home", "--harness", "--owner"]:
        return False
    home, harness, owner = argv[2], argv[4], argv[6]
    if owner != OWNER or harness not in ("codex", "claude"):
        return False
    envelope = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(envelope, dict):
        return False
    if envelope.get("tool_name") not in ({"spawn_agent", "collaborationspawn_agent", "Agent"} if harness == "codex"
                                         else {"Agent"}):
        return True
    session = envelope.get("session_id")
    if not isinstance(session, str) or not session or len(session) > 256 or any(c in session for c in "\r\n\0"):
        return False
    # tw_core.record_path
    record = (Path(home).expanduser().resolve() / ".thinker-worker" / "state" / harness /
              f"{hashlib.sha256(session.encode('utf-8')).hexdigest()}.json")
    return not record.exists()


def main() -> int:
    if sys.argv[1:2] == ["hook"]:
        try:
            payload = sys.stdin.buffer.read()
        except Exception:
            payload = None  # tw_core reads stdin itself and fails closed
        if payload is not None:
            try:
                if inactive(sys.argv[1:], payload):
                    return 0
            except Exception:
                pass  # malformed input: tw_core decides (it denies)
            sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")  # tw_core.hook reads the same bytes
    import tw_core
    return tw_core.main()


if __name__ == "__main__":
    raise SystemExit(main())
