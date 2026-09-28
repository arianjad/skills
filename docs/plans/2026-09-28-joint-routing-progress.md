# Joint routing (slices A, B) — progress

Worker log, TDD per item. Suite = every `python thinker-worker/scripts/test_tw_*.py`.
Baseline before A1: 16/16 test scripts exit 0 (2026-09-28, Windows).

| Item | Test (seam) | Red evidence | Green |
|---|---|---|---|
| A1 floor | test_tw_route.py shipped block: physics brief under the coin at tw-worker-high is advised `tw-worker-medium` (hook) | JSONDecodeError: hook printed nothing (floor high lifted the explored pick back to high: no action) | routes.json physics=medium; suite 16/16. test_tw_act BASE pins physics=high (floor mechanics, not shipped value); test_tw_routes activate line now physics=medium |
| A1 models + A2 | test_tw_codex.py (renamed from test_tw_astra.py; codex CLI + fake codex): Sol worker, Luna leaf, Sol review admitted with `-m <model>` and the role body on stdin; Luna worker denied (`not allowed for worker`), Sonnet denied (`not a Codex model`); `codex-` tool_use_id; dispatch rows `tool_name: codex` | argparse: invalid choice 'codex' | routes.json Claude roles gain gpt-6-sol (worker, review), gpt-6-luna (leaf); list[0] unchanged; `astra` -> `codex --model`; suite 16/16 |
