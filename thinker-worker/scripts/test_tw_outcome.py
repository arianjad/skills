"""`tw.py outcome` labels a guarded dispatch accepted/rejected, keyed by the tool_use_id the coordinator sees
(background notifications carry <tool-use-id>; subagent meta.json maps agentId -> toolUseId).
Run: python test_tw_outcome.py"""
import json
import tempfile
from pathlib import Path

from test_tw_hook import pinned_routes, run_main
from test_tw_receipt import HDR, SESSION, hook, receipts


def outcome(home, tool_use_id, accepted, cause=None):
    args = ["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
            "--tool-use-id", tool_use_id, "--accepted", accepted]
    return run_main(args + (["--cause", cause] if cause else []))[0]


if __name__ == "__main__":
    pin = pinned_routes()  # shipped routing mode pinned out for the whole run
    pin.__enter__()
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high",
                                       "prompt": "TW-Role: worker\n" + HDR + "x"})
        assert outcome(home, "toolu_x", "no") == 0
        last = receipts(home, "claude")[-1]
        assert last["kind"] == "outcome" and last["tool_use_id"] == "toolu_x" and last["accepted"] is False, last
        assert outcome(home, "toolu_x", "yes") == 0  # a later verdict supersedes; readers take the last
        assert receipts(home, "claude")[-1]["accepted"] is True
        n = len(receipts(home, "claude"))
        assert outcome(home, "toolu_unknown", "yes") != 0   # no orphan labels
        assert len(receipts(home, "claude")) == n
    with tempfile.TemporaryDirectory() as home:          # no receipts at all for this session
        assert outcome(home, "toolu_x", "yes") != 0
        assert not list(Path(home).rglob("*.jsonl"))
    with tempfile.TemporaryDirectory() as home:          # cause: why a rejection happened (design §5 censoring)
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high",
                                       "prompt": "TW-Role: worker\n" + HDR + "x"})
        assert outcome(home, "toolu_x", "no", "tier") == 0
        assert receipts(home, "claude")[-1]["cause"] == "tier"
        assert outcome(home, "toolu_x", "yes") == 0 and receipts(home, "claude")[-1]["cause"] is None
        n = len(receipts(home, "claude"))
        assert outcome(home, "toolu_x", "yes", "tier") != 0      # a cause only explains a rejection
        assert outcome(home, "toolu_x", "no", "vibes") != 0      # closed vocabulary
        assert len(receipts(home, "claude")) == n
    print("PASS outcome appends kind=outcome for a known dispatch; unknown ids refused")
