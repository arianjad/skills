# Attribution and adaptation

This standalone skill is adapted from [obra/superpowers](https://github.com/obra/superpowers), specifically `skills/systematic-debugging/`, at commit [`8ca22dba9a94f28898bbce59f2537ff4d87c747d`](https://github.com/obra/superpowers/tree/8ca22dba9a94f28898bbce59f2537ff4d87c747d/skills/systematic-debugging). The public `main` revision was resolved on 2026-10-07. This is a pinned extraction, not a claim to track future releases or an official Superpowers distribution.

Copyright (c) 2025 Jesse Vincent. The exact upstream MIT license and notice are included in [LICENSE](LICENSE); retain them when copying or distributing this adaptation. New adaptation text is also provided under that MIT license.

Retained: `SKILL.md` and the three supporting Markdown techniques: root-cause tracing, defense in depth, and condition-based waiting. The four phases, root-cause investigation first, single hypotheses, minimal isolated experiments, boundary instrumentation, and architectural reassessment after three failed fixes remain central.

Changes from the pinned source:

- Replace calls to Superpowers test-driven-development and verification-before-completion with explicit failing reproduction, focused regression test, fresh-output verification, and evidence reporting.
- Replace the credential-printing shell example with safe boundary diagnostics; add scope, authorization, and redaction guidance.
- Replace the polluter script dependency with isolated test-subset/order investigation, including clean baselines.
- Replace the domain-specific TypeScript helper reference with self-contained waiting guidance. Clarify that the illustrative polling interval depends on the system.
- Make defense checks proportional to diagnosed boundaries and improve the path-containment example to reject sibling-prefix paths; note symlink considerations.
- Clarify that repeated failures prompt architecture reassessment rather than prove a wrong architecture. Remove an unsupported statistical claim about incomplete investigations and historical numerical success anecdotes.
- Add Codex UI metadata, provenance, and optional local-use instructions. No executable files, plugin configuration, hooks, tool dependencies, global settings, or other Superpowers skills are included.

Omitted from the portable package (inspected and retained only in the extraction evidence): `CREATION-LOG.md` is authoring history; `test-academic.md` and `test-pressure-1.md` through `test-pressure-3.md` are skill evaluation fixtures; `find-polluter.sh` is a shell/npm-specific test runner; `condition-based-waiting-example.ts` depends on a particular application's ThreadManager types. Their useful operational guidance is covered in the retained references without requiring execution or application dependencies.

At extraction time, this package had not been installed, published, or submitted to any registry. The retained examples are illustrative upstream material, not independent validation results for this adaptation.

