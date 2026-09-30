# Adding, updating, or archiving a model

`routes.json` in the skill's source repository (`~/Code/skills/thinker-worker`) is the one place a model is admitted.
Edit it only with `tw.py model`, which validates the result before writing and keeps the file in canonical form (a
test fails on a hand edit that is not canonical). Scope: the Claude/Codex dispatch router in `tw.py`. The decision
backends (`router.backends`) never see the model, and no other router is touched.

Run from the source repo root: `python thinker-worker/scripts/tw.py <command>`.

1. **Identify.** Get the exact id and where it runs.
   - Claude model: the native alias (`opus`, `sonnet`, `fable`) plus the full id the transcripts record. Probe what an
     alias resolves to: `grep -ho '"model":"claude-<family>[^"]*"'` over recent `~/.claude/projects/*/subagents/*.jsonl`.
   - Codex model: the id `codex exec -m <id>` accepts. Probe it once: `codex exec -m <id> "reply OK"`. Check the CLI version actually used by `tw.py codex`; a desktop model listing does not prove CLI availability.
   - Decide the roles (worker, leaf, independent-review, ideation) and, per role, the tiers if narrower than the
     role's (e.g. a cheaper model admitted as worker only at `high,xhigh`).
2. **Priors.** Per model, a `*` tier and any per-class tiers (`router.priors` classes). Either the user states them,
   or, on request, dispatch a Sonnet leaf (`tw-leaf-medium`, `TW-Class: R-research`) to collect cited facts only
   (ids, effort levels, independent and vendor benchmarks against the models it may replace, price, regressions; no
   recommendations). The coordinator turns the facts into a proposed prior table, cites the facts in one line each,
   and gets a yes before writing. Priors are a starting point; step 6 is how the model is actually compared.
3. **Write.** One `model set` per (harness, role). A Codex model dispatched from Claude Code needs both a
   `--harness claude` and a `--harness codex` entry for the role, or `tw.py codex` refuses it.
   ```
   tw.py model set --harness codex  --role worker --model <id> [--tiers high,xhigh] [--prior "*=medium" --prior C-coding=high]
   tw.py model set --harness claude --role worker --model <id> [--tiers ...]
   ```
   For worker additions, use the per-assignment model selection policy in `SKILL.md` and retain existing class priors unless model-specific evidence or the user supplies a change. `--default` is for an explicitly requested fixed preference; this worker policy uses no fixed preference. `--default` makes it the role's `router.defaults` model. Running the same command again changes nothing. A new model
   is appended; a role's first model (the Claude agent file's pin) is never changed here. A superseded model stays
   admitted (drop its default with `--default` on the successor). A model no longer offered:
   `tw.py model archive --model <id>` (removes it everywhere, keeps a dated record under `archived`; `model set`
   re-admits it for the given role and drops the record). Machine-local priors go in the override file named by `routes.json` `$override`, not here.
4. **Verify.** `tw.py models --harness claude` and `--harness codex` show the result; run every
   `thinker-worker/scripts/test_tw_*.py`; commit (the message names the prior source); `tw.py upgrade`; `tw.py check`.
   Push, and `git pull` + `tw.py upgrade` on the other machine, only after the user approves the push.
5. **Review.** A change to `tw.py` itself gets an independent review from another model family. A config-only change
   through `tw.py model` does not.
6. **Evidence.** `tw.py promote --harness claude --model <id>` reports per-class verdicts from receipts once the model
   has labeled dispatches. Revise its priors with `model set --prior` when the evidence disagrees.
