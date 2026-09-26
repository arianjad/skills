# Effort routing across Claude Code and Codex: architecture design

Status: DRAFT 2 2026-09-26 (Windows), for Arian's decision. No code changed. §7 records Arian's rulings
from the first round; the remaining open items are the backend bench order and the approach itself. Written from scratch per Arian ("not attached to prior
setup; R&D and prototyping"), not as a patch to thinker-worker as built.

Labels: **[V]** verified this session (ran/read, with the artifact), **[D]** primary documentation read
this session, **[I]** inference, **[A]** Arian's stated requirement, **[?]** open.

## 0. The decision in one paragraph

A dispatch picks a *cell* = (model, effort) for a *role* (worker, leaf, review, ideation) on a *harness*.
Today the cell is chosen by the coordinator from hardcoded tables in `tw.py`. Proposed: one data file
`routes.json` holds the policy (which cells each role may use, per harness); one function
`route(harness, role, header, body) → {tier, probs, confidence, source}` picks the effort inside that policy
through a pluggable backend (coordinator | effortmining table | a small local decision model: Kev, SemIf,
Laya | the resident 27B scorer when it happens to be up); the thinker-worker hook keeps two fail-closed jobs
(**model policy** gate, receipt) and gains a fail-open one (record the router's pick next to the
coordinator's, and in `enforce` mode deny a disagreement unless the brief carries `TW-Override:`). Effort
policy is deliberately loose: the gate only checks that the tier is inside the role's allowed range; which
tier is the router's job [A, 2026-09-26 round 2]. Effort is applied per harness by the only mechanism each has: on Claude by choosing a
generated tier-pinned agent, on Codex by `reasoning_effort`. Backends walk `off → shadow → advisory →
enforce` per class on real-dispatch outcomes, with a small exploration fraction as the only ground truth.
effortmining supplies priors and training data, never the route.

## 1. Mechanism facts the design rests on

| Fact | Status | Evidence |
|---|---|---|
| Claude: the Agent tool has `model` per call, no effort field; effort comes only from the agent file's `effort:` | [V] | setup plan step 1 (2026-09-26): `CLAUDE_EFFORT` read `low`/`xhigh` in miner-low/xhigh children with the parent at `high` |
| Claude: a PreToolUse hook **can rewrite** an Agent dispatch: `updatedInput` on `subagent_type` and `model` is honored (child `meta.json` `agentType: effortmining:miner-xhigh`, `EFFORT=xhigh`; child `message.model = claude-sonnet-5`). **But** when another hook on the same matcher also returns `updatedInput`, only one survives: the context-mode plugin's Agent hook (returns `{...toolInput, prompt: prompt+block}` from the original input, `hooks/core/routing.mjs` ~907–927) won 3/3 and masked the rewrite in the first probe. Resolution order (settings vs plugin, first vs last) is being probed | [V] | `%TEMP%\tw-probe\REPORT.md` runs B2/C2 with `enabledPlugins: {context-mode: false}` (Claude Code 2.1.283, `-p`, bypassPermissions); confounded runs A–C there and A–E in the scratchpad probe. Interactive mode untested [I: same code path] |
| Claude: hooks can deny with a reason the model sees; SubagentStop receives `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message` | [D] | code.claude.com/docs/en/hooks |
| Claude: `meta.json` in the subagent dir maps `toolUseId` ↔ agent; transcript assistant rows carry `message.model` and `usage` | [V] | probe run C files |
| Codex: `spawn_agent` takes `model` and `reasoning_effort` per call; on MultiAgentV2 the brief is ciphertext at PreToolUse, so a hook sees model/effort only | [V] | `tw.py:224-235`, `references/codex.md` |
| Codex: docs say PreToolUse can "block or rewrite" local function tools incl. `spawn_agent` | [D, unverified on the real path] | learn.chatgpt.com/docs/hooks, "Tool coverage". Moot on v2: nothing to route on |
| Local scorer: `Decider.ask(question, state)` posts a shared prefix plus one closed-set question to `POST /v1/score` (igorls NInfer fork, Qwen3.8-27B on the Windows 5090), returns renormalised option probabilities; 100–220 ms at production flags; concurrency 3, shared with the Telegram bot | [V code, measurements from the design note] | `%LOCALAPPDATA%\hermes\hermes-agent\agent\gvs5h\decide.py:5-8,63-135`; `Local-Agent/docs/plans/2026-09-22-harness-decision-layer-design.md:14-25` |
| Local sidecars on the Hermes route question: Kev-0.8B CPU `route_real` 0.683, Laya 0.491; the 27B scorer 0.98 on `route`. A different question from ours; Arian: Hermes benches of decision models are not transferable | [V], [A] | `Local-Agent/local_decisions/bench/results/summary.md` |
| Coordinator logits are not obtainable: the Anthropic Messages API reference has no logprobs field (indexed page, zero hits); OpenAI's Responses API has a `logprobs` field but the Codex harness does not surface it to a coordinator. A coordinator can give only a text pick + self-reported confidence | [D], [I for the harness claim] | platform.claude.com/docs/en/api/messages; developers.openai.com/api/docs/guides/reasoning |
| Small local candidates (plan of 2026-09-21, numbers from their own READMEs): Kev 0.8B bf16 ~1.6 GB, CPU measured here ~150 ms/route; Laya 421M encoder, 33–40 ms GPU / 190–460 ms CPU; SemIf scores logits of any frozen GGUF/MLX/CUDA model (same mechanism as the 27B scorer) | [V read of the plan; numbers [3P]] | `Local-Agent/docs/plans/2026-09-21-local-classifier-plan.md:168-232` |
| effortmining calibration: Opus 4.8, n = 9–18 per class, every class `confidence: low`, bench path is `claude -p --effort`, not a subagent | [V] | `effortmining/bench/state/calibration.json`, `bench/effort.py:968-985` |
| Output tokens do not separate tiers on an easy closed-form task on Opus 5.5 (low 1057/2019/5712 vs xhigh 1971/2549/2822) | [V] | setup plan step 1 |
| Receipts today: 38 dispatch rows, 0 with a routing header, 0 outcome rows; Codex 1 file | [V] | tally of `~/.thinker-worker/receipts/` this session |

Consequence of row 2: **on Claude the router can substitute the agent (tier) and model in the hook**, so a
true `active` rung exists, provided the routing hook is the only `updatedInput` writer on `Agent` or the
resolution order lets it win (open; ordering probe in flight). Approach 2 in §3 is therefore live again,
and "coordinator-assigned" [A] becomes a policy choice (advisory by default, rewrite only in `active`)
rather than a mechanism limit. §3–§4 below are written for the coordinator-invoked path and will be
re-ranked once the ordering result is in.

## 2. Requirements [A]

1. thinker-worker owns routing, modularly: the routing table is data, the decision backend is pluggable.
2. Local Jev-like decision models are first-class backends, chosen for speed at dispatch time. Candidates
   for now: Kev, SemIf, Laya. The resident 27B's logits are used only when it is already running (Windows,
   bot up); nobody launches Qwen for routing. A survey of newer candidates is in flight (Opus, 2026-09-26).
3. Coordinator-assigned effort per dispatch on both harnesses; review/ideation effort included.
4. effortmining is calibration and training data, not the router.
5. Hermes/local-Qwen results and "those tests" do not transfer as-is to Claude/Codex (which tests: §7 Q1).
6. Simpler than what exists.

## 3. Approaches

### Approach 1: coordinator-invoked router, hook records and (later) enforces — RECOMMENDED

- Coordinator runs `tw.py route --harness H --role R --brief-file F` before dispatching. In `shadow` it prints
  only a ticket id (the pick is logged, the coordinator stays blind); in `advisory` it prints the pick and
  probabilities; in `enforce` the hook denies a dispatch whose cell disagrees with the ticket unless the brief
  carries `TW-Override: <reason>`.
- The hook stays the single observation point: gate (fail closed), receipt (fail closed), route join (fail
  open: no ticket or scorer down → `source: coordinator`).
- Works identically on Claude, Codex legacy, and Codex v2 (the CLI sees the plaintext brief even when the hook
  cannot).
- Cost: one Bash tool call per dispatch (~0.3 s wall with the scorer, ~150 output tokens); no retries.
- Weakness: relies on the coordinator calling `route` (enforceable: the hook can require the ticket line the
  way it requires the header today).

### Approach 2: hook-invoked router, advice by denial

- No CLI. The hook itself calls `route()` on the plaintext brief and, above the cutoff in `advisory`/`enforce`,
  denies a disagreeing dispatch with the suggestion in the reason; the coordinator re-dispatches or overrides.
- Zero coordinator overhead when router and coordinator agree; one wasted Agent round trip (the whole brief
  re-sent) when they disagree.
- Blind on Codex v2 (ciphertext), so Codex needs Approach 1 anyway. Two code paths for one decision.
- Verdict: a later optimisation of Approach 1 for Claude, once shadow data says how often they disagree.
  Not the first build.

### Approach 3: dispatch workers as headless CLI processes

- The coordinator (or the hook, via a wrapper) runs `claude -p --model M --effort E --agent <role>` or
  `codex exec --model M -c model_reasoning_effort=E` instead of the Agent tool.
- Native per-call effort on both harnesses, no tier agents, and the production path equals effortmining's
  bench path (closes the memo's "calibrated on a different path than used" conflict).
- Loses: the harness's agent integration (`/tasks`, notifications, SendMessage continuation, permission
  inheritance), prompt-cache sharing with the parent (stripped `-p` runs cost $0.36–0.40 each with ~42k
  cache-creation tokens, setup plan step 4), and the PreToolUse gate as an observation point (it would gate a
  Bash command line instead).
- Verdict: rejected as the dispatch path; kept as the *calibration* path (already is). Trigger to revisit:
  Anthropic adds per-call effort to Agent, which makes tier agents redundant either way.

### Approach 0 (baseline, not an option): coordinator routes alone

Fable/Astra picks the cell with the effortmining table as a prior. Zero new code. Every backend must beat
this on the promotion gate in §5 or it does not get promoted; it is the `coordinator` backend in `routes.json`.

## 4. Recommended architecture in detail (Approach 1)

### 4.1 Components

| Component | Where | Replaces |
|---|---|---|
| `routes.json` | shipped with the skill, copied by the installer, hashed in the manifest | `CODEX_*`, `CLAUDE_*`, `CLAUDE_ROLES`, `MINER_TYPE`, `CODEX_EFFORTS` in `tw.py:28-45` and the three inline role maps (audit findings 2, 5) |
| `route()` + backends | `tw.py` (stdlib `urllib`, same as `decide.py`) | nothing; new |
| `tw.py route` CLI | `tw.py` | nothing; new |
| Tier agents `tw-<role>-<tier>.md` | generated by `tw.py install` from `routes.json` into `~/.claude/agents/` | `thinker-worker-opus/sonnet/fable-review.md`, the missing `dreamer`, and the `effortmining:miner-*` special case |
| Hook | `tw.py hook` | same entry; smaller `decide()` (audit findings 3, 4) |
| Receipts + outcomes + cost | `~/.thinker-worker/receipts/` | same files; new `kind: route` rows and a `cost` field |
| Activation | `tw.py activate --harness --session` | the four per-role flags go (audit finding 1) |

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
        "worker": {"models": ["gpt-6-sol","gpt-5.6-sol"], "tiers": ["low","medium","high","xhigh"], "default": "high"},
        "leaf":   {"models": ["gpt-6-luna"],              "tiers": ["low","medium"],                "default": "low"},
        "review": {"models": ["gpt-6-astra"],             "tiers": ["medium","high","xhigh"],      "default": "high"},
        "ideation": {"models": ["gpt-6-astra"],           "tiers": ["medium","high","xhigh"],      "default": "high"}
      }
    }
  },
  "router": {
    "backends": ["scorer27b", "kev", "table"],
    "fallback": "coordinator",
    "scorer27b": {"url": "http://127.0.0.1:8080/v1", "timeout_s": 2, "only_if_up": true},
    "kev": {"model": "jaredpalmer/kev-0.8b", "device": "cpu", "download_prompt": true},
    "body_chars": 6000,
    "classes": {"*": {"mode": "shadow", "cutoff": 0.8, "explore": 0.0}}
  }
}
```

`backends` is an ordered preference list: the first one that is reachable answers, the receipt records
which (`source`). On the Mac the 27B entry is never up, Kev/SemIf run on CPU or MPS (first use prompts to
download the weights), and if the user declines the answer is the coordinator's [A, round 1 Q3].

Notes. (a) Claude roles pin **one** model in the generated agent file (`model:` + `effort:` frontmatter); the
hook rejects a per-call `model` that differs from the file. This replaces "explicit model required" with
"model is a role property": fewer knobs, same protection against inherited-model children [I: the
per-invocation `model` overrides frontmatter per the subagents doc, hence the check]. (b) Codex keeps
per-call `model` + `reasoning_effort`; a non-empty `tiers` list means effort is required, which is Arian's
2026-09-26 revert for Astra review/ideation expressed as data. (c) Terra is absent because `tw.py` never
allowed it; adding `gpt-6-terra` to `worker.models` is one data edit (memo open question 3, still Arian's
call). (d) `classes."*"` is the default; per-class overrides use effortmining's class names.

### 4.3 `route()` and the scorer question

```
route(harness, role, header: dict, body: str, cfg) -> {
  "tier": "medium", "probs": {"low": .12, "medium": .71, "high": .15, "xhigh": .02},
  "confidence": .71, "source": "scorer" | "table" | "coordinator", "mode": "shadow", "ms": 180}
```

Backends, one function each behind the same signature:

- `coordinator`: returns the role default; `confidence` 0. The baseline. (Its logits are not obtainable, §1.)
- `table`: effortmining `calibration.json` class → tier (Opus 4.8 today, Opus 5.5 after the calibration run).
- `scorer27b`: the `Decider._score` request shape verbatim (system prefix = state, one user question, letters
  A–D → tiers, `temperature 0`, `enable_thinking false`) against `/v1/score`, only when the endpoint answers
  `/models` within the timeout. State = the four header keys plus the first `body_chars` of the brief;
  question text: "A coordinator is delegating this brief to a <model> worker on <harness>. Choose the lowest
  reasoning-effort tier at which the worker still meets the TW-Accept line." Option descriptions come from
  effortmining's class vocabulary (T1 mechanical … T4 hard reasoning).
- `semif`: the same question and options through SemIf's logit scoring of a small frozen GGUF/MLX model.
  Same mechanism as `scorer27b`, so the prompt and the option letters are shared code; only the transport
  differs. This is the Mac-capable twin of the 27B path.
- `kev`: Kev-0.8B's typed `choice` API over the same state and options; CPU here (~150 ms measured on the
  Hermes question), MPS on the Mac.
- `laya`: Laya's typed `choice`; the speed floor (encoder, one forward pass).

All local backends are deterministic at temperature 0: the same header and body give the same
probabilities, which is what lets the policy gate loosen on effort once a backend is in `enforce`. The
scorer sees the body at decision time (the CLI reads the file). Receipts never store it; the private body
store does (§4.5).

### 4.4 Per-dispatch flow

Claude:
1. Coordinator writes the brief: `TW-Role:` line, header (`TW-Class`, `TW-Deliverable`, `TW-Accept`,
   `TW-Risk`), body. Same as today minus the 600-char cap (per-value cap 128 chars instead, the receipt's
   existing rule, audit finding 6).
2. `python tw.py route --harness claude --role worker --brief-file brief.md` → in `shadow` prints
   `TW-Route: t-7f3a` (ticket only); in `advisory` also prints `medium (0.71) [low .12 high .15]`; the pick
   and probabilities are written as a `kind: route` receipt row keyed by the ticket.
3. Coordinator appends the `TW-Route:` line and dispatches `Agent(subagent_type="tw-worker-<tier>", prompt=…)`
   with the tier it chose. No `model` argument needed.
4. Hook: gate (role allowed, `subagent_type` is a generated tier agent for that role, tier in the role's
   list, no fork/resume keys, ticket present when the router is not `off`); in `enforce`, deny if the tier
   differs from the ticket's above-cutoff pick and no `TW-Override:` line; receipt row with `header`,
   `ticket`, `picked_tier`, `routed_tier`, `source`, `decision`.
5. SubagentStop hook (new, Claude only): parse `agent_transcript_path` `usage` rows → append
   `kind: cost` with output/input/cache tokens, joined by `tool_use_id` from `meta.json`.
6. Coordinator labels: `tw.py outcome --tool-use-id … --accepted yes|no` (exists).

Codex: steps 1–2 identical; step 3 is `spawn_agent(model, reasoning_effort=<tier>, message=…)`; step 4
on v2 gates model/effort only and joins the ticket by session + most recent unconsumed route row (the
brief is ciphertext); step 5 is manual from turn metadata until Codex exposes a stop hook with usage.

### 4.5 Policy split, fail modes, privacy

- **Model policy** (kept, data, fail closed): which models each role may run on each harness, fresh
  dispatch only, no inherited-model child, header and role line present. This is the part Arian wants to
  keep adjustable "more around model policy than effort policy" [A, round 2].
- **Effort policy** (loose): the gate checks only that the tier is inside the role's `tiers` range. Which
  tier is the router's call; holding the coordinator to it is the `enforce` mode, switched on per class from
  evidence (§5), never a standing rule.
- Router: fail open. No backend reachable, timeout, malformed probs, or no ticket → `source: coordinator`,
  dispatch proceeds, receipt says so.
- Receipts store the header (per-value cap 128), the ticket, tiers, probs, source, outcome, cost. Never the
  body. The body goes to a private local store `~/.thinker-worker/bodies/<session>/<ticket>.md`, gitignored,
  never synced, for offline replay and training [A, round 1 Q2: yes].

### 4.6 What is deleted (audit-backed, `tw-audit.md` in the scratchpad)

- Per-role activation flags `--review/--luna/--sonnet/--ideation` and their record fields; activation is
  on/off, roles come from `routes.json`.
- Hardcoded constants and inline role maps; `MINER_TYPE`; `CODEX_EFFORTS` (replaced by `tiers`).
- Four brief scanners (`first_role`, `review_details`, `routing_header`, `opus_reason`) → one parser that
  splits on `\n` only (fixes the `splitlines()` inconsistency at `tw.py:171,176`).
- `TW-Opus-Reason` (never reached receipts); ideation on Opus becomes a `routes.json` edit if wanted.
- `effortmining:miner-*` as a thinker-worker route; miners stay in the plugin for benchmarking.
- The three hand-written agent files (generated instead) and the never-shipped dreamer.
- Not deleted: the 600-char header cap becomes a per-value cap; fresh-dispatch-only checks; fail-closed hook.

### 4.7 The one runnable check

`scripts/test_tw_route.py`: (1) `route()` with `backend: table` returns the class default; (2) with a stub
scorer returning fixed logits it returns normalised probs and the argmax; (3) with the stub unreachable it
returns `source: coordinator`; (4) in `enforce` mode the hook denies a brief whose tier disagrees with its
ticket and admits the same brief with `TW-Override:`; (5) `install` in a temp home generates
`tw-worker-{low,medium,high,xhigh}.md` with matching `effort:` lines and no `tw-worker-max.md`. Each case
has a reachable FAIL.

## 5. Ground truth, ladder, promotion

The question the router answers is "cheapest tier that passes this brief's own `TW-Accept`". Neither the
Hermes benches (a different question on a different harness) nor effortmining's synthetic grids (a
different path and model) measure it; both are priors [A, requirement 5]. Real dispatches with outcomes
are the only ground truth, and they only reveal the counterfactual if a lower tier is sometimes tried.

- **shadow**: router logs; coordinator blind. Yields agreement rate and the router's confidence
  distribution per class. No cost.
- **advisory**: coordinator sees the pick; still decides. Yields "coordinator accepted/overrode router" and
  the outcome of each.
- **enforce** with `explore: ε`: above the cutoff the hook holds the coordinator to the router's tier unless
  overridden; additionally a fraction ε of dispatches where the router's tier is below the coordinator's are
  run at the router's tier (denial reason says "exploration"). Briefs with `TW-Risk: destructive|physics`
  are exempt. This is the measurement; it costs some rejected dispatches. Needs Arian's yes (§7 Q1).
- **Promotion per class** (proposal, R&D numbers): move shadow → advisory at ≥ 30 labeled dispatches with
  agreement ≥ 0.7; advisory → enforce when, on the explored/advised-lower dispatches, acceptance is within
  0.1 of the coordinator-tier acceptance rate with n ≥ 15. Demotion on the reverse. Recorded as
  `classes.<class>.mode` edits in `routes.json` with the date and the receipt count, not silently.
- effortmining's role: option descriptions and few-shot examples for the scorer prompt; the `table` backend
  as a second baseline; the Opus 5.5 calibration run (separate handoff) refreshes both; graded synthetic runs
  are training rows for a later Kev fine-tune, labeled `synthetic`.

## 6. Deliberately left out (with the trigger that adds it)

- An MCP server for `route`: the CLI suffices. Trigger: wanting Codex v2 to route without the coordinator
  calling anything (Codex hooks can call MCP tools with arguments expanded from the event [D]).
- Hook-side routing (Approach 2) on Claude. Trigger: shadow data shows the coordinator agrees with the
  scorer > 90% of the time, so the pre-dispatch call is mostly waste.
- Kev backend and any fine-tune. Trigger: ≥ 200 labeled real dispatches, or the Mac needs a local scorer.
- Cross-harness calibration table. Effort labels are per-model dials; per-harness tables only.
- Body replay harness. Trigger: §7 Q2 = yes.
- A `max` tier: effortmining found no gain over xhigh in any class; `tiers` in `routes.json` can add it back.
- Installer simplification (ledgers, `machines`, portable PowerShell twin): out of this brief; the audit's
  installer section lists candidates.

## 7. Open questions for Arian

1. **Ground truth.** Which tests are non-transferable: the Hermes route/nimble benches, effortmining's
   synthetic grids, or both? And: accept ε-exploration on real dispatches (a fraction routed one tier below
   the router's pick, graded by your accept/reject) as the measurement? Recommendation: both are priors;
   yes to exploration, ε = 0.2, risk-flagged briefs exempt.
2. **Brief bodies.** Allow a private local store `~/.thinker-worker/bodies/<session>/<ticket>.md`, never
   synced, opt-in per session, for offline replay and training? Recommendation: yes; headers alone are thin
   training data and the scorer already sees the body at decision time.
3. **Mac.** Is the Windows scorer reachable from the Mac (Tailscale/LAN)? If not, Mac sessions run
   `source: coordinator` until a Kev-on-MPS backend is measured. Recommendation: fail open now.

Defaults taken unless objected to: everything in §4.6; `TW-Class` stays required as the coordinator's label
(agreement with the scorer's implied class is measured before dropping it); Terra stays out of the Codex
worker set until you say otherwise; Claude roles pin one model in the agent file.

## 8. After the yes

Hand to `writing-plans` in `~/Code/skills`, TDD per seam, one commit per green seam, in this order:
(1) `routes.json` + loader + generated agents + gate rewrite behind existing tests; (2) `route()` with
`coordinator`/`table` backends + CLI + `kind: route` receipts + `TW-Route` join; (3) `scorer` backend
against the live `/v1/score` with the stub test; (4) SubagentStop cost rows; (5) `enforce` + exploration;
(6) re-baseline the real install (the gate in the setup plan) and lift the five-session HOLD. The Opus 5.5
calibration run proceeds in parallel and feeds (2)'s `table` backend.

Sources read in full this session: `tw.py`, `SKILL.md`, `references/{claude,codex}.md`, the three agent
files, the setup-plan handoff, the Local-Agent decision-layer design and `decide.py` headers, the
unification memo, the Codex survey, `POLICY.md`, `ROUTING-KB.md`, `CPU_POOLS.md`, the bench summary, the
Claude hooks/subagents docs and the Codex hooks doc (indexed), the probe report, and `tw-audit.md`.
