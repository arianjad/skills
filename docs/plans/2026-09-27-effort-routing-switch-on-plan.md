# Effort routing switch-on (advisory + exploration one tier below) — implementation plan

**Goal:** the five-session run starts with the router on: every class in `advisory` with `explore: 0.2`,
exploration one tier below the coordinator's tier with no backend and no table, per-flag risk floors, and
outcome labels that say whether a rejection was the tier's fault, so the run produces tier labels (design §5
Stage 2).

**Approach:** six TDD tasks in `thinker-worker` (1, 1b, 1c, 2, 3, 4) (red test first, then the code, then the full suite), a
Fable review gate, then a reinstall and live check that needs Arian's OK at that moment, then the launch
prompts. `backends` stays `[]`: when no backend answers, `route()` itself picks the next tier below the
coordinator's for a fraction ε of tickets (`source: "explore"`), and `act()` advises it.

**Design:** `docs/plans/2026-09-26-effort-routing-architecture-design.md` §5 (Stages 1–4, censoring, Stage 2
one tier below, risk floor, cost side) and §7 decision 7 (default tiers, `risk_floor` values). Advisory with
exploration for the five-session run, ε = 0.2, exploration one tier below without a table: Arian, 2026-09-27.

**Constraints:**
- Python: `C:/Users/Arian/anaconda3/envs/claude-code/python.exe` (`$PY`); stdlib only; tests are plain
  scripts run from `thinker-worker/scripts/` (`"$PY" test_tw_<x>.py`), no pytest.
- TDD per task: add or change the test first, run it and paste the failing message, then implement, then the
  full suite. A red run may fail with a TypeError (e.g. `out[...]` on a `None` hook output), a KeyError on a
  row field not yet written, or argparse's exit (T1: `unrecognized arguments: --cause tier`) rather than an
  AssertionError; paste whichever it is. Full suite: `cd thinker-worker/scripts && for f in test_tw_*.py; do "$PY" "$f" >/dev/null 2>&1 || echo "FAIL $f"; done; echo SUITE_DONE`
  (expected: only `SUITE_DONE`).
- Real `~/.claude`, `~/.codex`, `~/.thinker-worker` are untouched until Task 6. No push. No `rm -rf` on
  computed paths. Commit by pathspec, message ends with the attribution line.
- Checkpoint: one line per task in `thinker-worker/ROUTING-PROGRESS.md` (new "Switch-on" section).
- `routes.json` is installer-owned: it changes only here in the source tree and reaches the real install only
  through Task 6. `router.table` stays in the file, inert while `backends` is `[]`.
- Exploration applies to Codex sessions too (`router.classes` is not per harness); an activated Codex
  session gets the same advisory denials with a `reasoning_effort=` hint (accepted, Arian 2026-09-27).
- Status: executing (Arian, 2026-09-27: "1 and 2"). One Opus worker per task, sequential; progress in
  `thinker-worker/ROUTING-PROGRESS.md` "Switch-on". Task 6 still needs Arian's OK at that moment.

## File map

- Modify `thinker-worker/scripts/tw.py`:
  - `outcome()` (~L335), the `outcome` parser (~L1275) and `main` (~L1311): optional `--cause`, validated in
    `main` against `tier|brief|other`, only with `--accepted no`; recorded as `cause` (null when absent). (Task 1)
  - `cost_row()` (~L422) and `promote()` (~L437): advisor-call detection and exclusion. (Task 1b)
  - `decide()` per-call model denial text (~L273), `cost_row()` `model` from the child transcript plus
    `advisor_available`, and the hook's route row (~L764) `agent_model`. (Task 1c)
  - `route()` (L518–557): backend-free exploration one tier below the coordinator; the hook's route row
    (~L762) records `explore`. (Task 2)
  - `load_routes()` (L59–78): validate `router.risk_floor`. (Task 3)
  - `act()` (L668–708): per-flag floor replaces "never the role's cheapest tier" and returns the floored
    target; the hook's route row records `target_tier` and derives `router_agent` from it; `promote()`
    compares the floored target. (Task 3)
- Modify `thinker-worker/routes.json`: the Opus ids in Claude `ideation.models` (Task 1c); `risk_floor`
  (Task 3); `"*"` → advisory, explore 0.2 (Task 4).
- Modify tests: `test_tw_outcome.py` (1), `test_tw_settle.py` (1b, 1c), `test_tw_promote.py` (1b, 3),
  `test_tw_route.py` (2, 4), `test_tw_act.py` (2, 3), `test_tw_routes.py` (1c, 3), `test_tw_receipt.py` (1c).
- Modify docs: `thinker-worker/SKILL.md`, `references/claude.md`, `references/codex.md`, `README.md`
  thinker-worker section (Task 4; it also lands Task 1c's per-call `model` rule).
- Outside the repo (Task 7, coordinator): `~/.claude/handoffs/2026-09-26-launch-five-project-sessions.md` and
  the five `C:\Users\Arian\Desktop\handoffs\*-prompt.md` contract blocks.

## Tasks

### Task 1: tier-attributed rejection label

Files: `tw.py` (`outcome`, parser, `main` call site ~L1311), `test_tw_outcome.py`.
Interfaces: `outcome(home, harness, session, tool_use_id, accepted: bool, cause: str | None = None)`; the
outcome row gains `"cause": None | "tier" | "brief" | "other"`. Consumed by Stage 3 scoring (phase 2) and
the launch contract (Task 7).

Red test. Replace the `outcome` helper in `test_tw_outcome.py`:

```python
def outcome(home, tool_use_id, accepted, cause=None):
    args = ["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
            "--tool-use-id", tool_use_id, "--accepted", accepted]
    return run_main(args + (["--cause", cause] if cause else []))[0]
```

and append inside `if __name__ == "__main__":`, before the final `print`:

```python
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
```

Code:

```python
# parser, next to --accepted. No argparse `choices`: argparse's SystemExit(2) escapes run_main (it catches
# nothing), so the closed vocabulary is checked in main, where a Conflict returns 2.
p.add_argument("--cause")
# main, outcome branch, before the outcome() call so a refusal writes nothing
if args.cause is not None and args.cause not in ("tier", "brief", "other"):
    raise Conflict(f"--cause must be tier, brief or other, not {args.cause!r}")
if args.cause and args.accepted == "yes":
    raise Conflict("--cause explains a rejection; use it only with --accepted no")
outcome(home, args.harness, session_value(args.session), args.tool_use_id, args.accepted == "yes", args.cause)
# outcome(): signature gains cause=None; the appended row gains "cause": cause
```

`main`'s handler returns 2 on `Conflict` (tw.py L1328–1330), so both refusals exit nonzero, before any row
is appended.

Check: `"$PY" test_tw_outcome.py` → `PASS outcome …`; then the full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_outcome.py && git commit -m "tw: outcome --cause tier|brief|other labels why a rejection happened (switch-on T1)" -- <same paths>`

### Task 1b: detect advisor use per dispatch and keep it out of promotion

Why: the Claude Code advisor tool (a server-side Fable consult, vault
`03-decisions/2026-09-27-claude-code-advisor-tool-off.md`) reaches every subagent once `advisorModel` is set
or `/advisor` is used, and cannot be switched off per agent. A `tw-worker-low` that consulted Fable measures
"low + Fable", not `low`. It is off today (Arian, 2026-09-27); this task makes a silent re-enable visible.
In a transcript an advisor call is an assistant `content` block `{"type": "server_tool_use", "name":
"advisor", "id": …}`; its tokens appear only in `usage.iterations[]` entries with `type: "advisor_message"`
(and `model`), never in top-level `usage`. Subagent rows may lack `iterations` (seen in the 2026-09-27 haiku
probe), so the call count is the primary signal and the token fields are best effort.

Files: `tw.py` (`cost_row` ~L422, `promote` ~L437), `test_tw_settle.py`, `test_tw_promote.py`.
Interfaces: the cost row gains `advisor_calls: int` (distinct advisor block ids), `advisor_model: str | None`,
`advisor_input_tokens: int`, `advisor_output_tokens: int`. `promote()` skips any route row whose
`tool_use_id` has a cost row with `advisor_calls > 0`, in both arms, and returns `n_advisor_excluded`.

Red tests. In `test_tw_settle.py`, give `child()` an `advisor=False` parameter that, when true, appends

```python
{"type": "assistant", "message": {"id": "m3", "content": [
    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}}],
    "usage": {"input_tokens": 1, "output_tokens": 2}}},
{"type": "assistant", "message": {"id": "m3", "content": [
    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}},
    {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_1", "content": {"type": "advisor_redacted_result"}}],
    "usage": {"input_tokens": 1, "output_tokens": 3, "iterations": [
        {"type": "message", "input_tokens": 1, "output_tokens": 1},
        {"type": "advisor_message", "model": "claude-fable-5-1", "input_tokens": 900, "output_tokens": 50}]}}}
```

(the same block id twice: one call, streamed over two rows), and add after the existing cost assertion:

```python
    assert (c["advisor_calls"], c["advisor_model"]) == (0, None), c           # the existing child has no advisor
    with tempfile.TemporaryDirectory() as home:          # an advisor call is counted once, tokens from iterations
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-worker-high", False, advisor=True)
        assert run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                         "--tool-use-id", "toolu_x", "--accepted", "yes"])[0] == 0
        c = [r for r in receipts(home, "claude") if r["kind"] == "cost"][0]
        assert (c["advisor_calls"], c["advisor_model"], c["advisor_input_tokens"], c["advisor_output_tokens"]) \
            == (1, "claude-fable-5-1", 900, 50), c
        assert c["output_tokens"] == 50, c                               # top-level counts unchanged: 40 + 7 + 3
```

In `test_tw_promote.py`, give `verdict()` an `advised=0` parameter that appends, for the first `advised`
router-arm rows, `{"kind": "cost", "tool_use_id": f"r{i}", "advisor_calls": 1}`, and assert:

```python
    v = verdict(9, advised=3)
    assert (v["n_router"], v["n_advisor_excluded"]) == (7, 3), v     # advisor-assisted rows leave the arm
```

Code, in `cost_row`, replacing the loop:

```python
    usage, advisor_ids = {}, set()
    for obj in read_rows(transcript):
        msg = obj.get("message") or {}
        if obj.get("type") != "assistant":
            continue
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "server_tool_use" and b.get("name") == "advisor":
                advisor_ids.add(b.get("id"))
        if msg.get("id") and msg.get("usage"):
            usage[msg["id"]] = msg["usage"]  # last row per message.id carries the final counts
    adv = [it for u in usage.values() for it in u.get("iterations") or [] if it.get("type") == "advisor_message"]
```

and in the returned dict add
`"advisor_calls": len(advisor_ids), "advisor_model": next((it.get("model") for it in adv), None),
"advisor_input_tokens": sum(it.get("input_tokens", 0) for it in adv),
"advisor_output_tokens": sum(it.get("output_tokens", 0) for it in adv)`.
In `promote`, after `race = …`:

```python
    advised_by = {r["tool_use_id"] for r in rows if r.get("kind") == "cost" and r.get("advisor_calls")}
```

at the top of the loop body `if r.get("tool_use_id") in advised_by: n_adv += 1; continue` (initialise
`n_adv = 0`), and `"n_advisor_excluded": n_adv` in the returned dict. Update `promote`'s docstring.

Check: `"$PY" test_tw_settle.py && "$PY" test_tw_promote.py` → both PASS lines; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_settle.py thinker-worker/scripts/test_tw_promote.py && git commit -m "tw: cost rows count advisor calls; promote excludes advisor-assisted dispatches (switch-on T1b)" -- <same paths>`

### Task 1c: record the model that ran; ideation may run on Opus

Why: ideation may run on Opus as well as Fable, with Fable the default (Arian, 2026-09-27); the mechanism is
the Fable review's (2026-09-27). Once a role admits two models, the receipts must say which one ran. Today the
cost row's `model` is meta.json's `model`, which tw-* children do not write (`agent-a9d90924aceef9171.meta.json`
in session `a14deb8e…` has only `agentType`, `description`, `toolUseId`, `spawnDepth`, `requestShape`,
`requestNonInteractive`), so it is `null` on every real row. The child transcript's assistant rows carry
`message.model`, the model that actually answered.

Per-call `model` rules (Fable recommendation, 2026-09-27):
- `model` on a Claude dispatch stays optional and absent by default; the generated agent file pins the role's
  default (`models[0]`). A coordinator passes `model` only to pick an allowed non-default model for the role;
  today that is `model: opus` on `tw-ideation-<tier>`. No new agent files.
- The gate's behavior is unchanged: a per-call model outside the role's `models` is denied, one inside is
  admitted. Only the denial text changes, from "per-call model <m> differs from the <role> agent's model" to
  `model <m> is not allowed for <role>`.
- Active rewrite: `act()` builds `updatedInput` as `{**inp, "subagent_type": pick}`, so a per-call `model`
  survives a tier rewrite. Intended: a tier change never changes the model. No code.
- Ticket, dispatch receipts and `promote` are unaffected: the ticket hashes the brief only, and dispatch rows
  already carry `requested_model`. `agent_model` on the route row is the request-time record; analyses group
  by the cost row's `model` (what ran).
- Review stays Fable-only for now (Arian, 2026-09-27).
- Verified: with no per-call model, the agent file's `model:` beats the coordinator's model. From an Opus 5.5
  coordinator, `tw-ideation-high` (agent file `model: fable`, dispatched with no `model` argument) ran as
  `claude-fable-5-1` per its transcript's `message.model` (agent `a5e9aa4b4a746abce`, session `a14deb8e…`,
  2026-09-27). Not yet verified live: that a per-call `model: opus` overrides the file's `model: fable`
  (Task 6 checks it).

Files: `routes.json` (Claude `ideation.models`), `tw.py` (`decide` ~L273, `cost_row` ~L422, the hook's route
row ~L764), `test_tw_settle.py`, `test_tw_routes.py`, `test_tw_receipt.py`.
Interfaces: Claude `ideation.models` becomes `["fable", "claude-fable-5", "claude-fable-5-1", "opus",
"claude-opus-5", "claude-opus-5-5"]` (Fable first, so the generated agent files keep `model: fable`). The cost
row's `model` is the last assistant row's `message.model` that is not `"<synthetic>"` (Claude Code's error
stub), falling back to meta.json's `model`; the cost row gains `advisor_available: bool`, true when any
transcript row has `attachment.type == "advisor_tool"` and `available: true` (the advisor was offered at some
point in the run; a later `available: false` removal does not clear it, as in `agent-ab847e54493bbfae9.jsonl`,
which has an add then a remove). Route rows gain `agent_model = d.model or pol["models"][0]`: the per-call
model when given, else the role's default; on Codex the requested `model` (always present, the gate requires
it). `d.model` is `tool_input["model"]` when it is a string, which is the only case the gate admits.
This task sits after 1b and its edits anchor on lines 1b leaves in place (`for obj in read_rows(transcript):`
and the `"agent_type": …, "model": …` line of the returned dict).

Red tests. In `test_tw_settle.py`, `child()` gains `ran=None, offered=()`; before `lines = …`:

```python
    if ran:  # the model that ran, on every assistant row; then an error stub, which names no model
        for r in rows[1:]:
            r["message"]["model"] = ran
        rows.append({"type": "assistant", "message": {"id": "m9", "model": "<synthetic>",
                                                      "usage": {"input_tokens": 0, "output_tokens": 0}}})
    rows += [{"type": "attachment", "attachment": {"type": "advisor_tool", "available": a,
                                                   "model": "claude-fable-5-1"}} for a in offered]
```

The existing cost block's `child(home, "tw-worker-high", False, sibling="{not json")` gains
`offered=(False,)`, and after its cost assertion (and after 1b's advisor assertion):

```python
        assert (c["model"], c["advisor_available"]) == ("opus", False), c   # no message.model: meta's; a removal is no offer
    with tempfile.TemporaryDirectory() as home:          # the model that ran comes from the transcript, not meta.json
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x", "action": None})
        child(home, "tw-ideation-high", False, ran="claude-opus-5-5", offered=(True, False))
        assert run_main(["outcome", "--home", home, "--harness", "claude", "--session", SESSION,
                         "--tool-use-id", "toolu_x", "--accepted", "yes"])[0] == 0
        c = [r for r in receipts(home, "claude") if r["kind"] == "cost"][0]
        assert (c["model"], c["advisor_available"]) == ("claude-opus-5-5", True), c   # offered, later removed: True
```

In `test_tw_routes.py` `CASES`, replace `("ideation on opus refused", …, False)` with the first line below and
add the rest:

```python
    ("ideation on opus per call", claude(IDEA, "tw-ideation-high", "opus").admitted, True),
    ("ideation on sonnet refused", claude(IDEA, "tw-ideation-xhigh", "sonnet").admitted, False),
    ("review stays fable-only", claude(REV, "tw-independent-review-high", "opus").admitted, False),
    ("ideation agent file stays fable", R["harnesses"]["claude"]["roles"]["ideation"]["models"][0], "fable"),
    ("denial names model and role", claude(W, "tw-worker-high", "sonnet").reason, "model sonnet is not allowed for worker"),
```

(Red today: "ideation on opus per call" and "denial names model and role". The other three pass today and
guard what must not move: Sonnet stays out, review stays Fable-only, the agent file keeps Fable.)

In `test_tw_receipt.py`'s main block, before the final `print`:

```python
    with tempfile.TemporaryDirectory() as home:          # route rows: the model each dispatch asked for
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        idea = "TW-Role: ideation\nTW-Authorization: t\nTW-Scope: t\n" + HDR + BODY
        hook(home, "claude", "Agent", {"subagent_type": "tw-ideation-high", "model": "opus", "prompt": idea})
        hook(home, "claude", "Agent", {"subagent_type": "tw-ideation-high", "prompt": idea})
        rows = receipts(home, "claude")
        assert [r["decision"] for r in rows if r["kind"] == "dispatch"] == ["admit", "admit"], rows
        assert [r["agent_model"] for r in rows if r["kind"] == "route"] == ["opus", "fable"], rows
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "codex", "--session", SESSION])
        hook(home, "codex", "spawn_agent", {"message": "TW-Role: worker\n" + HDR + BODY, "model": "gpt-6-sol",
                                            "reasoning_effort": "high", "fork_turns": "none"})
        assert [r["agent_model"] for r in receipts(home, "codex") if r["kind"] == "route"] == ["gpt-6-sol"]
```

(`tw-ideation-high` is the role's cheapest tier, so Task 4's exploration never denies it; the Codex worker
dispatch may be explored, but its route row is written before any denial.)

Code. `routes.json`, Claude `ideation`: append `"opus", "claude-opus-5", "claude-opus-5-5"` to `models`.
`decide()`, the Claude per-call model check:

```python
            return Decision(False, f"model {model} is not allowed for {role}", role, model, fields=fields)
```

`cost_row()`: bind the transcript once (`rows = read_rows(transcript)`, then `for obj in rows:`), and after
the loop:

```python
    ran = [m for m in ((o.get("message") or {}).get("model") for o in rows if o.get("type") == "assistant")
           if m and m != "<synthetic>"]  # an error stub names no model
    att = [o.get("attachment") or {} for o in rows if o.get("type") == "attachment"]
```

In the returned dict, `"model": ran[-1] if ran else meta.get("model")` and
`"advisor_available": any(a.get("type") == "advisor_tool" and a.get("available") is True for a in att)`.
The hook's route-row dict, after `"router_tier": r["tier"],`:

```python
               "agent_model": d.model or routes["harnesses"][harness]["roles"][d.role]["models"][0],
```

Demonstrated 2026-09-27 on a scratch copy of `thinker-worker/` at `74a9abf` (Tasks 1–4 not applied): the
red tests above fail against today's `tw.py` and `routes.json` and pass with only these edits; the full
suite is then `SUITE_DONE` only. Composition with 1b is by anchor (above), not run.

Check: `"$PY" test_tw_settle.py && "$PY" test_tw_routes.py && "$PY" test_tw_receipt.py && "$PY" test_tw_agents.py`
→ four PASS lines; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/routes.json thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_settle.py thinker-worker/scripts/test_tw_routes.py thinker-worker/scripts/test_tw_receipt.py && git commit -m "tw: cost rows record the model that ran and advisor availability; route rows record agent_model; ideation may run on Opus per call (switch-on T1c)" -- <same paths>`

### Task 2: exploration one tier below the coordinator, no backend

Files: `tw.py` (`route`, the hook's route row), `test_tw_route.py`, `test_tw_act.py`.
Interfaces: `route()` returns `source: "explore"`, `tier` = the role's next tier below `coord_tier`,
`probs {tier: 1.0}`, `confidence 0.0` when (a) no backend answered, (b) the class's `explore` > 0, (c) the
ticket fraction `int(ticket, 16) / 16 ** 12` < `explore` (the same draw `act()` uses), and (d) `coord_tier`
is not the role's cheapest tier. The explore pick is computed in any mode and acted on in advisory/active:
a `shadow` class with `explore` > 0 logs `source: "explore"` rows and stays silent (a free control-arm
generator). `act()` is unchanged: its existing `explored` test fires on these rows and advises with
"exploration"; `prior_route` caches `explore` rows like any backend decision, so a re-dispatch of the same
brief at either tier is admitted (`source: "cached:explore"`, explore 0).
The hook's route row gains `"explore": r["explore"]` on every row: the class ε at this dispatch (0.0 on a
cached row). With `ticket` it says whether the coin fell below ε, which the phase-2 control arm needs.

**Promote on the five-session run gives counts, not a verdict.** Under advisory + explore, `promote`'s
coordinator arm (action None, non-coordinator source, eligible, lower) is fed only by explored rows the
coordinator kept with `TW-Override`, a selected sample. The valid control is the coordinator-source rows
whose coin fell ≥ ε, compared with the complied explore rows: `action None and source == "coordinator" and
explore > 0 and coordinator_tier == <the explored rows' original tier>` (the tier condition also drops
cheapest-tier rows, which are never explored). Until that arm lands (phase 2), read `n_router`, `n_coord`
and the labels from `promote`, not its `verdict` or `p`.

Red tests. Append to `test_tw_route.py`'s main block (match its imports):

```python
    r0 = json.loads(json.dumps(tw.load_routes()))
    r0["router"].update(backends=[], classes={"*": {"mode": "advisory", "explore": 1.0}})
    f = {"TW-Class": "C-coding", "TW-Deliverable": "d", "TW-Accept": "a", "TW-Risk": "none"}
    r = tw.route(r0, "claude", "worker", f, "x", "high")
    assert (r["source"], r["tier"], r["confidence"]) == ("explore", "medium", 0.0), r
    assert tw.route(r0, "claude", "worker", f, "x", "low")["source"] == "coordinator"       # cheapest: never explored
    assert tw.route(r0, "claude", "independent-review", f, "x", "xhigh")["tier"] == "high"  # the role's own ladder
    assert tw.route(r0, "claude", "leaf", f, "x", "medium")["tier"] == "low"
    r0["router"]["classes"]["*"]["explore"] = 0.0
    assert tw.route(r0, "claude", "worker", f, "x", "high")["source"] == "coordinator"
```

In `test_tw_act.py`, give `run()` a `backends=("stub",)` parameter used in
`routes["router"].update(backends=list(backends), …)`, and add:

```python
    out, row = run("advisory", explore=1.0, backends=())            # no backend: explore one tier below
    assert "tw-worker-medium" in out["permissionDecisionReason"] and "exploration" in out["permissionDecisionReason"]
    assert row["source"] == "explore" and row["router_tier"] == "medium" and row["eligible"] is True, row
    assert row["explore"] == 1.0, row                                                      # ε recorded
    out, row = run("advisory", explore=1e-9, backends=())           # coin >= ε: the phase-2 control shape
    assert out is None and row["source"] == "coordinator" and row["explore"] == 1e-9, row
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-medium", ""))   # take the pick
    assert out is None and row["source"] == "cached:explore" and row["explore"] == 0.0, row
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-high", ""))     # rejected, back to high
    assert out is None and row["source"] == "cached:explore", row
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-low")[0] is None       # nothing below low
    out, row = run("shadow", explore=1.0, backends=())              # computed in shadow, not acted on
    assert out is None and row["source"] == "explore" and row["action"] is None, row
```

Code, in the hook's route-row dict (~L762), next to `"mode": r["mode"]`: `"explore": r["explore"],`.
In `route()` just before the final `return`:

```python
    if found["source"] == "coordinator" and explore > 0 and int(tick, 16) / 16 ** 12 < explore \
            and coord_tier in pol["tiers"] and pol["tiers"].index(coord_tier) > 0:
        below = pol["tiers"][pol["tiers"].index(coord_tier) - 1]  # design §5 Stage 2: one tier below, no backend
        found = {**found, "tier": below, "probs": {below: 1.0}, "confidence": 0.0, "source": "explore"}
```

Check: `"$PY" test_tw_route.py && "$PY" test_tw_act.py` → both PASS lines; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_route.py thinker-worker/scripts/test_tw_act.py && git commit -m "tw: exploration one tier below the coordinator without a backend (switch-on T2)" -- <same paths>`

### Task 3: per-flag risk floor

Files: `tw.py` (`load_routes`, `act`, the hook's route row, `promote`), `routes.json` (add `risk_floor`
only; modes unchanged here), `test_tw_act.py`, `test_tw_routes.py`, `test_tw_promote.py`.
Interfaces: `routes["router"]["risk_floor"]: {"physics": "high", "destructive": "medium", "external": "medium"}`
(Arian, 2026-09-27; keys exactly `RISKS`, values in `TIERS`). `act()` semantics: the router's pick (backend
or explore) is raised to the highest floor among the brief's flags; if the raise leaves it at or above the
coordinator's tier, no action and `eligible` is false (a floored row cannot reach the router arm, design
phase-2 eligible rule). This replaces "risk-flagged briefs never route to the role's cheapest tier", so
review/ideation (tiers high–xhigh) can now be advised down to `high` when flagged.
The floor only lifts the router's pick. A coordinator dispatching a physics brief at `medium` is not advised
up; "physics never below `high`" stays a coordinator prompt rule (Task 4 docs). Enforcing it would belong in
`decide()` as strict model policy (a deny), not in `act()`.
`act()` returns a 5-tuple `(hook output | None, action, guard, eligible, target)`: `target` is the floored
tier, computed first and returned on every path (on a coordinator-source row it is the coordinator's tier:
there is no router pick to floor). Its only call site is `hook()` (tw.py L773); no test calls `act()` directly
(`grep -n "act(" thinker-worker/scripts/*.py`). The hook writes `row["target_tier"] = target` (the raw
`r["tier"]` when `act()` raises) and derives `router_agent` from `target`, so `race_check` compares a
rewritten child with the agent actually picked. `router_tier` stays the raw backend/explore pick (the
backend's evidence). `promote` compares `target_tier` (falling back to `router_tier` on rows written before
this task) in the `advised` map, `rewrite_lower`, and the coordinator-arm lower test, so a coordinator who
complies at the floored tier counts as `complied`.

Red tests. In `test_tw_act.py` replace the three risk lines with:

```python
    assert run("advisory", risk="physics")[0] is None                    # floor high = coordinator's high
    out, row = run("advisory", risk="external")                          # floor medium: advised to medium
    assert "tw-worker-medium" in out["permissionDecisionReason"] and row["router_tier"] == "low", (out, row)
    assert (row["target_tier"], row["router_agent"]) == ("medium", "tw-worker-medium"), row   # floored target
    assert run("advisory", risk="destructive,physics")[0] is None        # the highest flag wins
    assert run("advisory", pick="medium", risk="physics")[0] is None     # a pick below the floor is raised
    assert run("advisory", risk="physics")[1]["eligible"] is False       # floored rows stay out of promote
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-xhigh", risk="physics")[0]["permissionDecisionReason"].count("tw-worker-high") == 1
```

and extend the existing `act()`-raises assertion (`run("active", guard=boom)`) with
`and row["target_tier"] == "low"` (the raw tier when `act()` fails).
(`row["router_tier"]` stays the raw pick; `target_tier`, `router_agent` and the denial name the floored
tier. `HDR.replace("TW-Risk: destructive", f"TW-Risk: {risk}")` already carries `destructive,physics`.)

In `test_tw_promote.py`'s main block, before the final `print`:

```python
    with tempfile.TemporaryDirectory() as tmp:           # floored advise, then compliance at the floored tier
        home = Path(tmp)
        base = {"kind": "route", "ticket": "fl", "class": "C-coding", "router_tier": "low", "target_tier": "medium"}
        tw.append_receipt(home, "claude", S, {**base, "tool_use_id": "f0", "action": "advise", "source": "table",
                                              "coordinator_tier": "high", "eligible": True})
        tw.append_receipt(home, "claude", S, {**base, "tool_use_id": "f1", "action": None, "source": "cached:table",
                                              "coordinator_tier": "medium", "eligible": False})
        tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": "f1", "accepted": True})
        v = tw.promote(home, "claude")
        assert (v["n_router"], v["n_coord"]) == (1, 0), v    # complied at the floored tier: router arm
```

In `test_tw_routes.py`'s
router-validation list, with `good` gaining `"risk_floor": {"physics": "high", "destructive": "medium", "external": "medium"}`, add:

```python
({**good, "risk_floor": {"physics": "high"}}, False),                         # every flag needs a floor
({**good, "risk_floor": {**good["risk_floor"], "physics": "max"}}, False),    # a real tier
({k: v for k, v in good.items() if k != "risk_floor"}, False),
```

Code. `load_routes`, in the router check:

```python
    floors = rt.get("risk_floor") if isinstance(rt, dict) else None
    ... or not isinstance(floors, dict) or set(floors) != RISKS or any(v not in TIERS for v in floors.values())
```

`act()`, replacing the `target`/`lower`/`disagree`/`explored`/`eligible` block and deleting the
`risky`/cheapest-tier lines:

```python
    raw = r["tier"]
    flags = [] if d.fields["TW-Risk"] == "none" else [x.strip() for x in d.fields["TW-Risk"].split(",")]
    floor = 0 if r["source"] == "coordinator" else max(   # the floor lifts the router's pick only
        (TIERS.index(routes["router"]["risk_floor"][f]) for f in flags), default=0)
    target = TIERS[max(TIERS.index(raw), floor)]
    floored = target != raw
    lower = TIERS.index(target) < TIERS.index(d.tier)
    disagree = target != d.tier and r["confidence"] >= routes["router"]["cutoff"]
    explored = lower and r["explore"] > 0 and int(r["ticket"], 16) / 16 ** 12 < r["explore"]
    eligible = r["source"] != "coordinator" and (disagree or explored) and not (floored and not lower)
    if floored and not lower:
        return None, None, None, eligible, target
```

Every other `return` in `act()` gains `target` as its 5th element (the rewrite and advise paths already use
`target` for the pick). In `hook()`: drop `"router_agent"` from the row literal; unpack
`out, row["action"], row["guard"], row["eligible"], target = act(...)`; in its `except` set `target = r["tier"]`;
then `row["target_tier"] = target` and
`row["router_agent"] = agent_name(d.role, target) if harness == "claude" else None`.
In `promote`, after `routes = …`:

```python
    tgt = lambda r: r.get("target_tier") or r["router_tier"]  # floored pick; rows before switch-on T3 lack it
```

and replace `r["router_tier"]` with `tgt(r)` in the `advised` map (both the value and the lower test),
`rewrite_lower`, and the coordinator-arm lower test. On eligible rows target-lower ⇔ raw-lower (eligible
excludes floored-not-lower), so the coordinator arm's counts do not move; the change there is uniformity.

A floored target outside the role's tiers (a physics leaf) is at or above every leaf tier, so it is never
`lower` and never acts; its `router_agent` names no installed agent, and `race_check` never reads it (it
checks rewrite rows only). Update the docstrings of `act()` and `promote()`, and the `test_tw_act.py`
header line.

Check: `"$PY" test_tw_act.py && "$PY" test_tw_routes.py && "$PY" test_tw_promote.py` → three PASS lines;
full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/routes.json thinker-worker/scripts/test_tw_act.py thinker-worker/scripts/test_tw_routes.py thinker-worker/scripts/test_tw_promote.py && git commit -m "tw: per-flag risk_floor replaces never-the-cheapest-tier; route rows carry the floored target (switch-on T3)" -- <same paths>`

### Task 4: routes.json switch-on + docs

Files: `routes.json`, `test_tw_route.py` (the shadow assertion at L31), `SKILL.md`, `references/claude.md`,
`references/codex.md`, `README.md`.
Interfaces: the shipped router block keeps `"backends": []` and changes only
`"classes": {"*": {"mode": "advisory", "explore": 0.2}}` (`budget_s`, `cutoff`, `risk_floor`, `table`
unchanged). ε = 0.2 (Arian, 2026-09-27): at 50–150 dispatches, ~10–30 explored.

Red test first: add to `test_tw_route.py`'s main block

```python
    shipped = tw.load_routes()
    assert shipped["router"]["backends"] == [] and shipped["router"]["classes"]["*"] == {"mode": "advisory", "explore": 0.2}
```

and make the L31 case independent of the shipped mode (pin `classes={"*": {"mode": "shadow"}}` inside
`routes_with`). Then edit `routes.json`; run the full suite and fix any other test that assumed shipped
`shadow` by pinning its own mode, never by changing its assertion's meaning.

Docs (describe what the code does now; delete the old assertion, do not keep it beside the new one):
- `SKILL.md` and `references/claude.md`: replace "This release ships `backends: []` and every class in
  `shadow` … Switch-on: set `backends: ["table"]` …" with the shipped state (no backend; every class
  advisory; 20 % of dispatches above the role's cheapest tier are advised one tier down); replace "never goes
  to the role's lowest tier" with the per-flag floors; add the **exploration protocol**:
  1. A denial saying `router picks <tier> (exploration)` means: re-dispatch the **same brief unchanged** at
     that agent. The same ticket reuses the cached decision, so it is admitted.
  2. Judge the result as usual. Rejected because the tier was too low → `tw.py outcome … --accepted no
     --cause tier`, then re-dispatch the same brief unchanged at your original tier (admitted: cached, no
     re-exploration). Rejected for another reason → `--cause brief` or `--cause other`.
  3. If the brief must change before a re-dispatch (at the explored tier or back at yours), add
     `TW-Override: exploration re-dispatch, brief changed` in lines 2–12. A changed brief is a new ticket, so
     without `TW-Override` a re-dispatch at t−1 can itself be explored down to t−2, and one at t can be
     explored again.
  4. Keep your tier with `TW-Override: <reason>` only where exploration is unsafe for a reason the risk flags
     do not capture; the override is logged.
- `SKILL.md`: the coordinator's tier rule from design §7 decision 7: `medium` by default; `low` for
  predictable work with a known outcome; `high` for tricky reasoning, physics or convention judgment; `xhigh`
  only for adversarial hard reasoning; physics or convention judgment never below `high`.
- `SKILL.md` and `references/claude.md`, the per-call model rule (Task 1c; Fable recommendation, 2026-09-27):
  "Dispatch `tw-<role>-<tier>` with no `model` argument, except to select an allowed non-default model for
  the role (today: `model: opus` on `tw-ideation-<tier>`); the agent file pins the default." Fable is the
  ideation default; Opus is the coordinator's choice when the Fable weekly budget binds (Arian,
  2026-09-27). Review stays Fable-only.
- `references/codex.md`: the same exploration protocol with `reasoning_effort=` wording.
- `README.md` thinker-worker section: shipped mode is advisory with exploration one tier below.

Check: full suite → `SUITE_DONE` only, and
`grep -rn "ships \`backends: \[\]\`\|lowest tier\|backends: \[\"table\"\]" thinker-worker/SKILL.md thinker-worker/references README.md`
→ no output (today it matches `references/claude.md:11`).
Commit: `git add -- thinker-worker/routes.json thinker-worker/scripts/test_tw_route.py thinker-worker/SKILL.md thinker-worker/references/claude.md thinker-worker/references/codex.md README.md && git commit -m "thinker-worker: switch on advisory exploration 0.2 one tier below; exploration protocol and default tiers in docs (switch-on T4)" -- <same paths>`

### Task 5: Fable review gate

Send `git log --oneline <T1 parent>..HEAD` and the diff range to the Fable session "Effort routing
architecture" for adversarial review (what is wrong, ranked). Apply fixes with an Opus worker under the same
TDD rule, one commit per fix batch. Check: Fable reports no must-fix outstanding.

Gate fixes applied 2026-09-27 (ROUTING-PROGRESS.md "T5 gate fixes"): `TW_ROUTES` pins test routing to a shadow
copy of the shipped file (one deliberate shipped-file test left in `test_tw_route.py`), `<synthetic>` rows are
not API calls in `cost_row`, worker `default` medium in both harnesses.

### Task 6: reinstall and live check (Arian's OK at this step)

Destructive boundary: rewrites the real `~/.claude/settings.json` hook entry, `~/.codex/hooks.json` and the
installed skill; `uninstall` deletes every activation record under `~/.thinker-worker/state/` (sessions
re-run `activate`). Ask Arian immediately before running it. Codex `/hooks` trust must be renewed by Arian
afterwards (his manual step).

Ordering rule (hard): because `uninstall` clears every activation record, Task 6 finishes before the first of
the five launches and never runs while any of the five sessions is live. A switch-on change after the run has
started (a routes.json or tw.py edit needs this reinstall) requires all five sessions to re-run `activate`;
until they do, their dispatches pass unguarded and unrouted, with no receipt.

Steps:
1. `"$PY" thinker-worker/scripts/tw.py machines` and read this machine's recorded flags; run the
   `uninstall && install` command those flags give (`install_command()` in `tw.py`), not a remembered one.
2. `"$PY" ~/.claude/skills/thinker-worker/scripts/tw.py check` → `installed: true`, `problems: []`.
3. Live check in a fresh Claude session (this one's hook set is fixed at session start): activate, then
   dispatch `tw-worker-high` with a real header and `TW-Risk: none`. To see exploration without luck, pick a
   brief whose ticket falls under 0.2: compute `int(tw.ticket(brief)[0], 16) / 16 ** 12` offline and vary a
   trailing line until it is < 0.2. Expected: deny with `(exploration)` naming `tw-worker-medium`; route row
   `source: "explore"`, `router_tier: "medium"`, `target_tier: "medium"`, `explore: 0.2`, `mode: "advisory"`;
   the re-dispatch at `tw-worker-medium`
   is admitted with `source: "cached:explore"`; `tw.py outcome … --accepted yes` writes the outcome and cost
   rows. Then dispatch `tw-ideation-high` with `model: opus` and label it: route row `agent_model: "opus"`,
   cost row `model` a `claude-opus-*` id (the per-call override of the file's `model: fable`, Task 1c).

Check: the rows above, pasted from the receipts file.
Record: `ROUTING-PROGRESS.md` switch-on section with the session id and rows; commit by pathspec.

### Task 7: launch contract (coordinator, outside the repo)

Files: the five `C:\Users\Arian\Desktop\handoffs\*-prompt.md` and
`~/.claude/handoffs/2026-09-26-launch-five-project-sessions.md`.
Edits, unique-match replace with read-back (backups first in the session scratchpad):
- (c): add the per-call model rule from Task 4's docs, verbatim ("Dispatch `tw-<role>-<tier>` with no
  `model` argument, except …; the agent file pins the default.").
- (d): add `--cause tier|brief|other` on every rejection.
- New (e): the four-step exploration protocol from Task 4, verbatim, including step 3's "A changed brief is
  a new ticket, so without `TW-Override` a re-dispatch at t−1 can itself be explored down to t−2".
- Handoff HOLD line: "the router is switched on (advisory, exploration 0.2 one tier below, installed <date>,
  live check <session id>). Reinstall (Task 6) finished before the first launch and never runs during the
  run; a mid-run switch-on change means all five sessions re-run `activate`." Lifting the HOLD stays
  Arian's call.

Check: `grep -c "cause tier" <each file>` = 1, `grep -c "(exploration)" <each file>` ≥ 1 and
`grep -c "explored down to" <each file>` = 1 and `grep -c "agent file pins the default" <each file>` = 1
for all six; `grep -c "re-run \`activate\`"` on the handoff ≥ 1.
Commit: the handoff in the home repo by pathspec (the Desktop prompts are not in git).

## Self-review

- Design coverage: §5 Stage 2 one tier below (Tasks 2, 4), censoring label (Task 1), risk floor decision 7
  (Task 3), default tier rule (Task 4 docs, Task 7), live switch-on (Task 6). Not here, by design: Stage 1
  scoring of decision-model arms, `tw.py serve`, the Stage 3 scoring script, cost-row verdicts, the routes
  override file, `uninstall` keeping `state/`, the Codex v2 `task_name` join (phase 2 proper).
- Numerical choices: ε = 0.2 and floors physics high / destructive medium / external medium (decided, Arian
  2026-09-27).
- Advisor contamination (Task 1b): detected per dispatch and excluded from promotion; the advisor itself is
  off (Arian, 2026-09-27). Task 1c adds `advisor_available` (offered, whether or not called).
- Model recording (Task 1c): the cost row's `model` is what ran (transcript), the route row's `agent_model`
  what was asked for; ideation admits Opus per call, review stays Fable-only (Arian, 2026-09-27). Model
  choice across models is an arm comparison, not a tier ladder (design §6, "Model routing", phase 2).
- Promote on this run: counts only. Its coordinator arm under advisory + explore holds only `TW-Override`
  rows (selected); the valid control (coordinator-source rows with `explore` > 0 whose coin fell ≥ ε, at the
  explored rows' original tier) is phase 2. Task 2 records `explore` on every route row so that arm can be
  built from this run's receipts.
- Floor vs. data (Task 3): route rows keep the raw pick in `router_tier` and the floored pick in
  `target_tier`; `promote` and `race_check` (via `router_agent`) read the floored one.
- Names agree: `cause`, `advisor_calls`, `n_advisor_excluded`, `advisor_available`, `agent_model`,
  `risk_floor`, `target_tier`, `explore`,
  `source: "explore"`, `cached:explore`, `load_routes`, `cost_row`, `promote`, `route`, `act`.
