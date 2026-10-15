---
name: anti-bloat-auditor
description: Audit codebases, agentic repos, and scientific simulations for LLM over-engineering, cryptographic ceremony, unnecessary abstractions, and hot-loop performance bottlenecks. Use when asked to audit repo bloat, simplify over-engineered code, generate read-only audit prompts for coding agents, or audit scientific and simulation hot loops for performance costs.
---

# Anti-Bloat Auditor

Find the smallest design that serves the actual callers, data, and scientific contracts. Focus on single-owner, local workflows; establish whether that assumption holds before applying it. Deliver evidence and surgical flattening plans, not a broad rewrite.

## Choose the mode

- **Audit:** Inspect and report without changing the repository or live state.
- **Prompt generation:** Produce the read-only audit prompt below, adapted to the repository and requested coverage.
- **Implementation:** After verifying audit claims, produce a concrete execution prompt or implement a patch only when requested or authorized.

For small or quantized coding models, recommend a lightweight read-only discovery pass with narrow source batches. Never combine audit and refactoring in the same prompt for these models. Generated prompts are task-scoped instructions; they do not override the receiving harness's policies or permissions.

## Audit method

1. Read repository guidance and inspect the stack, entrypoints, data flow, configuration, and literal persisted schemas. Identify scientific contracts, external consumers, and local concurrency. Decide which audit categories can apply here.
2. Trace each candidate through callers, writers, readers, tests, and documented requirements. Search definitions and references, including CLI commands, analysis notebooks, reports, and external interfaces where available.
3. Estimate the runtime and cognitive cost. Mark profiling measurements separately from suspected costs; source inspection alone does not establish a speedup.
4. Identify the top friction and propose the smallest replacement. Prefer existing functions, arrays, flat files, and direct CRUD over new infrastructure.
5. Report search coverage, excluded/generated/vendor paths, queries used for absence claims, inaccessible consumers, and uncertainty. A missing consumer in a partial search is unresolved, not proof of dead code.

During read-only discovery, do not execute project imports, tests, CLI commands, or initialization paths that may create caches, databases, logs, or other files. Read their source instead. Static tools that read files without importing or running project code are allowed: text search (`git grep`, `rg`), git history (`git log`, `git blame`), byte comparison (`cmp`, hashing files to find duplicates), and AST-only parsers such as an unused-import scan with Python's `ast`. Use already available profiles or request a separately authorized run when measurement is needed.

A requirement counts as documented only when it traces to the user (text citing them, a recorded decision or ruling) or to an external contract (a published result, a file format another tool reads). Agent-written rationale without that attribution, such as a docstring explaining why something is kept, is a candidate, not a requirement: when its reasoning looks sound, give it a decision-table row noting that no user decision was found.

## Five audit categories

Use only the categories that can apply. A category that cannot apply here, such as status and polling scans in a repository with no services, gets one line, `N/A: <reason>`, instead of a search.

### 1. Integrity and coordination ceremony

Look for:

- SHA256/Blake2 hash chains, Merkle trees, and repeated file-drift hashing not traceable to a documented requirement.
- Hash comparisons against an expected value, including warn-only comparisons that keep running.
- Hard-coded numbers, tolerances, counts, or prior outputs used as expected values, such as coordinates pinned from an earlier run, fixed row counts, or exact-match tolerances.
- Cache reuse decided by a hash or another proxy for the inputs.
- Single-user SQLite event logs with projectors/replay layers where direct SQLite CRUD, flat records, Parquet, or NumPy arrays would serve the actual operation.
- Custom lockfiles, resource leases, and heartbeat daemons without demonstrated coordination needs.

For each hash-based check, the default is to delete it. When in doubt, remove the check rather than replace it. Replace it only when it guards a nameable defect that has occurred or would plausibly recur. In that case, identify the actual condition the check is meant to establish and check that condition directly, using the relevant parameters, state, schema, content, or invariant, and report the concrete mismatch with expected versus observed values. Neither hash equality nor another proxy such as modification time substitutes for that check: where the condition is byte-for-byte identity, compare the content; where it is restart compatibility, check the relevant state and parameter constraints. For example, a plot-color change should not fail a restart-compatibility check, while a changed required state-array shape should report the actual shape mismatch. Do not invent which scientific changes are compatible; put an unresolved requirement in the decision table. Preserve the underlying records needed to perform and explain the check.

Hashes used only as identifiers (commit SHAs, cache file names, names in a run manifest) are fine and not a finding. Any comparison of a hash against an expected value is validation, whatever it is called: a provenance, recovery, or integrity label does not exempt it.

Treat a pinned value or tolerance the same way. State the condition the check is actually trying to establish, check that condition directly, and flag every tolerance without a stated derivation. A gate that fails when an upstream calculation legitimately re-optimizes is checking chronology, not correctness. A value from an external contract, such as a published table or a measured reference, is a legitimate expected value.

A cache reuse decision is a check whose essence is "same inputs". List every input that changes the cached result, store those inputs with the cache, and decide reuse by comparing them directly, reporting which input differs. A hash may name the cache file but never decides reuse. Where the inputs are too large to store, put the cache in the decision table.

For event logs, locks, leases, and heartbeats, check who relies on replay, audit history, or coordination before proposing removal. Recovery contracts with a real consumer and locks preventing real local races can be legitimate; compare their cost against the requirement, not against a blanket ban.

### 2. Scientific and simulation hot loops

Look for:

- Python element or timestep loops potentially expressible in NumPy, PyTorch, JAX, or Numba already present in the stack.
- Pydantic/model_validate, deepcopy, JSON serialization, file I/O, logging, or SQLite calls inside integration steps, particle loops, or Monte Carlo iterations.
- Repeated np.append, np.concatenate, or torch.cat that reallocates growing arrays; consider preallocation or bounded collection followed by one assembly.
- Repeated np.asarray, tolist, cpu calls, and host/device transfers; inspect dtype, copy behavior, synchronization, and where data must cross boundaries.

Locate the loop on the real execution path. Distinguish algorithmic complexity, allocations, transfers, and validation overhead. Report suspected bottlenecks as hypotheses until a relevant profile or benchmark supports them.

Preserve sequential dependence, random-number generation and ordering requirements, precision, physical model, units, and memory limits. A timestep recurrence cannot be vectorized as independent steps. Batching can change RNG streams, reductions, numerical stability, and peak memory. State whether equivalence requires exact trajectories, distributional agreement, or another scientific criterion; use justified tolerances and preserve required reproducibility.

### 3. Abstractions and configuration churn

Look for:

- ABC, Protocol, Factory, Registry, Provider, Manager, or Base classes, or strategies selected by string, dict, or enum dispatch, with fewer than three concrete implementations used on real code paths. Test fakes, mocks, and stubs do not count; strategies reached only from benchmarks go in the decision table.
- Thin wrappers containing only initialization and one forwarding method.
- YAML -> Pydantic -> dataclass -> dict conversion chains and unused configuration knobs.

Count real implementations and inspect contracts, plugin boundaries, dependency injection, and callers. Below the threshold, flattening is the default; a flat function or one boundary configuration structure is often sufficient. When such an abstraction has a demonstrated benefit or protects an existing requirement, neither keep it silently as an exception nor delete it automatically: put it in the decision table with its source location, actual callers, purpose, concrete benefit, simpler alternative, what retaining or replacing it would change, and a recommendation. Honor an explicit user decision or documented requirement already given, and state its cost. Abstractions with no demonstrated benefit are ordinary flattening candidates, not questions.

### 4. Linear scans in status and startup paths

Look for O(N) scans or globs in health checks, status commands, CLI startup, and polling; whole JSONL reads; repeated directory traversal; and rehashing unchanged files.

Determine N, invocation frequency, and whether completeness is required. Consider a targeted lookup, bounded tail, or modification-time check when it preserves the contract. Tail readers must handle incomplete records and rotation where applicable. Avoid building a new index or daemon unless its demonstrated benefit outweighs its maintenance cost.

### 5. Write-only telemetry

Trace telemetry writers to active UI, analysis, reports, alerts, tests, or operational consumers. Flag counters, event streams, and logs with no demonstrated reader or decision they support.

Verify consumer-search coverage before calling telemetry unused. Required scientific records and historical readable logs are not disposable merely because no live UI reads them. Propose removing or reducing future writes while preserving evidence and required diagnostics.

## Side bugs noticed while tracing

Do not search for bugs; the audit is about bloat. When tracing a candidate surfaces a correctness defect (a producer/consumer contract mismatch, a check whose failure branch cannot fire, a reference that is not independent of the code it checks, a drifted constant), list it in one line with its source anchor and whether it was verified, just before the decision table. Investigate no further than the tracing already went.

## Decision table

Never ask decision questions inline. Collect them into one decision table at the end of the report. Group findings that share a pattern and a recommendation into one row per class, for example "12 receipt-hash gates in producers, no nameable defect: delete all?". Split a class only where instances differ in what keeping them buys. Columns:

Pattern Class | Instances (count + source anchors) | What Keeping It Buys | Recommendation | Effect If Unanswered (left unchanged)

In an implementation, finish all unaffected authorized work first, then present the table once.

## Read-only audit prompt

Adapt the placeholders and source scope before handing this to a coding agent:

```text
SYSTEM INSTRUCTION: READ-ONLY OVER-ENGINEERING & PERFORMANCE AUDIT

Audit [repository/path] for a [single-owner/local/scientific or stated deployment] workflow. Read applicable repository guidance. This prompt is task-scoped and does not override harness policies or permissions.

Inspect source without writes, migrations, refactoring, or iterative coding loops. Do not execute project imports, tests, initialization, or commands that may write caches, logs, databases, or other state. Static tools that read files without importing or running project code are allowed: git grep/rg, git log/blame, cmp or file hashing to find duplicates, and AST-only parsers. Use source inspection and existing measurement artifacts.

A requirement counts as documented only when it traces to the user (text citing them, a recorded decision) or to an external contract (a published result, a file format another tool reads). Agent-written rationale without that attribution is a candidate; when its reasoning looks sound, give it a decision-table row noting that no user decision was found.

Investigate the five categories. A category that cannot apply here (for example, polling scans in a repository with no services) gets one line, "N/A: <reason>", instead of a search.
- Integrity ceremony: hash chains, hash comparisons against expected values (including warn-only), pinned values and tolerances used as expected values, cache reuse decided by a hash, event sourcing, custom locks/leases/heartbeats.
- Scientific hot-loop validation, serialization, I/O, allocation, and host/device costs where applicable.
- Single-implementation abstractions and configuration conversion churn.
- O(N) health/status/startup/polling scans, whole-log reads, and rehashing.
- Write-only telemetry with no demonstrated active consumer.

Treat patterns as candidates. Trace callers, writers, readers, concurrency, and contracts. Do not infer a measured bottleneck from syntax alone. Do not propose scientific vectorization that changes sequential dependence, RNG/order requirements, precision, physical model, units, or memory limits.

Hash checks: the default is to delete them; when in doubt, recommend removal rather than replacement. Recommend replacement only for a check that guards a nameable defect that has occurred or would plausibly recur, and then name the direct check of the actual condition (parameters, state, schema, content, or invariant) with expected versus observed values. Neither a hash nor modification time substitutes for that check, and a provenance, recovery, or integrity label does not exempt a hash comparison. Hashes used only as identifiers (commit SHAs, cache file names, manifest names) are not findings. Treat pinned values and tolerances the same way: state the condition the check is trying to establish, check it directly, and flag every tolerance without a stated derivation; a published table or measured reference is a legitimate expected value. Cache reuse is a check whose essence is "same inputs": recommend storing every input that changes the cached result and comparing those inputs directly, reporting which one differs, with a hash used at most as a file name.

Abstractions: count only implementations on real code paths, including strategies selected by string, dict, or enum dispatch; test fakes, mocks, and stubs do not count, and benchmark-only strategies go in the decision table. Below three, flattening is the default. If one has a demonstrated benefit or protects an existing requirement, recommend neither silent retention nor automatic deletion; put it in the decision table with source location, callers, purpose, benefit, simpler alternative, and a recommendation.

Return:
1. Stack, entrypoints, and data flow.
2. Literal schemas and state structures, with source anchors.
3. Integrity ceremony: hash checks and pinned-value checks (deletion, or the direct check that replaces one), cache reuse tests, event sourcing, locks/leases/heartbeats, and their real consumers.
4. Hot-loop bottlenecks if applicable; separate measured evidence from hypotheses.
5. Single-implementation abstractions and configuration churn.
6. O(N) health/status/startup/polling scans.
7. Write-only telemetry, with the consumer search behind each claim.
8. A deletion/flattening table:
   File:Line | Bloat Pattern | Runtime/Cognitive Cost | 1-Sentence Flat Replacement
9. Side bugs noticed while tracing, one line each with anchor and whether verified. Do not search for bugs; list only what tracing surfaced.
10. A decision table, last. Ask no decision questions anywhere else. One row per class of findings that share a pattern and recommendation; split a class only where instances differ in what keeping them buys:
   Pattern Class | Instances (count + source anchors) | What Keeping It Buys | Recommendation | Effect If Unanswered (left unchanged)

Also report the top friction, retained requirements, search scope and queries for absence claims, excluded/inaccessible paths, evidence, and uncertainty. Include only candidates supported by inspected source. Stop after the report; do not implement changes.
```

## Turn an audit into action

Verify reported claims against the current source before accepting them. Rank by actual friction and likely benefit, not the number of named patterns. Produce a short **rip-it-out table** with source anchor, proposed removal/replacement, affected callers/contracts, preservation needs, and decisive check.

If implementation is requested, fill in exact targets and a stepwise execution prompt. If patching directly, follow the same scope and checks. Avoid adding infrastructure, unnecessary dependencies, a blanket test suite, or a broad rewrite as the price of simplification.

## Implementation prompt

```text
Implement the verified flattening plan for [repository/path]. Read applicable guidance and preserve unrelated changes. This prompt is task-scoped and does not override harness policies or permissions.

Deployment assumption: single-user, trusted localhost unless the user states otherwise. Verify this against current callers and requirements. Use the existing stack and add zero unnecessary dependencies.

Default design: flat functions, direct SQLite CRUD where persistence is needed, and suitable numeric vectorization. Remove hash chains, event sourcing, and distributed-lock ceremony not traceable to a documented requirement from the named scope after verifying their consumers. Retain necessary local race protection. Explicit documented user requirements may be retained and surfaced rather than deleted.

Hash checks: delete by default; when in doubt, remove the check rather than replace it. Replace one only when it guards a nameable defect that has occurred or would plausibly recur, using a direct check of the actual condition (parameters, state, schema, content, or invariant) that reports expected versus observed values. Do not substitute modification time or another proxy. A provenance, recovery, or integrity label does not exempt a hash comparison, including a warn-only one. Hashes used only as identifiers (commit SHAs, cache file names, manifest names) stay. Apply the same rule to pinned values and tolerances used as expected values: check the condition they stand for directly; a published table or measured reference stays as a legitimate expected value. Decide cache reuse by comparing the stored inputs that change the cached result, reporting which one differs, never by a hash. Do not invent which scientific changes are compatible; put that question in the decision table.

Apply the Rule of Three default: do not introduce ABC/Protocol/Factory/Base classes or string/dict/enum strategy dispatch unless three or more concrete implementations exist on real code paths; test fakes, mocks, and stubs do not count. Flatten existing ones below the threshold by default. When one has a demonstrated benefit or protects an existing requirement, leave it unchanged and put it in the decision table with its source location, actual callers, purpose, concrete benefit, simpler alternative, what retaining or replacing it would change, and a recommendation; do not silently retain it or automatically delete it. Honor explicit user decisions and documented requirements already given, and state their cost; a requirement counts as documented only when it traces to the user or an external contract, not to unattributed agent-written rationale. Count implementations, not hypothetical future extensions. Preserve only compatibility required by callers and contracts.

Keep pure numeric kernels free of Pydantic validation, deepcopy, JSON, logging, database writes, and dynamic growing-array concatenation. Move necessary validation and logging to boundaries. Preserve sequential dependence, RNG/order requirements, precision, physical model, units, reproducibility requirements, and memory limits.

Do not destructively drop live database schemas unless explicitly requested. Preserve historical readable logs and uncommitted evidence. Where needed, introduce a flat table or bypass ceremony using a bounded, reversible migration with a recovery path.

Verified scope and steps:
1. [Exact source anchors, callers, and required behavior.]
2. [Smallest removal/replacement and any reversible data transition.]
3. [Update affected callers and maintained documentation.]
4. [Run the decisive existing checks; inspect the final diff.]

For Python repos, run fast relevant pytest checks where pytest is the existing test system; otherwise use the equivalent existing test system. Benchmark the real execution path before claiming performance improvement. For scientific changes, justify equivalence criteria and numerical tolerances; distinguish exact, distributional, and conditional results.

Ask no decision questions mid-task. Leave unresolved contracts, physics assumptions, consequential data changes, scope expansion, and abstractions or hash checks awaiting direction unchanged, and finish all unaffected authorized work. Then return one decision table, last. One row per class of findings that share a pattern and recommendation; split a class only where instances differ in what keeping them buys:
Pattern Class | Instances (count + source anchors) | What Keeping It Buys | Recommendation | Effect If Unanswered (left unchanged)

Also return exact artifacts, changes, checks and observed results, measured performance if available, preserved requirements, and uncertainty.
```

## Completion criteria

An audit is complete when the requested source scope has been examined, findings have evidence, costs, consumers, replacements, and explicit limits, and every open question is in the decision table. An implementation is complete when authorized changes and affected context are updated, relevant checks pass, and claims match observed results. Leave suspected speedups and unresolved consumers labeled as such.
