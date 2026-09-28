# Controlled runs for two-sided (model, effort) labels: plan (2026-09-28, Windows)

Status: proposed. Full-run parameters need Arian's yes (design D16). Design context:
`2026-09-28-joint-routing-design.md` (D4, D6, D7, §4). Why: mined transcripts give 81 pass : 1 fail
(`scratchpad/labels/PILOT.md`), so mined labels cannot bound a pair from above.

## 1. OptimalThinkingBench (OTB) findings

| Fact | Source (opened 2026-09-28) |
|---|---|
| Paper: OptimalThinkingBench, Aggarwal et al., Meta. Two halves: OverthinkingBench (simple queries) and UnderthinkingBench (reasoning tasks). | arXiv 2508.13141, https://arxiv.org/abs/2508.13141 |
| Dataset: `facebook/optimal_thinking_bench`, one file `otl_bench.jsonl`, not gated, sha `949ee6b5dc7960928dab98704cb380ded43c7636`. It holds 1,877 rows: 1,327 overthinkingbench + 550 underthinkingbench (11 Reasoning Gym tasks × 50). The HF copy omits the math problems (card: "only a subset ... that does not contain the math problems"). | https://huggingface.co/api/datasets/facebook/optimal_thinking_bench ; https://huggingface.co/datasets/facebook/optimal_thinking_bench/raw/main/README.md ; counted from the downloaded file |
| License: the HF `LICENSE` file and the code repo `projects/otb/LICENSE` are both **CC BY-NC 4.0**. The HF card text says "OptimalThinkingBench Research License". Non-commercial research use fits; the dataset is not redistributed (kept untracked under `scratchpad/controlled/`). | HF `LICENSE` at the sha above; https://raw.githubusercontent.com/facebookresearch/RAM/main/projects/otb/LICENSE |
| Programmatic half = **UnderthinkingBench** (confirms Astra). `evals/underthink_eval.py` extracts the first `\boxed{...}`, applies per-task formatting (A::B: non-`#AB` chars to spaces), and calls `reasoning_gym.create_dataset(task).score_answer(...)`. OverthinkingBench is graded by an LLM judge (`evals/overthink_eval.py`), so it is out of scope for hard labels. | https://github.com/facebookresearch/RAM/tree/main/projects/otb ; `evals/underthink_eval.py` (raw, main) |
| OTB pins `reasoning_gym==0.1.23`. The prompt is `question + " Answer the final answer in \boxed{}"` (`generate.py`). | `projects/otb/requirements.txt`, `generate.py` (raw, main) |
| `reasoning_gym` is not installed in any env here, and installing it is out of scope for this task. The scorers for 5 of the 11 tasks are pure Python and were ported verbatim from the v0.1.23 tag. `ab`: exact match. `bitwise_arithmetic`: `eval(problem) == int(ans, 0)`. `fraction_simplification`: exact simplified numerator and denominator. `letter_counting` and `maze`: the base-class rule (exact match = 1.0; a substring gets partial credit). I diffed these against `main`: the scorers are identical, and `dataset.py` only adds a cascade method. | https://raw.githubusercontent.com/open-thought/reasoning-gym/v0.1.23/reasoning_gym/... |
| The other 6 tasks have custom scorers (knight_swap 89 lines, advanced_geometry 53 and needs numpy+sympy, quantum_lock 28, propositional_logic 25, puzzle24 21 and needs sympy, tsumego 18). They are portable, but not yet ported. | same tag |

Label rule: pass iff the ported scorer returns 1.0; any partial credit counts as fail. This is stricter than OTB's
mean score, and it is on purpose: we want a binary sufficiency label.

## 2. How each item reaches each pair

(filled from the smoke; see §4)

## 3. Anchor battery candidates

(pending)

## 4. Smoke run

(pending)

## 5. Proposed full-run parameters (need Arian's yes)

(pending)

## 6. Unverified

(pending)
