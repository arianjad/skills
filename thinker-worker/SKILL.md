---
name: thinker-worker
description: Delegate bounded work to child agents from Claude Code or Codex - native subagents, or Codex, Claude, the local OMP agent or Gemini through agy started as a separate process. Gives the four roles, the brief template, the role paragraphs to paste, model and effort guidance, the runner commands, and a reader that shows which model and effort each native child ran. Use at a session's first delegation (standing instructions count). Work a few tool calls settle stays inline.
---

# Thinker/worker

The coordinator is the session you are in. It frames the task, writes briefs, dispatches, merges results and keeps records current; it can read sources and run checks itself. A child returns exact artifacts, checks and uncertainties. Spot-check a child's load-bearing claims at the source before you rely on them.

## Roles

Name the role on the brief's first line, `TW-Role: <role>`. It is a label for the child and for `tw.py ran`; nothing checks it.

- `worker`: substantial bounded execution, or a tough problem for a thinker (ask for the answer, its evidence, the strongest argument against it, and what stays unknown).
- `leaf`: a short, objectively checkable step (extraction, inventory, simple reconciliation). Keep physics judgment, architecture, adversarial review and acceptance off a leaf.
- `independent-review`: an open "what is wrong" pass on an artifact at a fixed commit or path. The brief carries the artifact, the acceptance criteria (a recompute check counts) and the scope, and none of the coordinator's own reasoning: no expected answers, no explanation of the artifact, no question that points at a suspected gap. Your hypotheses go to a second, fresh dispatch after the first report.
- `ideation`: at most N ranked divergent directions, as its own dispatch, never folded into a review.

## Brief template

```
TW-Role: <role>
Goal: <what and why, one or two lines>
Context: <context file to read first>
Write scope: <explicit file list; or "read-only">
Deliverable: <path>
Done when: <a check that can fail>
Boundaries: <destructive boundary; kill only processes you launched>
Constants: <name> read from <source>
Checkpoint: write <file> at the first milestone and update it as results land
Stop: <stop condition>

<the role paragraph below, pasted as the last thing in the brief>
```

Name a native child's deliverable for its task, not `report`, `summary`, `findings` or `analysis*.md`: Claude Code refuses a subagent's Write to those names.

## Role paragraphs

Paste the paragraph for the brief's role at the end of the brief.

- worker: "Execute the coordinator's bounded assignment. Preserve other agents' edits, checkpoint meaningful progress, run proportional checks, and report exact artifacts, results and uncertainties; escalate a changed objective or consequential assumption to the coordinator."
- leaf: "Complete only this bounded leaf assignment with the rules given. Report exact artifacts and checks; escalate ambiguity or judgment calls to the coordinator."
- independent-review: "Review the assigned artifact adversarially. Do your own open pass for what is wrong against the acceptance criteria first: identify unsupported, incorrect, fragile or overbuilt parts with exact source references, and run a check yourself when it settles a claim. If the brief lists claims to test, answer them after your findings, in their own section. Report findings; do not edit the files under review."
- ideation: "Propose at most the requested number of ranked directions. Label each speculative and state what would confirm or kill it; cite prior art you find. Do not edit project files."

## Model and effort

Pick per dispatch: Sonnet for mechanical work, Opus for delegated reasoning, Fable for thinking, Haiku only to watch or relay. Name the model on every dispatch. Effort: medium when the brief fixes what to do, high when choosing the next step is part of the job, xhigh for adversarial or the hardest reasoning; physics or convention judgment never below medium. Native calls take the alias (`sonnet`, `opus`, `fable`, `haiku`); the runners take the tool's own model id (`tw.py claude` the full Claude id; `tw.py codex`, `agy` and `omp` their own ids).

## Native dispatch

Claude Code:

```
Agent(subagent_type: "general-purpose", model: "<alias>", effort: "<effort>", prompt: <brief>)
```

Add `name: "<name>"` to message the child later with SendMessage, and `isolation: "worktree"` when its writes must be isolated. `/tasks` shows each running child's model and effort.

Codex: `spawn_agent` with an explicit `model`, `reasoning_effort` and `fork_turns: "none"` (the current tool needs a fork setting other than full history for a model override). Claude models go through `tw.py claude`.

## Runners

For a model the native tool cannot start (a Codex model from Claude Code, a Claude model from Codex, the local OMP agent, Gemini through agy), write the brief to a file and run, in the background (Claude Code: Bash with `run_in_background: true`; Codex: an exec session you keep polling until the process exits):

```
python "${CLAUDE_SKILL_DIR}/scripts/tw.py" <codex|claude|omp|agy> --brief-file <brief.md> --cd <repo or scratch dir> --model <id> --effort <effort>
```

The brief goes to the tool on stdin, verbatim. The command waits and prints one JSON line: `model` (the model that ran, where the tool reports it), `effort`, `session_id`, `last_message` (path of the closing message; the deliverable is wherever the brief put it), `completed`, `exit_code`, `timed_out`, `usage`. The same line is appended to `~/.thinker-worker/log.jsonl`; each run's events, stderr and closing message stay in `~/.thinker-worker/<tool>/<run_id>/`. From Codex, the skill folder is `~/.codex/skills/thinker-worker`.

- `--timeout` is seconds per attempt, default 7200 (two hours) for every runner.
- `--mode` overrides the permission default: Codex full access (`danger-full-access`, passed as `--sandbox`), Claude `bypassPermissions` (`claude -p` cannot answer a permission prompt), agy `--dangerously-skip-permissions`, OMP its own approval policy.
- `--resume <id>` continues a session (claude, agy, omp; OMP takes the session file). Codex: `codex exec resume <session_id>`.
- `--model` and `--effort` are optional; omitted, the tool's own default runs.
- `tw.py claude` runs `claude -p --model <id> --effort <effort> --output-format json`; `model` comes from the result's `modelUsage`.
- `tw.py codex`: `model` and `effort` come from the Codex rollout's `turn_context`.
- [OMP](references/omp.md): continues a timed-out run once and returns a `resume_command`. [agy](references/agy.md).

## What each native child ran

```
python "${CLAUDE_SKILL_DIR}/scripts/tw.py" ran "${CLAUDE_SESSION_ID}"
```

One JSON line per native child of the session: `name`, `agent_type`, `requested` (model and effort on the call), `role` (from the brief's `TW-Role:` line), `turns` (`[model, effort, consecutive turns]`, as the child's transcript records them), and token totals. It reads Claude Code's own transcripts under `<config dir>/projects/<project>/<session>/subagents/`, for `~/.claude` and for `CLAUDE_CONFIG_DIR`; without a session id it reads the session whose children changed last. That layout and the per-turn effort field are undocumented: if they change, it prints nothing.
