---
name: read-it-fully
description: Use when the user explicitly asks Claude to read something fully, carefully, completely, in depth, or to not skim — on files, papers, transcripts, threads, multi-file code dumps, or pasted text. Plans a structured walk through the whole input, verifies that specifics from every section can be cited back, and hands the user a response drawn from the substance rather than the frame. Wait for the user's explicit ask before triggering; input size alone is not a trigger.
---

# Read It Fully

Goal: when the user asks you to read something completely, ingest every part before responding. Skimming long input (sampling the start and end, pattern-matching to a familiar shape, glancing at headings) gives shallow answers and misses load-bearing detail in the middle.

This skill operationalizes the rule already in the user's global instructions:
> When I share a file, link, paper, or thread: read it fully before responding. No skimming, no pattern-matching to a pre-chosen frame, no compressing-by-skipping.

The failure mode is attention, not mechanics. Even when the bytes sit in context (pasted text, fully-loaded files), autoregressive generation biases the response toward salient anchors (start, headings, end) and away from the middle. Force intermediate generation steps that re-anchor attention across the input.

## When to use

Trigger on explicit asks:
- "read it fully", "read all of it", "read in depth", "read carefully", "read completely"
- "go through everything", "don't skim"
- Close variants

Wait for the user's explicit ask before triggering. If they want full reading, they'll say so. The skill biases toward under-triggering; over-triggering on every file drop would thrash.

## The core loop

### 1. Survey first
Know the shape before reading. Tools vary by source; the discipline holds.
- Files: `wc -l <path>` + `head -50 <path>` for size and shape
- PDFs: `pdf_info` for page count, `pdf_get_toc` for structure. If the TOC is empty, probe with `pdf_search` on likely section keywords ("method", "result", "discussion"); fall back to fixed-page chunks if nothing surfaces.
- URLs: fetch via `ctx_fetch_and_index` or `defuddle`, then survey
- Pasted text already in context: scan for structure (headings, speaker turns, section breaks)

### 2. One-shot if it fits
The Read tool defaults to ~2000 lines per call. If the input fits in one Read with reasonable line lengths, read it once. Chunking costs extra tool calls and risks boundary splits; it buys nothing when one Read suffices.

The skill still fires for sub-threshold inputs. "Read fully" is about discipline (walk every section, cite specifics, cover the whole thing); it applies to a one-Read ingestion as much as a chunked one.

### 3. Decide by context budget
If reading the whole input would dominate the remaining context window, surface the tradeoff and let the user pick:

- **Full ingest.** Chunked parent reading; default when the input is a manageable fraction of remaining context.
- **Subagent digest.** Dispatch agents that read the raw content and return summaries. Named honestly as delegation, not personal reading.
- **Two-pass.** Low-resolution sweep (headings + first/last lines per section), then deep-read only sections relevant to the user's question. User opt-in.
- **Narrow scope.** Ask the user which parts matter most.

### 4. Plan the chunks: prefer semantic over fixed
When the input overflows one Read and fits the budget, look for natural boundaries before defaulting to fixed sizes.
- Markdown / papers: section headings
- Code: function or class boundaries; file boundaries in a multi-file dump
- Transcripts: speaker turns, timestamps, topic shifts
- PDFs: chapters or sections from the TOC

If you surveyed boundaries, split on them. Arbitrary midpoints after finding real boundaries waste the survey. Fall back to fixed chunks only when the survey finds nothing usable.

Fixed-chunk defaults:
- Sparse code or logs: 500–1000 lines per chunk
- Dense academic prose, math, legal text: 200–400 lines
- Tables / structured data: chunk by row groups
- PDFs: by section if available, else 5–10 pages

### 5. Read each chunk to completion
Use `Read` with explicit `offset` and `limit`, or the medium-appropriate equivalent (`pdf_read_pages`, etc.). Read each chunk through to its end.

PDFs: use `pdf_read_pages`, not `Read`. `Read` on a `.pdf` extracts text but silently truncates after the first few calls (observed cutting off at p. 19 of a 27-page document on 2026-04-27). The result looks substantive but misses later sections (supplemental material, late references, final equations). `pdf_read_pages` with explicit page ranges covers any page range you specify.

For pasted text already in context, walk each section in your reasoning. Name one specific detail from each section before forming conclusions. Re-read until each section yields a detail.

### 6. Verify before responding
Before answering, point to specific content from each section: a line range, a heading, a page, a quote. This is the attention gate. Only details that surface in intermediate generation steps reach the final response.

Two moves for the response:
- Cite locations when making claims: "section 4 says X", "line 220 shows Y", "page 7 discusses Z". Gives the user spot-check material and matches the standing rule that reports are leads, not ground truth.
- For multi-chunk reads, add a brief coverage note at the end (which sections or ranges you covered). Keep it terse. Makes coverage auditable while keeping the response lean.

### 7. Recover split concepts (only when chunks are reasoned over independently)
Fixed boundaries sometimes land mid-function, mid-paragraph, mid-table, mid-argument. That matters when chunks are read in separate reasoning contexts (different turns or different subagents), where chunk N has collapsed to a summary by the time chunk N+1 lands.

Back-to-back Reads in a single tool-use block let both responses land in context before reasoning. Skip recovery there.

When it matters:
- Shift the window: re-read with offset moved by half a chunk.
- Merge: read the two chunks as one larger chunk when the split spans most of both.

Pick whichever costs less. Re-chunking is internal.

### 8. Serial vs parallel: by dependency, not speed
- Parallel Reads in one tool-use block: fine, parent sees all bytes. Use when chunks are independent (multi-file code dumps, logs).
- Serial: when later chunks need earlier context (tutorials, narrative arguments, sequential reasoning).
- Subagent fanout: a user-menu choice from step 3, named as delegation. Not a default.

When in doubt, serial is safer; parallel is faster.

### 9. Track coverage
For long multi-chunk reads, note which ranges or sections you read. Matters most when interleaving reads with other work, or when re-chunking creates overlapping ranges.

## Patterns

- **Read every chunk through to its end.** The middle requires its own reading. Extrapolating from early chunks is pattern-matching, not reading.
- **Middles carry load-bearing detail.** A clean frame from start and end tells you nothing about the interior.
- **Heading scans are navigation, not ingestion.** The read comes after.
- **Specifics before synthesis.** Before forming conclusions, name a concrete detail from each section. Re-read any section that yields no detail; attention will land on the second pass.
- **Keep the mechanics internal.** The user wants the result of having read everything, not the play-by-play.

## Examples

**Long log file (8000 lines)**
Survey: `wc -l error.log` → 8000 lines, uniform line format.
Plan: 8 chunks of 1000 lines each. Parallel Reads in one tool-use block: parent receives all 8 ranges before reasoning.
Execute: read all 8, synthesize.

**Academic paper (PDF, 40 pages)**
Survey: `pdf_info` → 40 pages; TOC shows 7 sections.
Plan: chunk by section. Serial: Results depend on Methods.
Execute: read each section through, then respond citing section numbers or page ranges for each claim.

**Fixed chunking splits a function (with intervening reasoning)**
Read 0–500 of a 1500-line source file, reason on it, then read 500–1000 a turn later. The last 30 lines of chunk 1 start a function that continues past line 500; by the time chunk 2 lands, chunk 1 has collapsed into a summary.
Recover: re-read 470–1000 to capture the function whole. Reading both chunks back-to-back in one tool-use block keeps them both in context and skips recovery.

**Multi-file code dump (12 files, ~300 lines each)**
Survey: list files, glance at each filename and first 20 lines for role.
Plan: one Read per file (each under the 2000-line one-shot threshold). Parallel: issue all 12 Reads in one tool-use block.
Execute: digest each, synthesize.
