# Skills

Skills I use with Claude Code, mostly in my physics research — long papers, code-as-experiment work.

Each skill lives in its own directory. `SKILL.md` is the tool-agnostic behavioral contract; an optional `references/` subdirectory holds environment-specific notes (e.g. `references/claude-code.md`) for users on a particular runtime.

## Reading

### read-it-fully

Forces an LLM agent to walk every section of a long input and cite specifics from each, instead of skimming the start and end and pattern-matching to a familiar shape. Triggers on phrases like "read this fully", "read carefully", "in depth".

The failure this addresses is attention, not mechanics: even when the bytes sit in context, autoregressive generation biases the response toward salient anchors at the start and end and away from the middle. The skill forces intermediate generation steps that re-anchor attention across the whole input.

Tested on synthetic logs, a meeting transcript, a 5000-line numerical campaign log, and real PDFs from my Downloads.

**Files:**
- `SKILL.md` — tool-agnostic behavioral contract (survey, evidence gate, honesty rules, anti-frame patterns, examples).
- `references/claude-code.md` — Claude Code-specific tooling (Read tool, pdf-mcp, ctx_fetch_and_index, defuddle) and observed gotchas like the silent PDF truncation in `Read`.

On other runtimes, `SKILL.md` alone is the portable artifact. Map the generic operations (survey, read, fetch URL) to your environment's tools, or write your own `references/<your-runtime>.md`.

**Install (Claude Code):**

```bash
mkdir -p ~/.claude/skills/read-it-fully/references
curl -fsSL https://raw.githubusercontent.com/arianjad/skills/main/read-it-fully/SKILL.md \
  -o ~/.claude/skills/read-it-fully/SKILL.md
curl -fsSL https://raw.githubusercontent.com/arianjad/skills/main/read-it-fully/references/claude-code.md \
  -o ~/.claude/skills/read-it-fully/references/claude-code.md
```

Or, if you have the skills CLI:

```bash
npx skills@latest add arianjad/skills/read-it-fully
```

## Orchestration

### thinker-worker

Coordinator/worker mode for substantial tasks: a strong model owns framing, planning, adversarial review and acceptance; bounded workers do the execution. Built for Codex (Astra/Sol/Luna) and ported to Claude Code (Opus workers, Sonnet leaves; independent review and ideation on Astra via `tw.py astra`, or on Fable/Opus natively, default per role in `router.defaults`).

A session-scoped PreToolUse guard (`scripts/tw.py hook`) checks every fresh agent dispatch in an activated session: the brief starts with `TW-Role: worker|leaf|independent-review|ideation` and carries a routing header (`TW-Class`, `TW-Deliverable`, `TW-Accept`, `TW-Risk`). The role policy in `routes.json` sets the allowed models and effort tiers: a Claude dispatch names a generated `tw-<role>-<tier>` agent, a Codex dispatch an allowed model and `reasoning_effort`. Any guard error before admission denies the dispatch. After admission a router logs a tier decision to the session's receipts; per task class it can advise a different tier or (Claude) rewrite the agent, and a routing failure never denies. As shipped the router has no backend and every class is `advisory` with exploration 0.2: about one in five dispatches above the role's cheapest tier is advised one tier down (raised to a per-flag risk floor), and the rest run at the coordinator's tier. `tw.py outcome` labels a child's result and, on Claude only, records its token cost and race-checks pending rewrites; `tw.py promote` turns labeled receipts into a promote/demote/hold verdict. The guard checks request fields only; it cannot confirm the model or effort the child actually ran.

**Files:**
- `SKILL.md` — the contract; `references/claude.md`, `references/codex.md` — per-harness routing, receipts, and context-mode coexistence.
- `routes.json` — role policy per harness and router config; the installer generates one Claude agent per role and tier from it into `~/.claude/agents/`.
- `scripts/tw.py` — reversible installer, activation, the guard hook, and the `route`/`outcome`/`promote`/`astra` commands; `scripts/test_tw_*.py` — plain test scripts (`python scripts/test_tw_<name>.py`).

**Install:** clone the repo, then `python thinker-worker/scripts/tw.py install` (writes both `~/.claude` and `~/.codex` copies, the generated Claude agents, and one guard hook per harness; `uninstall` reverses it, `check` verifies). Activate per session with the command in `SKILL.md`.

- `--harness claude` (or `codex`) installs one harness only; the default `both` is the behaviour above.
- `--portable` writes the Claude hook as a home-relative bash command instead of absolute paths, for a `settings.json` synced between machines. It finds the skill under `$USERPROFILE` on Windows and `$HOME` elsewhere, runs the first of `python3`, `python`, `py -3` that starts, and does nothing if the skill is not installed on that machine. `--python-cmd '<cmd>'` puts your own interpreter first, inserted verbatim (for example `--python-cmd '"$USERPROFILE/anaconda3/python.exe"'`); if it does not start, the search falls back to the list. If no interpreter starts, the hook exits 2 (blocking the dispatch, with a fix hint on stderr) when this machine holds any thinker-worker activation state, and does nothing otherwise. With `--portable` the Codex hook gets the same home-relative `command`, plus a PowerShell `commandWindows` that searches `python3`, `python`, `py -3` on PATH (`--python-cmd` is bash syntax and applies only to `command`).
- On a second machine whose synced config already holds exactly the entry this install would write, `install` adopts it instead of adding a duplicate; a differing entry is refused. Use the same `--portable`/`--python-cmd` options on every machine sharing the file.
- Each install, adopt, and uninstall writes this machine's ledger to `~/.claude/thinker-worker-installs/<machine-id>.json` (override with `--ledger-dir`), which syncs with `~/.claude`. It records machine id (OS plus hostname, or `TW_MACHINE_ID`), OS, install and update times (UTC), the `tw.py` SHA-256, the install flags, each harness's hook entry and whether it was written or adopted, and `installed` or `uninstalled`. Rerunning `install` on an existing install refreshes the ledger. The private `~/.thinker-worker/manifest.json` is unchanged in role and not synced.
- `tw.py machines` (read-only) lists every ledger, marks this machine with `*`, and flags each installed machine whose `tw.py` SHA differs from the most recently updated one, printing the uninstall-then-install command built from that machine's own recorded flags.
- `uninstall` removes a shared hook entry only if no other machine's ledger with status `installed` claims the same entry; otherwise it keeps the entry and names the machine holding it.

## Adding more

New skills land here in their own subdirectory as I write them. Each follows the same structure: a tool-agnostic `SKILL.md`, optional `references/` for runtime-specific implementation notes.

## License

MIT.
