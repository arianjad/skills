# Decision-router lessons: Kev, Laya and disabling behavior

Date: 2026-10-25 UTC
Status: audit plus authorized call-disable trial and cache fix. The resolution below supersedes the historical cache caveat; other improvement proposals remain unimplemented.
Owner: Thinker–Worker, in skills_public/thinker-worker.
Scope: file-only audit during RAM reliability testing. No inference, benchmark, download, process change or configuration change was performed. This document is the only authorized write.

## Finding

The models have influenced routing, but only two retained model-driven effort changes are verified as executed. Both were Laya upgrades from high to xhigh. Most attempted model calls failed at the connection stage; most successful answers failed the confidence-margin gate. Exploration, rather than model advice, accounts for almost all rewrite intentions. These receipts do not establish a quality improvement or token saving.

Local-Agent's Hermes shadow scorer is separate. Its current scored paths use its resident model's chat log probabilities, not Kev/Laya. Keeping model environments under Local-Agent/local_decisions does not establish consumer ownership.

## Provenance and scope

Audit source: all 282 *.jsonl files under C:/Users/Arian/.thinker-worker/receipts, 3,527,965 bytes, parsed in memory with Python standard library; 4,697 rows and zero malformed lines. No model packages were imported. Percentiles below use nearest rank. Rows were joined on (harness, session_id, tool_use_id), without treating duplicate outcome labels as independent tasks.

There are 1,115 route rows, all marked harness=claude, from 2026-09-27T02:05:33.542970Z through 2026-10-23T14:05:57.798515Z. Both backends appear in 860 rows, September 28–October 23. No claim is made that every receipt is production traffic: setup/probe traffic is not consistently labeled. Retention, historical configuration versions and dropped events are not fully documented. Counts are a dated snapshot, not a live dashboard.

Implementation inspected: installed ~/.codex/skills/thinker-worker/scripts/tw.py and ~/.claude/skills/thinker-worker/scripts/tw.py; source servers/decision_servers.py and servers/laya_serve.py; C:/Users/Arian/Code/kev/kev/serve.py. Relevant functions: load_routes, merge_override, prior_route, route, ask_backends, backend_jev, act, routed, claude_run and spool_once. Installed copies have slightly different line offsets; use function names. Source repo files and installed copies must not be assumed identical after an update.

Live verification limitation: Get-CimInstance Win32_Process failed with “Access to a CIM resource was not available to the client.” No alternate process API was used. Current PIDs, parent trees, process ownership, RAM usage and loaded model bytes remain unverified. Startup records are not live identity proof.

## Retained performance

| Metric | Kev | Laya |
|---|---:|---:|
| Valid answers / calls | 27 / 860 (3.1%) | 135 / 860 (15.7%) |
| URLError: urlopen error timed out | 720 | 720 |
| Shared-deadline timeout | 113 | 5 |
| Successful response p50 | 1,312 ms | 1,281 ms |
| Successful response p95 | 2,000 ms | 1,656 ms |
| Successful response maximum | 2,000 ms | 1,890 ms |
| October 23 valid answers | 0 / 23 | 23 / 23 |

The 720 paired URL failures are consistent with connection availability failures under JEV_CONNECT_S=0.5, not demonstrated model-quality failures. They do not prove the processes were stopped. All routing rows have p50 547 ms, p95 2,000 ms and maximum 2,016 ms. Successful-response percentiles exclude timeouts; many deadline failures lack individual backend ms. A low overall median is largely fast failure, not fast successful reasoning.

Modes: active 865; advisory 232; shadow 18. Pins: true 277, false 663, missing in older rows 175. Sources: coordinator 956, explore 127, cached:explore 25, bayes 7. Gate: no result 980, margin rejection 128, pass 7. All 135 rows with a valid model result were active-mode rows; the retained shadow/advisory rows do not provide a model-quality control arm.

Seven gate passes break down as follows:

- Four agreed with the coordinator's medium tier, with no change.
- Two on October 15, 03:53:04 and 03:53:18 UTC changed high to xhigh. Laya answered; Kev timed out. Each has action=rewrite, cost effort=xhigh, race lost=false and accepted=true. Neither has a mechanical check row.
- One on October 22, 18:57:38 UTC suggested high to medium, but pinned=true preserved high. Its rejected outcome is not evidence about the ignored medium suggestion.

There are 70 rewrite intentions: 68 from exploration, two from bayes. Their verification rows report 65 lost=false, four lost=true and one absent verification. Therefore an action=rewrite record alone is not executed behavior. Advisory actions total 23; these are denials with advice, not proof of a changed run.

There are 963 outcome and 251 check rows globally. Joining route IDs gives 928 routes with at least one outcome, 942 outcome records (863 accepted, 79 rejected), and 249 checks (240 pass, nine fail). Repeated labels exist. Task acceptance measures the delivered task, not the correctness of a minimum-effort classification. There are no matched counterfactual baseline runs for the two Laya upgrades. Do not infer accuracy, causal benefit or savings from acceptance ratios.

## Exact fallback and disable semantics

The coordinator tier is the requested dispatch effort: native Codex reasoning_effort, the tier encoded in a Claude tw-role-tier agent, or a pipeline's explicit tier argument. Prior tables guide coordinator selection and are logged separately; a model failure does not replace the request with a global default such as medium.

For a fresh decision, route asks every configured backend concurrently under one shared two-second deadline. Invalid/error/late answers are excluded. Valid answers are combined using a weighted geometric mean; the top-two probability margin must reach 0.2. Until that gate passes, the base pick is the coordinator's requested tier.

Then exploration is applied independently: for an unpinned dispatch above the cheapest allowed tier, its deterministic ticket draw can choose one tier below that base pick. Current inherited schedule is epsilon=max(0.05,min(1,0.5/t**0.25)), where t is the class's non-pinned route count plus one. Thus both all-models-failed and backends=[] can still lead to exploration. Missing answers are not by themselves a hard guarantee of unchanged effort.

Before fresh scoring, prior_route can reuse the first non-coordinator decision for the same session and brief ticket. Cached results bypass new backend calls and exploration; the tier is clamped to the current model's allowed ladder. A cached bayes result can still act after backends are disabled. A cached exploration result is not re-advised by act's source eligibility rule, but stays recorded as the cached pick. Tickets omit model and configuration version. Disabling calls is not cache invalidation.

act applies risk floors to non-coordinator picks; the floor is zero for a coordinator-source result. Current shipped physics/destructive/external floors are medium. It suppresses action if the resulting target is ineligible, agrees with the coordinator, is lifted by a floor to or above the coordinator from below, is shadow, is pinned, or has TW-Override. It does not silently repair a coordinator tier through a router risk floor. Separate admission validates role/model/tier constraints.

Active Claude routing may rewrite the agent tier if competing-writer and prior lost-race guards permit it. Otherwise it advises by denying with a suggested tier. Plaintext native Codex active routing advises rather than rewriting. The owned tw.py codex pipeline can apply its own tier rewrite. A routing exception after admission logs an error and leaves the admitted dispatch alone; malformed input or admission failures are a separate path and can deny.

| Control | Backend requests | Applied effort change | Resident models / startup |
|---|---|---|---|
| Servers unavailable | Attempted, bounded wait | Base coordinator; exploration or cached decision may still act | No change |
| router.backends=[] | None for fresh decisions | Exploration and cached decisions remain possible | No unload; autostart still loads |
| mode=shadow | Still attempted unless cached | No router action | No unload/startup change |
| TW-Pin | Fresh backend calls still possible; exploration zero | No router action | No unload/startup change |
| TW-Override | Fresh calls/exploration may be logged | No router action | No unload/startup change |
| Empty backends plus shadow for every applicable class | No fresh backend requests | No router action, including cached suggestions | Separate lifecycle controls needed |

Set explore=0 as well when the desired report should not even show hypothetical exploration. This does not clear existing cached suggestions; shadow blocks their application. Preserve admission/role guards. There is no unified router off mode in the inspected mode set; do not invent one.

Configuration precedence: explicit routes path, then TW_ROUTES (both bypass overrides); otherwise installed routes plus TW_ROUTES_OVERRIDE or ~/.thinker-worker/routes.json. Backend lists replace; class overrides inherit merged star settings, including exploration. Invalid overrides are ignored with an error and installed defaults remain. A star change must not be assumed to override every existing class-specific entry. Inspect effective configuration for each class.

## Timeouts, queues and model identity

Kev and Laya calls run concurrently, not serially. A Kev timeout can hold a 1.3-second Laya response until the two-second common deadline. Thread join deadlines stop waiting, not server inference. Both servers serialize work under a model lock. The inspected request paths do not propagate a request deadline or cancellation check before inference; a disconnected client's request can wait and then execute. This is a code-supported risk, not measured proof of a current queue backlog. Kev's returned inference latency starts after its lock, so it excludes that queue wait.

Configured CPU launch hides CUDA, sets OMP/MKL threads to six and HF_HUB_OFFLINE=1; Laya explicitly sets six Torch threads. Kev uses device auto-selection and inherits environment options, so exact live dtype/device is not verified. Python environments are CPython 3.12.3. No live memory measurements were taken.

- Kev: jaredpalmer/kev-0.8b cache revision 54f4f8777356cd5bbbb6c6919c657f26e6f2f6d8; Qwen/Qwen3.5-0.8B-Base, recorded base revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68; LoRA rank 16. Adapter 43,338,624 bytes and head 2,103,103 bytes exclude base weights. Local serving checkout recorded HEAD 90990a5fac2995b9faa3190f7d437e84f2067768, branch windows-pin-2026-09-22; dirty-tree equivalence unverified.
- Laya: convaiinnovations/laya, typed-decisions, cache revision 1c5edc17a7acd8701df6fc341c0d179f1c62c982; ModernBERT-large, two-layer head, configured max_len 1024; model file 842,609,220 bytes. Artifact sizes are not RAM usage.

Interface: POST /v1/systemone; state is role line, routing header and truncated brief body (Kev 1500 characters, Laya 1100). A choice question asks for the lowest effort tier that completes the delegated task correctly, with text criteria for the role/model's permitted low/medium/high/xhigh options. Responses supply probabilities, normalized over permitted tiers. This is a provisional effort-label task, not general chat generation.

## Modular controls and lessons

What happened: model environments were mistaken for Local-Agent dependencies; active configuration was mistaken for applied model decisions; silence/empty logs invited obsolete-service conclusions.
What should happen: separate consumer, call enablement, decision application, process residency and logon lifecycle. Report configured, requested, scored, gated, intended and executed states distinctly.
Why: these are independent controls, and model calls can be useful, ineffective, timed out or ignored without changing a worker tier.

Existing runtime lifecycle is servers/decision_servers.py start|stop|status. start loads both models and warms them; stop relies on CIM identity checks and is not verified usable under this audit's denial. The Startup thinker-worker-decision-servers.cmd unconditionally invokes start. Disabling router backends does not disable that launcher. The spool watcher is a separate optional sandbox-to-Claude bridge; it has no direct need to keep decision models resident.

Local-Agent: /router off suppresses scored edges and managed questions in that chat; ordinary inference and rule edges remain. Its separate step_reasoning.policy is already off. Per-site off disables scoring; shadow still scores. Classifier mode off controls older classification logging, not the classification operation itself. None of these controls unload Kev/Laya.

Observed failures: connection timeouts; inference/deadline timeouts; four rewrite-verification mismatches. Their root causes are not established here. Design risks: stale cached choices across configuration changes; exploration after disabling model calls; work surviving client timeouts; incomplete timing and provenance; ambiguous user-facing disable semantics. Proposals below are not observed fixes or proven defects.

## Improvements to implement later

1. Define explicit disabled behavior: no backend calls, no exploration, no application of cached suggestions, unchanged requested coordinator tier, admission guards retained. Record disabled as a reason. Keep scoring-only and apply-decisions controls separate. Lifecycle enablement should be persistent and honored by manual start and autostart; it must not silently stop an already running service.
2. Add a request ID shared by dispatch, router and server records. Include schema version, effective config digest, code version, model/base/adapter revisions, allowed tier ladder, truncation counts and server instance ID. Distinguish requested settings from live attestation.
3. Separate connect, queue, encode, inference, response and total elapsed times; record deadline, timeout stage, cancellation/disconnect, late completion and dropped-before-start events. Use bounded queues and request expiry before inference; define cancellation limits for already-running forwards.
4. Log all valid score distributions, top-two margin/cutoff, backend failures, fallback reason, cached origin/config, coordinator/raw/floored/intended/executed tiers, mode, pin, override, exploration ticket/probability and execution verification. Do not call intention execution.
5. Join downstream checks and outcomes with request IDs, objective check provenance and rejection cause. Keep repeated labels with timestamps and an explicit final-label rule. Separate diagnostics/probes from normal tasks and mark missing telemetry.
6. Define retention and privacy: rotated bounded logs, documented time coverage, redacted error messages, no credentials or raw briefs by default. Store opt-in evaluation inputs separately with access/retention controls; digests are linkage, not anonymization. Report deletions and gaps so empty directories cannot masquerade as no usage.

## Evaluation and validation plan (not executed)

First fix observability/availability; do not replace models merely because connections failed. After the RAM hold is lifted, freeze a consented task set with objective checks. Compare unchanged coordinator and simple rule/prior baselines against Laya, Kev and candidate replacements under the same hardware, queue load, input budget and deadline. Separate model identity from effort. Record full retry/verification cost, quality, latency, availability and intervention rate; a higher successful effort is not a saving. Use paired or randomized assignments, retain propensities and failures, and avoid training/test leakage. Score calibration and selective risk at the margin gate, not just top-tier agreement with a coordinator who may also be wrong.

Tests should use mocked backends/servers first: no valid answers retains base tier before exploration; one valid answer can gate; pinned makes no change; shadow makes no change but still scores; empty backends makes zero calls; explicit off makes zero calls/exploration/cache application; stale cache cannot defeat off; class overrides and pinned route files obey precedence; risk floors and allowed ladders hold; native/pipeline actions and race verification remain distinct. Exercise slow/expired requests with stubs to prove bounded waiting and no execution after queue expiry. Lifecycle-disabled start must make zero Popen/model-load/warm calls; re-enable restores existing behavior. No tests or policy changes were executed in this audit.

## Open questions

Why did both endpoints fail to connect for long periods? Why is Kev frequently over budget when Laya responds? How much is queue wait versus inference? Were rewrite mismatches already fixed elsewhere? What fraction of retained rows are probes? Which baseline and acceptable quality/latency tradeoff should govern replacement? Resolve these from improved evidence rather than inferring model accuracy from current logs.

No existing project knowledge folder/index or OKF-specific convention was found in the inspected owning project and global instruction locations. This dated, project-local evidence note preserves source pointers, observed/proposed separation and open questions without migrating other documents.
## Authorized follow-through: trial without decision-model calls

After the initial audit, Arian explicitly requested a trial without decision models, preserving modular backend choice. On 2026-10-25 the user override C:/Users/Arian/.thinker-worker/routes.json changed only router.backends from ["kev", "laya"] to []. The classes star mode remains active. Exact prior bytes were saved to C:/Users/Arian/.thinker-worker/backups/routes-before-no-decision-models-20261025.json. The edit refused an unexpected prior value, preserved all other bytes and checked for concurrent edits before writing.

Before: {"router": {"backends": ["kev", "laya"], "classes": {"*": {"mode": "active"}}}}
After:  {"router": {"backends": [], "classes": {"*": {"mode": "active"}}}}

Verification (no inference): loaded both installed Codex and Claude tw.py modules with bytecode writing disabled; called their load_routes functions and compared each effective result to its own prior configuration merged from the backup. Only router.backends changed. Both effective configurations have backends=[] and classes.*={mode: active, explore: {c: 0.5, power: 0.25, floor: 0.05}}. A mocked backend resolver in ask_backends observed zero backend calls and an empty result. No worker, model, benchmark or test inference was launched. This small configuration check is the only test performed; the proposed validation suite above remains unexecuted.

TW_ROUTES and TW_ROUTES_OVERRIDE were absent in this process and persisted User/Machine environment scopes. Explicit pinned route paths still bypass this override; environments privately inherited by other already-running processes were not inspected because the CIM denial remains. Therefore the verified coverage is ordinary loading in both installed copies with the inspected environment, not every possible external caller. Old cached model suggestions can be reused without making new model calls; exploration is intentionally unchanged. The user's trial disables fresh decision-model calls, not all routing adjustments.

No server was stopped, no Startup entry changed, and no Local-Agent Hermes or spool setting changed. Resident models may still occupy memory; logon startup can still load and warm them. This is a separate lifecycle decision, not part of the call-disable change.

Rollback: preferably change only router.backends back to ["kev", "laya"], preserving any intervening edits. The exact backup can restore the whole previous file only after confirming there have been no subsequent changes. Rollback re-enables calls; it neither proves endpoint health nor starts a stopped server. Keep the RAM reliability workload hold until separately released.

## Resolution: disabled backends bypass historical model decisions (2026-10-25)

Implemented in source scripts/tw.py and deployed to both installed copies. With router.backends=[], prior_route skips historical model-derived rows, retains eligible later exploration-only rows, and never edits receipt history. route also filters an explicitly supplied prior, protecting callers that bypass normal lookup. With backends enabled, cache selection behavior is unchanged. Fresh disabled routing starts from the requested coordinator tier and applies the existing exploration, pin/override and risk-floor policy.

Attribution follows actual routing data: a bayes origin, passed model gate, or retained model provenance establishes model dependence. New fresh and cached route records carry model_derived, including exploration performed around a model-derived base pick. This field survives cache reuse and is persisted in receipts. Repeated cached: prefixes are normalized by their terminal source. Old fresh exploration with no passed gate/provenance remains reusable. An orphan legacy cached exploration row whose origin information was erased is conservatively bypassed when models are disabled; ordinary histories retain their earlier original row and thus preserve proven exploration-only cache semantics. No archival or deletion was necessary.

Source baseline: skills_public HEAD 10b2879fb8f62ff6c0bb5ab07815d4f1f04e7f26. Initial git status contained only the knowledge folder from this task. No commit/push occurred. Tracked diff: scripts/tw.py, 32 changed lines (26 additions, six deletions); scripts/test_tw_route.py, three changed lines. Added scripts/test_tw_disabled_cache.py with nine focused unittest cases. The existing enabled-cache test now explicitly enables a backend, because its prior assumption that empty backends reuse model suggestions is the behavior being fixed. git diff --check passes (Git reports only expected LF/CRLF conversion warnings).

Tests: the initial regression reproduced disabled backends returning cached:bayes/xhigh instead of coordinator/high, and cached model-derived exploration surviving disabling. After the fix, nine focused tests pass in source and separately against each actual installed Codex and Claude module (27 executions total). Coverage includes model-derived exploration, legacy repeated prefixes, disabled zero backend invocations, enabled cache behavior, coordinator-only exploration, later eligible cache lookup, unchanged receipt bytes, persisted attribution, pins, explicit overrides, role-tier clamping and risk floors. Existing test_tw_route.py, test_tw_act.py, test_tw_backends.py and test_tw_lifecycle.py all pass. These use temporary homes, mocks and local stub HTTP servers; no model inference or actual worker tasks ran. Initial sandbox attempts blocked temporary-file replacement and stub sockets; the authorized tests subsequently passed outside those restrictions. CIM was never retried.

Deployment preserved an unrelated pre-existing Claude-only --sandbox option. Source and installed Codex had matched before the fix; installed Claude differed by that reviewed option. The deployment saved exact originals, applied only the cache replacements to Claude using the installer's compare-before-write atomic_write, then invoked the existing guarded upgrade with a reviewed Claude-specific source_items overlay. Its ordinary hook/manifest conflict checks remained active; only the two tw.py payloads differed. upgrade reported one remaining owned-file replacement (Codex), retained hooks/activation/receipts, and updated manifest and install ledger. Both installed payloads were then hash-checked against their manifest and tested directly. This is a per-harness preservation overlay, not evidence the two files should be identical. Future source-based upgrades must retain or deliberately reconcile the Claude sandbox-option divergence; it has not been migrated into source by this narrow fix.

Verified SHA-256:
- Source and installed Codex tw.py: 4af49f5a053427b967330bfdc1d8000c7a97156f081a4124f6130bc5f42a1c43
- Installed Claude tw.py, including its preserved option: 96e5e23c112e88356ca300c11005e5345b9940673003bdd74aef8766c852ff52

Rollback folder: C:/Users/Arian/.thinker-worker/backups/cache-fix-20261025/. Contains source-tw.before.py, installed-codex-tw.before.py, installed-claude-tw.before.py, manifest.before.json, ledger.before.json and exact replacement pairs. A narrow rollback should reverse those reviewed replacements only after checking current hashes and preserving intervening edits, then reconcile installer metadata. Restoring full manifest/ledger is safe only if no subsequent install changes occurred. Reverting this fix restores the old cache defect; it does not re-enable backend calls. The separate routes-before-no-decision-models-20261025.json backup controls the call-disable rollback.

Effective configuration was reloaded from both actual installed copies: backends=[], mode active and explore={c:0.5,power:0.25,floor:0.05}. No runtime settings changed in this phase. Existing processes that already imported old code were not restarted; newly invoked installed hooks use the fixed files. Explicit route files or privately inherited environment overrides remain outside the verified ordinary user-config path. Servers, autostart, Hermes and spool remain untouched; RAM workload hold remains. Remaining questions are availability/queue root causes, telemetry quality, evaluation design, and the separately preserved Claude option, not cache invalidation for the verified disabled-backend path.
