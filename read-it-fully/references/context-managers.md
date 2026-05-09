# Read It Fully — Composing with Context Managers

Read-it-fully has two modes: load it whole, or load it in chunks. Search is a way to obtain chunks, not a separate mode.

For native Claude Code tooling, see [`claude-code.md`](claude-code.md).

## Two modes

**Whole.** All content into parent context in one call. Default when it fits.

**Chunks.** Semantic pieces of original content into parent context across multiple calls. Default for large content. Search plays three roles inside chunks-mode:

- *Chunking mechanism.* For indexed content, query each section ("methods", "results", "conclusions") to retrieve that section's text. Exhaustive only if you query every section the document has. A section never queried is a section never read. Couple queries to the TOC/headings before claiming full coverage.
- *Follow-up.* After the read, search for cross-references, specific terms, or facts you need to verify.
- *Re-chunking.* When a fixed-boundary chunk split a concept (function spanning two reads, paragraph crossing pages), re-query to retrieve the joined view.

## Priority

Read-it-fully wins on conflicts. SessionStart "no Read for analysis" is for routine work; an explicit "read fully" overrides for prose comprehension.

## Tools by source

Pick the tool by source; both modes work with most sources.

| Source | Whole | Chunks (direct) | Chunks (search-based) |
|---|---|---|---|
| URL | `defuddle` (clean markdown into context) | — | `ctx_fetch_and_index` → `ctx_search` |
| Local text | `Read` | `Read` with `offset`/`limit` | `ctx_index` → `ctx_search`; `ctx_execute_file` for extraction (your code over the file) |
| PDF | (small PDFs only) | `pdf_read_pages` by section/page range | `pdf_search` (within pdf-mcp) |
| JS / auth page | — | `browser-use` (Playwright DOM / screenshots) | — |

The ctx-mode family (`ctx_fetch_and_index`, `ctx_index`, `ctx_batch_execute`, `ctx_execute(_file)` with `intent`) all stage content into the same FTS5/BM25 sandbox. `ctx_search` retrieves matching chunks of the original text. No model in the loop. Purely lexical retrieval.

Named tools are illustrative as of writing. Classify a new ingestion tool by what it returns: original-content chunks (fits Whole or Chunks) vs LLM-generated summary (separate concern below).

## Avoid: LLM-summarizer tools

A separate concern from the modes above.

Examples: `WebFetch` (Claude Code's WebFetch passes pages through a small fast sub-model and returns the sub-model's response, not raw content), hypothetical "distill"-style MCPs that wrap an internal LLM, `Agent` dispatch (a subagent is itself a model reasoning over the source). Parent never sees the original text behind any of these.

For read-it-fully, treat LLM-summarizer tools as SKILL.md step-3's honest-digest path: name the delegation, get user opt-in, spot-check load-bearing claims against the source. Never claim "I read it fully" if a summarizer was the only contact with the source.

For GitHub URLs specifically, WebFetch's description recommends `gh` CLI via Bash. That path returns raw content directly to the parent and is suitable for read-it-fully.

## At session start

Note what's loaded. Match source → tool. For chunks-mode, decide whether direct addressing (sequential reads, page ranges) or search-based retrieval (query per section, exhaustive coverage check) is the better mechanism for the document's structure. Keep the parent in the read seat.