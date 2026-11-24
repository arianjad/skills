# Antigravity (agy) runner

`tw.py agy` runs the Antigravity CLI (`agy`) headless in stream-json mode, from any caller. One attempt per run; the OMP continuation is OMP-only.

```
python <thinker-worker>/scripts/tw.py agy --brief-file <brief.md> --cd <checkout> [--model <id>] [--effort low|medium|high|xhigh|max] [--mode accept-edits|auto|plan] [--resume <conversation_id>] [--timeout <s>]
```

- `--model` is an id from `agy models`; ids that end in an effort suffix (`-low`, `-medium`, `-high`, `-xhigh`) already carry the effort, so leave `--effort` out for those. Omitted, agy uses its own default. `reported_model` is the id in agy's `init` event: with `--model` it repeats the requested id, and without it `init` carries no model, so it is null (agy 1.5.9, probed 2026-11-15). agy's stream reports no executed model or effort.
- Permissions: by default the run passes `--dangerously-skip-permissions` (Arian's choice, 2026-11-15). `--mode <m>` passes that mode instead and drops the skip flag.
- The brief goes to agy's standard input as one JSON line (`{"event":"user","message":{"content":...}}`). The process working directory is `--cd` (agy has no cwd flag).
- Resume: `--resume` takes the `session_id` (agy's conversation id) an earlier run returned and passes it as `--conversation`.
- `completed` means exit 0, no timeout, a final `result` event with status `SUCCESS`, and a non-empty response.
- agy loads the user's global agent rules, so even a trivial reply costs tens of thousands of input tokens.
