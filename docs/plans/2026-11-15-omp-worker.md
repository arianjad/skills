# OMP thinker-worker execution backend

Goal: invoke an OMP worker from any calling agent or shell, using OMP's configured model by default, with resumable sessions and independent result verification.

Design: user request in chat, 2026-11-15. Add an execution command rather than admitting a particular model or forcing caller identity. Keep the existing OMP installation, profile/model configuration and service. No daemon, RPC layer, new scheduler or provider switch. Explicit optional model/thinking overrides stay per-run; absent values are omitted from OMP argv. Calling-harness activation is irrelevant to this explicit subprocess route; existing native guards remain intact.

Constraints: preserve existing source changes/commits; all commits local; no push. No live service, model-server or production memory changes. Runtime smoke uses isolated configuration/state and a small actual local request. Respect host permissions; inherit OMP approval settings unless explicitly overridden. Meaningful tests and a fresh independent review are required. Source was clean at d00ff22 before this branch.

## File map

- Modify thinker-worker/scripts/tw.py: add `omp` CLI/backend, package the new reference, allow the existing outcome/tally interface to read OMP execution records without changing native harness configuration/guards.
- Create thinker-worker/scripts/test_tw_omp.py: fake executable CLI checks for model/caller independence, resume, result/error/timeout handling and existing outcome integration.
- Create thinker-worker/references/omp.md: one shared backend recipe for all callers.
- Modify thinker-worker/SKILL.md and references/{codex,claude,add-model}.md: discover the OMP backend and distinguish executable selection from fixed-model registration.
- Modify README.md only if its current thinker-worker description becomes inaccurate.
- Operational checkpoint: this chat's work/omp-worker-checkpoint.md. Nemotron owns tw.py/new test; parent owns documentation; reviewer writes isolated findings only.

## Tasks

1. Implement backend and tests. Command: `tw.py omp --role worker|leaf|independent-review|ideation --brief-file PATH --cd DIR`, optional `--model`, `--thinking`, `--resume`, `--timeout`, and `--approval-mode`. Inherit OMP's configured model/profile/effort when omitted; preserve current capabilities. Reuse first_role/header_fields/review_details, run_bounded, receipt/append_receipt and outcome/tally. Persist a fresh execution directory with session/events/final text; return compact JSON including execution/session IDs, resume file, process result, actual provider/model from OMP event metadata, requested versus observed thinking and log paths. Do not use Codex/Claude caller IDs, install a new model registry entry, or require an activation receipt to run. Validate structural inputs before spending inference; review/ideation retain their existing scope/authorization header. Process exit zero without successful final model output is not success. Record partial output without claiming completion. Check: python thinker-worker/scripts/test_tw_omp.py. Commit owned code/test at green milestone.

2. Document and install. Shared reference explains defaults, model overrides, resume, process limits, actual artifact verification and CLI output. Harness docs point to it; source installer packages it through SKILL_FILES. Check: source help plus temporary-home install/upgrade/check tests. Commit docs locally, then use the existing owned upgrade path without changing hook definitions/default models or production services.

3. Validate and review. Run every existing test_tw_*.py once through the repository's standard standalone-script pattern (bounded general compute, no GPU benchmarks). Run a small isolated real OMP start/resume/file-tool smoke using the current local provider, then verify the requested file/result directly. Exercise omission of a model and absent Codex/Claude caller context. A fresh reviewer from another model family examines the fixed change and its controls; author repairs concrete findings. Check installed help/check and source/install agreement. Final local commit caps repairs and checkpoint.

## Delegation brief and stop condition

Nemotron implementation scope: thinker-worker/scripts/tw.py and thinker-worker/scripts/test_tw_omp.py only, including SKILL_FILES's new omp.md entry. Parent writes reference/docs. You are not alone; preserve others' edits and do not commit, push, change services/model configuration, write production memory or dispatch children. Kill only processes you launched. First milestone checkpoint in the chat's work directory; finish with exact diff, command and test result, or leave a precise partial result. Parent retains framing/acceptance; independent reviewer did not author the code. Do not recreate caller-specific guards or fixed-model admissions around OMP.

## Delivered 2026-11-15

Source implementation b6c22cd plus final documentation/context correction. Local implementation attempt stopped after drifting; parent implemented using existing bounded-process/receipt helpers. Installed to existing Codex and Claude package locations with normal upgrade; no hook/default-model/service changes. Both installed copies match source bytes.

All 21 standalone test scripts checked. Nineteen passed initially; the two portability scripts selected WindowsApps bash. Both passed with Git for Windows bash first in PATH. New OMP test reran after adding explicit working-directory context to the prompt. No repeat full suite for that one-line prompt change.

Real isolated configured-local OMP start and same-session continuations ran with no model/thinking override and no Codex/Claude caller IDs. Initial artifact rejected for wrong directory. Repair used exact path but omitted the requested newline; preserve that limitation, not a strict-pass claim. Later continuation wrote the correct remembered marker to the exact file; payload/path checks and deliberately wrong-marker controls passed. Evidence: chat work/omp-real-smoke/verified.json and original separate turn logs.

Independent Opus 5.5/high review of b6c22cd completed from the same resumed review agent after stopping its overlong exploration: no blocking defect. Documented caller-timeout/evidence-loss limitations, trusted launch directory/PATH, and main-assistant-only usage accounting. Restored explicit new-model trigger wording. Raw child exit codes and refusal directories remain ordinary diagnostic details; no new runtime framework or hardening layer was added. Reviewer resume-relocation uncertainty is bounded by the actual same-file/same-session smoke; nested-agent usage/identity is not claimed validated.

Initial delivery was subsequently merged into main and pushed at Arian's request on 2026-11-15. Backend transport completion does not accept a worker's artifact; independent checks remain required. The later prompt-packaging diagnosis and inline-transport correction are recorded in this chat's work/packaging-comparison/RESULT.md and work/omp-inline-fix/verified.json.
