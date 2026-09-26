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
are small resident local scorers (SemIf over a 4B GGUF with AnyJev's bias-free readout; Kev-0.8B, Eos-0.8B,
Laya as comparison arms); nobody launches the 27B for this. Backends are first compared offline on
effortmining's calibration grids, then validated in shadow on real receipts; promotion is by a posterior rule
with a hold band, and per-class promotion is out of reach of the five-session run, only a pooled one.

## 1. Mechanism facts the design rests on

| Fact | Status | Evidence |
|---|---|---|
| Claude: Agent has `model` per call, no effort field; effort comes only from the agent file's `effort:` | [V] | setup plan step 1: `CLAUDE_EFFORT` read `low`/`xhigh` in miner children with the parent at `high` |
| Claude: a PreToolUse hook **can rewrite** an Agent dispatch. `updatedInput` on `subagent_type` and `model` is honored (child `meta.json` `agentType: effortmining:miner-xhigh`, `EFFORT=xhigh`; child `message.model = claude-sonnet-5`) | [V] | `2026-09-26-hook-updatedinput-probe-report.md` runs B2/C2, context-mode disabled |
| Claude: hooks on one call run **in parallel** and when several return `updatedInput` the **last to finish wins**, whole object, no merge; listing order and settings-vs-plugin source do not matter. context-mode's Agent hook returns a full replacement on every dispatch (~350–380 ms Node start) | [V] 7/7 runs | `2026-09-26-hook-ordering-probe-report.md` O1–O6, O4/O4b |
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
7. One writer for Agent-call rewrites; whether context-mode stays is a separate assessment (round 4).
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
        "review":   {"model": "fable",  "tiers": ["high","xhigh"],               "default": "high", "tools": ["Read","Glob","Grep"]},
        "ideation": {"model": "fable",  "tiers": ["high","xhigh"],               "default": "high", "tools": ["Read","Glob","Grep","WebSearch","WebFetch"]}
      }
    },
    "codex": {
      "apply": "reasoning_effort",
      "roles": {
        "worker":   {"models": ["gpt-6-sol","gpt-5.6-sol"], "tiers": ["low","medium","high","xhigh"], "default": "high"},
        "leaf":     {"models": ["gpt-6-luna"],              "tiers": ["low","medium"],                "default": "low"},
        "review":   {"models": ["gpt-6-astra"],             "tiers": ["medium","high","xhigh"],      "default": "high"},
        "ideation": {"models": ["gpt-6-astra"],             "tiers": ["medium","high","xhigh"],      "default": "high"}
      }
    }
  },
  "router": {
    "backends": ["semif4b", "kev", "table"],
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
- `table`: effortmining `calibration.json` class → tier (Opus 5.5 after the parallel calibration run).
- `semif4b`: one closed-set question over the state (four header keys + body prefix), letters → tiers,
  temperature 0, scored from a 4B GGUF's logits by SemIf (llama.cpp on CPU, MLX on the Mac). The
  `anyjev-L0` readout averages option-order bias over rotations and divides out the label prior with zero
  labels; `L1` adds a temperature once ~100 labels exist. Question text: "A coordinator is delegating this
  brief to a <model> worker on <harness>. Choose the lowest reasoning-effort tier at which the worker still
  meets the TW-Accept line." Option descriptions come from effortmining's class vocabulary.
- `kev`, `eos`, `laya`: the same state and options through each model's typed `choice` API. Comparison arms.

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
   `subagent_type` swapped to the router's tier agent (same override escape) and the context-mode block
   appended if §4.6 resolves to "router appends it".
4. SubagentStop hook (new): parse `agent_transcript_path`, group assistant rows by `message.id`, keep the
   last row per id, sum input / cache-create / cache-read / output → `kind: cost`, joined by `tool_use_id`
   from `meta.json`. Not the parent's `totalTokens`. Whether the final row is flushed before SubagentStop
   fires is checked once in the plan.
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

Claude keeps the last `updatedInput` to finish and discards the rest (§1). context-mode's Agent hook writes
one on every dispatch. So a routing hook that rewrites must be the only writer: either context-mode goes, or
its Agent hook is disabled and the routing hook appends context-mode's block itself, or the routing hook
wraps context-mode's script. B and C couple the router to a plugin that may be removed. Decided separately
by the assessment prompt at `%TEMP%\tw-probe\PROMPT-context-mode-assessment.md`; until then `active` mode is
not enabled and `shadow`/`advisory` (which return no `updatedInput`) are unaffected.

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

## 5. Evaluation: offline testbed, then real dispatches

**Stage 1, offline on effortmining grids [A].** Each calibration task has a measured cheapest-passing tier on
Opus 5.5 (the parallel calibration run). Every backend scores every task's prompt as if it were a brief;
metrics per backend: exact-tier accuracy, mean signed tier error (over-routing costs tokens, under-routing
costs a failed dispatch), calibration (ECE), latency. In-distribution for *comparing backends*, even though
the absolute tiers may not transfer to real briefs. This is the bench that picks the first `backends[0]`.

**Stage 2, shadow on receipts.** Router logs; coordinator blind. Output: per-class agreement with the
coordinator and the confidence distribution. shadow → advisory at ≥ 30 labeled dispatches with agreement
≥ 0.7 (advisory costs nothing when they agree).

**Stage 3, advisory / enforce with exploration.** Exploration = a fraction ε of the dispatches where the
router's tier is *below* the coordinator's are run at the router's tier (denial reason says "exploration");
`TW-Risk: destructive|physics` briefs and any risk-flagged brief never route to the cheapest tier (the same
deterministic prior hermes-jev-skills uses). "One tier below the router" is a later experiment, labeled
separately, for classes already in `enforce`.

**Promotion rule** (posterior, hold band = hysteresis): with k accepted of n explored/advised-lower
dispatches, p_router ~ Beta(1+k, 1+n−k), p_coord likewise from the coordinator-tier arm; promote advisory →
enforce when P(p_router − p_coord ≥ −0.15) > 0.8, demote when < 0.2, hold between. Count table for a known
coordinator rate of 0.85 (review resolutions §1):

| n | promote if k ≥ | demote if k ≤ |
|---|---|---|
| 10 | 9 | 5 |
| 15 | 13 | 9 |
| 30 | 24 | 19 |
| 50 | 38 | 32 |

What the five-session run buys: 50–150 labeled dispatches, ~10–30 explored at ε = 0.2. That resolves a
0.2–0.3 acceptance drop **pooled across classes**, not 0.1, and not per class (a 0.1 drop needs 68–144
per arm). Per-class outputs from that run are shadow agreement rates; per-class promotion waits.

## 6. Deliberately left out (with the trigger)

- Rewrite on Codex. Trigger: the Codex hook-rewrite probe passes on legacy spawn.
- An MCP server for `route`. Trigger: wanting Codex v2 to route without the coordinator calling anything
  (Codex hooks can call MCP tools with event-expanded arguments [D]).
- AnyJev L2 (hidden-state head). Trigger: the 4B runs in-process rather than behind SemIf's server.
- Any fine-tune on our labels. Trigger: ≥ 200 labeled real dispatches.
- Cross-harness calibration table; the 27B as a routing backend; a `max` tier; installer simplification.

## 7. Decisions for Arian

1. **Backend arms:** SemIf-4B + AnyJev L0 as `backends[0]`; Kev-0.8B, Eos-0.8B, Laya as Stage-1 comparison
   arms. Yes/no.
2. **Codex review/ideation effort:** the setup-plan handoff (2026-09-26 evening) records your ruling that
   Astra review/ideation must carry an explicit `reasoning_effort`; `tw.py:262` still implements the earlier
   "may omit" and says so in its comment. Draft assumes the handoff ruling and lists the revert as plan step 1.
   Confirm.
3. **Terra:** rollouts show `gpt-5.6-terra` dispatched as a worker on 2026-09-24. Add it to the Codex
   `worker.models`, or keep it out?
4. **Ideation/review tiers and tools** (§4.2): `["high","xhigh"]` on Claude, `["medium","high","xhigh"]` on
   Codex, ideation with web tools, review read-only. Placeholders; change any.
5. **context-mode:** keep or remove, from the separate assessment. `active` mode waits on it.

Defaults taken unless objected to: everything in §4.7; `TW-Class` stays required as the coordinator's label;
per-dispatch cutoff 0.85; exploration ε = 0.2 once a class reaches advisory.

## 8. After the yes

`writing-plans` in `~/Code/skills`, TDD per seam, one commit per green seam:
(1) `routes.json` + loader + generated agents + gate rewrite + Codex effort-required revert, behind the
existing tests; (2) hook order gate → receipt → route with the `coordinator` and `table` backends, route
rows, ticket digest; (3) `tw.py serve` + `semif4b` backend + stub-server tests; Stage-1 offline bench script
over an effortmining grid; (4) SubagentStop cost rows and the flush check; (5) `advisory`, exploration,
promotion script over receipts; (6) `active` after the context-mode decision; (7) Codex: `task_name` join
probe, then the CLI path; (8) re-baseline the real install and lift the five-session HOLD. The Opus 5.5
calibration run proceeds in parallel and feeds (2) and (3).

Sources read in full this session: `tw.py`, `SKILL.md`, `references/{claude,codex}.md`, the three agent
files, the setup-plan handoff, the Local-Agent decision-layer design and `decide.py` headers, the
unification memo, the Codex survey, `POLICY.md`, `ROUTING-KB.md`, `CPU_POOLS.md`, the Claude hooks and
subagents docs and the Codex hooks doc (indexed), both probe reports, the ordering report, `tw-audit.md`,
the decision-model survey, and the 13-item review resolutions.
