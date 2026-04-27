---
name: read-it-fully
description: Use when the user explicitly asks Claude to read something fully, carefully, completely, in depth, or to not skim — on files, papers, transcripts, threads, multi-file code dumps, or pasted text. Plans a structured walk through the whole input, verifies that specifics from every section can be cited back, and hands the user a response drawn from the substance rather than the frame. Do not auto-trigger on input size alone; wait for the explicit ask.
---

# Read It Fully

Goal: when the user asks you to read something completely, actually ingest every part of it before responding. Skimming long input — sampling the start and end, pattern-matching to a familiar shape, glancing at headings — produces shallow answers and misses load-bearing detail buried in the middle.

This skill operationalizes the rule already in the user's global instructions:
> When I share a file, link, paper, or thread: read it fully before responding. No skimming, no pattern-matching to a pre-chosen frame, no compressing-by-skipping.

The failure mode isn't mechanical — it's attention. Even when the bytes are already in context (pasted text, fully-loaded files), autoregressive generation biases the response toward salient anchors (start, headings, end) and away from the middle. The skill's job is to force intermediate generation steps that re-anchor attention across the whole input.

## When to use

Trigger on explicit asks:
- "read it fully", "read all of it", "read in depth", "read carefully", "read completely"
- "go through everything", "don't skim"
- Close variants

Don't auto-trigger on file size or perceived importance. If the user wants full reading, they'll say so. This deliberately biases toward under-triggering — over-triggering on every file drop would thrash.

## The core loop

### 1. Survey first
Know the shape before reading. Tools vary by source; the discipline doesn't.
- Files: `wc -l <path>` + `head -50 <path>` for size and shape
- PDFs: `pdf_info` for page count, `pdf_get_toc` for structure. If the TOC is empty, probe with `pdf_search` on likely section keywords ("method", "result", "discussion"); fall back to fixed-page chunks if nothing surfaces.
- URLs: fetch via `ctx_fetch_and_index` or `defuddle`, then survey
- Pasted text already in context: scan the existing content for structure — headings, speaker turns, section breaks

### 2. One-shot if it fits
The Read tool defaults to ~2000 lines per call. If the input is under that and not dominated by huge single lines, read it once. Chunking is a cost — extra tool calls, boundary-split risk — and buys nothing when the whole thing fits in one response.

The skill still fires for sub-threshold inputs. "Read fully" is about discipline (no skimming, cite specifics, walk the whole thing), which applies to a one-Read ingestion just as much as a chunked one.

### 3. Decide by context budget
If the input is large enough that reading all of it would dominate the remaining context window, don't silently degrade. Surface the tradeoff and let the user pick:

- **Full ingest** — chunked parent reading. Default when the input is a manageable fraction of remaining context.
- **Subagent digest** — dispatch agents that read the raw content and return summaries. Named honestly as delegation, not personal reading.
- **Two-pass** — low-resolution sweep (headings + first/last lines per section), then deep-read only sections relevant to the user's question. User opt-in.
- **Narrow scope** — ask the user to specify which parts matter most.

### 4. Plan the chunks — prefer semantic over fixed
When the input overflows one Read and fits the budget, look for natural boundaries before defaulting to fixed sizes.
- Markdown / papers: section headings
- Code: function or class boundaries; file boundaries in a multi-file dump
- Transcripts: speaker turns, timestamps, topic shifts
- PDFs: chapters or sections from the TOC

**If you surveyed boundaries, split on them.** Committing chunks to arbitrary midpoints after finding real boundaries wastes the survey. Only fall back to fixed chunks when the survey finds nothing usable.

Fixed-chunk defaults:
- Sparse code or logs: 500–1000 lines per chunk
- Dense academic prose, math, legal text: 200–400 lines
- Tables / structured data: chunk by row groups
- PDFs: by section if available, else 5–10 pages

### 5. Read each chunk to completion
Use `Read` with explicit `offset` and `limit`, or the medium-appropriate equivalent (`pdf_read_pages`, etc.). Don't sample within a chunk; read it through to its end.

**PDFs: use `pdf_read_pages`, not `Read`.** `Read` on a `.pdf` extracts text but silently truncates after the first few calls (observed cutting off at p. 19 of a 27-page document on 2026-04-27). The result looks substantive but is missing later sections — supplemental material, late references, final equations. `pdf_read_pages` with explicit page ranges has no such limit.

For pasted text already in context, there's no new tool call — the read is mental. Walk each section and name one specific detail from it before forming conclusions. If you can't, you haven't read it yet.

### 6. Verify before responding
Before writing your answer, be able to point to specific content from each section you're claiming to have read — a line range, a heading, a page, a quote. This is the attention gate: if a detail doesn't surface in an intermediate generation step, it won't inform the final response.

Two concrete moves for the response itself:
- **Cite locations when making claims** — "section 4 says X", "line 220 shows Y", "page 7 discusses Z". Gives the user something to spot-check and matches your standing rule that reports are leads, not ground truth.
- **For multi-chunk reads, add a brief coverage note at the end** — which sections or ranges you covered. Keep it terse. Makes coverage auditable without flooding the response.

### 7. Recover split concepts — only when chunks are reasoned over independently
Fixed boundaries sometimes land mid-function, mid-paragraph, mid-table, mid-argument. That matters when chunks are read in **separate reasoning contexts** — different turns or different subagents — where chunk N has already collapsed to a summary by the time chunk N+1 lands.

Back-to-back Reads in a single tool-use block don't have this problem. Both responses land in context before you reason over either. Skip recovery there.

When a split does matter:
- **Shift the window** — re-read with offset moved by half a chunk
- **Merge** — read the two chunks as one larger chunk when the split spans most of both

Pick whichever costs less. Re-chunking is internal.

### 8. Serial vs parallel — by dependency, not speed
- **Parallel Reads in one tool-use block** — fine, parent sees all bytes. Use when chunks are independent (multi-file code dumps, logs).
- **Serial** — when later chunks need earlier context (tutorials, narrative arguments, sequential reasoning).
- **Subagent fanout is not a default mechanism** — it's a user-menu choice from step 3, named as delegation.

When in doubt, serial is safer; parallel is faster.

### 9. Track coverage
For long multi-chunk reads, briefly note which ranges or sections are read. Matters most when interleaving reads with other work, or when re-chunking creates overlapping ranges.

## Patterns

- **Read every chunk through to its end.** Early chunks don't predict the middle; extrapolating from them is pattern-matching, not reading.
- **Middles carry load-bearing detail.** A clean frame from start and end is not evidence that the interior is redundant.
- **Heading scans are navigation, not ingestion.** The read comes after.
- **Specifics before synthesis.** Before forming conclusions, name a concrete detail from each section. If you can't, re-read — attention didn't land there.
- **Keep the mechanics internal.** The user wants the result of having read everything, not the play-by-play.

## Examples

**Long log file (8000 lines)**
Survey: `wc -l error.log` → 8000 lines, no obvious section structure.
Plan: 8 chunks of 1000 lines each. Parallel Reads in one tool-use block — parent receives all 8 ranges before reasoning.
Execute: read all 8, synthesize.

**Academic paper (PDF, 40 pages)**
Survey: `pdf_info` → 40 pages; TOC shows 7 sections.
Plan: chunk by section. Serial — Results depend on Methods.
Execute: read each section through, then respond citing section numbers or page ranges for each claim.

**Fixed chunking splits a function (with intervening reasoning)**
Read 0–500 of a 1500-line source file, reason on it, then read 500–1000 a turn later. Last 30 lines of chunk 1 start a function that continues past line 500 — by the time chunk 2 lands, chunk 1 has already collapsed into a summary.
Recover: re-read 470–1000 to capture the function whole. If both chunks are read back-to-back in one tool-use block, no recovery is needed.

**Multi-file code dump (12 files, ~300 lines each)**
Survey: list files, glance at each filename and first 20 lines for role.
Plan: one Read per file (each under the 2000-line one-shot threshold). Parallel — issue all 12 Reads in one tool-use block.
Execute: digest each, synthesize.