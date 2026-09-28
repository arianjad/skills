"""Settle: race check at dispatch (meta agentType vs router_agent, or context-mode's block) writes one race
row per rewrite and flips the session to advisory on a loss; outcome writes one cost row summing the last
usage row per message.id. meta.json's agentType is the sole criterion when present; the block text decides only
without it. outcome runs the race check first. A torn sibling meta or transcript line is skipped; an unreadable
transcript yields a race-error row and the dispatch is still decided; a torn receipts line is skipped by readers
and does not swallow the next appended row.
Run: python test_tw_settle.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import W_MIN, pinned_routes, run_main
from test_tw_receipt import SESSION, hook, receipts


def child(home, agent_type, block, meta_text=None, torn=False, sibling=None, advisor=False, ran=None, offered=()):
    sub = Path(home) / ".claude" / "projects" / "p" / SESSION / "subagents"
    sub.mkdir(parents=True)
    prompt = "TW-Role: worker\n..." + ("\n<context_window_protection>x</context_window_protection>" if block else "")
    rows = [{"type": "user", "message": {"content": prompt}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 5}}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 40}}},
            {"type": "assistant", "message": {"id": "m2", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100,
                                                                    "output_tokens": 7}}}]
    if advisor:  # one advisor call streamed over two rows (same block id); its tokens only in usage.iterations
        rows += [
            {"type": "assistant", "message": {"id": "m3", "content": [
                {"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}}],
                "usage": {"input_tokens": 1, "output_tokens": 2}}},
            {"type": "assistant", "message": {"id": "m3", "content": [
                {"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}},
                {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_1",
                 "content": {"type": "advisor_redacted_result"}}],
                "usage": {"input_tokens": 1, "output_tokens": 3, "iterations": [
                    {"type": "message", "input_tokens": 1, "output_tokens": 1},
                    {"type": "advisor_message", "model": "claude-fable-5-1", "input_tokens": 900,
                     "output_tokens": 50}]}}}]
    if ran:  # the model that ran, on every assistant row; then an error stub, which names no model
        for r in rows[1:]:
            r["message"]["model"] = ran
        rows.append({"type": "assistant", "message": {"id": "m9", "model": "<synthetic>",
                                                      "usage": {"input_tokens": 0, "output_tokens": 0}}})
    rows += [{"type": "attachment", "attachment": {"type": "advisor_tool", "available": a,
                                                   "model": "claude-fable-5-1"}} for a in offered]
    lines =['{"type": "user", "mess'] * torn + [json.dumps(r) for r in rows]
    (sub / "agent-a1.jsonl").write_text("\n".join(lines), encoding="utf-8")
    meta = {"toolUseId": "toolu_x", "model": "opus", **({"agentType": agent_type} if agent_type else {})}
    (sub / "agent-a1.meta.json").write_text(meta_text or json.dumps(meta), encoding="utf-8")
    if sibling is not None:  # another child's meta, sorted first by glob
        (sub / "agent-a0.meta.json").write_text(sibling, encoding="utf-8")
    return str(Path(home) / ".claude" / "projects" / "p" / f"{SESSION}.jsonl")


def race(agent_type, block, action="rewrite", **kw):
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                          "action": action, "router_agent": "tw-worker-low"})
        tp = child(home, agent_type, block, **kw)
        tw.race_check(Path(home), "claude", SESSION, tp)
        tw.race_check(Path(home), "claude", SESSION, tp)          # idempotent: one race row per rewrite
        rows = [r for r in receipts(home, "claude") if r["kind"] == "race"]
        flag = tw.advisory_flag(Path(home), "claude", SESSION).exists()
        return (len(rows), rows[0]["lost"] if rows else None, flag)


def dispatch(home, tp):
    return hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": W_MIN}, "toolu_new",
                transcript_path=tp)


if __name__ == "__main__":
    pin = pinned_routes()  # shipped routing mode pinned out for the whole run
    pin.__enter__()
    assert race("tw-worker-low", False) == (1, False, False)
    assert race("tw-worker-high", False) == (1, True, True)     # context-mode's full replacement won
    assert race("tw-worker-low", True) == (1, False, False)     # agentType is the sole criterion when present
    assert race(None, True) == (1, True, True)                  # meta without agentType: the block text decides
    assert race(None, False) == (1, False, False)
    assert race(None, True, torn=True) == (1, True, True)       # a torn transcript line is skipped, not an error
    assert race("tw-worker-low", False, sibling="{not json") == (1, False, False)   # torn sibling meta skipped
    assert race("tw-worker-high", False, action=None) == (0, None, False)
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x",
                                                          "decision": "admit"})  # outcome needs a dispatch that ran
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-worker-high", False, sibling="{not json", offered=(False,))
        for verdict in ("yes", "no"):
            code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                                "--tool-use-id", "toolu_x", "--accepted", verdict])
            assert code == 0
        cost = [r for r in receipts(home, "claude") if r["kind"] == "cost"]
        assert len(cost) == 1, cost
        c = cost[0]
        assert (c["api_calls"], c["output_tokens"], c["input_tokens"], c["cache_read_input_tokens"],
                c["agent_type"]) == (2, 47, 3, 100, "tw-worker-high"), c
        assert (c["advisor_calls"], c["advisor_model"]) == (0, None), c           # the existing child has no advisor
        assert (c["model"], c["advisor_available"]) == ("opus", False), c   # no message.model: meta's; a removal is no offer
    with tempfile.TemporaryDirectory() as home:          # the model that ran comes from the transcript, not meta.json
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x",
                                                          "decision": "admit"})  # outcome needs a dispatch that ran
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-ideation-high", False, ran="claude-opus-5-5", offered=(True, False))
        assert run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                         "--tool-use-id", "toolu_x", "--accepted", "yes"])[0] == 0
        c = [r for r in receipts(home, "claude") if r["kind"] == "cost"][0]
        assert (c["model"], c["advisor_available"]) == ("claude-opus-5-5", True), c   # offered, later removed: True
    with tempfile.TemporaryDirectory() as home:          # a <synthetic> error stub is not an API call
        sub = Path(home) / ".claude" / "projects" / "p" / SESSION / "subagents"
        sub.mkdir(parents=True)
        stub = [{"type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5",
                                                  "usage": {"input_tokens": 3, "output_tokens": 9}}},
                {"type": "assistant", "message": {"id": "m9", "model": "<synthetic>",
                                                  "usage": {"input_tokens": 0, "output_tokens": 0}}}]
        (sub / "agent-a1.jsonl").write_text("\n".join(map(json.dumps, stub)), encoding="utf-8")
        (sub / "agent-a1.meta.json").write_text(json.dumps({"toolUseId": "toolu_x"}), encoding="utf-8")
        c = tw.cost_row(Path(home), "claude", SESSION, "toolu_x")
        assert (c["api_calls"], c["input_tokens"], c["output_tokens"]) == (1, 3, 9), c
    with tempfile.TemporaryDirectory() as home:          # an advisor call is counted once, tokens from iterations
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x",
                                                          "decision": "admit"})  # outcome needs a dispatch that ran
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-worker-high", False, advisor=True)
        assert run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                         "--tool-use-id", "toolu_x", "--accepted", "yes"])[0] == 0
        c = [r for r in receipts(home, "claude") if r["kind"] == "cost"][0]
        assert (c["advisor_calls"], c["advisor_model"], c["advisor_input_tokens"], c["advisor_output_tokens"]) \
            == (1, "claude-fable-5-1", 900, 50), c
        assert c["output_tokens"] == 50, c                               # top-level counts unchanged: 40 + 7 + 3
    with tempfile.TemporaryDirectory() as home:          # outcome verifies the last rewrite before labeling it
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x",
                                                          "decision": "admit"})  # outcome needs a dispatch that ran
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                          "action": "rewrite", "router_agent": "tw-worker-low"})
        child(home, "tw-worker-high", False)
        code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                            "--tool-use-id", "toolu_x", "--accepted", "yes"])
        rows = receipts(home, "claude")
        assert code == 0 and [r["lost"] for r in rows if r["kind"] == "race"] == [True], rows
        assert tw.advisory_flag(Path(home), "claude", SESSION).exists()
    with tempfile.TemporaryDirectory() as home:          # unreadable child transcript: race-error row, dispatch decided
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                          "action": "rewrite", "router_agent": "tw-worker-low"})
        tp = child(home, None, False)
        transcript = Path(tp).with_suffix("") / "subagents" / "agent-a1.jsonl"
        transcript.unlink()
        transcript.mkdir()
        code, out = dispatch(home, tp)
        rows = receipts(home, "claude")
        assert code == 0 and out == "", (code, out)
        assert [r["kind"] for r in rows if r["kind"].startswith("race")] == ["race-error"], rows
        assert [r["decision"] for r in rows if r["kind"] == "dispatch"] == ["admit"], rows
        assert not tw.advisory_flag(Path(home), "claude", SESSION).exists()
    with tempfile.TemporaryDirectory() as home:          # torn last line (concurrent hook): readers skip it
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "dispatch", "tool_use_id": "toolu_x",
                                                          "decision": "admit"})
        path = tw.receipts_path(Path(home), "claude", SESSION)
        with path.open("ab") as s:
            s.write(b'{"kind": "route", "tool_use_id": "toolu_x", "act')
        code, _ = run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                            "--tool-use-id", "toolu_x", "--accepted", "yes"])
        assert code == 0
        rows = tw.read_rows(path)
        assert [r["kind"] for r in rows] == ["dispatch", "outcome"], rows    # the row after the torn line parses
        assert tw.prior_route(Path(home), "claude", SESSION, "abc") is None
    print("PASS settle: race row per rewrite (agentType, else block), advisory flag on loss, torn sibling meta and "
          "transcript line skipped, race check at outcome, one cost row at outcome, unreadable transcript -> "
          "race-error + admit, torn receipts line skipped")
