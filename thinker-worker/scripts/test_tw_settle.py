"""Settle: race check at dispatch (meta agentType vs router_agent, or context-mode's block) writes one race
row per rewrite and flips the session to advisory on a loss; outcome writes one cost row summing the last
usage row per message.id. A corrupt meta.json yields a race-error row and the dispatch is still decided; a
torn receipts line is skipped by readers and does not swallow the next appended row.
Run: python test_tw_settle.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import SESSION, receipts


def child(home, agent_type, block, meta_text=None):
    sub = Path(home) / ".claude" / "projects" / "p" / SESSION / "subagents"
    sub.mkdir(parents=True)
    prompt = "TW-Role: worker\n..." + ("\n<context_window_protection>x</context_window_protection>" if block else "")
    rows = [{"type": "user", "message": {"content": prompt}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 5}}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 40}}},
            {"type": "assistant", "message": {"id": "m2", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100,
                                                                    "output_tokens": 7}}}]
    (sub / "agent-a1.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (sub / "agent-a1.meta.json").write_text(meta_text or json.dumps({"toolUseId": "toolu_x", "agentType": agent_type,
                                                                     "model": "opus"}), encoding="utf-8")
    return str(Path(home) / ".claude" / "projects" / "p" / f"{SESSION}.jsonl")


def race(agent_type, block, action="rewrite"):
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                          "action": action, "router_agent": "tw-worker-low"})
        tp = child(home, agent_type, block)
        tw.race_check(Path(home), "claude", SESSION, tp)
        tw.race_check(Path(home), "claude", SESSION, tp)          # idempotent: one race row per rewrite
        rows = [r for r in receipts(home, "claude") if r["kind"] == "race"]
        flag = tw.advisory_flag(Path(home), "claude", SESSION).exists()
        return (len(rows), rows[0]["lost"] if rows else None, flag)


def dispatch(home, tp):
    env = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION, "tool_use_id": "toolu_new",
           "transcript_path": tp,
           "tool_input": {"subagent_type": "tw-worker-high",
                          "prompt": "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: d\nTW-Accept: a\n"
                                    "TW-Risk: none\nx"}}
    return run_main(["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))


if __name__ == "__main__":
    assert race("tw-worker-low", False) == (1, False, False)
    assert race("tw-worker-high", False) == (1, True, True)     # context-mode's full replacement won
    assert race("tw-worker-low", True) == (1, True, True)       # block text alone also counts
    assert race("tw-worker-high", False, action=None) == (0, None, False)
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-worker-high", False)
        for verdict in ("yes", "no"):
            code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                                "--tool-use-id", "toolu_x", "--accepted", verdict])
            assert code == 0
        cost = [r for r in receipts(home, "claude") if r["kind"] == "cost"]
        assert len(cost) == 1, cost
        c = cost[0]
        assert (c["api_calls"], c["output_tokens"], c["input_tokens"], c["cache_read_input_tokens"],
                c["agent_type"]) == (2, 47, 3, 100, "tw-worker-high"), c
    with tempfile.TemporaryDirectory() as home:          # corrupt meta.json: race-error row, dispatch still decided
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                          "action": "rewrite", "router_agent": "tw-worker-low"})
        tp = child(home, "tw-worker-low", False, meta_text="{not json")
        code, out = dispatch(home, tp)
        rows = receipts(home, "claude")
        assert code == 0 and out == "", (code, out)
        assert [r["kind"] for r in rows if r["kind"].startswith("race")] == ["race-error"], rows
        assert [r["decision"] for r in rows if r["kind"] == "dispatch"] == ["admit"], rows
        assert not tw.advisory_flag(Path(home), "claude", SESSION).exists()
    with tempfile.TemporaryDirectory() as home:          # torn last line (concurrent hook): readers skip it
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x"})
        path = tw.receipts_path(Path(home), "claude", SESSION)
        with path.open("ab") as s:
            s.write(b'{"kind": "route", "tool_use_id": "toolu_x", "act')
        code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                            "--tool-use-id", "toolu_x", "--accepted", "yes"])
        assert code == 0
        rows = tw.read_rows(path)
        assert [r["kind"] for r in rows] == ["dispatch", "outcome"], rows    # the row after the torn line parses
        assert tw.prior_route(Path(home), "claude", SESSION, "abc") is None
    print("PASS settle: race row per rewrite (agentType or block), advisory flag on loss, one cost row at outcome, "
          "corrupt meta -> race-error + admit, torn line skipped")
