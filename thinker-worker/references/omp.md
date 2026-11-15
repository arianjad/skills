# OMP execution from any caller

Use `tw.py omp` to delegate through the existing OMP agent. It is an execution backend, not a fixed model or a native Codex/Claude child. Any agent or shell that can run Python can use the same command; no caller-harness activation or caller session ID is required. Existing host permissions and the caller's authorization still apply.

OMP owns model selection. With no model/thinking override, a fresh worker uses OMP's configured model and thinking settings; a resumed worker uses its saved session. Changing the configured local model does not require a thinker-worker model-registry edit. The backend does not choose a server, switch a service's model, or assert that an arbitrary configured provider is local. Select the intended OMP profile/configuration normally and inspect the returned provider/model evidence. Native model admissions in `routes.json` continue to govern native routes only.

## Dispatch

Write a bounded brief with the normal `TW-Role`, routing header, owned files, context pointers, meaningful acceptance check and stop condition. The command's role must match the brief. Independent-review and ideation briefs retain explicit authorization and scope. Assign independent verification to a different author/session.

```
python <thinker-worker>/scripts/tw.py omp --role worker --brief-file <brief.md> --cd <checkout>
```

Here `--role` selects the assignment type, `--brief-file` names the written assignment, and `--cd` selects the worker's working directory. Omit model and thinking to inherit OMP defaults. Optional `--model` requests an OMP provider/model selector; `--thinking` requests a thinking setting supported by that OMP model. These are per-run overrides, not new defaults. Unsupported selections are errors, not permission to substitute another route.

The backend preserves OMP's configured tools, extensions, skills and approval policy. An explicit `--approval-mode` changes approval handling for that run; omitting it leaves the configuration authoritative. Approval settings do not prove OS-level isolation. Use isolated configuration for tests that would otherwise capture production memory.

## Results and continuation

The command saves process events, stderr, final assistant text and a persistent worker session, then prints compact JSON. Distinguish the execution's receipt key from the actual OMP worker session. Provider/model fields come from OMP metadata; requested settings, observed settings and unavailable evidence remain distinct. A process exit, terminal model response and acceptance of the delivered artifact are separate facts. Inspect partial files after failure or timeout; retain that attempt rather than relabeling it as a successful later run.

```
python <thinker-worker>/scripts/tw.py omp --role worker --brief-file <follow-up.md> --cd <checkout> --resume <returned-session-file>
```

`--resume` continues the saved conversation; the follow-up is another bounded brief. Preserve assignment and authorship: a resumed author does not become an independent reviewer of its own work. Each invocation has separate execution records while the worker session can continue. Keep independent writers in separate checkouts or disjoint scopes.

Optional `--timeout` sets the process allowance in seconds. Choose it for the task; a short limit is not a model-quality verdict. Timeout cleanup applies only to the launched process tree. Reconcile uncertain cleanup before assigning another writer to those files. This is a subprocess runner, not a background service or scheduler; callers use their existing foreground/background tools.

Set the caller's own process timeout longer than this allowance plus cleanup time, or run it with the caller's background mechanism. Event/result files are finalized after OMP exits; forcibly killing the wrapper can lose those logs and leave the worker running. As with the existing backends, launch from a trusted directory with a trusted `PATH`; Windows executable lookup can prefer a program in the launch directory.

## Verification

Run a check that can fail on a materially wrong delivered artifact, with a known-positive control. Worker-written tests alone do not establish acceptance. Record acceptance through the existing outcome command with the returned receipt session/run identifiers and OMP namespace; an optional `TW-Check` runs in the recorded working directory. Outcome labels do not turn partial execution into completed work.

```
python <thinker-worker>/scripts/tw.py outcome --harness omp --session <session_id> --tool-use-id <tool_use_id> --accepted yes
python <thinker-worker>/scripts/tw.py tally --harness omp
```

Use the OMP namespace with the existing tally command to inspect outcomes. Model evidence is per execution, so an OMP configuration change can produce a different model without rewriting native admissions or priors. Do not infer general model quality from one trial or token-cost figures from missing usage.

The returned `usage` sums the main assistant's streamed messages, not a total bill for auxiliary services or nested agents.

## Boundaries

The native hook mechanism does not intercept this subprocess as a native child. Structural brief checks and execution records do not establish semantic authorization, hook interception, effective permissions or correctness. Use the route when authorized; respect an explicit denial rather than changing backends to evade it. No daemon, MCP server or live OMP restart is needed.
