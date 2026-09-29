"""`tw.py outcome` labels a guarded dispatch accepted/rejected, keyed by the tool_use_id the coordinator sees
(background notifications carry <tool-use-id>; subagent meta.json maps agentId -> toolUseId).
Run: python test_tw_outcome.py"""
import json
import os
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

    # R2 (Astra review finding 2): only a dispatch that ran is labeled or has its TW-Check run. A gate-denied
    # dispatch, a router-advised one (denied at the hook), and a codex-exec dispatch without a cost row (codex never
    # ran) exit 2, run nothing and write nothing.
    import tw
    from test_tw_check import brief, dispatch
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        work = Path(home) / "work"
        work.mkdir()
        marker = work / "marker.txt"
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "model": "haiku",
                                       "prompt": brief("echo review-marker > marker.txt")}, "t_deny", cwd=str(work))
        assert [r["decision"] for r in receipts(home, "claude") if r["kind"] == "dispatch"] == ["deny"]
        # advised: advisory mode, explore 1.0, no backends -> a high dispatch is advised to medium (denied)
        doc = json.loads(Path(os.environ["TW_ROUTES"]).read_text(encoding="utf-8"))
        doc["router"] = {**doc["router"], "backends": [], "classes": {"*": {"mode": "advisory", "explore": 1.0}}}
        adv = Path(home) / "advisory.json"
        adv.write_text(json.dumps(doc), encoding="utf-8")
        old, os.environ["TW_ROUTES"] = os.environ["TW_ROUTES"], str(adv)
        try:
            out = dispatch(home, brief("echo review-marker > marker.txt"), str(work), "t_adv")[1]
        finally:
            os.environ["TW_ROUTES"] = old
        assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny", out
        assert [r["action"] for r in receipts(home, "claude") if r["kind"] == "route"] == ["advise"]
        # codex-exec dispatch row, admitted, but no cost row: codex never ran
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "codex-0", "decision":
                                                          "admit", "tool_name": "codex", "check":
                                                          "echo review-marker > marker.txt", "cwd": str(work)})
        n = len(receipts(home, "claude"))
        for tid in ("t_deny", "t_adv", "codex-0"):
            for extra in ([], ["--accepted", "yes"]):
                code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                                    "--tool-use-id", tid, *extra])
                assert code == 2, (tid, extra, code)
                assert not marker.exists(), f"{tid}: the TW-Check of a dispatch that never ran was executed"
                assert len(receipts(home, "claude")) == n, (tid, extra, receipts(home, "claude")[n:])
        # the same codex dispatch once it has a cost row: labeled, check runs
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "cost", "tool_use_id": "codex-0",
                                                          "via": "codex-exec", "exit_code": 0})
        code, out = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                              "--tool-use-id", "codex-0"])
        assert code == 0 and "pass" in out and marker.exists(), (code, out)
    print("PASS R2 outcome refuses denied, advised, and never-run codex dispatches (exit 2, no check, no rows)")
