# Antigravity (agy) execution from any caller

`tw.py agy` delegates to the Antigravity CLI (`agy`) in headless stream-json mode. Like `tw.py omp` it is an execution backend for any caller: no native activation, no `routes.json` entry, no caller session ID. Read [OMP dispatch](omp.md) for the shared contract (brief validation, saved evidence, outcome, boundaries); this file lists only what differs.

```
python <thinker-worker>/scripts/tw.py agy --role worker --brief-file <brief.md> --cd <checkout> [--model <id>] [--effort low|medium|high|xhigh|max] [--mode accept-edits|auto|plan] [--resume <conversation_id>] [--timeout <s>]
```

- `--model` is an id from `agy models` (the effort suffix is part of some ids, e.g. `gemini-3.8-flash-low`). Omitted, agy uses its own default. agy owns the catalogue. `reported_model` is the id in agy's `init` event: with `--model` it repeats the requested id, and without it `init` carries no model, so it is null (agy 1.5.9, probed 2026-11-15). agy's stream carries no executed-model metadata, so there is no `effective_model`.
- `--effort` is agy's own effort flag, passed only when given. agy reports no executed effort, so receipts hold `requested_effort` only. `tally --harness agy` therefore counts every run at model null and tier null.
- Permissions: by default the run passes `--dangerously-skip-permissions` (Arian's choice, 2026-11-15). `--mode <m>` passes that mode instead and drops the skip flag. The receipt and result JSON record requested and resolved settings under `permissions`; effective enforcement stays unverified, as for the other backends.
- The brief goes to agy's standard input as one JSON line (`{"event":"user","message":{"content":...}}`), never on the command line. The process working directory is `--cd` (agy has no cwd flag).
- Resume: `--resume` takes the `conversation_id` the earlier run returned and passes it as `--conversation`.
- Completed means exit 0, no timeout, final `result` event with status `SUCCESS`, and a non-empty response. `ERROR`, a missing `result` event, an empty response or a nonzero exit are all not completed.
- Evidence under `<home>/.thinker-worker/agy/<run_id>/`: `events.jsonl`, `stderr.log`, `last.md` (the response), `result.json`. `TW_AGY_TIMEOUT` sets the default timeout (seconds, else 3600).
- Record outcomes with `outcome --harness agy` and read them with `tally --harness agy`.
- agy loads the user's global agent rules, so even a trivial reply costs tens of thousands of input tokens.
