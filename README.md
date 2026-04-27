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

## Adding more

New skills land here in their own subdirectory as I write them. Each follows the same structure: a tool-agnostic `SKILL.md`, optional `references/` for runtime-specific implementation notes.

## License

MIT.
