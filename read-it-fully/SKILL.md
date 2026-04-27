---
name: read-it-fully
description: Use when the user explicitly asks Claude to read something fully, carefully, completely, in depth, or to not skim — on files, papers, transcripts, threads, multi-file code dumps, or pasted text. Plans a structured walk through the whole input, verifies that specifics from every section can be cited back, and hands the user a response drawn from the substance rather than the frame. Wait for the user's explicit ask before triggering; input size alone is not a trigger.
---

# Read It Fully

Goal: when the user asks you to read something completely, ingest every part before responding. Skimming long input — sampling the start and end, pattern-matching to a familiar shape, glancing at headings — gives shallow answers and misses load-bearing detail in the middle.

The failure mode is attention, not mechanics. Even when the bytes sit in context (pasted text, fully-loaded files), autoregressive generation biases the response toward salient anchors (start, headings, end) and away from the middle. Force intermediate generation steps that re-anchor attention across the input.

## When to use

Trigger on explicit asks:
- "read it fully", "read all of it", "read in depth", "read carefully", "read completely"
- "go through everything", "don't skim"
- Close variants

Wait for the user's explicit ask. The skill biases toward under-triggering; over-firing on every file drop would thrash.

## The core loop

### 1. Survey first

Know the shape before reading. Use whatever your environment provides:
- File length and head
- Document structure or table of contents (for PDFs, books, structured docs)
- URL content extraction
- Pasted text already in context: scan inline for headings, speaker turns, section breaks

For PDFs without a usable TOC, probe with keyword search on likely section names ("method", "result", "discussion") before falling back to fixed-page chunks.

### 2. One-shot if it fits

If the input fits in a single read with reasonable scope, read it once. Chunking costs extra tool calls and risks boundary splits; it buys nothing when one read suffices.

Even short inputs benefit from this discipline when the user explicitly asks for a full read. The skill is about walking every section, citing specifics, and covering the whole — applies regardless of size.

### 3. Decide by context budget

If reading the whole input would dominate remaining context, surface the tradeoff and let the user pick:

- **Full ingest.** Chunked parent reading; default when the input is a manageable fraction of remaining context.
- **Delegated full-read digest.** Dispatch agents that read the raw content and return summaries. Named honestly as delegation — see Honesty rules.
- **Two-pass.** Low-resolution sweep first (headings, first/last lines per section), then deep-read sections relevant to the user's question. User opt-in.
- **Narrow scope.** Ask which parts matter most.

### 4. Plan the chunks: prefer semantic over fixed

When the input overflows one read and fits the budget, look for natural boundaries before defaulting to fixed sizes.
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

Read each chunk through to its end. For pasted text already in context, walk each section in your reasoning — name a specific detail from each before forming conclusions.

### 6. Evidence gate before responding

Before answering, surface specific content from each section: a quoted line, a parameter, a result, a heading-anchored claim. This is the attention gate — only details that surface in intermediate generation steps reach the final response.

For each section, the surfaced detail must be **non-heading, content-bearing**: a result, caveat, parameter, definition, example, exception, or concrete claim. Section titles alone do not count. Re-read any section whose only surfaced detail is its title or general topic; attention will land on the second pass.

When making claims, cite locations: "section 4 says X", "line 220 shows Y", "page 7 discusses Z". Gives the user spot-check material.

**Optional coverage ledger.** For multi-chunk consequential reads (long papers, large code dumps, dense legal text), include a compact ledger:

| Section / range | Status | One content-bearing detail | Used in answer? |
|---|---|---|---|
| §3 Methods | read | fits 3-parameter model after binning cuts that drop 40% of points | yes |
| §5 Discussion | delegated | author concedes systematic at 5% level | no |
| §A.2 Appendix | surveyed | (none surfaced) | no |

Skip the ledger for short reads; bureaucracy on a 30-line file is worse than no ledger at all.

### 7. Visual content

For PDFs, papers, scans, or reports, extracted text is not enough when figures, equations, tables, or diagrams carry the argument. Inspect rendered pages or the relevant figure/table regions before relying on them. If your environment lacks a rendering pathway, say so — do not infer figure content from caption text alone.

### 8. Recover split concepts (only when chunks are reasoned over independently)

Fixed boundaries sometimes land mid-function, mid-paragraph, mid-table, mid-argument. That matters when chunks are read in separate reasoning contexts (different turns or different subagents), where chunk N has collapsed to a summary by the time chunk N+1 lands.

Back-to-back reads in a single tool-use block let both responses land in context before reasoning. Skip recovery there.

When it matters:
- Shift the window: re-read with offset moved by half a chunk.
- Merge: read the two chunks as one larger chunk when the split spans most of both.

Pick whichever costs less. Re-chunking is internal.

### 9. Serial vs parallel: by dependency, not speed

- **Parallel** ingestion in one tool-use block is acceptable for independent chunks (multi-file code dumps, logs). After parallel ingestion, still run the evidence gate per chunk before synthesis — bytes in context is not the same as attended to.
- **Serial:** when later chunks need earlier context (tutorials, narrative arguments, sequential reasoning).
- **Delegated fanout:** a user-menu choice from step 3, named as delegation, not a default.

When in doubt, serial is safer; parallel is faster.

### 10. Track coverage

For long multi-chunk reads, note which ranges or sections you read. Matters most when interleaving reads with other work, or when re-chunking creates overlapping ranges. The optional ledger in §6 covers this when needed.

## Honesty rules

- Do not say "I read it fully" if the parent process only read summaries.
- Name delegated reading as delegation.
- In two-pass mode, name what was surveyed and what was deeply read.
- If anything could not be read, say so before answering.

## Patterns

- **Read every chunk through to its end.** The middle requires its own reading. Extrapolating from early chunks is pattern-matching, not reading.
- **Middles carry load-bearing detail.** A clean frame from start and end tells you nothing about the interior.
- **Heading scans are navigation, not ingestion.** The read comes after.
- **Specifics before synthesis.** Before forming conclusions, surface a non-heading, content-bearing detail from each section. Re-read any section that yields no detail.
- **Don't let the frame decide the answer.** Abstracts, intros, conclusions, READMEs, and issue titles advertise what the document wants to be; the middle shows what it actually does. Read the middle before letting the frame anchor the response.
- **For multi-file code dumps:** read every file through; map call flow before judging architecture; note tests or their absence.
- **Keep mechanics internal.** The user wants the result of having read everything, not the play-by-play.

## Examples

**Long log file (8000 lines).** Survey shows 8000 lines, uniform format. Plan: 8 chunks of 1000 lines, parallel reads in one tool-use block (parent receives all 8 ranges before reasoning). Execute, run the evidence gate per chunk, synthesize.

**Academic paper (PDF, 40 pages).** Survey shows 40 pages and 7 sections from the TOC. Plan: chunk by section, serial — Results depends on Methods. Execute each section through; surface a content-bearing detail per section before responding; cite section numbers or page ranges in claims. For figures that carry the argument, render and inspect them, not just the caption text.

**Fixed chunking splits a function (with intervening reasoning).** Read 0–500 of a 1500-line file, reason on it, then plan to read 500–1000 a turn later. The last 30 lines of chunk 1 start a function that continues past line 500. By the time chunk 2 lands, chunk 1 has collapsed to a summary. Recover: re-read 470–1000 to capture the function whole. Reading both chunks back-to-back in one tool-use block keeps them both in context and skips recovery.

**Multi-file code dump (12 files, ~300 lines each).** Survey: list files, glance at filename and first 20 lines of each for role. Plan: one read per file, parallel in one tool-use block. Map call flow across files before judging architecture; note tests or their absence. Synthesize.

**Bad vs good: paper critique.**

- *Bad:* User asks for critique of a 40-page paper. Assistant reads abstract, intro, conclusion; gives generic feedback ("limited sample size", "future work could extend"). Looks like a review; isn't.
- *Good:* Assistant surveys sections, deep-reads methods/results/discussion, surfaces a content-bearing detail from each (e.g., "they fit a 3-parameter model to data with effectively 4 free DOF after the cuts in §3.2"), then critiques the actual claims, controls, and assumptions. Coverage note names which sections were read deep and which were skimmed.

## Environment-specific notes

For Claude Code-specific tooling — `Read` tool defaults, PDF handling, URL fetching, and observed gotchas — see [`references/claude-code.md`](references/claude-code.md).
