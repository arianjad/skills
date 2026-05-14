---
name: brown-carrington
description: Use when answering questions about diatomic molecule structure, rotational/rovibrational spectroscopy, Hund's coupling cases (a/b/c/d/e), effective Hamiltonians, lambda-doubling, parity in diatomics, spin-rotation/spin-orbit/hyperfine couplings in diatomics, Stark/Zeeman effects on diatomic levels, basis transformations, sign conventions for spectroscopic constants, or selection rules for diatomic transitions. Brown & Carrington is the user's canonical reference; consult the PDF before answering, not memory.
---

# Brown & Carrington — Rotational Spectroscopy of Diatomic Molecules

Authoritative for matrix elements, sign conventions, basis transformations, and coupling-case definitions in diatomics.

## Core rule

For a question in scope, open the PDF before answering. Memory is not acceptable. Cite the equation number and PDF page when answering.

If a search returns nothing relevant, say so. Don't fall back to memory silently. Don't paraphrase formulas: copy them verbatim or transcribe to LaTeX exactly.

## PDF location

**Resolve in this order; first hit wins:**

1. **Zotero (local, fast)** — `find ~/Zotero/storage -maxdepth 2 -iname 'Brown and Carrington*.pdf'`. The hash subdirectory (e.g. `CKZKCGXY`) differs per machine, so don't hardcode it.
2. **Google Drive (canonical, cross-machine)** — `/Users/arianjadbabaie/Library/CloudStorage/GoogleDrive-arianjad@mit.edu/Shared drives/EMA-data-server/Books/AMO/Brown and Carrington, Rotational Spectroscopy of Diatomic Molecules.pdf`

If `pdf_info` on the Drive path returns `Failed to open file`, the file is a cloud-only placeholder (metadata is on disk, bytes aren't hydrated). Either right-click → "Available offline" in Finder, or use the Zotero copy. The two PDFs are the same edition; page and equation numbers match.

## Out of scope

Don't use B&C for:
- Polyatomic structure (use Bunker & Jensen, Hougen, Herzberg vol. III)
- Atomic structure (use Cowan, Sobelman)
- General angular-momentum theory unconnected to molecules (use Zare, Sakurai)
- Ab initio chemistry or numerical methods

## How to consult

PDF tools: `mcp__pdf-mcp__pdf_search` (exact / FTS5), `mcp__pdf-mcp__pdf_semantic_search` (concept), `mcp__pdf-mcp__pdf_read_pages` (range).

Workflow:
1. Map the topic to a chapter using the table below.
2. Run `pdf_search` with a precise term: an operator name, equation phrase, "case (a)", "Λ-doubling". If exact terms miss, fall back to `pdf_semantic_search`. **Use Λ as Unicode**, not "Lambda" — FTS5 indexes the literal character.
3. **Read the top ~5 hits**, not just the first. The first hit is often a passing reference; the authoritative derivation usually sits in a different chapter. Scan the `excerpt` field of each match to identify which is the operator definition, which is the case-reduction, and which is a worked example.
4. For each strong hit, read **2–4 pages on either side** with `pdf_read_pages` (e.g. `689-693`, not just `691`). Equations reference earlier definitions; sign conventions are stated paragraphs before the equation; assumptions about Λ, Σ, Ω being signed quantities live in surrounding text.
5. **Triangulate across chapters** when relevant: operator form (Ch 4 / Ch 7) ↔ case-(a) matrix elements (Ch 5) ↔ molecule-specific worked example (Ch 9–11). If two hits give superficially different forms, find the transformation that connects them rather than picking one.
6. Quote equation number and PDF page in the answer. If you read several pages, cite all of them.

The PDF's bookmark TOC is useless: just `Page_001` … `Page_1013`. Use the chapter map below.

### Why multiple hits and surrounding context

A single hit gives a formula. The surrounding text gives:
- Sign conventions ("Λ, Σ, Ω are signed quantities")
- Basis restrictions ("with the assumption that this operator connects states with Λ = +1 and −1 only")
- Centrifugal distortion or higher-order corrections deferred to a later equation
- Whether "A" means the effective-Hamiltonian constant or the microscopic single-electron parameter

Skipping the context is how sign errors and basis-mismatch errors creep in.

## Chapter map

| Ch | Topic | Primary use |
|----|-------|-------------|
| 1  | Historical introduction | Rarely cited |
| 2  | Foundations of QM and angular momentum | Spherical tensors, 3j/6j/9j, Wigner-Eckart, time reversal |
| 3  | Electronic states of diatomics | Born-Oppenheimer, term symbols, parity, e/f labels |
| 4  | Interactions within molecules | Spin-orbit, spin-rotation, spin-spin, hyperfine: operator forms |
| 5  | Angular momentum coupling and basis sets | Hund's cases (a)–(e); matrix elements per case; case-to-case transformations |
| 6  | External fields | Stark, Zeeman, anomalous Zeeman, magnetic moments per case |
| 7  | Effective Hamiltonian | Van Vleck / contact transformation; derivation of fitted constants |
| 8  | Molecular beam magnetic / electric resonance | Method; transition strengths |
| 9  | Microwave / FIR magnetic resonance | LMR, EPR, lambda-doubling spectroscopy |
| 10 | Pure rotational spectroscopy | Pure rotation, centrifugal distortion |
| 11 | Double resonance, electronic spectroscopy | Multi-laser methods, electronic transitions |

By question type:
- "Matrix element of operator O in case X" → Ch 4 for the operator, Ch 5 for the case reduction
- "Case (a) ↔ case (b) transformation" → Ch 5
- "What does fitted constant K represent?" → Ch 7
- "Stark or Zeeman shift for state |X⟩?" → Ch 6
- "Selection rule for transition X?" → Ch 6 or Ch 11

## Sign conventions

B&C uses Condon-Shortley phases with Brown's body-fixed sign choices. PGopher flips some signs. The Molecule-Structure codebase mostly follows B&C; flag any discrepancy rather than reconciling silently. Spectroscopic constants in B&C are MHz throughout, matching the codebase.

## Common rationalizations — STOP

| Excuse | Reality |
|--------|---------|
| "I know this, case (a) is standard" | Memory has a non-zero error rate on signs and phases. The user asks B&C-grade questions for that reason. Open the PDF. |
| "Search returned nothing" | Try semantic search; try synonyms (Λ-doubling vs lambda-doubling). Then say "not found": don't substitute memory. |
| "Just paraphrasing, not quoting" | Paraphrasing equations is how sign errors propagate. Copy verbatim. |
| "User asked for intuition, not a citation" | Cite the page even when explaining. |
| "PDF tool failed once" | Retry once with a different query. If it still fails, surface the failure. |

## Red flags — restart

- About to write a matrix element or fitted-constant formula without a PDF page reference
- About to compare to PGopher conventions without verifying B&C's sign choice
- About to say "the standard convention is..." without a citation

All mean: open the PDF first.
