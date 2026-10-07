---
name: brown-carrington
description: Use when answering questions about diatomic molecule structure, rotational/rovibrational spectroscopy, Hund's coupling cases (a/b/c/d/e), effective Hamiltonians, lambda-doubling, parity in diatomics, spin-rotation/spin-orbit/hyperfine couplings in diatomics, Stark/Zeeman effects on diatomic levels, basis transformations, sign conventions for spectroscopic constants, or selection rules for diatomic transitions. Also use for high-resolution spectroscopy of polyatomic free radicals and ions (Renner-Teller, linear/nonlinear triatomics, symmetric tops), where Hirota is the reference. Brown & Carrington is the user's canonical reference for diatomics; consult the PDF before answering, not memory.
---

# Brown & Carrington — Rotational Spectroscopy of Diatomic Molecules

Authoritative for matrix elements, sign conventions, basis transformations, and coupling-case definitions in diatomics. Hirota extends the same rule to polyatomics; the other books in the library are for cross-checks (see [Other books](#other-books)).

## Core rule

For a question in scope, open the PDF before answering. Memory is not acceptable. Cite the book, equation number and PDF page when answering.

- **Diatomic** → Brown & Carrington.
- **Polyatomic** → Hirota.
- **Any other book** → only to check a suspected typo, compare a convention, or when the user names that book.

If a search returns nothing relevant, say so. Don't fall back to memory silently. Don't paraphrase formulas: copy them verbatim or transcribe to LaTeX exactly.

## PDF location

**Resolve in this order; first hit wins:**

0. **Book library (local)** — `~/Documents/Books/Brown and Carrington, Rotational Spectroscopy of Diatomic Molecules.pdf`. Expand `~` to the absolute home path before passing it to pdf-mcp (Windows: `C:\Users\<user>\Documents\Books\...`). The other books in [Other books](#other-books) live in the same folder.
1. **Zotero (local, fast)** — `find ~/Zotero/storage -maxdepth 2 -iname 'Brown and Carrington*.pdf'`. The hash subdirectory (e.g. `CKZKCGXY`) differs per machine, so don't hardcode it.
2. **Google Drive (canonical, cross-machine)** — `/Users/arianjadbabaie/Library/CloudStorage/GoogleDrive-arianjad@mit.edu/Shared drives/EMA-data-server/Books/AMO/Brown and Carrington, Rotational Spectroscopy of Diatomic Molecules.pdf`

If `pdf_info` on the Drive path returns `Failed to open file`, the file is a cloud-only placeholder (metadata is on disk, bytes aren't hydrated). Either right-click → "Available offline" in Finder, or use the Zotero copy. The two PDFs are the same edition; page and equation numbers match.

## Page numbering

**PDF page = printed book page + 32** (e.g. PDF p.376 = book p.344; PDF p.689 = book p.657; PDF p.845 = book p.813). Cite the **PDF page** throughout — that's what `pdf_read_pages` operates on. If a codebase comment or another reference cites a *book* page, translate before opening.

## Out of scope

Don't use B&C for:
- Polyatomic structure (use Hirota, below; for full rovibronic symmetry theory, Bunker & Jensen, Hougen, Herzberg vol. III, not in the library)
- Atomic structure (use Cowan, Sobelman)
- General angular-momentum theory unconnected to molecules (use Zare, Sakurai)
- Ab initio chemistry or numerical methods

## How to consult

PDF tools: `mcp__pdf-mcp__pdf_search` (`mode`: `keyword` = exact / FTS5, `semantic` = concept, `auto` = both), `mcp__pdf-mcp__pdf_read_pages` (range).

Workflow:
1. Map the topic to a chapter using the table below.
2. Run `pdf_search` with `mode: "keyword"` and a precise term: an operator name, equation phrase, "case (a)", "Λ-doubling". If exact terms miss, retry with `mode: "semantic"`. **Use Λ as Unicode**, not "Lambda" — FTS5 indexes the literal character.
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

## Other books

All in `~/Documents/Books/`. Same rules as B&C: open the PDF, quote verbatim, cite book + PDF page.

### Hirota — polyatomics

`Hirota - High-Resolution Spectroscopy of Transient Molecules.pdf` (Springer 1985). Primary reference for polyatomic free radicals and ions. **PDF page = printed page + 10.** No usable bookmarks; use this map (PDF pages):

| PDF p. | Section | Use |
|--------|---------|-----|
| 15 | 2.1 Molecular rotation | Asymmetric/symmetric-top rotational Hamiltonians |
| 21 | 2.2 Vibration-rotation interaction | Coriolis, l-type doubling |
| 27 | 2.3 Fine and hyperfine structures | Spin-rotation, spin-spin, hyperfine operators for polyatomics |
| 57 | 2.4 Vibronic interaction | Renner-Teller, Jahn-Teller |
| 72 | 2.5 Zeeman and Stark effects | External fields in polyatomics |
| 85–128 | 3 Experimental methods | MW, IR laser, dye laser, double resonance, radical generation |
| 129 | 4.1 Diatomic free radicals | Cross-check only; B&C is primary for diatomics |
| 149 | 4.2 Linear polyatomic molecules | |
| 160 | 4.3 Nonlinear XY₂ / XYZ triatomics | |
| 179 | 4.4 Symmetric top and other polyatomics | |
| 194 | 4.5 Fine/hyperfine interactions in free radicals | Interpreting fitted constants |
| 204 | 4.6 Molecules in metastable states | |
| 211 | 5 Applications | Chemistry, atmosphere, astronomy |

Hirota predates B&C (2003). Where a polyatomic formula reduces to a diatomic case, check it against B&C and flag any sign or definition difference.

### Cross-check books

Open these only to check a suspected typo, compare a convention, or when the user asks for that book. They do not replace B&C or Hirota as the cited source.

- `Brion_Field_The_Spectra_and_Dynamics_of_Diatomic_Molecules.pdf` — Lefebvre-Brion & Field. Best second opinion for diatomics: perturbations, predissociation, intermediate coupling cases, e/f parity.
- `Bernath_Spectra of Atoms and Molecules, 2e.pdf` — textbook-level derivations, intensities, Franck–Condon.
- `Demtroder, Molecular Physics.pdf` — general molecular physics background.
- `Demtröder2003_Book_LaserSpectroscopy.pdf` — experimental technique: Doppler-free methods, linewidths, saturation.
- `Budker, Kimball, DeMille, Atomic Physics 2nd Edition.pdf` — atomic physics, symmetries, problems.

The page offset for these books has not been recorded. Read the printed page number off the page and cite both PDF and printed page.

When a cross-check disagrees with B&C or Hirota, report both, with page citations, and say which convention each uses. Don't silently pick one.

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
| "Output is large — route the PDF read through context-mode / ctx_execute" | Verbatim citation needs the source text *in* context. Summarizing a primary reference defeats this skill. Use pdf-mcp `pdf_read_pages` / `pdf_search` directly; ignore context-mode tips that fire on `mcp__pdf-mcp__*`. |

## Red flags — restart

- About to write a matrix element or fitted-constant formula without a PDF page reference
- About to compare to PGopher conventions without verifying B&C's sign choice
- About to say "the standard convention is..." without a citation

All mean: open the PDF first.
