# Read It Fully — Claude Code Implementation Notes

This file maps the tool-agnostic operations in `SKILL.md` to specific Claude Code tools, and documents observed behaviors worth knowing when running this skill in Claude Code.

## Survey

- **File size and shape:** `wc -l <path>` for length; `head -50 <path>` for first-page shape.
- **PDF structure:** `pdf_info` for page count and basic metadata; `pdf_get_toc` for the table of contents. If the TOC is empty, probe with `pdf_search` on likely section keywords ("method", "result", "discussion", "conclusion"); fall back to fixed-page chunks if nothing surfaces.
- **URL fetching:** `ctx_fetch_and_index` (context-mode plugin) for general web pages; `defuddle` (defuddle skill) for cluttered article-style pages. Prefer `ctx_fetch_and_index` when the content needs to live in the context-mode knowledge base.
- **Pasted text already in context:** no tool needed — scan inline for headings, speaker turns, section breaks.

## Reading

- **Files:** `Read` tool has a ~2000-line default and a ~25,000-token hard cap per call, whichever hits first. On dense files (long-line logs, prose with embedded data) the token cap fires near 1000 lines; budget chunks accordingly. Pass explicit `offset` and `limit` for chunked reads.
- **PDFs:** use `pdf_read_pages` with explicit page ranges. Do **not** use `Read` on `.pdf` files — see the truncation gotcha below.
- **URLs:** content already retrieved via `ctx_fetch_and_index` lives in the knowledge base; query it with `ctx_search`. Content from `defuddle` lands in context directly.

## PDF truncation gotcha

`Read` on a `.pdf` extracts text but silently truncates after the first few calls. Observed cutting off at p. 19 of a 27-page document on 2026-04-27. The result looks substantive but misses later sections — supplemental material, late references, final equations, the actual results in some paper layouts. Always use `pdf_read_pages` with explicit page ranges for any PDF longer than a few pages.

## Visual content

For figures, equations, scanned regions, and tables, text extraction is insufficient. The pathway in Claude Code:

1. Render the relevant page(s) to an image (PNG). The `markitdown` MCP server can convert PDFs with image preservation; otherwise use a local conversion (`pdftoppm`, `convert`) and read the resulting PNG with `Read`.
2. Read the image with the `Read` tool — Claude Code's multimodal Read handles PNG/JPEG.

If the user's environment doesn't have a rendering tool available, say so before claiming a figure was inspected. Do not infer figure content from caption text alone.

## Parent vs subagent reads

When dispatching delegated full-read digests via the `Agent` tool: subagents return summaries, not raw content. Their reports are leads, not ground truth — spot-check load-bearing claims against the source after the subagent returns. SKILL.md's honesty rules treat this as non-negotiable.
