# Effort routing switch-on (advisory + table-driven exploration) — implementation plan

**Goal:** the five-session run starts with the router on: `backends: ["table"]`, every class in `advisory`
with `explore: 0.2`, per-flag risk floors, and outcome labels that say whether a rejection was the tier's
fault, so the run produces two-sided tier labels (design §5 Stage 2).

**Approach:** four TDD tasks in `thinker-worker` (red test first, then the code, then the full suite), a
Fable review gate, then a reinstall and live check that needs Arian's OK at that moment, then the launch
prompts. Exploration needs no decision model: the table says `low` for every class, `table` confidence is 0
so only exploration can act, and a fraction 0.2 of dispatches sent above the floor is denied toward it.

**Design:** `docs/plans/2026-09-26-effort-routing-architecture-design.md` §5 (Stages 1–4, censoring, risk
floor, cost side) and §7 decision 7 (default tiers, `risk_floor` values), at `d3dc865`. Advisory with
exploration for the five-session run: Arian, 2026-09-27.

**Constraints:**
- Python: `C:/Users/Arian/anaconda3/envs/claude-code/python.exe`; stdlib only; tests are plain scripts run
  from `thinker-worker/scripts/` (`python test_tw_<x>.py`), no pytest.
- TDD per task: add or change the test first, run it and paste the failing message, then implement, then the
  full suite: `cd thinker-worker/scripts && for f in test_tw_*.py; do "$PY" "$f" >/dev/null 2>&1 || echo "FAIL $f"; done; echo SUITE_DONE`
  (expected: only `SUITE_DONE`).
- Real `~/.claude`, `~/.codex`, `~/.thinker-worker` are untouched until Task 6. No push. No `rm -rf` on
  computed paths. Commit by pathspec, message ends with the attribution line.
- Checkpoint: one line per task in `thinker-worker/ROUTING-PROGRESS.md` (new "Switch-on" section).
- `routes.json` is installer-owned: it changes only here in the source tree and reaches the real install only
  through Task 6.
- Exploration applies to Codex sessions too (`router.classes` is not per harness); an activated Codex
  session gets the same advisory denials with a `reasoning_effort=` hint (accepted, Arian 2026-09-27).
- Status (Arian, 2026-09-27): plan written, **not to be executed yet**; the table values (Task 2) are
  still open.

## File map

- Modify `thinker-worker/scripts/tw.py`:
  - `outcome()` (~L335) and the `outcome` parser (~L1275): optional `--cause tier|brief|other`, only with
    `--accepted no`; recorded as `cause` (null when absent). (Task 1)
  - `load_routes()` (L59–78): validate `router.risk_floor`; resolve a relative `router.table.path` against
    the routes file's directory. (Tasks 2, 3)
  - `SKILL_FILES` (L30): add `tables/opus-5-5-2026-09-26.json`. (Task 2)
  - `act()` (L668–705): per-flag floor replaces "never the role's cheapest tier". (Task 3)
- Create `thinker-worker/tables/opus-5-5-2026-09-26.json`: the exploration table. (Task 2)
- Modify `thinker-worker/routes.json`: `risk_floor` (Task 3); switch-on (Task 4).
- Modify tests: `test_tw_outcome.py` (1), `test_tw_route.py` (2, 4), `test_tw_routes.py` (3), `test_tw_act.py` (3).
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

(`Conflict` raised in `main` must already map to a nonzero exit; confirm by reading `main`'s handler, and
if it does not, return the same code the existing "no receipt" refusal returns.)

Check: `"$PY" test_tw_outcome.py` → `PASS outcome …`; then the full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_outcome.py && git commit -m "tw: outcome --cause tier|brief|other labels why a rejection happened (switch-on T1)" -- <same paths>`

### Task 2: Opus 5.5 exploration table, shipped with the skill

Files: create `thinker-worker/tables/opus-5-5-2026-09-26.json`; `tw.py` (`SKILL_FILES`, `load_routes`);
`test_tw_route.py`.
Interfaces: `load_routes(path)` returns `router.table.path` absolute (relative paths resolve against
`path.parent`); `backend_table` unchanged (reads `classes[cls]["recommended_tier"]`, `model`, `fitted_date`).

Table (values for Arian's approval: **every class `low`**). It is an exploration prior, not a fit:
T2/T3 generators, the X1 composite and C6 saturate at `low` on Opus 5.5
(`~/Code/effortmining-runs/2026-09-26-opus55/PROGRESS.md` §§2a, 5, 10, 11). T1, T4 and R were not
re-measured on 5.5 and are set `low` because the table's only job in Stage 2 is to point exploration at `low`.

```json
{
  "model": "claude-opus-5-5",
  "fitted_date": "2026-09-26",
  "kind": "exploration-prior",
  "source": "effortmining-runs/2026-09-26-opus55/PROGRESS.md: synthetic tasks saturate at low on Opus 5.5; T1, T4, R not re-measured. Design §4.3: a class prior, not a per-dispatch signal.",
  "classes": {
    "T1-mechanical": {"recommended_tier": "low"},
    "T2-simple-transform": {"recommended_tier": "low"},
    "T3-moderate-reasoning": {"recommended_tier": "low"},
    "T4-hard-reasoning": {"recommended_tier": "low"},
    "R-research": {"recommended_tier": "low"},
    "C-coding": {"recommended_tier": "low"}
  }
}
```

Red test, append to `test_tw_route.py`'s main block:

```python
    table = tw.source_root() / "tables" / "opus-5-5-2026-09-26.json"
    cal = json.loads(table.read_text(encoding="utf-8"))
    assert set(cal["classes"]) == tw.TASK_CLASSES and {c["recommended_tier"] for c in cal["classes"].values()} == {"low"}
    assert "tables/opus-5-5-2026-09-26.json" in tw.SKILL_FILES
    with tempfile.TemporaryDirectory() as tmp:           # a relative table path resolves next to routes.json
        (Path(tmp) / "tables").mkdir()
        (Path(tmp) / "tables" / "t.json").write_bytes(table.read_bytes())
        doc = json.loads(json.dumps(tw.load_routes()))
        doc["router"]["table"] = {"path": "tables/t.json"}
        (Path(tmp) / "routes.json").write_text(json.dumps(doc), encoding="utf-8")
        got = tw.load_routes(Path(tmp) / "routes.json")
        assert Path(got["router"]["table"]["path"]) == Path(tmp) / "tables" / "t.json", got["router"]["table"]
        got["router"]["backends"] = ["table"]
        for cls in sorted(tw.TASK_CLASSES):
            f = {"TW-Class": cls, "TW-Deliverable": "d", "TW-Accept": "a", "TW-Risk": "none"}
            r = tw.route(got, "claude", "worker", f, "x", "high")
            assert (r["source"], r["tier"]) == ("table", "low"), (cls, r)
            r = tw.route(got, "claude", "independent-review", f, "x", "xhigh")
            assert (r["source"], r["tier"]) == ("table", "high"), (cls, r)   # clamped into the role's tiers
```

(Match the file's existing imports; add `json`, `tempfile`, `Path` if absent.)

Code, at the end of `load_routes` before `return doc`:

```python
    tbl = rt.get("table")
    if isinstance(tbl, dict) and isinstance(tbl.get("path"), str):
        p = Path(os.path.expanduser(tbl["path"]))
        tbl["path"] = str(p if p.is_absolute() else path.parent / p)
```

and `SKILL_FILES` gains `"tables/opus-5-5-2026-09-26.json"`. Confirm `test_tw_install.py` still passes (the
installer copies every `SKILL_FILES` entry, `tw.py:800`); if it asserts an exact installed-file list, add
the table there.

Check: `"$PY" test_tw_route.py` → its PASS line; full suite → `SUITE_DONE` only.
Commit: `git add -- thinker-worker/tables/opus-5-5-2026-09-26.json thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_route.py && git commit -m "tw: Opus 5.5 exploration table shipped with the skill; relative table paths (switch-on T2)" -- <same paths>`

### Task 3: per-flag risk floor

Files: `tw.py` (`load_routes`, `act`), `routes.json` (add `risk_floor` only; modes unchanged here),
`test_tw_act.py`, `test_tw_routes.py`.
Interfaces: `routes["router"]["risk_floor"]: {"physics": "high", "destructive": "medium", "external": "medium"}`
(Arian, 2026-09-27; keys exactly `RISKS`, values in `TIERS`). `act()` semantics: the router's pick is raised
to the highest floor among the brief's flags; if the raised pick is at or above the coordinator's tier and
the raise changed it, no action and `eligible` is false (a floored row cannot reach the router arm, design
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
    assert run("advisory", conf=0.1, explore=1.0, risk="external")[0]["permissionDecisionReason"].count("medium") >= 1
```

(`row["router_tier"]` stays the backend's raw pick; the denial names the floored agent. If `run()`'s `HDR`
replacement cannot express two flags, extend it the same way it handles one.) In `test_tw_routes.py`'s
router-validation list add, with `good` gaining `"risk_floor": {"physics": "high", "destructive": "medium", "external": "medium"}`:

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
Interfaces: shipped router block becomes

```json
"backends": ["table"],
"table": {"path": "tables/opus-5-5-2026-09-26.json"},
"classes": {"*": {"mode": "advisory", "explore": 0.2}}
```

(`budget_s`, `cutoff`, `risk_floor` unchanged.) **ε = 0.2** (Arian, 2026-09-27; design §7 defaults line). At 50–150 dispatches that is ~10–30 explored.

Red test first: add to `test_tw_route.py`'s main block

```python
    shipped = tw.load_routes()
    assert shipped["router"]["backends"] == ["table"] and shipped["router"]["classes"]["*"] == {"mode": "advisory", "explore": 0.2}
    assert Path(shipped["router"]["table"]["path"]).exists(), shipped["router"]["table"]
```

and make the L31 case independent of the shipped mode (set `classes={"*": {"mode": "shadow"}}` inside
`routes_with`). Then edit `routes.json`; run the full suite and fix any other test that assumed shipped
`shadow` by pinning its own mode, never by changing its assertion's meaning.

Docs (describe what the code does now; delete the old assertion, do not keep it beside the new one):
- `SKILL.md` and `references/claude.md`: replace "This release ships `backends: []` and every class in
  `shadow` … Switch-on: …" with the shipped state; replace "never goes to the role's lowest tier" with the
  per-flag floors; add the **exploration protocol**:
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
- `README.md` thinker-worker section: shipped mode is advisory with exploration.

Check: full suite → `SUITE_DONE` only, and
`grep -rn "ships \`backends: \[\]\`\|never goes to the role's lowest tier\|lowest tier" thinker-worker/SKILL.md thinker-worker/references README.md`
→ no output.
Commit: `git add -- thinker-worker/routes.json thinker-worker/scripts/test_tw_route.py thinker-worker/SKILL.md thinker-worker/references/claude.md thinker-worker/references/codex.md README.md && git commit -m "thinker-worker: switch on table + advisory exploration 0.2; exploration protocol and default tiers in docs (switch-on T4)" -- <same paths>`

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
   dispatch `tw-worker-high` with a real header and `TW-Risk: none`. Expected route row: `source: "table"`,
   `router_tier: "low"`, `mode: "advisory"`. To see a denial without luck, pick a brief whose ticket falls
   under 0.2: compute `int(tw.ticket(brief)[0], 16) / 16 ** 12` offline and vary a trailing line until it
   is < 0.2. Expected: deny with `(exploration)` naming `tw-worker-low`; re-dispatch at `tw-worker-low` is
   admitted with `source: "cached:table"`; `tw.py outcome … --accepted yes` writes the outcome and cost rows.

Check: the three expected rows above, pasted from the receipts file.
Record: `ROUTING-PROGRESS.md` switch-on section with the session id and rows; commit by pathspec.

### Task 7: launch contract (coordinator, outside the repo)

Files: the five `C:\Users\Arian\Desktop\handoffs\*-prompt.md` and
`~/.claude/handoffs/2026-09-26-launch-five-project-sessions.md`.
Edits, unique-match replace with read-back (backups first in the session scratchpad):
- (a): after activation, `status` shows the session activated; no change otherwise.
- (d): add `--cause tier|brief|other` on every rejection.
- New (e): the four-step exploration protocol from Task 4, verbatim.
- Handoff HOLD line: "the calibration has landed and the router is switched on (advisory + exploration
  0.2, installed <date>, live check <session id>)". Lifting the HOLD stays Arian's call.

Check: `grep -c "cause tier" <each file>` = 1 and `grep -c "(exploration)" <each file>` ≥ 1 for all six.
Commit: the handoff in the home repo by pathspec (the Desktop prompts are not in git).

## Self-review

- Design coverage: §5 Stage 2 (Tasks 2, 4), censoring label (Task 1), risk floor decision 7 (Task 3), default
  tier rule (Task 4 docs, Task 7), live switch-on (Task 6). Not here, by design: Stage 1 offline scoring of
  other arms, `tw.py serve`, Stage 3 scoring script, cost-row verdicts, the routes override file,
  `uninstall` keeping `state/`, the Codex v2 `task_name` join (phase 2 proper).
- Numerical choices: table all `low` (open); ε = 0.2 and floors physics high / destructive medium /
  external medium (decided, Arian 2026-09-27).
- Names agree: `cause`, `risk_floor`, `tables/opus-5-5-2026-09-26.json`, `load_routes`, `act`, `route`,
  `backend_table`.
