# OMP execution from any caller

`tw.py omp` hands a bounded assignment to the local OMP agent from any harness or shell that can run Python. It is an execution backend, not a fixed model: OMP's configuration picks the model, so a local model switch needs no thinker-worker edit. Native admissions in `routes.json` govern native routes only. The caller's authorization and host permissions still apply.

## Dispatch

Write a brief with the normal `TW-Role`, routing header, owned files, context pointers, an acceptance check that can fail, and a stop condition. The command's `--role` must match the brief. Review and ideation briefs keep `TW-Authorization` and `TW-Scope`. Give independent verification to a different author or session. When the assignment owns files or has a useful partial result, add these header lines; the wrapper turns them into an assignment contract the worker sees first:

```
TW-Scope: exact owned files and allowed operations
TW-Checkpoint: useful partial artifact to save as work progresses
TW-Stop: condition that ends this assignment
```

Run the canonical command through the caller's background mechanism (Claude Code: `run_in_background: true`; Codex: a long-running exec) and wait for its completion notice:

```
python <thinker-worker>/scripts/tw.py omp --role worker --brief-file <brief.md> --cd <checkout>
```

- `--role` names the assignment type, `--brief-file` the written assignment (sent to OMP as plain prompt text on standard input, and saved for inspection), `--cd` the worker's working directory.
- Leave `--model` and `--thinking` unset so the worker runs OMP's configured model. For a deliberate per-run override, pass the full `provider/id` selector; a bare id such as `local-model` can resolve to an old alias provider. An unsupported selection is an error, never permission to switch routes.
- `--approval-mode` overrides OMP's approval policy for one run. Approval settings are not OS-level isolation. Use an isolated OMP configuration for tests that would otherwise write production memory.

OMP's configured tools, extensions, skills and approval policy carry through unchanged.

## Time limits and resuming

Each attempt gets 7,200 s (2 h) by default. Leave `--timeout` unset: real local assignments run for tens of minutes, and a short cap cuts the worker off mid-task. The wrapper must outlive its allowance, so run it in the background or give the caller's own command limit more than the allowance plus cleanup time; killing the wrapper can lose its logs and leave the worker running.

A timeout keeps the work: the worker's files and its saved OMP conversation stay on disk, and the wrapper continues from them.

1. **Automatic continuation.** After a clean timeout (the process tree exited and a saved session exists), the wrapper resumes the same session once and tells the worker to inspect current files, keep completed work, and stop on any operation whose outcome is uncertain. `TW-Risk: external` or `destructive` skips this step; `--no-retry-on-timeout` turns it off.
2. **Resume command.** A run that still ends timed out returns `resume_command`. Run it as given to continue the same session; it sends `continue.md`, a continuation brief with the original header, written in the run folder. Repeat while the work progresses, checking partial files between runs. For `external` or `destructive` work, establish what already happened before resuming.

Set `--timeout <s>` (seconds per attempt) or `--total-timeout <s>` (hard wall-clock budget across both attempts; the continuation receives what remains) only for a deliberately bounded run such as a smoke test. `TW_OMP_TIMEOUT` sets the per-attempt default for a shell. A timeout is not a model-quality verdict.

## Results

The command prints one JSON line and saves the events, stderr, final assistant text and worker session under `~/.thinker-worker/omp/<run_id>/`.

- `session_id` and `tool_use_id` key this execution's receipt. `worker_session_id` and `session_file` identify the OMP conversation, which can span several executions.
- `model_name` is the display name OMP shows for the model (the `name:` in OMP's `models.yml`, rewritten on each local model switch); read it to know which model ran. `provider` and `effective_model` come from OMP metadata and can stay fixed across model switches.
- `completed` requires exit 0, no timeout, a terminal response and a non-empty final answer, all from the last attempt. A process exit, a terminal answer and an accepted artifact are separate facts. Each execution keeps its own record; label a later run on its own.
- `usage` sums the main assistant's streamed messages only, not auxiliary services or nested agents.

To give the same worker follow-up work, write a new bounded brief and add `--resume <session_file>` to the canonical command. A resumed author stays the author: send its work to a different session for independent review. Keep independent writers in separate checkouts or disjoint scopes. Timeout cleanup covers only the launched process tree; when a result shows `kill_failed: true`, reconcile that tree before assigning another writer to those files.

## Verification

Run a check that can fail on a materially wrong delivered artifact, with a known-positive control. Worker-written tests alone do not establish acceptance. Record acceptance with the returned receipt identifiers in the OMP namespace; an optional `TW-Check` runs in the recorded working directory. Outcome labels do not turn partial execution into completed work.

```
python <thinker-worker>/scripts/tw.py outcome --harness omp --session <session_id> --tool-use-id <tool_use_id> --accepted yes
python <thinker-worker>/scripts/tw.py tally --harness omp
```

Model evidence is per execution, so an OMP configuration change can bring a different model without touching native admissions or priors. Judge model quality from many trials, and token cost only from recorded usage.

## Boundaries

The native hook does not intercept this subprocess as a native child. Structural brief checks and execution records do not establish semantic authorization, effective permissions or correctness. Use the route when authorized, and respect an explicit denial rather than switching backends around it. Launch from a trusted directory with a trusted `PATH`; Windows executable lookup can prefer a program in the launch directory. No daemon, MCP server or OMP restart is needed.
