# Router ensembles, joint (model, effort) routing, cold start, pinned choices: literature survey (2026-09-28)

Context: `thinker-worker/scripts/tw.py` `route()` (l.681-725) runs backends in order and takes the FIRST valid
answer (no combination), fails open to the coordinator tier, and explores one tier below the coordinator on a
ticket-hash coin. Backends are zero-shot typed-choice classifiers (see `2026-09-27-decision-model-survey.md`).

Evidence labels: [raw] = text read from the fetched page (ctx_fetch_and_index, full-text search);
[summ] = WebFetch answer, i.e. a small model's summary of the page I fetched (quotes are its extraction, not
re-verified byte-for-byte); [inferred] = my reasoning. Every source below was opened this session.

## Q1. Combining several routers' probability outputs

**Direct answer: I found no paper that ensembles several independent router/classifier models' probability
outputs for LLM model or effort selection and reports the gain over the best single router.** What exists is
adjacent: seed-averaging of one router, cluster-score aggregation inside one router, cascades that combine an
ex-ante router with a post-hoc quality check, and pipelines that combine one router's margin with other signals.

Queries run (WebSearch): `ensemble of LLM routers combining router probabilities model selection arXiv`;
`"mixture of routers" LLM routing`; `router ensemble stacking multiple LLM routers outperforms best single router`;
`"ensemble" of routers LLM routing "majority vote" OR "averaging" router predictions arXiv 2025 2026`;
`"meta-router" OR "router of routers" OR "combining routers" LLM model selection arXiv`;
`LLM routing multiple difficulty classifiers "log-linear" OR "product of experts" OR "stacking" ...`;
`"ensemble router" OR "router ensemble" LLM arXiv`; `LLM query difficulty estimation ensemble of predictors
routing calibration combine classifiers ...`; `"multiple routers" OR "ensembling routers" LLM model selection ...`.
Positive control for the query shape: the same searches returned many single-router papers (RouteLLM, RouterDC,
Router-R1, kNN routing), so the zero is not an empty-index artifact.

Surveys checked for router-level ensembling:
- LLM-ensemble survey, arXiv 2502.18036 [summ]: "none of the methods described involve ensembling or combining
  multiple routers"; all routing methods use a single router. https://arxiv.org/html/2502.18036v6
- Routing+cascading survey, arXiv 2603.04445 [summ]: router ensembles "not discussed".
  https://arxiv.org/html/2603.04445v2
- LLMRouterBench, arXiv 2601.07206 [summ + raw]: benchmarks 10 routers individually; no router combination. Its
  headline: "several recent routing methods, even including the commercial router OpenRouter, do not outperform a
  simple baseline" (Best Single model), and "many routing approaches achieve broadly comparable performance".
  https://arxiv.org/html/2601.07206v1
- **Secondary-source misattribution:** the Nadir blog states "Ensemble routing consistently outperformed
  single-classifier baselines. Combining multiple independent predictors averages out stochastic failures" and
  attributes it to LLMRouterBench [summ]. The LLMRouterBench fetch above does not support that claim. Treat as
  unsupported. https://getnadir.com/blog/llmrouterbench-acl-2026-most-routers-fail-baseline/

Closest adjacent work, with numbers:
- **Seed ensemble of one router** (arXiv 2603.20895, "LLM Router: Rethinking Routing with Prefill Activations")
  [summ]: 10 seeds trained, top 5 by validation BCE kept, "at inference, their predictions are averaged"
  (arithmetic mean). No ablation of ensemble vs single seed was reported in the extract; the reported comparison
  is SharedTrunkNet mean per-model AUC 0.8560 vs 0.8040 for the next-best approach. https://arxiv.org/html/2603.20895v2
- **Avengers-Pro** (arXiv 2508.12631) [raw]: one router, but it sums per-cluster "cost-capability scores ... over"
  the top-p=4 nearest of k=60 k-means clusters (Qwen3-embedding-8B), and picks the argmax model. vs strongest single
  model GPT-5-medium: +7.1% accuracy at comparable cost; -27% cost at comparable accuracy; -63% cost at 90% of
  GPT-5-medium's performance. The comparison is to single *models*, not single routers. (Nadir's "7% better at 63%
  lower cost" merges two different operating points.) https://arxiv.org/html/2508.12631
- **Cascade routing** (Dekoninck et al., arXiv 2410.10347) [raw]: unifies routing (ex-ante quality estimate) and
  cascading (post-hoc estimate) into one sequential policy; "improving performance by up to 8% on the RouterBench
  benchmark ... and by 14% on the SWE-Bench benchmark"; routing beats the baseline cascade by 10% when ex-ante
  estimates are accurate, cascade routing beats all. Noted failure: a binary post-hoc quality signal makes a
  threshold cascade degenerate ("either admit all models (τ=0) or only correct ones"). https://arxiv.org/html/2410.10347
- **CoMed** (arXiv 2609.26913) [summ]: gates on (i) self-consistency of N samples, (ii) a single router's top-1/top-2
  probability margin m(x)=p(1)-p(2) as an ambiguity signal, (iii) a verifier-checked peer disagreement; sequential
  gating, not pooling. MedQA: router alone 68.0% -> router+CoMed 76.3% (+8.4 pt); ~33% fewer decoded tokens than
  always-collaborate. https://arxiv.org/html/2609.26913
- **DART** (arXiv 2606.23181) [raw]: combines K no-think drafts, not routers, but reports the voting-rule trade-off
  directly relevant to pooling: on MATH-500, unanimity K=2 accept 78.0% / precision 90.8%; unanimity K=3 73.6% /
  93.5%; majority vote K=3 100.0% / 82.4%. Unanimity (agreement gating) beat majority vote on precision.
  https://arxiv.org/html/2606.23181
- **vLLM Semantic Router** (arXiv 2603.04444) [raw]: combines many signals through priority-ordered Boolean
  decision blocks, "hard routing with early exit: the first decision whose gate evaluates to true captures the
  request" — the same first-wins structure as tw.py, deliberately symbolic rather than a learned pooling.
  https://arxiv.org/html/2603.04444
- **TO-Router** (arXiv 2408.12320) [raw]: frames routing as MoE gating and cites ensemble learning as related,
  but trains one router. https://arxiv.org/html/2408.12320v3

Not found: any use of log-linear (geometric) pooling or stacking across router models for LLM routing.

## Q2. Joint (model, effort / thinking-budget) routing

**Direct answer: yes, several; the dominant pattern is a flat product action space scored by predicted
(quality, cost) with a scalar trade-off, not an ordered ladder explored step by step.** Effort-only routers
(Ares, DART) do exploit ordering: labels are "lowest sufficient tier", and inference escalates.

Queries run: `joint model and reasoning effort routing LLM router thinking budget arXiv 2025`; `routing reasoning
effort "low" "medium" "high" select model and effort level router GPT-5 reasoning_effort arXiv`; plus follow-ups
on the named papers.

Joint (model x effort-like knob):
- **Route-To-Reason (RTR)**, arXiv 2505.19435 [raw]: action = (model, reasoning strategy) pair. Learned embeddings
  per model and per strategy + query encoder feed two predictors (accuracy, output tokens), giving a "routing
  table ... for all combinations of candidate models and strategies"; policy picks argmax of
  score = λ·â − (1−λ)·l̂. Ordering: none beyond the scalar cost prediction. Numbers: 82.5% avg accuracy; vs best
  baseline EmbedLLM matches or beats accuracy with >39.6% fewer tokens; vs QwQ-32B alone +2.5 pt accuracy, >60%
  fewer output tokens. Trained offline on full labels (every pair evaluated). https://arxiv.org/html/2505.19435
- **R2-Router**, arXiv 2602.02823 [raw]: "selecting both the best LLM and an appropriate budget constraint"
  (output-length budget set by prompt instruction). Each LLM becomes a quality-vs-cost *curve*, interpolated from
  "only 6 anchor budgets"; "comparable quality at 4-5x lower cost" than prior routers; oracle AUDC +15% from
  curve data. Caveat they measured: models <4B follow tight length budgets poorly. https://arxiv.org/html/2602.02823v1
- **Avengers-Pro**, arXiv 2508.12631 [raw]: pool mixes thinking and non-thinking variants of one family
  (Qwen3-235B and Qwen3-235B-thinking) and GPT-5-medium, so model x mode is flattened into arms; usage shifts with
  α ("When α is low, Avengers-Pro tend to route queries to Qwen3 and Qwen3-thinking"). https://arxiv.org/html/2508.12631
- **OpenAI GPT-5 system** (system card, arXiv 2601.03267) [summ]: router between "a smart and fast model" and "a
  deeper reasoning model", using "conversation type, complexity, tool needs, and explicit intent (for example, if
  you say 'think hard about this' in the prompt)"; "continuously trained on real signals, including when users
  switch models, preference rates for responses, and measured correctness". Two arms, no public ordering/
  exploration detail. https://arxiv.org/html/2601.03267v1
- **Anthropic effort** (platform docs) [raw via WebFetch]: effort ladder `low, medium, high, xhigh, max`; "Effort is
  a behavioral signal, not a strict token budget"; recommends "Consider dynamic effort: Adjust effort based on task
  complexity" and per-model starting points (e.g. Opus 5.5 default medium; Fable 5 "Start with high"). No
  first-party router over (model, effort) is documented there. https://platform.claude.com/docs/en/build-with-claude/effort
- GitHub practice (issues, [summ]):
  - Cercano #32: "Return a structured decision: model, supported reasoning effort, short rationale, and whether the
    decision needs reassessment"; "Reassess semi-dynamically at task-phase boundaries ... or evidence of difficulty
    such as repeated failures." https://github.com/bryancostanich/Cercano/issues/32
  - swarm-automation #195: "Model selection and reasoning-effort selection must be treated as separate decisions",
    yet scores "each eligible model/effort combination" with fixed weights (expected success 35%, task fit 20%,
    ...); benchmark data as priors to be overridden by local stats later. https://github.com/SWARM-Media-Steaming/swarm-automation/issues/195
  - aidevops #32672: routes model tier + effort variant; raised the effort floor to medium after 18 attempts at
    `low` gave 13 blocked, 2 premature exits, 3 completions. https://github.com/marcusquinn/aidevops/issues/32672

Effort-only, ordered ladders (relevant to how tw.py explores):
- **Ares**, arXiv 2603.07915 [raw + summ]: per-step router picks gpt-oss-style `reasoning_effort` low/medium/high
  (prompt: "Produce exactly one word: low, medium, or high"). Labels: run each effort K=3 times; a level is
  sufficient if it reproduces the reference action in at least M of K trials; "we assign the label y_t by picking
  the lowest-cost sufficient level" [summ quote]. Results: SFT router ~35.2% (TAU-Bench Retail), 41.8%
  (BrowseComp-Plus), 45.3% (WebArena) fewer reasoning tokens at on-par-or-better success vs always-high; RL stage:
  Airline success 36.0% -> 42.0% and tokens 678k -> 133k vs SFT. https://arxiv.org/html/2603.07915
- **DART**, arXiv 2606.23181 [raw]: training-free two-stage: K no-think drafts, accept on agreement, else escalate to
  think mode with a budget set from draft entropy. Stage-1 accept falls 97.7% (MATH L1) -> 59.7% (L5) at 83.8-95.5%
  precision; vs adaptive-thinking baseline -35% tokens +2.6 pt (MATH-500), -55% thinking tokens +19.6 pt (HumanEval)
  on Qwen3-8B. https://arxiv.org/html/2606.23181

Model-only (checked, no effort axis): RouteLLM (arXiv 2406.18665) [summ] routes "between a stronger and a weaker
LLM", preference data + augmentation, cost "by over 2 times in certain cases". Router-R1 (project page) [summ]
interleaves "think" and "route" actions with a cost coefficient α; no effort/thinking-budget knob on the callee.
https://arxiv.org/abs/2406.18665 , https://ulab-uiuc.github.io/Router-R1/

Not verified: "Adaptive Model and Strategy Routing for Cost-Efficient LLM Services" (Pan, WWW'25; PDF at
home.ustc.edu.cn refused connection). RouterDC and RouterBench were not opened this session; no claims made.

## Q3. Cold start: zero/few labels, priors, bandits, censored feedback

**Direct answer:** three families: (a) zero-shot signals used directly (LLM judge / self-confidence), (b) bandits
with explicit forced exploration, optionally warm-started from offline data or priors, (c) learning under
partial feedback (only the chosen arm's outcome). One-sided feedback in the strict sense is studied (SLARouter,
apple tasting). I found nothing that matches our exact design, where the router probes one tier below the pick
and observes accept/reject. Monotone threshold bandits are the closest abstraction [inferred].

Queries run: `LLM routing cold start bandit Thompson sampling few labels arXiv`; `"one-sided feedback" OR "apple
tasting" OR "censored feedback" bandit routing escalation LLM`; `zero-shot LLM-as-judge router no training labels
difficulty routing cold start arXiv`; `monotone threshold bandit ordered arms "lowest sufficient" OR "minimum
sufficient" model LLM escalation cascade online learning`.

Zero-shot / no-label routing:
- **Zero-shot confidence for local-to-cloud escalation**, arXiv 2605.02241 [summ]: token log-prob, self-assessment,
  self-consistency, knowledge similarity. In-distribution (MMLU-Pro) best zero-shot AUROC 0.650-0.714 vs supervised
  0.644-0.676; OOD (TriviaQA) log-prob 0.717-0.833 vs supervised 0.512-0.564; "A supervised baseline trained on
  1,000 labeled examples never exceeds the zero-shot signal"; RouteLLM "unstable at small N, converges around
  N=250-500". Scope: factual QA, 7-8B local models. https://arxiv.org/html/2605.02241v1
- **Ares** (Q2) trains an LLM-prompted router by SFT on labels it produces itself, re-running each effort level
  K=3 times. That makes it a label factory, not a zero-shot router. https://arxiv.org/html/2603.07915
- **DART** (Q2) is training-free: agreement among cheap drafts is the gate. https://arxiv.org/html/2606.23181

Bandits, exploration schemes, warm starts:
- **OrcaRouter**, arXiv 2605.30736 [raw + summ]: LinUCB over models with variants LinTS, epsilon-greedy LinUCB, and
  round-robin warmup + UCB (n_RR in {30,100,300}); "These variants mitigate single-arm collapse when bandit feedback
  is sparse". Cold-start partial-information RouterArena scores: vanilla LinUCB 69.81+-0.40, LinTS 70.00+-0.42,
  epsilon-greedy 70.71+-0.25, RR+UCB 70.74+-0.08; offline full-information warm-up 73.54 (tuned 74.05). A
  non-contextual (bias-only) model "collapses the router to always selecting DeepSeek-chat".
  https://arxiv.org/html/2605.30736v1
- **ParetoBandit**, arXiv 2604.00136 [raw]: new arm added "with no warmup priors"; a good-and-cheap model reached
  sustained adoption in all 80 trials within ~142 steps; a bad-and-cheap one "correctly rejects ... in every seed".
  https://arxiv.org/html/2604.00136
- **BaRP**, arXiv 2510.07429 [raw]: "most routers are trained offline with labels for all candidate models, an
  assumption that breaks in deployment, where only the outcome of the chosen model is observed"; trains with policy
  gradient under simulated bandit feedback from offline logs; avg 73.57%, a relative +15.53% / +12.44% over
  full-information RouterDC / GraphRouter. The paper names its own limitation: it was trained on static logs,
  not truly online.
  https://arxiv.org/html/2510.07429
- **Contextual queueing bandits from user retrials**, arXiv 2602.02061 [summ, abstract]: implicit feedback from
  user retrials (explicit ratings "degrade user experiences"); "Thompson sampling with forced exploration at a
  decaying rate"; regret O~(sqrt t). https://arxiv.org/abs/2602.02061
- **LLM-derived priors for Thompson sampling**, arXiv 2608.03382 [summ, abstract]: LLM-extracted signals converted
  into Bayesian priors that warm-start TS; gains largest "once a small amount of interaction evidence has
  accumulated". Recommendation, not LLM routing. https://arxiv.org/abs/2608.03382
- Routing+cascading survey 2603.04445 [summ] lists PILOT (preference-prior LinUCB), MixLLM (contextual bandit with
  "binary user feedback"), MetaLLM, GreenServ as bandit routers; I did not open those papers.

One-sided / censored feedback:
- **SLARouter**, arXiv 2606.19376 [summ]: feedback "pertains to exactly one model response. So, the performance of
  all other models remains unknown", and is sparse ("fewer than 5% of requests may receive any signal"; observed
  IID with probability phi). Exploration: uniform random model with probability p_t = min(1, c/t^(1/4)), else a
  virtual-queue objective over per-model satisfaction heads; SLA and cost guarantees; up to 2.2x cost reduction on
  11 benchmarks. Models: Qwen3.5 2B/9B/35B/122B, an ordered size ladder, though the method does not use the order.
  https://arxiv.org/html/2606.19376
- **Apple tasting**, arXiv 2410.10404 [summ, abstract]: "the learner receives feedback only when predicting 1".
  https://arxiv.org/abs/2410.10404 (I could not read the paper body. The Helmbold et al. random-flip reduction
  comes only from a search snippet, so treat it as unverified.)
- **Threshold bandits with monotone arms**, arXiv 2509.02119 [summ, abstract]: "a monotonic structure of arm means",
  goals include identifying "the first above tau", i.e. the minimally sufficient level (clinical dosing is the
  stated analogue). https://arxiv.org/abs/2509.02119
- **Cascade escalation decision theory**, arXiv 2605.06350 [summ, abstract]: a "lightweight pre-generation router
  exceeds the best cascade policy on four of five datasets, mainly because it avoids the cheap model's generation
  cost". https://arxiv.org/abs/2605.06350
- Dekoninck cascade routing (Q1) [raw]: a binary quality signal makes threshold cascades degenerate.
  https://arxiv.org/html/2410.10347

## Q4. User-pinned choices in routing logs and evaluation

**Direct answer: not found as a studied topic.** I found no paper or benchmark that specifies how explicitly
user-pinned model choices are excluded, weighted, or used in router training or evaluation logs. The evidence
comes from three places: (i) product docs and issue trackers on precedence, (ii) one frontier system that uses
user switching as a training signal, and (iii) causal-routing work on logged-assignment confounding, which
covers pinned rows only by implication.

Queries run: `LLM router user explicitly selects model override bypass router logs training data selection bias
off-policy evaluation`; `OpenRouter auto router explicit model override ...; Not Diamond router fallback user
specified model`; `counterfactual LLM routing logged data propensity "routing policy" confounding treatment bias
regret minimization arXiv`.

- **GPT-5 router** (system card, arXiv 2601.03267) [summ]: trained on "when users switch models, preference rates
  for responses, and measured correctness"; routes on "explicit intent (for example, if you say 'think hard about
  this')". A manual switch is used as a *label*, not dropped. https://arxiv.org/html/2601.03267v1
- **OpenRouter Auto Router** docs [summ]: per-request settings override saved defaults ("request wins, unless you
  enable the section's 'prevent overrides' toggle"); the response `model` field records which model was used;
  optional router metadata header exposes the task classification; `cost_tier` bands low/medium/high/xhigh/max,
  "a tier is a band, not a ceiling". https://openrouter.ai/docs/guides/routing/routers/auto-router
- **Cercano #32** [summ]: "Keep explicit user model/effort choices authoritative. Let users pin a choice for a
  task, disable automatic routing, or restrict routing to local/approved providers."
  https://github.com/bryancostanich/Cercano/issues/32
- **aidevops #32672** [summ]: a user env override below the new floor is "raised to meet the floor 'with a
  warning'", so the floor beats the pin. https://github.com/marcusquinn/aidevops/issues/32672
- **Causal methods for LLM development**, arXiv 2605.25998 sec. 3.3.1 [summ]: "LLM routers are trained on data
  generated under an existing routing or evaluation policy ... outcomes under alternative model assignments remain
  unobserved"; "observed outcomes are confounded by the historical assignment mechanism"; whether logged context
  suffices for adjustment "is open". No mention of user self-selection. https://arxiv.org/html/2605.25998v1
- **Causal LLM Routing**, arXiv 2505.16037 [summ, abstract]: learns routing from observational data that "records
  only the outcome of the model actually deployed", minimizing decision regret directly. https://arxiv.org/abs/2505.16037
- **Routing collapse**, arXiv 2602.03478 [summ]: routers drift to the strongest model (~100% GPT-4 calls at high
  budget vs <20% for oracle). The cause: 94.90% of RouterBench queries have top-candidate margins <= 5e-2. The
  paper does not discuss logging feedback loops. https://arxiv.org/html/2602.03478v1

## What this means for tw.py [inferred]

1. No source shows that pooling several routers' probabilities beats the best single router; the one production analogue (vLLM Semantic Router) keeps tw.py's first-valid-wins shape. If backends are ever combined, agreement gating (DART unanimity, CoMed's top-1/top-2 margin) has measured precision gains; averaging has none on record here.
2. The below-the-pick exploration probe matches a monotone threshold bandit, and apple tasting describes the feedback: accept at tier k-1 says min-sufficient <= k-1, reject says > k-1, and non-explored rows say nothing about lower tiers. Ares's "lowest sufficient tier" label is the matching target, so fit P(min tier <= t) ordinally rather than a 4-way softmax.
3. For cold start: forced exploration (round-robin, epsilon, decaying c/t^(1/4)) beat vanilla UCB by ~1 pt in OrcaRouter, while an offline warm-up bought ~3-4 pt. The zero-shot backends are the prior, and one tier below at a known coin rate is the forced exploration.
4. For joint (model, effort), the literature flattens to a product action space scored by predicted quality minus lambda*cost (RTR) or per-model cost curves (R2-Router). Near-flat backend probabilities (the survey's Laya probe gave .17/.35/.20/.28) are the margin regime where routing collapse was measured.
5. Log coordinator/pinned rows with their propensity (1.0 for a deterministic pick, the explore rate for coin rows; route() already returns `explore` and `source`, l.724-725). Use pinned rows as outcome data but keep them out of off-policy value estimates, since positivity fails for them. GPT-5 instead treats user switches as labels, which is the alternative design.
