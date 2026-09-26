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

Coordinator/worker mode for substantial tasks: a strong model owns framing, planning, adversarial review and acceptance; bounded workers do the execution. Built for Codex (Astra/Sol/Luna) and ported to Claude Code (Opus workers, Sonnet leaves, Fable independent review).

A session-scoped PreToolUse guard (`scripts/tw.py hook`) checks every fresh agent dispatch in an activated session: the brief must start with `TW-Role: worker|leaf|independent-review`, the `model` must be explicit and allowed for that role, and the agent type must match the role. Worker and leaf roles also accept [effortmining](https://github.com/nagisanzenin/effortmining) `effortmining:miner-<tier>` agents, which pin reasoning effort; the per-role model check still applies. The guard checks request fields only; it cannot confirm the model or effort the child actually ran, and it denies the dispatch if it hits an internal error.

**Files:**
- `SKILL.md` — the contract; `references/claude.md`, `references/codex.md` — per-harness routing.
- `claude-agents/` — the three Claude worker agents the installer places in `~/.claude/agents/`.
- `scripts/tw.py` — reversible installer, activation, and the guard hook; `scripts/test_tw_*.py` — guard routing, hook fail-closed, and install round-trip tests (`python scripts/test_tw_<name>.py`).

**Install:** clone the repo, then `python thinker-worker/scripts/tw.py install` (writes both `~/.claude` and `~/.codex` copies plus one guard hook per harness; `uninstall` reverses it, `check` verifies). Activate per session with the command in `SKILL.md`.

## Adding more

New skills land here in their own subdirectory as I write them. Each follows the same structure: a tool-agnostic `SKILL.md`, optional `references/` for runtime-specific implementation notes.

## License

MIT.
