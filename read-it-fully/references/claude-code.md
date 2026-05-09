# Read It Fully — Native Claude Code Tooling

Maps the tool-agnostic operations in `SKILL.md` to native Claude Code tools — those that come with the Claude Code engine and behave the same in CLI, VS Code extension, JetBrains, and web. The extension wraps the CLI engine, sharing settings (`~/.claude/settings.json`) and tool descriptions; semantics are identical.

For non-native ingestion tools (PDF MCPs, content extractors, sandboxing/indexing plugins, browser automation), see [`context-managers.md`](context-managers.md).

**Conflict rule.** If anything here contradicts read-it-fully when the user has explicitly asked, read-it-fully wins.

## Read (files)

- `file_path` must be absolute.
- A default line cap exists (templated in the system prompt as `MAX_LINES_CONSTANT`; the value varies by Claude Code version, so don't assume a fixed number). Pass explicit `offset` and `limit` for chunked reads.
- Hard cap of ~25,000 tokens per call, observed via the tool error `File content (N tokens) exceeds maximum allowed tokens (25000)`. On dense files (logs with long lines, prose with embedded data) this fires near 700–1000 lines. Budget chunks accordingly — 500–700 lines on dense content, more on sparse text.
- Multimodal: reads images (PNG, JPG) visually in a single Read call. Reads Jupyter notebooks (`.ipynb`) with cell outputs.
- Cannot read directories.
- Empty files return a system-reminder warning in place of content.

## Read on PDFs

The native Read tool can open `.pdf` files, but its current spec requires structural hints for anything beyond a short document:

- For PDFs longer than ~10 pages, you MUST pass `pages` (e.g. `pages: "1-5"`). Without it the call fails.
- Maximum 20 pages per request.
- Earlier versions silently truncated `.pdf` reads without `pages` (observed: 5+7+7 = 19 of 27 pages on a Nature Reviews PDF, 2026-04-27, with no error).

For any multi-page PDF, prefer a format-specific tool (pdf-mcp). See `context-managers.md` for the chunks-mode tool table. Native Read on `.pdf` is for spot-checks, not full reads.

## REPL shorthands

The REPL exposes shorthands mapping to native primitives. Verified caps:

- `cat(path, off?, lim?)` — line-based, uncapped output. `off` and `lim` are line numbers, not bytes.
- `sh(cmd, ms?)` — merged stdout+stderr, byte-truncated at exactly 30,000 bytes after the subprocess exits. Pipe to a file and `cat()` it back when output may exceed.
- `rg(pattern, path?, opts?)` — silently caps at 250 matches (`head` option default). Pass `{head: N}` for more.
- `rgf(pattern, path?, glob?)` — silently caps at 250 paths.
- `gl(pattern, path?)` — uncapped.
- `put(path, content)` — never throws; returns error text on permission-denied or timeout.

The `o` auto-await is one layer deep — see CLAUDE.md and `plans/repl-auto-await-one-layer-deep.md` for the patterns that bite.

## WebFetch (URL fetching)

**Important — WebFetch does not return raw page content.** From Claude Code's system prompt:

> Fetches the URL content, converts HTML to markdown. Processes the content with the prompt using a small, fast model. Returns the model's response about the content. Results may be summarized if the content is very large.

WebFetch passes the page through a small fast sub-model with the caller's prompt and returns that sub-model's response. The parent never sees raw text. **For read-it-fully, this is delegated reading** — only suitable as SKILL.md step-3's honest-digest path, with user opt-in. Spot-check load-bearing claims against the source.

Do not confuse Claude Code's `WebFetch` with the Anthropic API's `web_fetch_*` server tool, which returns the actual document content. Different tools, same name; only the API tool returns raw content, and it isn't exposed in Claude Code sessions.

Other WebFetch behaviors:
- 15-minute self-cleaning cache.
- HTTP→HTTPS auto-upgrade.
- Cross-host redirects are NOT auto-followed; the tool reports the redirect URL and you re-issue the call.
- WebFetch's own description recommends the `gh` CLI via Bash for GitHub URLs (`gh pr view`, `gh issue view`, `gh api`). That path returns raw content directly to the parent and IS suitable for read-it-fully.

For raw URL ingestion that satisfies the evidence gate, use a non-native tool — see `context-managers.md` (URL row of the tools table: `defuddle`, `ctx_fetch_and_index` + `ctx_search`, or `browser-use` for JS/auth pages).

## Bash

Bash output is hard-capped at 30,000 characters (`BASH_MAX_OUTPUT_LENGTH` default). Truncation is **middle-cut**, not tail — head and tail are kept, the middle is dropped. For large outputs needed for a full read, redirect to a file (`cmd > /tmp/out`) and Read in chunks.

## Agent (subagent dispatch)

Agent spawns a subagent with its own context window. For read-it-fully, this maps to SKILL.md step-3's "delegated full-read digest" option. Name it as delegation in the response, and spot-check load-bearing claims against the source after the subagent returns. Subagent reports are leads, not ground truth.

## Multimodal reads for figures

Render PDF pages or other documents to PNG locally (e.g. `pdftoppm`), then Read the PNG. Multimodal Read handles PNG/JPG visually. If no rendering pathway is available in the environment, say so — never infer figure content from caption text alone.
