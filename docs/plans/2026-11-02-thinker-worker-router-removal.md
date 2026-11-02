# thinker-worker router removal: implementation plan

**Goal:** Remove the post-admission tier router (exploration, decision-model backends, combining, rewrite/advise, race and competing-writer guards, promote) from thinker-worker. Keep the guard, the tier priors and their reminder line, `outcome`/`check`/`cost` receipts, and the Codex/Claude pipelines.
**Approach:** The guard (`decide`) already admits or denies before the router runs, and the dispatch receipt already records class, tier and model. So the router can go entirely: no `route` rows, no tier changes. A small `reminder()` in `hook` keeps the prior line. A small `tally` command replaces `promote`, giving accept counts per class, executed model and executed tier for hand-tuning priors. Retired override keys are ignored, not errors, so existing `~/.thinker-worker/routes.json` files (Windows and Mac) keep working.
**Design:** in chat, 2026-11-02. Evidence: 1,443 route rows. 102 of 104 rewrites came from the exploration coin flip, 2 from a backend. Rewritten dispatches were accepted 86/95 vs 804/835 for untouched ones (Fisher p ≈ 0.015; labels mostly coordinator self-reports). Nothing fed outcomes back into the priors. Arian chose removal over shadow mode.
**Constraints:**
- Repo `~/Code/skills_public` (`arianjad/skills`, public). Commit per task, with "(Windows)" in each message. No push without Arian's yes.
- Test interpreter: `PY=~/anaconda3/python.exe`. Full suite: `cd thinker-worker/scripts && for f in test_tw_*.py; do "$PY" "$f" >/dev/null 2>&1 || echo "FAIL $f"; done; echo SUITE_DONE`. Expected output: only `SUITE_DONE`. Baseline at f64055a: green, 94 s.
- Do not touch historical receipts under `~/.thinker-worker/receipts/`. Readers must still parse old `route`/`race` rows without error.
- `tw.py` is shared by both harnesses, and the same hook code runs for Claude and Codex. The installed copies change only via `tw.py upgrade` (Task 6).
- Leave the `kev` repo and `Local-Agent/local_decisions` untouched. Freeing their disk space or RAM is Arian's call.

## File map
- Modify `thinker-worker/scripts/tw.py`:
  - delete: `MODES`, `ticket`, `coin`, `backend_table`, `JEV_*`, `backend_jev`, `BACKENDS`, `backend_fn`, `prob`, `valid_route`, `class_mode`, `epsilon`, `class_count`, `model_derived_route`, `prior_route`, `ask_backends`, `combine`, `route`, `_win_claude_start`, `_posix_claude_start`, `claude_process_start`, `competing_agent_writer`, `advisory_flag`, `act`, `quota`, `routed`, `race_check`, `promote`, `arms`, `tgt`, `is_jev`
  - rewrite: `OVERRIDABLE`, `merge_override`, the router part of `check_routes`, `priors_line`, the end of `hook`, the router block in `codex_run`, `outcome` (drop the `race_check` call), `activate`/`status` (drop `store_bodies`), the CLI (`route` and `promote` out, `tally` in)
  - keep: `clamp` (used by `prior`), `harness_rows`, `dispatch_key`
  - add: `reminder()`, `tally()`
- Modify `thinker-worker/routes.json`: `router` keeps only `priors`, `model_priors`, `defaults`.
- Delete tests: `test_tw_backends.py`, `test_tw_route.py`, `test_tw_act.py`, `test_tw_promote.py`, `test_tw_promote_sessions.py`, `test_tw_disabled_cache.py`, `test_tw_guard.py` (it tests only `competing_agent_writer`).
- Modify tests: `test_tw_settle.py` (cost parts stay, race parts go), `test_tw_routes.py` (router-block cases → new block plus retired-key cases), `test_tw_codex.py` (route/rewrite assertions go), `test_tw_hook.py` (`pinned_routes` stops writing `classes`; add reminder cases), `test_tw_outcome.py`, `test_tw_claude.py` (drop `advise` expectations; keep `deny`).
- Create test: `thinker-worker/scripts/test_tw_tally.py`.
- Delete dirs: `thinker-worker/servers/` (Kev/Laya launchers), `thinker-worker/bench/` (router evaluation scripts), `thinker-worker/ROUTING-PROGRESS.md` (finished scaffolding; git keeps it).
- Prune `docs/plans/`: `2026-09-26-effort-routing-*`, `2026-09-27-effort-routing-switch-on-plan.md`, `2026-09-28-joint-routing-*`, `2026-09-28-router-ensemble-joint-routing-survey.md`.
- Modify docs: `thinker-worker/SKILL.md`, `references/claude.md`, `references/codex.md`, `references/add-model.md` (if it names router keys), `README.md` (thinker-worker section), `thinker-worker/knowledge/2026-10-25-decision-router-lessons.md` (a status line only).
- Outside the repo (Task 6): `~/.thinker-worker/routes.json` (Windows override), a vault decision note, and a memory update.

## Tasks

### Task 1: Config: routes.json, override merge, validation, priors line
Files: `routes.json`, `tw.py` (`OVERRIDABLE`, `merge_override`, `check_routes`, `priors_line`, delete `MODES` and `is_jev`), `test_tw_routes.py`, `test_tw_hook.py` (`pinned_routes`).
Interfaces: produces `routes["router"]` = `{priors, model_priors, defaults}`. After an override, the merged doc also carries `_override_ignored: list[str]`.
Steps:
1. In `routes.json`, delete `router.backends`, `kev`, `laya`, `combine`, `options`, `budget_s`, `risk_floor`, `table` and `classes`. Keep `defaults`, `priors` and `model_priors` byte-identical.
2. In `tw.py`:
```python
# The router keys the user override file may set; any other key (a retired router setting) is ignored and named by
# activate/status, so an override written for the old router keeps working.
OVERRIDABLE = {"priors", "model_priors", "defaults"}


def merge_override(doc: dict, ov_path: Path) -> dict:
    """Key by key over the installed router block: each OVERRIDABLE key is an object merged over the installed one
    (model_priors per model). The merged doc is validated like the installed one."""
    ov = read_json(ov_path, None)
    rt = ov.get("router") if isinstance(ov, dict) else None
    if (not isinstance(ov, dict) or set(ov) != {"router"} or not isinstance(rt, dict)
            or not all(isinstance(rt[k], dict) for k in OVERRIDABLE & set(rt))):
        raise Conflict("may set only router." + ", router.".join(sorted(OVERRIDABLE)) + " (each an object)")
    merged = json.loads(json.dumps(doc))
    mr = merged["router"]
    for k in sorted(OVERRIDABLE & set(rt)):
        v = rt[k]
        if k == "model_priors":  # per model: the override's table merges over the installed one
            mr[k] = {**mr.get(k, {}), **{m: {**mr.get(k, {}).get(m, {}), **t} for m, t in v.items()}}
        else:
            mr[k] = {**mr.get(k, {}), **v}
    check_routes(merged, ov_path)
    merged["_override"] = str(ov_path)
    merged["_override_ignored"] = sorted(set(rt) - OVERRIDABLE)
    merged["_override_model_priors"] = rt.get("model_priors", {})  # which prior values came from the override
    return merged
```
   In `check_routes`, delete `num`, `good_explore`, `good_class`, `good_jev`, `good_models` and the `budget`/`classes`/`floors` checks. The router test becomes:
```python
    rt = doc.get("router")
    priors = rt.get("priors") if isinstance(rt, dict) else None
    if (not isinstance(rt, dict) or not isinstance(priors, dict) or "*" not in priors
            or not set(priors) <= TASK_CLASSES | {"*"} or any(v not in TIERS for v in priors.values())):
        raise Conflict("routes.json: bad router block")
```
   (The `model_priors`, `archived` and `defaults` checks below it stay.) In `priors_line`, drop the `"; risk floors: ..."` segment and append `+ (f"; ignored override keys: {', '.join(routes['_override_ignored'])}" if routes.get("_override_ignored") else "")`. `RISKS` stays: the header still validates `TW-Risk`.
3. `test_tw_hook.pinned_routes`: delete the line that sets `doc["router"]["classes"]`.
4. `test_tw_routes.py`: delete the cases that test `classes`/`explore`/`mode`/`risk_floor`/`backends`/`combine`/`options`/`budget_s`/jev blocks. Add:
```python
def retired_override_keys():
    with tempfile.TemporaryDirectory() as d:
        ov = Path(d) / "routes.json"
        ov.write_text(json.dumps({"router": {"backends": [], "classes": {"*": {"mode": "active"}},
                                             "T4-hard-reasoning": {"explore": 0}, "priors": {"C-coding": "medium"}}}))
        os.environ["TW_ROUTES_OVERRIDE"] = str(ov)
        try:
            r = tw.load_routes()
        finally:
            del os.environ["TW_ROUTES_OVERRIDE"]
        assert "_override_error" not in r, r.get("_override_error")
        assert r["router"]["priors"]["C-coding"] == "medium"
        assert r["_override_ignored"] == ["T4-hard-reasoning", "backends", "classes"]
        assert "ignored override keys: T4-hard-reasoning, backends, classes" in tw.priors_line(r)
        assert set(r["router"]) == {"priors", "model_priors", "defaults"}
```
   and call it from the file's main block. Before the edit, check how the file calls `load_routes` (the `TW_ROUTES` pin bypasses the override) and make sure `TW_ROUTES` is unset inside this case.
Check: `"$PY" test_tw_routes.py && "$PY" test_tw_models.py`. Expected: both print PASS. Note that most other tests will fail until Task 2, because `route()` still reads `router.classes`.
Commit: `git add thinker-worker/routes.json thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_routes.py thinker-worker/scripts/test_tw_hook.py && git commit -m "thinker-worker: router config reduced to priors/model_priors/defaults; retired override keys ignored and named (Windows)"`. This is a WIP commit: the suite is red until Task 2.

### Task 2: Hook and pipelines without the router
Files: `tw.py` (`hook`, `codex_run`, `outcome`, `activate`, `status`, CLI, deletions listed in the file map, unused imports), the test deletions/edits listed in the file map, except `test_tw_tally.py`.
Interfaces: consumes `prior()` (unchanged). Produces `reminder(harness: str, d: Decision, routes: dict, brief: str) -> dict | None`. After this task, no new receipt has `kind: "route"` or `"race"`.
Steps:
1. Add, next to `denial`:
```python
def reminder(harness: str, d: Decision, routes: dict, brief: str) -> dict | None:
    """Claude only: an additionalContext line when an admitted dispatch's tier differs from its class prior, unless the
    user pinned the tier (TW-Pin). ponytail: Codex's handling of additionalContext without a decision is unverified."""
    p = prior(routes, harness, d.role, d.fields["TW-Class"], d.model)
    if harness != "claude" or d.tier == p or flagged(brief, "TW-Pin"):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext":
            f"thinker-worker: prior for {d.fields['TW-Class']} is {p}; you dispatched {d.tier} (fine if deliberate)"}}
```
2. In `hook`, delete the `rows = read_rows(...)` try-block and the `race_check(...)` call. Replace everything after `if d.role is None or tool == "collaborationspawn_agent": return` with:
```python
    out = reminder(harness, d, routes, envelope["tool_input"].get("prompt"))
    if out:
        print(json.dumps(out))
```
3. In `codex_run`, delete the block from `hint, row = routed(...)` through the `print(hint[...additionalContext])` line, and delete the trailing `if row and row["action"] == "rewrite": ... race ...` append. `record` is still needed for the activation check; keep it.
4. In `outcome`, delete the `if harness == "claude": race_check(...)` lines and the `state == "advise"` raise. In `dispatch_state`, keep the `advise` branch: historical advised dispatches never ran, and that stays true. Update the `outcome` docstring to match.
5. In `activate`, drop the `store_bodies` parameter and the record key. `activation()` keeps accepting the key in old records. In `status`, drop the `store_bodies` output line. In the CLI, drop `--store-bodies`.
6. CLI: remove the `route` and `promote` subcommands and their argument blocks. Leave `tally` for Task 3.
7. Delete the functions listed in the file map. Then run `rg -n "routed|race_check|advisory_flag|competing_agent_writer|quota\(|\bact\(|promote|ticket\(|epsilon|class_mode|backend" thinker-worker/scripts/tw.py`. Expected: no hits, except the word "promote" inside unrelated prose, which you then reword. Remove imports that are now unused (`random`, `threading`, `socket`, `math` if unused); check with `"$PY" -m pyflakes tw.py`, or failing that `"$PY" -We -c "import ast,sys; ast.parse(open('tw.py').read())"` plus the suite.
8. Tests: delete the seven files listed in the file map. In `test_tw_settle.py`, delete `race()`, its asserts, the advisory-flag case and the race-error case. Keep the cost-row cases, and rename the PASS line to `PASS settle: one cost row at outcome, torn sibling meta and transcript line skipped, torn receipts line skipped`. In `test_tw_codex.py`, `test_tw_outcome.py` and `test_tw_claude.py`, delete the assertions on `route`/`race` rows and on `advise`. In `test_tw_hook.py`, add:
```python
def reminder_cases():
    routes = tw.load_routes()
    d = tw.Decision(True, "admitted-request-only", "worker", None, "high",
                    {"TW-Class": "T1-mechanical", "TW-Deliverable": "x", "TW-Accept": "x", "TW-Risk": "none"})
    out = tw.reminder("claude", d, routes, "TW-Role: worker\nTW-Class: T1-mechanical")
    assert "prior for T1-mechanical is low; you dispatched high" in out["hookSpecificOutput"]["additionalContext"]
    assert tw.reminder("claude", d._replace(tier="low"), routes, "") is None            # at the prior
    assert tw.reminder("codex", d, routes, "") is None                                  # Codex: none
    assert tw.reminder("claude", d, routes, "TW-Role: worker\nTW-Pin: user high") is None  # pinned
```
   Call it inside the file's `pinned_routes()` context, so the shipped priors apply (T1 = low).
Check: the full suite command. Expected: only `SUITE_DONE`. Also `"$PY" tw.py --help` lists no `route` or `promote`.
Commit: `git add -A thinker-worker/scripts && git commit -m "thinker-worker: remove the tier router (exploration, backends, rewrite/advise, race and competing-writer guards, promote); hook keeps the prior reminder (Windows)"`.

### Task 3: `tally` replaces `promote`
Files: `tw.py` (`tally` + CLI), `test_tw_tally.py` (new).
Interfaces: `tally(home: Path, harness: str) -> list[dict]`, where each dict is `{"class", "model", "tier", "n", "accepted", "rate"}`. Reads `harness_rows` and `dispatch_key` (kept from before).
Steps:
```python
def tally(home: Path, harness: str) -> list[dict]:
    """Accept counts per (class, executed model, executed tier) over labeled, admitted dispatches. Label: the latest
    check row (pass/fail; unknown ignored), else the coordinator's latest outcome. Executed model/tier: the cost row's
    model and effort, else the tier of its tw-* agent_type; a dispatch with neither is counted at its requested tier
    with model None. Historical exploration rewrites therefore count at the tier that actually ran."""
    rows = harness_rows(home, harness)
    latest = lambda kind: {dispatch_key(r): r for r in rows if r.get("kind") == kind}
    disp, cost, out, chk = latest("dispatch"), latest("cost"), latest("outcome"), latest("check")
    groups: dict = {}
    for k, d in disp.items():
        m = re.search(r"^TW-Class: (.+)$", d.get("header") or "", re.M)
        label = {"pass": True, "fail": False}.get((chk.get(k) or {}).get("label"))
        if label is None:
            label = (out.get(k) or {}).get("accepted")
        if d.get("decision") != "admit" or not m or label is None:
            continue
        c = cost.get(k) or {}
        agent = AGENT_NAME.fullmatch(c.get("agent_type") or "")
        tier = c.get("effort") or (agent.group(2) if agent else d.get("tier"))
        g = groups.setdefault((m.group(1), c.get("model"), tier), [0, 0])
        g[0] += 1
        g[1] += bool(label)
    return [{"class": cls, "model": mod, "tier": t, "n": n, "accepted": a, "rate": round(a / n, 3)}
            for (cls, mod, t), (n, a) in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
```
CLI: a `tally` subparser with `--harness` (required) and `--home`, read-only, that prints one JSON line per group (copy how `promote` printed). The test `test_tw_tally.py`:
```python
"""tally: check outranks outcome; executed tier from cost; unlabeled, denied, headerless skipped.
Run: python test_tw_tally.py"""
import json
import tempfile
from pathlib import Path

import tw

H = "TW-Class: C-coding\nTW-Deliverable: x\nTW-Accept: x\nTW-Risk: none"
with tempfile.TemporaryDirectory() as home:
    home = Path(home)
    p = tw.receipts_path(home, "claude", "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"kind": "dispatch", "tool_use_id": "a", "decision": "admit", "header": H, "tier": "high"},
        {"kind": "cost", "tool_use_id": "a", "model": "claude-opus-5-5", "agent_type": "tw-worker-medium"},  # rewritten: ran medium
        {"kind": "outcome", "tool_use_id": "a", "accepted": True},
        {"kind": "dispatch", "tool_use_id": "b", "decision": "admit", "header": H, "tier": "high"},
        {"kind": "cost", "tool_use_id": "b", "model": "claude-opus-5-5", "agent_type": "tw-worker-high"},
        {"kind": "outcome", "tool_use_id": "b", "accepted": True},
        {"kind": "check", "tool_use_id": "b", "label": "fail"},                                          # check wins
        {"kind": "dispatch", "tool_use_id": "c", "decision": "admit", "header": H, "tier": "high"},       # unlabeled
        {"kind": "dispatch", "tool_use_id": "d", "decision": "deny", "header": H, "tier": "high"},
        {"kind": "outcome", "tool_use_id": "d", "accepted": True},                                       # denied
        {"kind": "dispatch", "tool_use_id": "e", "decision": "admit", "header": None, "tier": "high"},
        {"kind": "outcome", "tool_use_id": "e", "accepted": True},                                       # no header
        {"kind": "route", "tool_use_id": "a", "action": "rewrite"},                                      # old rows parse
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = tw.tally(home, "claude")
    assert got == [
        {"class": "C-coding", "model": "claude-opus-5-5", "tier": "high", "n": 1, "accepted": 0, "rate": 0.0},
        {"class": "C-coding", "model": "claude-opus-5-5", "tier": "medium", "n": 1, "accepted": 1, "rate": 1.0},
    ], got
print("PASS tally: check outranks outcome, executed tier from cost, unlabeled/denied/headerless skipped")
```
Before you run it, confirm that `receipts_path` really puts the file where `harness_rows` globs (`state_root(home)/"receipts"/harness`). If it doesn't, write to the path `harness_rows` reads.
Check: `"$PY" test_tw_tally.py`, which should print PASS; then a read-only run on real data, `"$PY" tw.py tally --harness claude | head`, which should print JSON lines with C-coding/T4 groups. Control: the real-data sum of `n` should be about 1,100 (≈1,227 outcome rows minus duplicate labels and Codex v2). If it's far off, find out why before committing.
Commit: `git add thinker-worker/scripts/tw.py thinker-worker/scripts/test_tw_tally.py && git commit -m "thinker-worker: tally (accept counts per class/model/executed tier) replaces promote (Windows)"`.

### Task 4: Delete router-only files
Files: `thinker-worker/servers/`, `thinker-worker/bench/`, `thinker-worker/ROUTING-PROGRESS.md`, the `docs/plans/` files listed in the file map.
Steps: first `"$PY" thinker-worker/servers/decision_servers.py status`. If anything is up, run `stop` (these are processes this repo's launcher started), then `git rm -r` the files. Confirm `SKILL_FILES` in `tw.py` names none of them (it doesn't at f64055a).
Check: `rg -n "servers/|bench/|ROUTING-PROGRESS" thinker-worker README.md`. Expected: no hits outside `knowledge/` (fixed in Task 5).
Commit: `git commit -m "thinker-worker: drop decision servers, router bench, routing progress and router plans (git keeps them) (Windows)"`.

### Task 5: Docs describe the router-less skill
Files: `SKILL.md`, `references/claude.md`, `references/codex.md`, `references/add-model.md`, `README.md`, `knowledge/2026-10-25-decision-router-lessons.md`.
Steps:
1. `SKILL.md` line 20: replace the span from "Pick the tier from the priors `activate` prints" through "…label it: `tw.py outcome" (exclusive) with:
   > Pick the tier from the priors `activate` prints for the brief's `TW-Class`; deviate by judgment when the brief is clearly easier or harder than its class; physics or convention judgment never below `medium`; `high` or `xhigh` for adversarial reasoning. The priors live in `routes.json` `router.priors` (a class without an entry takes `*`; the result is clamped into the role's tiers) and `router.model_priors`, merged key by key with the user override file `~/.thinker-worker/routes.json` (or `TW_ROUTES_OVERRIDE`), which may set `router.priors`, `router.model_priors` and `router.defaults` and survives reinstalls (e.g. `{"router": {"defaults": {"independent-review": "fable"}}}`); other keys there are ignored and named by `activate`/`status`; a bad override is ignored, logged as an `error` row (`where: "override"`) on every dispatch, and named by `activate`/`status`. The guard never changes your tier. In Claude Code a dispatch at a tier other than its prior gets one `additionalContext` line (`thinker-worker: prior for <class> is <tier>; you dispatched <tier> (fine if deliberate)`). When the user asked for a model or effort, add `TW-Pin: user <what was asked>` in lines 2–12; it suppresses that line. After accepting or rejecting a child's result,
   
   Then, in the rest of that paragraph, drop "advised by the router" from the list of things `outcome` refuses. After the `outcome` sentences, add: "`tw.py tally --harness <h>` prints accept counts per class, executed model and executed tier (a `check` label outranks yours); move a prior in `routes.json` when a class's counts clearly support it." Delete the exploration-protocol list (lines 22–26). In the Codex-pipeline paragraph (line 34), delete the sentences from "After admission the router acts as on a native dispatch" to the end of that paragraph.
2. `references/claude.md`: delete the paragraphs **Routing**, **Decision servers** and **Exploration protocol**, the `route` and `race` receipt bullets, the `tw.py route` paragraph (line 33) and the promotion paragraph (line 35). Add one sentence on `tally`. Keep the `context-mode` paragraph's heal/nudge text, but delete its sentences about the competing-writer guard.
3. `references/codex.md` line 17: replace it with "Plaintext Codex dispatches get no router decision and no prior reminder. `tw.py outcome` and `tally` take `--harness codex`." Keep the `TW-Check` sentences of that line unchanged. Delete lines 19–23 (the exploration protocol) and the exit-2 "or advised" wording in line 27.
4. `README.md` thinker-worker section: replace the router sentences (from "After admission a router logs" through "the rest run at the coordinator's tier.") with "After admission the guard adds, on Claude, a one-line reminder when the tier differs from the class prior; it never changes the tier." Change `route`/`outcome`/`promote`/`codex` to `outcome`/`tally`/`codex`, and "router config" to "tier priors".
5. In the knowledge note, under the Status line, add "Superseded 2026-11-02: the router was removed (docs/plans/2026-11-02-thinker-worker-router-removal.md); kept as the record of why."
Check: `rg -n -i "explor|advis|rewrite|backend|kev|laya|promote|TW-Override|TW-Route|risk.floor|race|router\.classes|shadow|budget_s|tw.py route" thinker-worker/SKILL.md thinker-worker/references README.md`. Expected: no hits. If one is legitimate (e.g. "explore" in unrelated prose), list it in the commit message.
Commit: `git add -A thinker-worker README.md && git commit -m "thinker-worker docs: no router; priors + reminder + tally (Windows)"`.

### Task 6: Install, live check, local state
Files: installed copies (via `upgrade`), `~/.thinker-worker/routes.json`, the vault, memory.
Steps:
1. `"$PY" thinker-worker/scripts/tw.py upgrade`, then `check`. Expected: `installed: true`, with the same sha as the source `tw.py`.
2. Rewrite `~/.thinker-worker/routes.json` to `{"router": {}}`. The previous content was `classes`/`backends` only, and `T4-hard-reasoning` explore 0, all now retired. Keep `routes.json.bak-2026-11-02`.
3. Live check in this session: `activate`, then dispatch one `tw-leaf-low` brief with class `T2-simple-transform` (prior low; no reminder expected), then one `tw-leaf-medium` with the same class (reminder expected). Confirm in the session receipts: two `dispatch` admit rows and no `route` row. Then `outcome --accepted yes` on one, and `tally --harness claude` includes it. Control: the second dispatch must show the reminder line. If neither shows a reminder, the hook isn't running the new code.
4. Vault: write `~/obsidian-vault/03-decisions/2026-11-02-thinker-worker-router-removed.md` (read `~/obsidian-vault/CLAUDE.md` for the schema first): the decision, the receipt evidence (numbers from the Design line), what replaced it (`tally` and hand-tuned priors), and what would bring a router back (a backend that clears acceptance parity on labeled data).
5. Memory: update any memory line that names the router, Kev/Laya or `promote` (rg the memory dir).
Mac: the next `git pull` plus `tw.py upgrade` there installs this. Its override, if any, keeps working (retired keys are ignored).
Check: step 3's receipts and control.
Commit: nothing in the repo; the vault commits in its own repo (`git -C ~/obsidian-vault commit -- <note>`).

## Self-review
- Coverage: exploration, backends (kev/laya/table/jev), combine, rewrite/advise, race, competing-writer, quota, promote and store_bodies are removed (Tasks 2–4). Kept: guard (`decide` untouched), priors and reminder (1, 2), outcome/check/cost (2), tally (3), docs (5), install (6). Codex: `codex_run` (2), hook path shared (2), codex.md (5).
- Old data: `dispatch_state` keeps `advise`; `tally` ignores `route`/`race` rows; the test includes an old route row.
- Not covered: the `kev` repo and the Local-Agent decision envs (Arian's call on deleting them); Mac upgrade (next sync).
- Strongest argument against: without exploration, no new evidence arrives that a lower tier suffices. `tally` only sees the tiers I choose. Mitigation: the 104 historical rewrites already sit in `tally` at their executed tier, and a deliberate lower-tier trial can be dispatched by hand when a class looks over-tiered.
