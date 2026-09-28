# Controlled runs for two-sided (model, effort) labels: plan (2026-09-28, Windows)

Status: proposed. The full-run parameters in §5 need Arian's yes (design D16). Design context:
`2026-09-28-joint-routing-design.md` (D4, D6, D7, §4). Motivation: mined transcripts give 81 pass : 1 fail
(`scratchpad/labels/PILOT.md`, untracked), so mined labels cannot bound a pair from above.
Runner: `thinker-worker/bench/controlled_runs.py`. Outputs and data are untracked, under `scratchpad/controlled/`.

## 1. OptimalThinkingBench (OTB) findings

| Fact | Source (opened 2026-09-28) |
|---|---|
| Paper: OptimalThinkingBench, Aggarwal et al. (Meta). It has two halves: OverthinkingBench (simple queries) and UnderthinkingBench (reasoning tasks). | arXiv 2508.13141, https://arxiv.org/abs/2508.13141 |
| Dataset: `facebook/optimal_thinking_bench`, a single file `otl_bench.jsonl`, not gated, sha `949ee6b5dc7960928dab98704cb380ded43c7636`. It has 1,877 rows: 1,327 overthinkingbench and 550 underthinkingbench (11 Reasoning Gym tasks × 50). The HF copy leaves out the math problems. | https://huggingface.co/api/datasets/facebook/optimal_thinking_bench , https://huggingface.co/datasets/facebook/optimal_thinking_bench/raw/main/README.md , row counts from the downloaded file |
| License: the HF `LICENSE` file and the code repo's `projects/otb/LICENSE` are both **CC BY-NC 4.0**. The card text calls it the "OptimalThinkingBench Research License". Non-commercial research use is covered. The data is not redistributed: it stays untracked in `scratchpad/controlled/otb/`. | HF `LICENSE` at the sha above; https://raw.githubusercontent.com/facebookresearch/RAM/main/projects/otb/LICENSE |
| The programmatically verified half is **UnderthinkingBench** (this confirms Astra). `evals/underthink_eval.py` does three things: it extracts the first `\boxed{...}` and cuts at the first `}`; it applies per-task formatting (for A::B, characters other than `#AB` become spaces); it calls `reasoning_gym.create_dataset(task).score_answer(...)`. OverthinkingBench is graded by an LLM judge (`evals/overthink_eval.py`), so it cannot give hard labels. | https://github.com/facebookresearch/RAM/tree/main/projects/otb , `evals/underthink_eval.py` (raw, main) |
| OTB pins `reasoning_gym==0.1.23`. Its prompt is `question + " Answer the final answer in \boxed{}"`. | `projects/otb/requirements.txt`, `generate.py` (raw, main) |
| No env here has `reasoning_gym` installed, and I did not install it (not allowed by the brief). Five of the 11 scorers are pure Python and were ported verbatim from tag v0.1.23: `ab` (exact), `bitwise_arithmetic` (`eval(problem) == int(ans, 0)`), `fraction_simplification`, and the base-class rule used by `letter_counting` and `maze` (exact match scores 1.0; a substring match gets partial credit). These scorers are identical on `main`. | https://raw.githubusercontent.com/open-thought/reasoning-gym/v0.1.23/reasoning_gym/... (diffed against main) |
| The other 6 tasks have custom scorers: knight_swap 89 lines; advanced_geometry 53 lines, needs numpy and sympy; quantum_lock 28; propositional_logic 25; puzzle24 21, needs sympy; tsumego 18. They are portable but not ported yet. | same tag |

**Label rule.** A run is labeled pass when the scorer returns 1.0. Partial credit counts as fail. A non-zero exit or
an empty answer is labeled unknown.

**Extraction fix (found in the smoke).** OTB's verbatim extraction scored 0 on answers that were correct but written in
LaTeX: `\boxed{\#A\ \#A ...}` and `\boxed{\mathrm{0xFD8D23813B8}}` (the cut at the first `}` keeps the `\mathrm{`).
The label therefore uses a normalized extraction that un-escapes `\#`, unwraps `\mathrm{}`, `\text{}`, `\texttt{}` and
`\mathtt{}`, and collapses A::B whitespace. OTB's verbatim score is kept in each row as `otb_score`. The selftest
asserts that both of these smoke cases fail with the OTB-verbatim extraction and pass with the normalized one.

## 2. How each item reaches each pair (flags checked with `--help`, claude 2.1.283, codex-cli 0.153.4)

- **Claude**: `claude -p --model <m> --effort <low|medium|high|xhigh|max> --output-format json
  --no-session-persistence --tools "" --setting-sources "" --strict-mcp-config --disable-slash-commands
  --system-prompt "You are a careful problem solver."`. The prompt goes in on stdin and the cwd is an empty temp dir.
  `--bare` would skip hooks, but it reads auth only from `ANTHROPIC_API_KEY`, which is unset here (OAuth). So the
  runner strips the call with `--setting-sources ""`, `--tools ""` and a short system prompt instead.
- **Codex**: `codex exec -m <m> -c model_reasoning_effort=<tier> -s read-only --ephemeral --json
  --skip-git-repo-check -C <tmp> -o <tmp>/last.md -`. Usage comes from `turn.completed` events, the same parser as
  `tw.py codex_evidence`. It is duplicated in the runner because `tw.py` is being edited by another worker.
- **No-tools line**: the prompt says "Answer directly from reasoning. Do not use tools, run code, or read files."
  Claude has no tools at all. Codex tool events are counted in `tool_events`: 0 in the smoke.
- **Codex model availability (blocker for the planned Codex pairs)**: `gpt-6-sol` returns HTTP 400 "not supported
  when using Codex with a ChatGPT account". The error arrives before any generation (0 tokens). The model catalog
  `~/.codex/models_cache.json` lists `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` and `gpt-5.5`; it has
  no `gpt-6-sol` and no `gpt-6-luna`. Rollouts from 2026-09-27 ran `gpt-6-sol` with token counts. Three rollouts from
  2026-09-28 02:16, which are not from this runner, hit the same 400. `routes.json` still names `gpt-6-sol` and
  `gpt-6-luna`.

## 3. Anchor battery candidates (private transcripts; referenced by tool_use_id only)

The selection criteria: a mined pass row; a local check command; a repo that is still present; a pre-dispatch commit
(`git rev-list -1 --first-parent --before=<dispatch ts>`); and a later commit that holds the check file in its
finished form. Two approaches are borrowed from SWE-bench, which builds tasks from real repo changes, gives the
model the codebase as it stood before the change, and has 2,294 tasks (arXiv 2310.06770, abstract): the pre commit is
the start state, and the check files at the post commit are hidden acceptance tests. I did not verify SWE-bench's
test-selection details this session.

| # | tool_use_id | repo | pin (pre) → hidden check (post) | check | summary | replay notes |
|---|---|---|---|---|---|---|
| A1 | toolu_01KztgFq6FiGhivyu4yH4kua | DSMC-sims | 91f7c99 → d55d82b (5 files) | `python tools/test_manifest.py` | write a manifest module to a contract | the brief mentions WSL/SPARTA 5×; confirm the check is pure Python |
| A2 | toolu_01FLVBpwkfjiCcjMQa8sJqSt | DSMC-sims | e829bff → 0d31381 (11 files; pre is 2 days old) | `python tools/test_ml3d_contract.py` | data contract + labelling checker | the check may need run artifacts that are not in git; WSL mentions |
| A3 | toolu_01CPPAPgX2o8rybLBxdTgqBf | DSMC-sims | 4670d94 → 2120d34 (31 files, concurrent workers) | `pytest -q tools/test_d2_bins.py` | exact-overlap bin scorer | the post diff mixes in other workers' changes; the check may read untracked run outputs |
| A4 | toolu_01A9fTHwVQvFJDWQfWu7dyTe | DSMC-sims | 4670d94; the check already existed and the child did not change it | `python3 -m unittest tools/wsl/test_ctest_gate.py` | smoke exit-code gate | runs under WSL python3; last choice |
| A5 | toolu_01Nvwe3AYU4437pQnfi2dRw9 | heff | 9196b67 → 808ca8d (3 files) | `conda run -n heff python -m pytest tests/ -q` | two-spin enumerator | clean, small, env `heff` |
| A6 | toolu_01FVc4wW7tK6esSiNZ4Edoe4 | heff | f26dae5 → b240cc7 (3 files) | same | geometry kernel + master reduction | clean, small |
| A7 | toolu_01UTK5K9xqpiuoD489uDhsny | Local-Agent | a68d0af → 01810b7 (9 files) | `python -m unittest tests.test_mnemosyne_maintenance` | bounded maintenance script | the script targets live Hermes memory: run with HOME/state dirs pointed at temp |
| A8 | toolu_01ENnvWmonJLwFztsLWWy8UZ | Unruh-Molecules | 1d7b01f → 79486d3 (72 files, 58k lines incl. results) | `python -m pytest tests/test_gate_a.py -q` | rotor Hamiltonian module | the post commit bundles concurrent work; extract only the test file |
| A9 | toolu_012atsrQHoGk4QLFbEsHN8ua | Unruh-Molecules | 1d7b01f → be67ae6 | `python -m pytest tests/test_gate_b.py -q` | AIT solver module | the check writes a results JSON (inside the clone only) |
| A10 | toolu_01891t2hQ7jkSnyJkpzDbHp6 | nsdpv-protocols-research | 44d97bd → 7a85a7bf (4 files) | `conda run -n structure python -m pytest -q scripts/test_molecular_noise_secondary.py` | apply review fixes | the brief depends on a review doc (check that it is in the pre tree). The mined output shows a mid-run `DID NOT RAISE` before a later pass: verify the mined pass label |
| A11 | toolu_014nqivbnq5ELzYnhx2cNuQj | skills (thinker-worker) | d10089a → 35529f8 (3 files) | `python thinker-worker/scripts/test_tw_outcome.py` | `outcome --cause` flag | small; the harness under test is itself the router |

Dropped: the gvs5h rows (tests never committed), `FEQoBHArm8` (its check scripts are not in a repo), `8s712ffRTM`
(needs the SPARTA ctest build), `DmXyYJkWdu` (its selftest calls decision-model servers), the scratch-workspace heff
rows (workspace gone), and Movies (the check prints dB levels and has no pass/fail).

**Replay protocol (proposed, not built).**
1. `git clone --no-hardlinks <repo> scratchpad/controlled/anchors/<id>/repo`, then `git remote remove origin`.
   A clone rather than a worktree, because a worktree shares `.git` with the live repo and a child's commits would
   land there. Removing the remote makes a push impossible.
2. Checkout the pre commit.
3. Read the original brief at run time from the parent transcript, by tool_use_id, and rewrite the absolute repo
   paths to the clone. All 11 briefs contain absolute `C:\Users\Arian\Code\...` paths.
4. Dispatch: `claude -p --model --effort` with default tools and cwd set to the clone, or `codex exec -s
   workspace-write -C <clone>`.
5. Restore the post-commit check files (`git checkout <post> -- <check paths>`) and run the check. The label is pass
   or fail from the exit code plus the pass marker.
6. Guard: `git -C <live repo> status --porcelain` and HEAD must be unchanged before and after. If either moved, the
   run is invalid.

Keyword scan of the 11 briefs, counts only: 5 mention push, 10 mention commit, 4 mention WSL. None asks for an install.
Whether a mention is an instruction or a prohibition is unread. Step 1 makes both harmless.

## 4. Smoke run (2026-09-28, the only spend)

Items `ab:0` and `bitwise_arithmetic:0`, K = 1, output in `scratchpad/controlled/smoke/results.jsonl` with raw stdout
under `raw/`. The planned Codex pair `gpt-6-sol:high` hit the 400 above with 0 tokens. I substituted
`gpt-5.6-sol:low`, the cheapest Codex worker pair in `routes.json` that is also in the catalog, so the spend stayed
at 4 model calls.

| item | pair | label | otb_score | wall s | output tok | overhead tok | cost |
|---|---|---|---|---|---|---|---|
| ab:0 | claude:sonnet:low | pass | 0.0 (LaTeX `\#`) | 92.2 | 8,493 (8,447 thinking) | 8,172 cache-create | $0.118 |
| bitwise_arithmetic:0 | claude:sonnet:low | pass | 1.0 | 25.9 | 1,811 | 8,047 cache-create | $0.050 |
| ab:0 | codex:gpt-5.6-sol:low | pass | 0.0 (LaTeX `\#`) | 23.5 | 731 (687 reasoning) | 30,751 input | n/a (ChatGPT plan) |
| bitwise_arithmetic:0 | codex:gpt-5.6-sol:low | pass | 0.0 (`\mathrm{`) | 29.7 | 1,152 (1,129 reasoning) | 30,667 input | n/a |
| ab:0, bitwise:0 | codex:gpt-6-sol:high | unknown (400) | – | 6.4, 4.7 | 0 | 0 | 0 |

Costs are the CLI's `total_cost_usd` at list price (`costBasis: list`). The account is on a subscription, so these
are API-equivalent figures, not billed amounts.

**Readings.**
- Every model answer was correct. The OTB-verbatim scorer produced 3 fails, and all 3 were formatting artifacts, so
  the smoke yields **no genuine fail label**. The verifier can produce fail, as the selftest shows with perturbed
  answers and with a mutated scorer that the selftest caught. These two items did not separate the cheapest pairs.
- The per-call cost trap, measured: after stripping, `claude -p` still writes **~8.1k cache-creation tokens per call**,
  with 0 cache reads between consecutive calls. On the short item that is 4.4× the output tokens. `codex exec` reads
  **~30.7k uncached input tokens per call** for a ~150-token prompt. A "skill descriptions were shortened" warning in
  the events suggests the user config's skills make up much of that. `--ignore-user-config` might cut it (untested).

## 5. Proposed full-run parameters (need Arian's yes)

**Status 2026-09-28: Stage 0 declined by Arian; no controlled run is approved.** The `gpt-6-sol` refusal in the smoke was the npm codex CLI 0.153.4; after updating to 0.158.0, gpt-6-sol and gpt-6-luna answer.


Strongest objection to OTB as the fail source: the smoke went 4/4 correct at the cheapest tiers. If UnderthinkingBench
saturates on 2026 models, it reproduces the one-sidedness of the mined labels. Its items were selected for a
thinking-versus-non-thinking gap in 2025 models (Astra report, §2 of the paper). So stage 0 measures the fail rate
before anything larger runs.

| Parameter | Value | Rationale |
|---|---|---|
| Stage 0 items | 50: 10 per ported task (ab, bitwise_arithmetic, fraction_simplification, letter_counting, maze), `--seed 0` | smallest set that gives a per-task fail rate to ±~15 pp; only ported scorers |
| Stage 0 pairs | `claude:sonnet:low`, `codex:gpt-5.6-sol:low` | the cheapest pair per harness is where fails must appear if they appear anywhere |
| Stage 0 K | 1 | item variety carries the replication on synthetic items; K = 3 is reserved for anchors (§4 of the design) |
| Stage 0 dispatches | 100 | 50 × 2 × 1 |
| Stage 0 estimate | Claude ≈ 50 × $0.05–0.12 ≈ **$2.5–6** list-equivalent, plus ~0.4M cache-create tokens. Codex ≈ 50 × ~32k ≈ **1.6M tokens** against the ChatGPT plan. Wall ≈ 50 × 59 s + 50 × 27 s ≈ **72 min** serial | smoke means (§4); the ranges are only two points per pair |
| Go rule | continue to stage 1 when stage 0's fail rate is ≥ 10 % for at least one pair. Otherwise port the 6 remaining scorers (knight_swap, puzzle24, tsumego, …) and repeat stage 0 on them | a benchmark with no fails adds nothing to D4 |
| Stage 1 pairs | `sonnet:low`, `sonnet:medium`, `opus:low`, `opus:high`, `gpt-5.6-sol:low`, `gpt-5.6-sol:high`. Swap in `gpt-6-sol` and `gpt-6-luna` if Codex access returns | spans the leaf and worker roles in `routes.json` at the tiers where a pass/fail boundary is plausible; Fable and Astra are review roles and OTB labels do not map onto review |
| Stage 1 dispatches | 50 × 6 × 1 = 300; opus cost not measured | measure opus on 2 items before the run |
| Anchor stage A | 1 anchor (A5 or A11, the smallest clean ones) × 2 pairs × K = 1, replay protocol §3 | tests the clone / path-rewrite / guard pipeline before any battery spend; its agentic cost is unmeasured |
| Anchor battery | 8 of A1–A11 that survive stage A (preference: A5, A6, A11, A7, A9, A10, A1, A8) × 4 pairs (`sonnet:medium`, `opus:low`, `opus:high`, `gpt-5.6-sol:medium`) × K = 3 = **96 dispatches** (design D8) | K = 3 and M-of-K sufficiency per design §4. The M-of-K rule is attributed to Ares (arXiv 2603.07915); I confirmed the paper this session (adaptive per-step effort selection for agents) but not the M-of-K detail |

## 6. Unverified or open

- Why stripped `claude -p` still writes ~8.1k cache-creation tokens (built-in scaffolding?) and why consecutive calls
  get no cache reads. Not probed.
- Whether `codex exec --ignore-user-config` still authenticates and cuts the ~30.7k-token input. Not run (no spend).
- The `gpt-6-sol`/`gpt-6-luna` 400: is it an account or plan change, or a renamed id? It affects `routes.json` and
  `tw.py codex` beyond this plan.
- Opus and Fable per-call cost; `gpt-6-astra` on OTB. Not measured.
- Anchor replays: none has been run. Every "replay notes" entry is inferred from commit metadata, and the keyword scan
  does not tell an instruction from a prohibition. The mined pass for A10 needs a re-check.
- The OTB `reasoning_gym` version: ported from tag v0.1.23 per `requirements.txt`. Whether Meta's own results used
  exactly that version was not checked.
