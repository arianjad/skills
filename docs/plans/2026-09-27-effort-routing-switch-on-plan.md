# Effort routing switch-on (advisory + exploration one tier below) — implementation plan

**Goal:** the five-session run starts with the router on: every class in `advisory` with `explore: 0.2`,
exploration one tier below the coordinator's tier with no backend and no table, per-flag risk floors, and
outcome labels that say whether a rejection was the tier's fault, so the run produces tier labels (design §5
Stage 2).

**Approach:** four TDD tasks in `thinker-worker` (red test first, then the code, then the full suite), a
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
  full suite: `cd thinker-worker/scripts && for f in test_tw_*.py; do "$PY" "$f" >/dev/null 2>&1 || echo "FAIL $f"; done; echo SUITE_DONE`
  (expected: only `SUITE_DONE`).
- Real `~/.claude`, `~/.codex`, `~/.thinker-worker` are untouched until Task 6. No push. No `rm -rf` on
  computed paths. Commit by pathspec, message ends with the attribution line.
- Checkpoint: one line per task in `thinker-worker/ROUTING-PROGRESS.md` (new "Switch-on" section).
- `routes.json` is installer-owned: it changes only here in the source tree and reaches the real install only
  through Task 6. `router.table` stays in the file, inert while `backends` is `[]`.
- Exploration applies to Codex sessions too (`router.classes` is not per harness); an activated Codex
  session gets the same advisory denials with a `reasoning_effort=` hint (accepted, Arian 2026-09-27).
- Status (Arian, 2026-09-27): plan written, **not to be executed yet**.

## File map

- Modify `thinker-worker/scripts/tw.py`:
  - `outcome()` (~L335) and the `outcome` parser (~L1275): optional `--cause tier|brief|other`, only with
    `--accepted no`; recorded as `cause` (null when absent). (Task 1)
  - `route()` (L518–557): backend-free exploration one tier below the coordinator. (Task 2)
  - `load_routes()` (L59–78): validate `router.risk_floor`. (Task 3)
  - `act()` (L668–705): per-flag floor replaces "never the role's cheapest tier". (Task 3)
- Modify `thinker-worker/routes.json`: `risk_floor` (Task 3); `"*"` → advisory, explore 0.2 (Task 4).
- Modify tests: `test_tw_outcome.py` (1), `test_tw_route.py` (2, 4), `test_tw_act.py` (2, 3),
  `test_tw_routes.py` (3).
- Modify docs: `thinker-worker/SKILL.md`, `references/claude.md`, `references/codex.md`, `README.md`
  thinker-worker section (Task 4).
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
# parser, next to --accepted
p.add_argument("--cause", choices=("tier", "brief", "other"))
# main, outcome branch
if args.cause and args.accepted == "yes":
    raise Conflict("--cause explains a rejection; use it only with --accepted no")
outcome(home, args.harness, session_value(args.session), args.tool_use_id, args.accepted == "yes", args.cause)
# outcome(): signature gains cause=None; the appended row gains "cause": cause
```

(Read `main`'s handler: a `Conflict` there must give a nonzero exit, as the existing "no receipt" refusal
does; if it does not, return that refusal's exit code.)

Check: `"$PY" test_tw_outcome.py` → `PASS outcome …`; then the full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_outcome.py && git commit -m "tw: outcome --cause tier|brief|other labels why a rejection happened (switch-on T1)" -- <same paths>`

### Task 2: exploration one tier below the coordinator, no backend

Files: `tw.py` (`route`), `test_tw_route.py`, `test_tw_act.py`.
Interfaces: `route()` returns `source: "explore"`, `tier` = the role's next tier below `coord_tier`,
`probs {tier: 1.0}`, `confidence 0.0` when (a) no backend answered, (b) the class's `explore` > 0, (c) the
ticket fraction `int(ticket, 16) / 16 ** 12` < `explore` (the same draw `act()` uses), and (d) `coord_tier`
is not the role's cheapest tier. `act()` is unchanged: its existing `explored` test fires on these rows and
advises with "exploration"; `prior_route` caches `explore` rows like any backend decision, so a re-dispatch
of the same brief at either tier is admitted (`source: "cached:explore"`, explore 0).

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
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-medium", ""))   # take the pick
    assert out is None and row["source"] == "cached:explore", row
    out, row = run("advisory", explore=1.0, backends=(), then=("tw-worker-high", ""))     # rejected, back to high
    assert out is None and row["source"] == "cached:explore", row
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-low")[0] is None       # nothing below low
    assert run("shadow", explore=1.0, backends=())[0] is None                              # shadow logs only
```

Code, in `route()` just before the final `return`:

```python
    if found["source"] == "coordinator" and explore > 0 and int(tick, 16) / 16 ** 12 < explore \
            and coord_tier in pol["tiers"] and pol["tiers"].index(coord_tier) > 0:
        below = pol["tiers"][pol["tiers"].index(coord_tier) - 1]  # design §5 Stage 2: one tier below, no backend
        found = {**found, "tier": below, "probs": {below: 1.0}, "confidence": 0.0, "source": "explore"}
```

Check: `"$PY" test_tw_route.py && "$PY" test_tw_act.py` → both PASS lines; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_route.py thinker-worker/scripts/test_tw_act.py && git commit -m "tw: exploration one tier below the coordinator without a backend (switch-on T2)" -- <same paths>`

### Task 3: per-flag risk floor

Files: `tw.py` (`load_routes`, `act`), `routes.json` (add `risk_floor` only; modes unchanged here),
`test_tw_act.py`, `test_tw_routes.py`.
Interfaces: `routes["router"]["risk_floor"]: {"physics": "high", "destructive": "medium", "external": "medium"}`
(Arian, 2026-09-27; keys exactly `RISKS`, values in `TIERS`). `act()` semantics: the router's pick (backend
or explore) is raised to the highest floor among the brief's flags; if the raise leaves it at or above the
coordinator's tier, no action and `eligible` is false (a floored row cannot reach the router arm, design
phase-2 eligible rule). This replaces "risk-flagged briefs never route to the role's cheapest tier", so
review/ideation (tiers high–xhigh) can now be advised down to `high` when flagged.

Red tests. In `test_tw_act.py` replace the three risk lines with:

```python
    assert run("advisory", risk="physics")[0] is None                    # floor high = coordinator's high
    out, row = run("advisory", risk="external")                          # floor medium: advised to medium
    assert "tw-worker-medium" in out["permissionDecisionReason"] and row["router_tier"] == "low", (out, row)
    assert run("advisory", risk="destructive,physics")[0] is None        # the highest flag wins
    assert run("advisory", pick="medium", risk="physics")[0] is None     # a pick below the floor is raised
    assert run("advisory", risk="physics")[1]["eligible"] is False       # floored rows stay out of promote
    assert run("advisory", explore=1.0, backends=(), st="tw-worker-xhigh", risk="physics")[0]["permissionDecisionReason"].count("tw-worker-high") == 1
```

(`row["router_tier"]` stays the raw pick; the denial names the floored agent. If `run()`'s `HDR`
replacement cannot express two flags, extend it the same way it handles one.) In `test_tw_routes.py`'s
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
    floor = max((TIERS.index(routes["router"]["risk_floor"][f]) for f in flags), default=0)
    target = TIERS[max(TIERS.index(raw), floor)]
    floored = target != raw
    lower = TIERS.index(target) < TIERS.index(d.tier)
    disagree = target != d.tier and r["confidence"] >= routes["router"]["cutoff"]
    explored = lower and r["explore"] > 0 and int(r["ticket"], 16) / 16 ** 12 < r["explore"]
    eligible = r["source"] != "coordinator" and (disagree or explored) and not (floored and not lower)
    if floored and not lower:
        return None, None, None, eligible
```

A floored target outside the role's tiers (a physics leaf) is at or above every leaf tier, so it is never
`lower` and never acts. Update the docstring's "risk floor" wording and the `test_tw_act.py` header line.

Check: `"$PY" test_tw_act.py && "$PY" test_tw_routes.py` → both PASS lines; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/routes.json thinker-worker/scripts/test_tw_act.py thinker-worker/scripts/test_tw_routes.py && git commit -m "tw: per-flag risk_floor replaces never-the-cheapest-tier (switch-on T3)" -- <same paths>`

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
  3. If the brief must change before re-dispatch, add `TW-Override: exploration rejected at <tier>` in lines
     2–12, since a changed brief is a new ticket and may be explored again.
  4. Keep your tier with `TW-Override: <reason>` only where exploration is unsafe for a reason the risk flags
     do not capture; the override is logged.
- `SKILL.md`: the coordinator's tier rule from design §7 decision 7: `medium` by default; `low` for
  predictable work with a known outcome; `high` for tricky reasoning, physics or convention judgment; `xhigh`
  only for adversarial hard reasoning; physics or convention judgment never below `high`.
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

### Task 6: reinstall and live check (Arian's OK at this step)

Destructive boundary: rewrites the real `~/.claude/settings.json` hook entry, `~/.codex/hooks.json` and the
installed skill; `uninstall` deletes every activation record under `~/.thinker-worker/state/` (sessions
re-run `activate`). Ask Arian immediately before running it. Codex `/hooks` trust must be renewed by Arian
afterwards (his manual step).

Steps:
1. `"$PY" thinker-worker/scripts/tw.py machines` and read this machine's recorded flags; run the
   `uninstall && install` command those flags give (`install_command()` in `tw.py`), not a remembered one.
2. `"$PY" ~/.claude/skills/thinker-worker/scripts/tw.py check` → `installed: true`, `problems: []`.
3. Live check in a fresh Claude session (this one's hook set is fixed at session start): activate, then
   dispatch `tw-worker-high` with a real header and `TW-Risk: none`. To see exploration without luck, pick a
   brief whose ticket falls under 0.2: compute `int(tw.ticket(brief)[0], 16) / 16 ** 12` offline and vary a
   trailing line until it is < 0.2. Expected: deny with `(exploration)` naming `tw-worker-medium`; route row
   `source: "explore"`, `router_tier: "medium"`, `mode: "advisory"`; the re-dispatch at `tw-worker-medium`
   is admitted with `source: "cached:explore"`; `tw.py outcome … --accepted yes` writes the outcome and cost
   rows.

Check: the rows above, pasted from the receipts file.
Record: `ROUTING-PROGRESS.md` switch-on section with the session id and rows; commit by pathspec.

### Task 7: launch contract (coordinator, outside the repo)

Files: the five `C:\Users\Arian\Desktop\handoffs\*-prompt.md` and
`~/.claude/handoffs/2026-09-26-launch-five-project-sessions.md`.
Edits, unique-match replace with read-back (backups first in the session scratchpad):
- (d): add `--cause tier|brief|other` on every rejection.
- New (e): the four-step exploration protocol from Task 4, verbatim.
- Handoff HOLD line: "the router is switched on (advisory, exploration 0.2 one tier below, installed <date>,
  live check <session id>)". Lifting the HOLD stays Arian's call.

Check: `grep -c "cause tier" <each file>` = 1 and `grep -c "(exploration)" <each file>` ≥ 1 for all six.
Commit: the handoff in the home repo by pathspec (the Desktop prompts are not in git).

## Self-review

- Design coverage: §5 Stage 2 one tier below (Tasks 2, 4), censoring label (Task 1), risk floor decision 7
  (Task 3), default tier rule (Task 4 docs, Task 7), live switch-on (Task 6). Not here, by design: Stage 1
  scoring of decision-model arms, `tw.py serve`, the Stage 3 scoring script, cost-row verdicts, the routes
  override file, `uninstall` keeping `state/`, the Codex v2 `task_name` join (phase 2 proper).
- Numerical choices: ε = 0.2 and floors physics high / destructive medium / external medium (decided, Arian
  2026-09-27).
- Names agree: `cause`, `risk_floor`, `source: "explore"`, `cached:explore`, `load_routes`, `route`, `act`.
