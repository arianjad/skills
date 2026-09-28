# Joint (model, effort) routing with decision models: design (2026-09-28, Windows)

Supersedes the effort-only framing of `2026-09-26-effort-routing-architecture-design.md` where they conflict; that
document's mechanism facts (§1), hook/one-writer rules (§4.6) and promotion rule (§5) still hold.
Sources: `2026-09-28-router-ensemble-joint-routing-survey.md` (prior art, arXiv ids checked), Astra ideation report
`scratchpad/astra/report-2026-09-28-joint-routing.md` (untracked; tool_use_id astra-031fd508d357),
`2026-09-27-decision-model-survey.md` (backends). "Agreed" = Arian said yes on that date; "proposed" = not yet.

## 1. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | The router (decision models + coordinator) picks **model and effort** jointly, over the discrete (model, effort) pairs a role allows in `routes.json`. | agreed 2026-09-28 |
| D2 | An explicit user model/effort request wins: brief carries `TW-Pin: user <what was asked>`; router logs, never acts or explores; row `pinned: true`, excluded from off-policy estimates, kept as an observation of the executed arm. A model-only pin restricts candidates to that model. | agreed 2026-09-28 (marker name proposed) |
| D3 | Discrete joint selection first, with light sharing across efforts within a model; an R2-Router-style per-model quality-vs-effort curve only after within-model effort structure is observed to be monotone and predictive; an unrestricted flat predictor stays the challenger. (RTR 2505.19435, R2-Router 2602.02823; both need supervised outcomes.) | agreed 2026-09-28 (Astra's suggestion) |
| D4 | No single global cross-model ladder is assumed. Per-task-family quality–cost frontiers from pairs measured on the same checkable briefs; an optional one-axis IRT fit, logit P(pass) = θ(model,effort) − b(task), only if held-out prediction supports it. | agreed 2026-09-28 |
| D5 | Decision models are prompted with **candidate cards** (capability profile, observed limitations, behavioral effort wording, evidence status measured/provisional/absent, explicit cost order), names only as identifiers. A/B: (a) per-pair sufficient/insufficient/unknown over a 3–4 pair shortlist, cheapest sufficient wins; (b) one flat choice among 4 pair cards + "insufficient evidence". Robustness: shuffled order, renamed ids. | agreed 2026-09-28 |
| D6 | Dispatch label = **pass / fail / unknown** with evidence source and category; optimize total workflow cost (child + checks + coordinator rescue + retries) at an acceptable verified-completion rate. Label sources ranked: executed `TW-Accept` checks (`TW-Check:` command) > transcript mining (hard evidence only) > OptimalThinkingBench verified half > blinded replay-judge > coordinator accept (weak). The user never grades. | agreed 2026-09-28 |
| D7 | Accept at t−1 then pass at t is **evidence** toward t, not an exact threshold (workers are stochastic); the label model is probabilistic. Corrects the older design §5 Stage 2 wording. | agreed 2026-09-28 |
| D8 | Transcript-mining pilot before any 96-dispatch anchor run; its labelable fraction is the go/no-go. | agreed 2026-09-28 |
| D9 | Exploration per the literature: decaying forced exploration ε_t = max(floor, min(1, c/t^¼)) (SLARouter 2606.19376), shipped c = 0.5, floor = 0.05, t counted per TW-Class; propensity logged on every row. | agreed 2026-09-28 (floor is ours) |
| D10 | Two exploration channels: one effort step down (current) and one model step down at the same effort (Opus→Sol, Sonnet→Luna), separate ε. The model order is a provisional prior until D4 frontiers exist. | proposed |
| D11 | Multiple decision models: every model's raw probabilities logged per dispatch; the acting rule is a Bayesian product of experts p ∝ prior · Π pᵢ^wᵢ with wᵢ = 1/n until fitted (correlated Qwen-based arms would double-count at wᵢ = 1), gated by a top-1/top-2 margin (DART 2606.23181, CoMed 2609.26913). Ranked-choice and mean pooling are scored offline from the same logs. No source shows pooling beats the best single router, so this is our experiment. | proposed (Arian named Bayesian or ranked choice) |
| D12 | Kev-0.8B is the first backend: `kev.serve` on CPU (`CUDA_VISIBLE_DEVICES=""`), 6 threads (4 acceptable), shadow only. Brief prefix ~1,500 chars to fit the 2 s budget at 6 threads. | agreed 2026-09-28 |
| D13 | Drift handling, items 1–5 of §4. | agreed 2026-09-28 |

## 2. Why shadow first

`route()` explores only when no deciding backend answers (`source == "coordinator"`). A deciding Kev would end
exploration, the only source of lower-bound labels. So decision models first run in a `router.shadow` list: each
scores every dispatch in parallel, its probabilities go on the route row, it steers nothing. A model moves into the
deciding set only after its shadow scores are calibrated against labels (older design §5 Stages 3–4).

## 3. Measured

Kev via `kev.serve`, CPU, prefix cache off (`scratchpad/kev_threads_probe.py`, 2026-09-28): 6 threads 597 ms at
164 tokens, 4,334 ms at 1,210 tokens, ready 13.6 s; 12 threads 371 / 2,656 ms, ready 10.6 s; ~3.6 ms/token at 6
threads. Same answers at both thread counts (short brief low p=.57; long medium p=.48).

## 4. Drift and nondeterminism (agreed 2026-09-28)

1. Every estimate is keyed by the executed model id (Claude `message.model`, Codex rollout `turn_context.model`),
   never an alias. A new version is a new arm whose prior is the previous version's posterior with inflated variance.
2. Per (model, effort, task family) a Beta posterior on pass rate; decisions use the posterior with a margin and the
   existing promote hold band; anchor tasks repeat K = 3 with an M-of-K sufficiency rule (Ares 2603.07915).
3. Exponential forgetting of old labels even for a fixed id: discounted Thompson sampling (Raj & Kalyani,
   arXiv 1707.09727) or discounted / sliding-window UCB (Garivier & Moulines, arXiv 0805.3415). Half-life starts at
   ~60 days, tuned to observed drift.
4. A fixed anchor battery (8–12 briefs with executable checks) re-run on each new model version seen in receipts and
   monthly; anchors equate the IRT scale across time.
5. Exploration never reaches zero (floor 0.05). A per-arm change detector (CUSUM or posterior predictive check on
   recent pass rate) triggers anchor re-runs and a temporary ε raise for that arm.

## 5. Build order

1. Slices 1–2 (in progress): Codex models callable from Claude (`tw.py codex`, which also fixes the `--out`
   last-message collision), router on the Codex path, model in ticket and `promote`, `TW-Pin`, decaying ε,
   propensity. Progress: `2026-09-28-joint-routing-progress.md`.
2. Transcript-mining pilot (in progress): `thinker-worker/bench/mine_labels.py`, outputs untracked under
   `scratchpad/labels/`.
3. `TW-Check:` header, then `tw.py outcome` runs it and records pass/fail/unknown; coordinator accept becomes a
   separate weak field.
4. `router.shadow` + `backend_jev` (POST `/v1/systemone`) + Kev in shadow; candidate-card A/B (D5) on mined labels.
5. Joint action space in routes/route rows (D1), model-step channel (D10), combination rule (D11) offline first.
6. Anchor battery, per-arm posteriors with forgetting, change detector (§4); then frontiers / IRT (D4).

## 6. Open

- Task-family partition for posteriors: TW-Class alone, or class × role? (Per-role priors only if labels show a
  difference.)
- Candidate-card content with zero measurements: provisional coordinator judgments, marked as such.
- Whether OptimalThinkingBench's verified half transfers to delegated agent work (Astra: unproven).
