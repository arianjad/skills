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

Delegation from Claude Code or Codex: four roles (`worker`, `leaf`, `independent-review`, `ideation`) named on a brief's first line, a brief template, the role paragraph to paste at the end of each brief, and model and effort guidance. Native children are the built-in agent with `model` and `effort` on the call. There are no hooks, no activation and no allow-lists: nothing can deny a dispatch.

`scripts/tw.py` starts another vendor's command-line agent on a brief file and waits: `tw.py codex`, `tw.py claude` (a direct `claude -p`), `tw.py omp` (the local OMP agent; it continues a timed-out run once) and `tw.py agy` (Antigravity). Each prints one JSON line with the model that ran, where the tool reports it, the session id and the last message's path, and appends it to `~/.thinker-worker/log.jsonl`. `tw.py ran [session]` reads Claude Code's own transcripts and shows, for each native child of a session, its role, the model and effort on every turn, and token totals.

**Files:** `SKILL.md` (the page); `references/omp.md`, `references/agy.md` (runner details); `scripts/tw.py`; `scripts/test_tw.py` (`python scripts/test_tw.py`, fake executables, no network).

**Install:** link the folder into each harness like the other skills (Windows: `mklink /J %USERPROFILE%\.claude\skills\thinker-worker <repo>\thinker-worker`, same for `.codex\skills`). `tw.py hook` exits 0 and prints nothing, for settings that still carry an old thinker-worker hook entry; remove such an entry by hand.

## Debugging

### systematic-debugging

A standalone adaptation of Superpowers' debugging skill: investigate the root cause, compare working patterns, test one hypothesis at a time, then verify a focused fix. The package includes three supporting technique documents and optional Codex UI metadata. It requires no Superpowers plugin, hooks, executable helpers or other skills.

The source is pinned to `obra/superpowers` commit `8ca22dba9a94f28898bbce59f2537ff4d87c747d`. Its MIT license and notice are retained inside the package. See [attribution](systematic-debugging/ATTRIBUTION.md) for the adaptation and [local-use instructions](systematic-debugging/INSTALL.md) for Claude Code, Codex or direct-file use by a local agent. Copy the whole `systematic-debugging/` directory to the receiving harness's skill directory.

## Codebase audits

### anti-bloat-auditor

Audits local codebases, agent repositories, and scientific simulations for unnecessary provenance machinery, abstraction layers, expensive polling, write-only telemetry, and numerical hot-loop overhead. Separates read-only discovery from guided implementation, with source evidence and checks that preserve data and numerical behavior.

The portable artifact is [anti-bloat-auditor/SKILL.md](anti-bloat-auditor/SKILL.md). Copy its directory into your harness's skill folder, or supply the file as instructions to another LLM. Invoke it with a request such as: "Use anti-bloat-auditor to audit this repo read-only and rank the smallest useful simplifications."

## Adding more

New skills land here in their own subdirectory as I write them. Each follows the same structure: a tool-agnostic `SKILL.md`, optional `references/` for runtime-specific implementation notes.

## License

MIT.
