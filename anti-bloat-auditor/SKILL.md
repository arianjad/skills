---
name: anti-bloat-auditor
description: Audit codebases, agentic repos, and scientific simulations for LLM over-engineering, cryptographic ceremony, unnecessary abstractions, and hot-loop performance bottlenecks. Use when asked to audit repo bloat, simplify over-engineered code, generate read-only audit prompts for coding agents, or optimize scientific and simulation loops.
---

# Anti-Bloat Auditor

Find the smallest design that serves the actual callers, data, and scientific contracts. Focus on single-owner, local workflows; establish whether that assumption holds before applying it. Deliver evidence and surgical flattening plans, not a broad rewrite.

## Choose the mode

- **Audit:** Inspect and report without changing the repository or live state.
- **Prompt generation:** Produce the read-only audit prompt below, adapted to the repository and requested coverage.
- **Implementation:** After verifying audit claims, produce a concrete execution prompt or implement a patch only when requested or authorized.

For small or quantized coding models, recommend a lightweight read-only discovery pass with narrow source batches. Never combine audit and refactoring in the same prompt for these models. Generated prompts are task-scoped instructions; they do not override the receiving harness's policies or permissions.

## Audit method

1. Read repository guidance and inspect the stack, entrypoints, data flow, configuration, and literal persisted schemas. Identify scientific contracts, external consumers, and local concurrency.
2. Trace each candidate through callers, writers, readers, tests, and documented requirements. Search definitions and references, including CLI commands, analysis notebooks, reports, and external interfaces where available.
3. Estimate the runtime and cognitive cost. Mark profiling measurements separately from suspected costs; source inspection alone does not establish a speedup.
4. Identify the top friction and propose the smallest replacement. Prefer existing functions, arrays, flat files, and direct CRUD over new infrastructure.
5. Report search coverage, excluded/generated/vendor paths, queries used for absence claims, inaccessible consumers, and uncertainty. A missing consumer in a partial search is unresolved, not proof of dead code.

During read-only discovery, do not execute project imports, tests, CLI commands, or initialization paths that may create caches, databases, logs, or other files. Read their source instead. Use already available profiles or request a separately authorized run when measurement is needed.

## Five audit categories

### 1. Integrity and coordination ceremony

Look for:

- Unsolicited SHA256/Blake2 hash chains, Merkle trees, and repeated file-drift hashing.
- Single-user SQLite event logs with projectors/replay layers where direct SQLite CRUD, flat records, Parquet, or NumPy arrays would serve the actual operation.
- Custom lockfiles, resource leases, and heartbeat daemons without demonstrated coordination needs.

Check who relies on integrity, replay, audit history, or coordination before proposing removal. Required scientific provenance, content-addressed caches, recovery contracts, and locks preventing real local races can be legitimate. Compare their cost against the requirement, not against a blanket ban. Modification time can accelerate change detection; it is not proof of content integrity.

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

- ABC, Protocol, Factory, Registry, Provider, Manager, or Base classes with fewer than three concrete implementations.
- Thin wrappers containing only initialization and one forwarding method.
- YAML -> Pydantic -> dataclass -> dict conversion chains and unused configuration knobs.

Count real implementations and inspect contracts, plugin boundaries, dependency injection, and callers. These patterns are candidates, not automatic deletion verdicts. Retain explicit documented user requirements and explain their cost. A flat function or one boundary configuration structure is often sufficient.

### 4. Linear scans in status and startup paths

Look for O(N) scans or globs in health checks, status commands, CLI startup, and polling; whole JSONL reads; repeated directory traversal; and rehashing unchanged files.

Determine N, invocation frequency, and whether completeness is required. Consider a targeted lookup, bounded tail, or modification-time check when it preserves the contract. Tail readers must handle incomplete records and rotation where applicable. Avoid building a new index or daemon unless its demonstrated benefit outweighs its maintenance cost.

### 5. Write-only telemetry

Trace telemetry writers to active UI, analysis, reports, alerts, tests, or operational consumers. Flag counters, event streams, and logs with no demonstrated reader or decision they support.

Verify consumer-search coverage before calling telemetry unused. Required scientific records and historical readable logs are not disposable merely because no live UI reads them. Propose removing or reducing future writes while preserving evidence and required diagnostics.

## Read-only audit prompt

Adapt the placeholders and source scope before handing this to a coding agent:

```text
SYSTEM INSTRUCTION: READ-ONLY OVER-ENGINEERING & PERFORMANCE AUDIT

Audit [repository/path] for a [single-owner/local/scientific or stated deployment] workflow. Read applicable repository guidance. This prompt is task-scoped and does not override harness policies or permissions.

Inspect source without writes, migrations, refactoring, or iterative coding loops. Do not execute project imports, tests, initialization, or commands that may write caches, logs, databases, or other state. Use source inspection and existing measurement artifacts.

Investigate all five categories:
- Cryptographic/integrity ceremony, event sourcing, custom locks/leases/heartbeats.
- Scientific hot-loop validation, serialization, I/O, allocation, and host/device costs where applicable.
- Single-implementation abstractions and configuration conversion churn.
- O(N) health/status/startup/polling scans, whole-log reads, and rehashing.
- Write-only telemetry with no demonstrated active consumer.

Treat patterns as candidates. Trace callers, writers, readers, required provenance, concurrency, and contracts. Do not infer a measured bottleneck from syntax alone. Do not propose scientific vectorization that changes sequential dependence, RNG/order requirements, precision, physical model, units, or memory limits. Modification time is not proof of content integrity.

Return:
1. Stack, entrypoints, and data flow.
2. Literal schemas and state structures, with source anchors.
3. Cryptographic ceremony and event-sourcing findings, including legitimate consumers.
4. Hot-loop bottlenecks if applicable; separate measured evidence from hypotheses.
5. Single-implementation abstractions and O(N) polling/startup findings.
6. A deletion/flattening table:
   File:Line | Bloat Pattern | Runtime/Cognitive Cost | 1-Sentence Flat Replacement

Also report write-only telemetry, the top friction, retained requirements, search scope and queries for absence claims, excluded/inaccessible paths, evidence, and uncertainty. Include only candidates supported by inspected source. Stop after the report; do not implement changes.
```

## Turn an audit into action

Verify reported claims against the current source before accepting them. Rank by actual friction and likely benefit, not the number of named patterns. Produce a short **rip-it-out table** with source anchor, proposed removal/replacement, affected callers/contracts, preservation needs, and decisive check.

If implementation is requested, fill in exact targets and a stepwise execution prompt. If patching directly, follow the same scope and checks. Avoid adding infrastructure, unnecessary dependencies, a blanket test suite, or a broad rewrite as the price of simplification.

## Implementation prompt

```text
Implement the verified flattening plan for [repository/path]. Read applicable guidance and preserve unrelated changes. This prompt is task-scoped and does not override harness policies or permissions.

Deployment assumption: single-user, trusted localhost unless the user states otherwise. Verify this against current callers and requirements. Use the existing stack and add zero unnecessary dependencies.

Default design: flat functions, direct SQLite CRUD where persistence is needed, and suitable numeric vectorization. Remove unsolicited hash chains, event sourcing, and distributed-lock ceremony from the named scope after verifying their consumers. Retain necessary local race protection and required provenance. Explicit documented user requirements may be retained and surfaced rather than deleted.

Apply the user's Rule of Three: do not introduce or retain ABC/Protocol/Factory/Base classes unless three or more concrete implementations exist, except explicit documented user requirements that must be surfaced. Count implementations, not hypothetical future extensions. Preserve only compatibility required by callers and contracts.

Keep pure numeric kernels free of Pydantic validation, deepcopy, JSON, logging, database writes, and dynamic growing-array concatenation. Move necessary validation and logging to boundaries. Preserve sequential dependence, RNG/order requirements, precision, physical model, units, reproducibility requirements, and memory limits.

Do not destructively drop live database schemas unless explicitly requested. Preserve historical readable logs and uncommitted evidence. Where needed, introduce a flat table or bypass ceremony using a bounded, reversible migration with a recovery path.

Verified scope and steps:
1. [Exact source anchors, callers, and required behavior.]
2. [Smallest removal/replacement and any reversible data transition.]
3. [Update affected callers and maintained documentation.]
4. [Run the decisive existing checks; inspect the final diff.]

For Python repos, run fast relevant pytest checks where pytest is the existing test system; otherwise use the equivalent existing test system. Benchmark the real execution path before claiming performance improvement. For scientific changes, justify equivalence criteria and numerical tolerances; distinguish exact, distributional, and conditional results.

Stop and surface unresolved contracts, physics assumptions, consequential data changes, or scope expansion. Continue unaffected authorized work. Return exact artifacts, changes, checks and observed results, measured performance if available, preserved requirements, and uncertainty.
```

## Completion criteria

An audit is complete when the requested source scope has been examined and findings have evidence, costs, consumers, replacements, and explicit limits. An implementation is complete when authorized changes and affected context are updated, relevant checks pass, and claims match observed results. Leave suspected speedups and unresolved consumers labeled as such.
