# Effort routing across Claude Code and Codex: architecture design

Status: DRAFT 3, 2026-09-26 (Windows), for Arian's yes. No code changed. Supersedes drafts 1–2 (git history).
Written from scratch per Arian ("not attached to prior setup; R&D and prototyping"). Evidence files are in
`~/.claude/notes/effort-routing/` (probe reports, ordering probe, audit, model survey, review resolutions).

Labels: **[V]** verified this session (ran or read, artifact named), **[D]** primary documentation read this
session, **[3P]** a third party's own number, **[I]** inference, **[A]** Arian's ruling, **[?]** open.

## 0. The decision in one paragraph

A dispatch picks a *cell* (model, effort tier) for a *role* (worker, leaf, review, ideation) on a *harness*.
Proposed: one data file `routes.json` holds **model policy** (which models each role may run, per harness;
kept strict and adjustable [A]) and loose **effort bounds** (which tiers a role may use); one function
`route(harness, role, header, body) → {tier, probs, confidence, source}` picks the tier inside those bounds
through a pluggable backend; the thinker-worker PreToolUse hook is the single observation point and, on
Claude, the actor: it gates (fail closed), writes the receipt (fail closed), then routes within a 2 s budget
(fail open) and, per class mode, logs (`shadow`), denies a disagreement with the suggestion (`advisory`), or
rewrites the dispatch to the router's tier agent (`active`, verified possible today). On Codex v2 the brief is
ciphertext, so there the coordinator calls `tw.py route` first and the ticket rides in `task_name`. Backends
are small resident local scorers compared as equal arms (SemIf over a 4B GGUF with AnyJev's bias-free
readout, Kev-0.8B, Eos-0.8B, Laya); none is preset as the first backend; nobody launches the 27B for this. Backends
run in shadow on real receipts first, then `table`-driven exploration generates two-sided tier labels, and
the backend is chosen on those labels (§5); promotion is by a posterior rule with a hold band, and per-class
promotion is out of reach of the five-session run, only a pooled one.

## 1. Mechanism facts the design rests on

| Fact | Status | Evidence |
|---|---|---|
| Claude: Agent has `model` per call, no effort field; effort comes only from the agent file's `effort:` | [V] | setup plan step 1: `CLAUDE_EFFORT` read `low`/`xhigh` in miner children with the parent at `high` |
| Claude: a PreToolUse hook **can rewrite** an Agent dispatch. `updatedInput` on `subagent_type` and `model` is honored (child `meta.json` `agentType: effortmining:miner-xhigh`, `EFFORT=xhigh`; child `message.model = claude-sonnet-5`) | [V] | `2026-09-26-hook-updatedinput-probe-report.md` runs B2/C2, context-mode disabled |
| Claude: hooks on one call run **in parallel** and when several return `updatedInput` the **last to finish wins**, whole object, no merge; listing order and settings-vs-plugin source do not matter. context-mode's Agent hook returns a full replacement on every dispatch (~350–380 ms Node start) | [V] 7/7 runs | `2026-09-26-hook-ordering-probe-report.md` O1–O6, O4/O4b |
| Claude: hook outputs come in two kinds. **Additive** channels (`additionalContext` on SessionStart, SubagentStart, PreToolUse, PostToolUse) compose: "When several hooks return `additionalContext` for the same event, Claude receives all of the values." **Replacing** channels (`updatedInput`) do not compose (row above). So `updatedInput` on a tool is a single-writer resource | [D] + [V] | hooks doc "Add context for Claude"; ordering report |
| Claude: SubagentStart `additionalContext` is injected into the subagent before its first prompt; a re-run does not duplicate it, and "the copy injected at launch stays in place, leaving the subagent's prompt cache intact" | [D] | hooks doc, SubagentStart |
| Claude: "There is no way to disable an individual hook while keeping it in the configuration"; only whole-plugin `enabledPlugins` or global `disableAllHooks` | [D] | hooks doc, "Disable or remove hooks" |
| context-mode's Agent hook uses a replacing channel for an additive job: it copies the input and appends a ~4.6 k-char routing block to `prompt` (`hooks/core/routing.mjs:907-928`, v1.0.169). It is its only `updatedInput` writer on `Agent`; its other hooks are additive, capture-only, or on other tools | [V] | `%TEMP%\tw-probe\context-mode-assessment.md` §1 |
| Subagent ctx use, 30 d: 35/57 used a ctx tool when the parent's own prompt mentioned ctx, 24/511 (4.7 %) when only the injected block did; the Read/Bash/Grep tips fire once per session (`routing.mjs:121-144`) and reached 14 of the 59 users | [V] | assessment §2, split script this session |
| Claude: a PreToolUse command hook that hits its `timeout` is cancelled and **does not block** the call; hooks have no user-interaction channel except `permissionDecision: "ask"` on the tool call itself | [D] | code.claude.com/docs/en/hooks, "Timeouts", JSON output table |
| Claude: a coordinator-invoked Bash round trip costs 4.3–8.7 s wall here (other Bash hooks dominate; API ~1 s), 74 output tokens, and a cache read of the whole coordinator context; a `--brief-file` path emits the brief twice | [V] | review resolutions §2, probe transcript `ceae70b8-…` |
| Claude: subagent transcript usage is per API call with one row per content block; the last row per `message.id` carries the true `output_tokens`; the parent's `toolUseResult.totalTokens` is the last call's context size, not a total | [V] 60 transcripts | review resolutions §13 |
| Codex: `spawn_agent` takes `model` and `reasoning_effort` per call; on v2 `message` is ciphertext but **`task_name` is plaintext** on all 1,640 v2 spawns in Arian's rollouts (charset `[a-z0-9_]`, ≤ 35 chars) | [V] rollouts; hook-side visibility [I] | review resolutions §7 |
| Codex: docs say PreToolUse can "block or rewrite" local function tools incl. `spawn_agent` | [D, unverified on the real path] | learn.chatgpt.com/docs/hooks |
| Coordinator logits are not obtainable: the Anthropic Messages API reference has no logprobs field; OpenAI's Responses API has `logprobs` but the Codex harness does not surface it | [D], [I] for the harness | platform.claude.com/docs/en/api/messages; developers.openai.com reasoning guide |
| Small local scorers cannot load per call: Laya typed-decisions loads in 6.9–7.5 s on CPU (process 9.3–9.8 s), Kev's Qwen base alone ~6 s, against the hook's 10 s timeout; warm scoring 0.15–0.26 s per question | [V] | review resolutions §4, `loadtime.py` |
| Input limits per backend: Laya typed-decisions 1,024 tokens (~2,400 body chars, silent truncation), Laya English 512, Kev trained at 384 tokens (~1,100 chars), the 27B 262k | [V] configs and tokenizer counts | review resolutions §6 |
| effortmining calibration: Opus 4.8, n = 9–18 per class, all `confidence: low`, bench path `claude -p --effort`; the Opus 5.5 run with a difficulty knob is in the parallel handoff | [V] | `bench/state/calibration.json`, `bench/effort.py:968-985` |
| Output tokens do not separate tiers on an easy closed-form task on Opus 5.5 | [V] | setup plan step 1 |
| Receipts today: 38 dispatch rows, 0 with a header, 0 outcomes | [V] | tally this session |
| Hermes/Local-Agent benches of decision models: **not evidence here** | [A] | Arian, rounds 1 and 3 |

## 2. Requirements [A]

1. thinker-worker owns routing, modularly: routing table is data, backend is pluggable.
2. Local Jev-like decision models are first-class, for speed at dispatch time. Options now: SemIf (4B only),
   Kev-0.8B, Eos-0.8B, Laya. AnyJev is a readout layer over any of the logit backends, not a model.
3. Coordinator-assigned effort per dispatch on both harnesses, review and ideation included.
4. effortmining is calibration and training data; its calibration runs are the offline testbed for router
   backends (Arian, round 3), never the router.
5. Model policy stays a strict, adjustable gate; effort policy is loose once routing is calibrated (round 2).
6. Brief bodies may be stored privately for replay and training (round 1). Mac falls back to a local CPU
   scorer or the coordinator (round 1).
7. One writer for Agent-call rewrites: the router. context-mode stays installed (Arian, 2026-09-26); its
   Agent hook is patched out and its subagent nudge moves to an additive channel (§4.6).
8. Simpler than what exists.

## 3. Approaches, re-ranked after the probes

### Approach A: hook-resident router on Claude, CLI on Codex v2 — RECOMMENDED

- Claude: the hook already parses the plaintext brief; it calls a resident local scorer within 2 s, writes
  the route row, and per class mode logs / denies-with-suggestion / rewrites `subagent_type` to the tier agent.
  `shadow` costs the coordinator nothing and keeps it blind by construction. `advisory` costs one wasted
  Agent round trip only on above-cutoff disagreement. `active` costs nothing and is the Hermes "active" rung.
- Codex legacy (plaintext): same as Claude minus the rewrite until the Codex rewrite path is probed.
- Codex v2: coordinator runs `tw.py route` (one round trip), names the task `<slug>_r<ticket>`, dispatches
  with the returned `reasoning_effort`; the hook gates model/effort and joins the route row by `task_name`.
- Constraint: exactly one `updatedInput` writer on `Agent` (§4.6).
- Weakness: the hook's 10 s budget must be measured on Windows with the portable wrapper before `enforce`;
  a router that overruns turns the gate fail-open (§4.5 keeps the router at ≤ 2 s for that reason).

### Approach B: coordinator-invoked CLI everywhere

- Uniform on both harnesses; no hook rewrite, no coexistence constraint.
- Measured cost on Claude: 4.3–8.7 s and a full-context cache read per dispatch, plus the brief emitted twice.
  On a 150k-token coordinator that is ~150k cache-read tokens per route call. Not acceptable as the default;
  kept as the Codex v2 path and as an explicit "ask the router first" option on Claude.

### Approach C: dispatch workers as headless CLI processes

- `claude -p --effort` / `codex exec` give native per-call effort and equal effortmining's bench path, but
  lose the harness's agent integration, prompt-cache sharing (stripped `-p` runs cost $0.36–0.40 each), and
  the hook as observation point. Rejected as the dispatch path; it stays the calibration path.

### Approach 0: coordinator routes alone

The baseline every backend must beat; it is the `coordinator` backend below.

## 4. Recommended architecture (Approach A)

### 4.1 Components

| Component | Where | Replaces |
|---|---|---|
| `routes.json` | shipped with the skill, installer-copied, manifest-hashed | `CODEX_*`, `CLAUDE_*`, `CLAUDE_ROLES`, `MINER_TYPE`, `CODEX_EFFORTS` (`tw.py:28-45`) and three inline role maps |
| `route()` + backends | `tw.py` (stdlib `urllib`) | new |
| `tw.py route` CLI | `tw.py` | new; Codex v2 and opt-in on Claude |
| `tw.py serve --backend <name>` | `tw.py` or a 30-line stdlib `http.server` wrapper | new; the resident scorer, asks before downloading weights on first run |
| Tier agents `tw-<role>-<tier>.md` | generated by `tw.py install` from `routes.json` | `thinker-worker-{opus,sonnet,fable-review}.md`, the missing dreamer, the `effortmining:miner-*` special case |
| Hook | `tw.py hook` | same entry; order gate → receipt → route → enforce; smaller `decide()` |
| Receipts | `~/.thinker-worker/receipts/` | same files; new `kind: route` and `kind: cost` rows |
| Body store | `~/.thinker-worker/bodies/<session>/<ticket>.md` | new; private, home repo ignores it (`.gitignore:2 *`) |
| Activation | `tw.py activate --harness --session` | the four per-role flags go |

### 4.2 `routes.json` (sketch, schema 1)

```json
{
  "schema": 1,
  "tiers": ["low", "medium", "high", "xhigh"],
  "harnesses": {
    "claude": {
      "apply": "agent",
      "roles": {
        "worker":   {"model": "opus",   "tiers": ["low","medium","high","xhigh"], "default": "high", "tools": null},
        "leaf":     {"model": "sonnet", "tiers": ["low","medium"],                "default": "low",  "tools": null},
        "review":   {"model": "fable",  "tiers": ["high","xhigh"],               "default": "high", "tools": null},
        "ideation": {"model": "fable",  "tiers": ["high","xhigh"],               "default": "high", "tools": null}
      }
    },
    "codex": {
      "apply": "reasoning_effort",
      "roles": {
        "worker":   {"models": ["gpt-6-sol","gpt-5.6-sol","gpt-5.6-terra"], "tiers": ["low","medium","high","xhigh"], "default": "high"},
        "leaf":     {"models": ["gpt-6-luna"],              "tiers": ["low","medium"],                "default": "low"},
        "review":   {"models": ["gpt-6-astra"],             "tiers": ["medium","high","xhigh"],      "default": "high"},
        "ideation": {"models": ["gpt-6-astra"],             "tiers": ["medium","high","xhigh"],      "default": "high"}
      }
    }
  },
  "router": {
    "backends": ["<Stage-3 winner>", "table"],   // phase 1 ships []: coordinator only until the Opus 5.5 table lands
    "fallback": "coordinator",
    "budget_s": 2.0,
    "semif4b": {"url": "http://127.0.0.1:8765", "readout": "anyjev-L0", "body_chars": 4000},
    "kev":     {"url": "http://127.0.0.1:8766", "body_chars": 1100},
    "laya":    {"url": "http://127.0.0.1:8767", "body_chars": 2400},
    "eos":     {"url": "http://127.0.0.1:8768", "body_chars": 4000},
    "table":   {"path": "<effortmining>/bench/state/calibration.json"},
    "cutoff": 0.85,
    "classes": {"*": {"mode": "shadow", "explore": 0.0}}
  }
}
```

Notes. (a) Claude roles pin **one** model in the generated agent file (`model:` + `effort:`); a per-call
`model` that differs from the file is denied (per-invocation overrides frontmatter [D]). Model is a role
property, effort is the dispatch's. (b) Codex keeps per-call `model` + `reasoning_effort`; a non-empty
`tiers` list means effort is required. (c) `backends` is an ordered preference list; the first reachable
server answers; `source` records which. `body_chars` is per backend (§1); the route row records
`body_chars_sent` because Laya truncates silently. (d) Placeholder values that are Arian's decisions: §7.
The worker `"default": "high"` on both harnesses is the phase-1 value (see §7 decision 7).
(e) `semif4b` port numbers and the 4B GGUF choice (`Qwen3.5-4B-Q4_K_M` is SemIf's documented example) are
implementation details for the plan.

### 4.3 `route()` and the scorer question

```
route(harness, role, header: dict, body: str, cfg) -> {
  "tier": "medium", "probs": {"low": .12, "medium": .71, "high": .15, "xhigh": .02},
  "confidence": .71, "source": "semif4b" | "kev" | "table" | "coordinator",
  "mode": "shadow", "ms": 180, "body_chars_sent": 4000, "ticket": "7f3a…"}
```

- `coordinator`: the role default, confidence 0. Baseline.
- `table`: effortmining `calibration.json` class → tier (Opus 5.5 after the parallel calibration run). It is
  a **prior on the class, not a per-dispatch signal**: the Opus 5.5 synthetic tasks saturate at `low` for
  nearly every class (`~/Code/effortmining-runs/2026-09-26-opus55/PROGRESS.md`), so in shadow `table` marks
  almost every dispatch "router wanted lower". That fills the coordinator arm fast but carries no information
  about the individual brief.
- `semif4b`: one closed-set question over the state (four header keys + body prefix), letters → tiers,
  temperature 0, scored from a 4B GGUF's logits by SemIf (llama.cpp on CPU, MLX on the Mac). The
  `anyjev-L0` readout averages option-order bias over rotations and divides out the label prior with zero
  labels; `L1` adds a temperature once ~100 labels exist. Question text: "A coordinator is delegating this
  brief to a <model> worker on <harness>. Choose the lowest reasoning-effort tier at which the worker still
  meets the TW-Accept line." Option descriptions come from effortmining's class vocabulary.
- `kev`, `eos`, `laya`: the same state and options through each model's typed `choice` API. All four
  backends are equal arms in Stage 3 (§5); the winner becomes `backends[0]` (Arian, 2026-09-26).

All backends run as **resident servers** started by `tw.py serve`, never loaded in the hook (§1). The
router is deterministic for a single request on CPU; a batching server can move a first-time score with
batch composition (Thinking Machines 2025), hence the 0.85 cutoff and the class hold band (§5). The scorer
sees the body at decision time; receipts never store it; the body store does.

### 4.4 Per-dispatch flow

Claude:
1. Coordinator writes the brief: `TW-Role:` line, header (`TW-Class`, `TW-Deliverable`, `TW-Accept`,
   `TW-Risk`), body. No 600-char cap; no per-value cap below 1,000 at the gate.
2. Coordinator dispatches `Agent(subagent_type="tw-<role>-<tier>", prompt=…)` with its own tier pick. No
   `model` argument. (Optional: `tw.py route --brief-file` first, when it wants advice before dispatching;
   `shadow` mode prints only a ticket.)
3. Hook, in order: **gate** (role allowed, `subagent_type` is a generated agent for that role with a tier in
   the role's list, no per-call model mismatch, no fork/resume keys, header present) → **receipt** (dispatch
   row, header values truncated at 256 chars with `…[+N]`, `route: pending`) → if denied, deny and stop →
   **route** in a daemon thread joined at 2.0 s; any exception, timeout, unreachable server, or invalid
   probs → `source: coordinator` → append `kind: route` row (ticket = first 12 hex of SHA-256 over the
   normalized brief minus any `TW-Route:` line, full digest stored) → **act** per class mode: `shadow`
   nothing; `advisory` deny with "router picks <tier> (p); add `TW-Override: <reason>` to keep <tier>" when
   confidence ≥ cutoff and tiers differ and no override line; `active` return `updatedInput` with
   `subagent_type` swapped to the router's tier agent (same override escape) and the prompt untouched;
   if another `updatedInput` writer on `Agent` is registered (§4.6 guard), act as `advisory` for that
   dispatch instead.
4. Cost rows at `outcome` (no SubagentStop hook; Fable review of the phase-1 plan, 2026-09-26). When the
   coordinator labels a child, find its transcript through `meta.json` (`toolUseId`). Group the assistant
   rows by `message.id`, keep the last row per id, and sum input / cache-create / cache-read / output into
   `kind: cost`. Not the parent's `totalTokens`. A labeled child has finished, so its transcript is final.
   Unlabeled children get no cost row.
5. Coordinator labels: `tw.py outcome --tool-use-id … --accepted yes|no` (exists).

Codex: step 1 identical; step 2 is `tw.py route` then `spawn_agent(model, reasoning_effort=<tier>,
task_name="<slug>_r<ticket>", message=…)`; step 3 on v2 gates model/effort only and joins the route row by
the `task_name` suffix (no suffix → `source: coordinator`; whether `task_name` reaches the hook unchanged is
the first Codex probe in the plan); no rewrite on Codex until its hook-rewrite path is probed; step 4 is
manual from turn metadata.

### 4.5 Policy split, fail modes, privacy

- **Model policy** (data, fail closed): role → model(s) per harness, fresh dispatch only, no inherited-model
  child, header and role line present. The part Arian keeps strict and adjustable.
- **Effort policy** (loose): the gate checks only that the tier is inside the role's `tiers`. Holding the
  coordinator to the router's tier is a per-class mode switched on from evidence, never a standing rule.
- **Router: fail open inside a 2 s wall budget the hook enforces itself.** A hook that overruns its 10 s is
  *allowed* by Claude Code, so the router's own budget is what keeps the gate closed. Gate and receipt run
  before the router and stay fail closed.
- **Receipts** store header (values truncated at 256 with marker), ticket + digest, coordinator tier, router
  tier, probs, source, mode, `body_chars_sent`, outcome, cost. Never the body.
- **Body store** `~/.thinker-worker/bodies/<session>/<ticket>.md`, opt-in per session, never synced [A].

### 4.6 One writer on `Agent`

**Rule: each tool's `updatedInput` has exactly one owner, and a hook that only adds text uses an additive
channel.** Claude keeps the last `updatedInput` to finish and discards the rest, while `additionalContext`
values all arrive (§1). The router's Agent rewrite changes the call (`subagent_type`), so it needs the
replacing channel and owns it. context-mode's Agent hook only appends prose, so it belongs on SubagentStart.

Decided (Arian, 2026-09-26): keep context-mode and remove its one conflicting hook. Assessment:
`%TEMP%\tw-probe\context-mode-assessment.md`. In it, all of context-mode's steering and capture hooks together
cost ~1.7 % of cost-weighted input over 30 days; the Agent block is 0.7 % of subagent input, the SessionStart
block 2.7 % of main.

1. **Patch:** delete the `PreToolUse` `"matcher": "Agent"` entry from the active context-mode
   `hooks/hooks.json`. Patch the JSON rather than `routing.mjs`: the hook process no longer spawns, the
   reapply is a parse-filter-write that tolerates upstream edits elsewhere, and context-mode's own normalizer
   only rewrites command paths inside existing entries (`hooks/normalize-hooks.mjs:95-130`) [V]. Keep its
   `PostToolUse` Agent capture (no input channel).
2. **Heal:** `~/.claude/hooks/plugin-patch-heal.mjs` removes that entry from the newest context-mode version
   dir at SessionStart and says so. That means auto-reapply, not the warn-only mode of the curl-gate check.
   Register it in `plugin-patches.json` and the vault's `local-plugin-patches.md`. The first session after a
   plugin update probably still carries the hook, if hooks load before SessionStart runs [I].
3. **Nudge:** a small SubagentStart hook of its own, not part of the router, returns a one-line
   `additionalContext` naming the ctx tools and their `ToolSearch select:` bootstrap (~60 tokens vs ~1.2 k).
   It emits only while `enabledPlugins["context-mode@context-mode"]` is true, so removing the plugin
   silences it. The router has no dependency on context-mode.
4. **Guard (Arian, 2026-09-26: mtime variant).** The hook set is fixed at session start. [V] In this
   session, with the Agent entry removed from `hooks.json` on disk, a fresh subagent's prompt still carried
   `<context_window_protection>` (control before the edit: present; test after the edit: present; file
   restored, sha1 `85c970cd…` and mtime unchanged). So the guard reasons about when the disk changed:
   - Resolve the active context-mode `hooks.json` via `installed_plugins.json` → `installPath`. If a
     PreToolUse `Agent` entry is present, the dispatch goes `advisory`.
   - If the entry is absent but `mtime(hooks.json) >= session_start − 1 s`, the heal patched it after this
     session loaded, and the whole session goes `advisory`. The 1 s allows for coarse mtime resolution;
     errors fall toward `advisory`, which is safe.
   - `session_start` is the start time of the Claude Code process, not the transcript. Per the Fable
     session's measurement [3P] (session 7609ebe8), the heal's write lands ~1.5 s after process start,
     before the transcript's first record and before the file exists. Anchoring on the transcript would
     read "clean" in exactly the dirty case.
   - Take the process start from the first ancestor of the hook process named `claude.exe` (Windows) or
     `claude`/`node` (Mac). The chain is ~5 hops: cmd → bash ×3 → claude.exe, per the same [3P]
     measurement. On Windows tw.py walks the ancestors with stdlib ctypes (`CreateToolhelp32Snapshot`,
     `GetProcessTimes`): 11–14 ms per call [V, 2026-09-26], so it is not cached. The Mac path uses `ps`
     and is unverified.
   - A context-mode entry "applies to Agent" by Claude Code's own matcher rule, read from the binary [V]:
     `""`/`*` match all; a plain `[A-Za-z0-9_|]` matcher is split on `|` and compared exactly after the
     legacy map (`Task` → `Agent`); anything else is `RegExp.test` (match anywhere).
   - The current `hooks.json` mtime is 2026-07-06 [V], so ordinary sessions do not false-positive.
   - **Tripwire:** at each dispatch and at `outcome` (so a session's last rewrite is checked before it is
     labeled), for each earlier rewrite not yet checked, compare the child's `meta.json` `agentType`,
     which is written at spawn, with the router's pick. If it differs, write a `race` receipt with
     `lost: true` and set the session to `advisory`. The `<context_window_protection>` text in the child's
     first user message counts only when `meta.json` lacks `agentType`, since briefs in this project can
     quote that tag. A lost race is then never silent, and `promote` counts only rewrites whose race row
     says `lost: false`.
5. **Measure:** the parent-silent subagent ctx rate was 24/511 (4.7 %) with the old block. Re-run the split
   after a week with the one-line nudge. If it falls well below that, lengthen the nudge; do not restore the
   prompt append.

Steps 1-2 landed on 2026-09-26 (home repo `a127a91`), and the O7a–c re-probe passed 3/3: the router's
`miner-xhigh` pick ran, with no `<context_window_protection>` and two nudge lines in each child prompt [V]
(the pre-patch O4b ran `low` with the block). `active` still stays off until a backend is switched on.
`shadow` and `advisory` return no `updatedInput` and are unaffected.

### 4.7 What is deleted (audit-backed)

Per-role activation flags and record fields; hardcoded constants and inline role maps; `MINER_TYPE`;
`CODEX_EFFORTS`; four brief scanners → one parser splitting on `\n` only (fixes `tw.py:171,176`);
`TW-Opus-Reason`; `effortmining:miner-*` as a TW route (miners stay bench-only); the three hand-written
agent files and the never-shipped dreamer; the 600-char total header cap (replaced by receipt-side
truncation at 256). Kept: fresh-dispatch-only checks, fail-closed gate and receipt, the `small()` 128-char
rule on identifier fields.

### 4.8 The one runnable check

`scripts/test_tw_route.py`: (1) `route()` with `backend: table` returns the class default; (2) with a stub
server returning fixed logits, normalised probs and the argmax; (3) with the stub down, `source:
coordinator` and no denial; (4) with the stub sleeping 5 s, the hook still writes the receipt and admits
within budget; (5) `advisory` denies a disagreeing brief and admits it with `TW-Override:`; (6) `active`
returns `updatedInput` whose `subagent_type` is the router's tier agent; (7) `install` in a temp home
generates `tw-worker-{low,medium,high,xhigh}.md` with matching `effort:` and no `max`. Each has a reachable
FAIL.

## 5. Evaluation: shadow, exploration, backend selection, then advisory

**What a receipt row can say.** Let c be the cheapest sufficient tier for a brief. An accepted dispatch at
tier t says only c ≤ t; a rejection at t that the coordinator attributes to the tier (not to the brief) says
c > t. Until something below the coordinator's tier is tried, every row is an upper bound, and on
upper-bound rows "always `low`" is consistent with every row and cheapest: the grids' saturation failure
again, on real data. Lower bounds come only from exploration, or from offline replay of a stored body at a
lower tier (expensive for agentic briefs, impossible for destructive ones). Hence the order below: labels
first, backend choice after. The outcome label needs a tier-attribution field for this; `tw.py outcome`
records only accepted yes/no today (phase 2).

**Stage 1, shadow on receipts (elimination round).** Router logs; coordinator blind. Every arm scores every
dispatch: the configured backend live on the route row, the others offline over the stored bodies
(`--store-bodies`). Outputs per arm: per-class agreement with the coordinator, latency, and the confidence
distribution with its calibration against the outcomes so far. An arm that is broken, too slow for the 2 s
budget, or badly calibrated is dropped here. The effortmining grids are not a selection set: on Opus 5.5 the
synthetic tasks saturate at `low` (the X1.3 gradient was a harness artifact, `PROGRESS.md` above), so every
backend that says `low` would score perfectly. The grids remain a smoke test that each backend answers and
the source of the `table` prior.

**Stage 2, exploration driven by `table` (label generation).** Exploration needs no chosen backend. `table`
says `low` for nearly every class (§4.3), so a class in `advisory` with `backends: ["table"]` and
`explore: ε` runs a fraction ε of the dispatches the coordinator sent above `low` at `low` (the denial says
"exploration"; `table`'s confidence is 0, so no other denial fires). The risk floor applies (below). An
explored dispatch accepted at `low` fixes c = `low`; one rejected at `low` for tier reasons and then accepted
at the coordinator's tier t gives `low` < c ≤ t. These are the two-sided rows.

**Stage 3, backend selection on interval labels [A].** Every Stage-1 survivor scores every labeled stored
brief. Metrics per arm, chosen to be robust to the censoring above:
(i) definite over-routing rate: the pick is strictly above a tier that was accepted;
(ii) definite under-routing rate: the pick is at or below a tier that was tried and rejected for tier reasons;
(iii) the fraction of rows with a two-sided interval, always reported next to (i), since a low (i) means
something only when enough rows could have exposed under-routing.
Latency and calibration carry over from Stage 1. The winner becomes `backends[0]`. An optional
over/under-thinking check, not a selection set, is a subsample of OptimalThinkingBench (§6), about 50
OverthinkingBench + 55 UnderthinkingBench items × 4 tiers sent straight to the API (≈420 calls; through
`claude -p` the per-call cache-creation overhead would dominate).

**Stage 4, advisory / active with the winner.** shadow → advisory at ≥ 30 labeled dispatches with agreement
≥ 0.7 (advisory costs nothing when they agree). Exploration continues: a fraction ε of the dispatches where
the router's tier is *below* the coordinator's are run at the router's tier (denial reason says
"exploration"). "One tier below the router" is a later experiment, labeled separately, for classes already
in `active`.

**Risk floor** (Stages 2 and 4). Phase-1 code (`tw.py` `act()`): a brief with any `TW-Risk` other than
`none` never routes to the role's cheapest tier (the same deterministic prior hermes-jev-skills uses). Phase 2
replaces this with per-flag floors in `routes.json` (§7 decision 7).

**Promotion rule** (posterior, hold band = hysteresis): with k accepted of n explored/advised-lower
dispatches, p_router ~ Beta(1+k, 1+n−k), p_coord likewise from the coordinator-tier arm; promote advisory →
active when P(p_router − p_coord ≥ −0.15) > 0.8, demote when < 0.2, hold between. Count table for a known
coordinator rate of 0.85 (review resolutions §1):

| n | promote if k ≥ | demote if k ≤ |
|---|---|---|
| 10 | 9 | 5 |
| 15 | 13 | 9 |
| 30 | 24 | 19 |
| 50 | 38 | 32 |

**Cost side of a verdict.** A verdict computes savings from `kind: cost` rows: median dollars per dispatch
per class × tier, each token kind priced with the per-M coefficients audited in `PROGRESS.md` §7 (cache write
$8.49/M and output $19.83/M from the regression; cache read $0.20/M from the clean full-cache probe, since
the regression's read coefficient is confounded; uncached input has no audited coefficient there and is
read from the published price sheet when the script is written). It does so once a class × tier cell holds
~20 cost rows. Before that the only number is a labeled prior: the paired Opus 5.5 output multipliers vs
`low`, medium 1.11, high 1.33, xhigh 2.16 (same file). Those are single-shot, tools-off bench outputs, and
the same run's tools-on control passed the map's `low` failures at `low` 4/4 (`PROGRESS.md` §10), so the
separation behind them disappears with tools on. Real dispatches are multi-turn and tool-heavy, and their
cost is all token kinds, not output alone.

**What the five-session run buys.** 50–150 labeled dispatches, ~10–30 explored at ε = 0.2. That is an
elimination round (Stage 1) plus latency and calibration, not a backend selection. Arms separate only on rows
where they disagree; with a prior saturated at `low` and two correlated Qwen-based arms, expect roughly a
fifth to a third of rows to be informative, i.e. ~10–50 rows (Fable's estimate, 2026-09-27, not measured).
A 0.1 difference in a definite rate needs 68–144 rows per arm, so picking `backends[0]` on quality needs
≳ 300 rows with two-sided intervals; short of that, Stage 3 picks on the secondary criteria (latency,
calibration, reliability) among the survivors and labels the pick provisional. For promotion the run
resolves a 0.2–0.3 acceptance drop **pooled across classes**, not 0.1, and not per class. Per-class outputs
from that run are shadow agreement rates; per-class promotion waits.

## 6. Deliberately left out (with the trigger)

- Rewrite on Codex. Trigger: the Codex hook-rewrite probe passes on legacy spawn.
- An MCP server for `route`. Trigger: wanting Codex v2 to route without the coordinator calling anything
  (Codex hooks can call MCP tools with event-expanded arguments [D]).
- AnyJev L2 (hidden-state head). Trigger: the 4B runs in-process rather than behind SemIf's server.
- Any fine-tune on our labels. Trigger: ≥ 200 labeled real dispatches.
- Cross-harness calibration table; the 27B as a routing backend; a `max` tier; installer simplification.

Prior art to cite (only the abstracts and, for OTB, the dataset sections have been read):
- **DART** (arXiv 2606.23181, training-free): two cheap no-think drafts; answer if they agree, else set the
  budget from draft entropy. Its entropy signal matches our confidence (entropy of the backend's tier
  distribution, already in `probs`, §4.3). Not adopted as a dispatch scheme: two worker runs per brief is
  the cost we are trying to cut. Not read by anyone here yet.
- **OptimalThinkingBench** (arXiv 2508.13141, Meta): OverthinkingBench (1,327 simple general questions +
  133 MATH L1–2, graded by an LLM judge) and UnderthinkingBench (550 Reasoning Gym puzzles, 11 types × 50,
  programmatic verifiers, plus harder math). Candidate over/under-thinking check once a backend is on
  (§5 Stage 3), not a selection set. Its hard half is synthetic, like the grids, so it cannot pick tiers for real briefs.
- **Learning When to Think** (arXiv 2608.20256): GRPO teaches a 1.5B model to pick NoThink/Short/Long as its
  first token; −41 % tokens on MATH500 at 0.782 vs 0.796 accuracy. A training method, not an eval; the
  learned-allocation reference, and relevant only if local Qwen models are routed. Trigger for a fine-tune
  of our own: the ≥ 200-label line above.

## 7. Decisions for Arian

Decided 2026-09-26 (Arian):

1. **Backend arms:** no preset `backends[0]`. SemIf-4B + AnyJev L0, Kev-0.8B, Eos-0.8B and Laya are compared
   as equal arms in Stage 3 (§5), and the winner becomes `backends[0]`.
2. **Codex review/ideation effort:** explicit `reasoning_effort` is required, with a floor of `medium`
   ("medium or better"), matching §4.2 `tiers: ["medium","high","xhigh"]`. Revert `tw.py:262` ("may omit")
   in plan step 1.
3. **Terra:** allowed as a Codex worker (`gpt-5.6-terra` in `worker.models`), but GPT-6 models are phasing it
   out. Nothing is built around it, and it is dropped when it stops being dispatched.
4. **Ideation/review tiers:** default `high` on both harnesses (tentative: "idk...high?"). Ranges stay as in
   §4.2 (Claude high–xhigh, Codex medium–xhigh). Tools: full access for both (`tools: null`, Arian
   2026-09-26). A reviewer can run tests itself to falsify a claim, and a Bash-capable role is never really
   read-only anyway. "Report findings; do not edit the files under review" is a line in the brief, not a
   tool restriction.
5. **§4.6 guard: the mtime variant, anchored at process start, plus the next-dispatch tripwire.** Fable's
   review, 2026-09-26: plugin hooks are fixed at session start, so a guard that only reads disk misses the
   first session after an update. Confirmed by this session's cache-edit test, whose file was restored.
6. **context-mode:** decided, keep; patch out its Agent hook and move the nudge to SubagentStart (§4.6).
7. **Default tiers once backends exist (Arian, 2026-09-27):** `low` for predictable work with a known outcome,
   `medium` as the worker default, `high` for tricky work. This replaces the `"default": "high"` for the
   worker role in §4.2 and the shipped `routes.json`, with the phase-2 routes rework (the file is
   installer-owned). Against it: the synthetic calibration saturates at `low`. For it: those tasks are not
   Arian's work. `promote` settles it per class from receipts.
   - **Where it lands.** `routes.json` `default` is nearly inert in code: the only runtime read is the
     `route` CLI (`tw.py:1320`); the hook routes against the tier the coordinator dispatched. So the lever
     is the coordinator's prompt rule and `SKILL.md`, where this decision has to land. Launch contract (c)
     (`~/.claude/handoffs/2026-09-26-launch-five-project-sessions.md` and the five Desktop prompts) said
     "medium for coding with a check; high for reasoning or physics"; aligned with this decision on
     2026-09-27 (Arian approved; edited by the coordinator session).
   - **Risk floor (Arian, 2026-09-27).** Phase-1 code (`tw.py` `act()`) implements only "a risk-flagged
     brief never routes to the role's cheapest tier", for any flag. The phase-2 routes rework replaces it
     with per-flag absolute floors in the router block:
     `"risk_floor": {"physics": "high", "destructive": "medium", "external": "medium"}`.
     Contract (c)'s physics-or-convention floor is a coordinator rule, not this flag: a convention
     judgment carries no `TW-Risk` flag.

Defaults taken unless objected to: everything in §4.7; `TW-Class` stays required as the coordinator's label;
per-dispatch cutoff 0.85; exploration ε = 0.2 in §5 Stage 2 (`table`-driven) and Stage 4.

## 8. After the yes

`writing-plans` in `~/Code/skills`, TDD per seam, one commit per green seam:
(1) `routes.json` + loader + generated agents + gate rewrite + Codex effort-required revert, behind the
existing tests; (2) hook order gate → receipt → route with the `coordinator` and `table` backends, route
rows, ticket digest; (3) `tw.py serve` + the four backend arms (`semif4b`, `kev`, `eos`, `laya`) + stub-server tests;
then, in §5 order, Stage 1 shadow (elimination, latency, calibration), Stage 2 `table`-driven exploration
for interval labels, and the Stage-3 selection script over the stored bodies and those labels, which picks
`backends[0]` (provisional below ~300 two-sided rows); (4) cost rows at `outcome` and the next-dispatch race check; (5) `advisory`, exploration,
promotion script over receipts; (6) the §4.6 patch, heal, nudge and guard, the O4b re-probe, then `active`; (7) Codex: `task_name` join
probe, then the CLI path; (8) re-baseline the real install and lift the five-session HOLD. The Opus 5.5
calibration run proceeds in parallel and feeds (2) and (3).

Sources read in full this session: `tw.py`, `SKILL.md`, `references/{claude,codex}.md`, the three agent
files, the setup-plan handoff, the Local-Agent decision-layer design and `decide.py` headers, the
unification memo, the Codex survey, `POLICY.md`, `ROUTING-KB.md`, `CPU_POOLS.md`, the Claude hooks and
subagents docs and the Codex hooks doc (indexed), both probe reports, the ordering report, `tw-audit.md`,
the decision-model survey, and the 13-item review resolutions.
