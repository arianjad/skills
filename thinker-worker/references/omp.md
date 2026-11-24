# OMP runner

`tw.py omp` hands a brief to the local OMP agent from any harness or shell that can run Python. OMP's own configuration picks the model, so a local model switch needs no thinker-worker edit.

```
python <thinker-worker>/scripts/tw.py omp --brief-file <brief.md> --cd <checkout>
```

- Leave `--model` and `--effort` unset so the worker runs OMP's configured model. For a deliberate per-run override, pass the full `provider/id` selector; a bare id such as `local-model` can resolve to an old alias provider. `--effort` is passed as OMP's `--thinking`.
- `--mode` passes OMP's `--approval-mode` for one run. Approval settings are not OS-level isolation. Use an isolated OMP configuration for tests that would otherwise write production memory.
- OMP's configured tools, extensions, skills and approval policy carry through unchanged.

## Time limits and resuming

Each attempt gets 7,200 s (2 h) by default. Leave `--timeout` unset: real local assignments run for tens of minutes, and a short cap cuts the worker off mid-task. With the automatic continuation the command can live for two allowances (about 4 h) plus cleanup, so run it in the background.

1. **Automatic continuation.** After a timeout, once the first process tree has exited and a saved session exists, the runner resumes the same session once and tells the worker to inspect current files, keep completed work, and stop on any operation whose outcome is uncertain. The result says `continued: true`.
2. **Resume command.** A run that still ends timed out returns `resume_command`. Run it as given to continue the same session; it sends `continue.md` (written in the run folder) and carries the run's model, effort, mode and timeout. Repeat while the work progresses, checking partial files between runs.
3. **Killed runner.** If the caller's own limit or a manual stop kills the runner, there is no result and no `resume_command`, but the saved session remains at `~/.thinker-worker/omp/<run_id>/sessions/*.jsonl` (the run folder exists from launch). Confirm the orphaned `omp` process tree has exited, then run the command with a continuation brief and `--resume <that file>`.

A timeout is not a model-quality verdict.

## Results

The JSON line's OMP fields:

- `session_id` and `session_file` identify the OMP conversation, which can span several runs. To give the same worker follow-up work, write a new brief and add `--resume <session_file>`.
- `model_name` is the display name OMP's `models.yml` held for the model at launch (Local-Agent's `switch-model.sh` rewrites it on each local model switch). `model_name_at_end` appears only when the name changed during the run, meaning a model switch happened mid-run. `provider` and `model` come from OMP's event metadata and can stay fixed across model switches. `effort` is the thinking level from the saved session.
- `completed` requires exit 0, no timeout, a terminal response with stop reason `stop`, and a non-empty final answer, all from the last attempt.
- `usage` sums the main assistant's messages across all attempts, not auxiliary services or nested agents.

Timeout cleanup covers only the launched process tree; when a result shows `kill_failed: true`, make sure that tree is gone before assigning another writer to those files.
