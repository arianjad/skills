# Effort routing, phase 1 — implementation plan

**Goal:** thinker-worker routes every dispatch through data-driven role policy, logs a router decision per
dispatch (shadow), can advise or rewrite the tier per class, records per-child cost, and coexists
deterministically with context-mode.

**Approach:** Replace tw.py's hard-coded role tables with `routes.json`, and generate `tw-<role>-<tier>`
agents from it. Add `route()` with the `coordinator` and `table` backends inside a 2 s budget, then the
`advisory` and `active` act modes. The context-mode guard compares mtime against process start. Add a
SubagentStop cost and tripwire hook, and a promotion script over receipts. On the home side:
- context-mode's Agent hook is removed by the heal;
- a SubagentStart hook carries the ctx nudge.

Local model backends (`tw.py serve`, SemIf/Kev/Eos/Laya) and the Codex v2 `task_name` join are phase 2;
see "Not in this plan".

**Design:** `docs/plans/2026-09-26-effort-routing-architecture-design.md`, commits through `f9d13eb`/`fbf89dc`
(§4.2 routes, §4.3 route(), §4.4 flow, §4.5 fail modes, §4.6 context-mode, §5 promotion rule, §7 rulings).

**Constraints (every task):**
- Python: `C:/Users/Arian/anaconda3/envs/claude-code/python.exe` (called `PY` below). `tw.py` stays
  stdlib-only; it runs as a hook under whatever interpreter the portable wrapper finds.
- Tests are plain scripts run from `thinker-worker/scripts` (`$PY test_tw_<name>.py`), printing
  `PASS …`. There is no pytest.
- TDD per task: write or modify the test, run it and see it fail for the stated reason, implement, run it
  and see it pass, then run the full suite (`for t in test_*.py; do $PY $t || break; done`). One commit per
  green task, `(Windows)` in the message, no push.
- The hook fails closed on PreToolUse. Any exception still ends in `denial()`, as in `main()` today.
- Receipts never store the brief body. Only the opt-in body store may.
- The router is fail-open inside its budget: an exception, timeout, or invalid output gives
  `source: coordinator` and no action.
- Commit by explicit pathspec (`git commit -m … -- <paths>`). Other sessions write `~/.claude` concurrently.
- Checkpoint: append one line per green task to `thinker-worker/ROUTING-PROGRESS.md`, in the style of
  `INSTALLER-PROGRESS.md`. Record any decision taken inside a task there too.

**Deviations from the design sketch (flag to reviewer):**
1. Role keys keep `independent-review` (the §4.2 sketch says `review`), so `TW-Role:` lines in briefs do
   not change.
2. Claude roles list `models` (alias sets such as `opus`, `claude-opus-5-5`). The generated agent file pins
   `models[0]`.
3. `table` backend confidence is 0.0. The calibration table is a baseline and never crosses the 0.85
   cutoff, so it cannot trigger advisory or active on its own.
4. `plugin-patches.json` is not edited. Its checker verifies that a substring is *present*, and this patch
   is an *absence*. The heal auto-reapplies it, and the vault note is the human registry.
5. The process start is computed per dispatch (measured 11 ms via stdlib ctypes on Windows), not cached.
6. Act modes are `shadow | advisory | active`. §5's "enforce" is `active`.

## File map

Repo `C:\Users\Arian\Code\skills` (all under `thinker-worker/` unless stated):

- Create: `routes.json` — role policy per harness plus router config (T1).
- Modify: `scripts/tw.py`:
  - constants block → `load_routes`, `Decision`, `AGENT_NAME`, `TIERS` (T1);
  - `first_role`, `review_details`, `routing_header` → a single `"\n"` parser, `header_fields`,
    `header_text` (T1);
  - `decide` rewritten (T1); `activation`/`activate`/`status` drop the per-role flags and add
    `store_bodies` (T1);
  - `receipt` (T1, T3); `hook` (T3, T5, T6); `source_items`/`SKILL_FILES`/`AGENT_FILES` → generated
    agents (T2);
  - `route`, `BACKENDS`, `ticket`, `route` CLI (T3); `competing_agent_writer`, `claude_process_start` (T4);
    `act` (T5);
  - `subagent_stop`, `hook_entry`/`owned_entries`/`add_entry`/`remove_entry`/`install`/`check`/`uninstall`
    for the SubagentStop entry (T6); `promote` plus CLI (T7).
- Delete: `claude-agents/` (3 files) (T2); `scripts/test_tw_miner.py` and `scripts/test_tw_ideation.py`
  (T1; their live cases move to `test_tw_routes.py`).
- Create tests:
  - `scripts/test_tw_routes.py` (T1)
  - `scripts/test_tw_agents.py` (T2)
  - `scripts/test_tw_route.py` (T3)
  - `scripts/test_tw_guard.py` (T4)
  - `scripts/test_tw_act.py` (T5)
  - `scripts/test_tw_stop.py` (T6)
  - `scripts/test_tw_promote.py` (T7)
- Modify tests:
  - `test_tw_header.py`, `test_tw_hook.py`, `test_tw_receipt.py`, `test_tw_outcome.py` and
    `test_tw_portable.py` for the new agent names and signatures (T1);
  - `test_tw_install.py:25` (T2);
  - `test_tw_portable.py:72`: the receipt count (T3).
- Modify: `SKILL.md`, `references/claude.md`, `references/codex.md`, and repo `README.md` (the
  thinker-worker section) (T9).
- Create: `ROUTING-PROGRESS.md` (T1, appended every task).

Home repo `C:\Users\Arian` (`~/.claude`):
- Modify: `.claude/hooks/plugin-patch-heal.mjs` — auto-remove context-mode's Agent entry (T8).
- Create: `.claude/hooks/ctx-subagent-nudge.mjs` — SubagentStart ctx pointer (T8).
- Modify: `.claude/settings.json` — register SubagentStart (T8). **The file has foreign uncommitted edits.
  See the T8 stop condition.**

Vault `~/obsidian-vault`:
- Modify: `02-solutions/local-plugin-patches.md` — patch entry (T8). Read `~/obsidian-vault/CLAUDE.md`
  for the schema first.

## Tasks

### Task 1: `routes.json` and a data-driven gate

Files: `routes.json` (new), `scripts/tw.py`, `scripts/test_tw_routes.py` (new), `test_tw_header.py`,
`test_tw_hook.py`, `test_tw_receipt.py`, `test_tw_outcome.py`, `test_tw_portable.py`; delete
`test_tw_miner.py` and `test_tw_ideation.py`.

Interfaces produced:
- `TIERS`
- `load_routes(path=None) -> dict`
- `Decision(admitted, reason, role, model, tier, fields)` (a NamedTuple)
- `decide(harness, envelope, routes) -> Decision`
- `header_fields(brief) -> (dict|None, str)`
- `header_text(fields, cap=256) -> str`
- `agent_name(role, tier) -> str`
- `activate(home, harness, session, store_bodies=False)`

`routes.json` (skill root, next to `SKILL.md`):

```json
{
  "schema": 1,
  "harnesses": {
    "claude": {"roles": {
      "worker":             {"models": ["opus", "claude-opus-5", "claude-opus-5-5"], "tiers": ["low", "medium", "high", "xhigh"], "default": "high", "tools": null},
      "leaf":               {"models": ["sonnet", "claude-sonnet-5"],               "tiers": ["low", "medium"],                 "default": "low",  "tools": null},
      "independent-review": {"models": ["fable", "claude-fable-5", "claude-fable-5-1"], "tiers": ["high", "xhigh"],             "default": "high", "tools": null},
      "ideation":           {"models": ["fable", "claude-fable-5", "claude-fable-5-1"], "tiers": ["high", "xhigh"],             "default": "high", "tools": null}
    }},
    "codex": {"roles": {
      "worker":             {"models": ["gpt-6-sol", "gpt-5.6-sol", "gpt-5.6-terra"], "tiers": ["low", "medium", "high", "xhigh"], "default": "high"},
      "leaf":               {"models": ["gpt-6-luna"],  "tiers": ["low", "medium"],          "default": "low"},
      "independent-review": {"models": ["gpt-6-astra"], "tiers": ["medium", "high", "xhigh"], "default": "high"},
      "ideation":           {"models": ["gpt-6-astra"], "tiers": ["medium", "high", "xhigh"], "default": "high"}
    }}
  },
  "router": {
    "backends": ["table"],
    "budget_s": 2.0,
    "cutoff": 0.85,
    "table": {"path": "~/Code/effortmining/bench/state/calibration.json"},
    "classes": {"*": {"mode": "shadow", "explore": 0.0}}
  }
}
```

`tw.py` edits:
1. **Imports:** add `from typing import NamedTuple`, `import threading`, `import time`, `import random`
   (the last three are used from T3/T7 on; add them now to keep later diffs small).
2. **Delete** `CODEX_WORKERS`, `CODEX_REVIEW`, `CODEX_LEAF`, `CLAUDE_WORKERS`, `CLAUDE_REVIEW`,
   `CLAUDE_LEAF`, `CLAUDE_ROLES`, `MINER_TYPE`, `CODEX_EFFORTS`, `HEADER_MAX` and `opus_reason()`.
3. **Add:**

```python
TIERS = ("low", "medium", "high", "xhigh")
AGENT_NAME = re.compile(r"tw-(worker|leaf|independent-review|ideation)-(low|medium|high|xhigh)")
VALUE_MAX = 1000  # per header value at the gate; receipts truncate at 256


class Decision(NamedTuple):
    admitted: bool
    reason: str
    role: str | None = None
    model: str | None = None
    tier: str | None = None
    fields: dict | None = None


def agent_name(role: str, tier: str) -> str:
    return f"tw-{role}-{tier}"


def load_routes(path: Path | None = None) -> dict:
    path = path or source_root() / "routes.json"
    doc = read_json(path, None)
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise Conflict(f"routes.json missing or not schema 1: {path}")
    for harness in HARNESSES:
        for role, pol in doc["harnesses"][harness]["roles"].items():
            if (not pol.get("models") or not pol.get("tiers") or any(t not in TIERS for t in pol["tiers"])
                    or pol.get("default") not in pol["tiers"]):
                raise Conflict(f"routes.json: bad policy for {harness}/{role}")
    return doc
```

4. **Replace** `first_role`, `review_details` and `routing_header` with one `"\n"`-only parser. This fixes
   the old `tw.py:171,176` `splitlines()` use.

```python
def first_role(brief: object) -> tuple[str | None, str]:
    if not isinstance(brief, str) or not brief:
        return None, "missing brief"
    match = ROLE_LINE.fullmatch(brief.split("\n")[0])
    return (match.group(1), "") if match else (None, "first brief line must be exactly TW-Role: worker, leaf, independent-review, or ideation")


def review_details(brief: str) -> bool:
    lines = brief.split("\n")[1:12]
    return (any(x.startswith("TW-Authorization: ") and x[18:].strip() for x in lines) and
            any(x.startswith("TW-Scope: ") and x[10:].strip() for x in lines))


def header_fields(brief: str) -> tuple[dict | None, str]:
    """Return ({key: value}, "") or (None, problem). Keys may sit anywhere in lines 2-12."""
    found: dict[str, str] = {}
    for line in brief.split("\n")[1:12]:
        key, sep, value = line.partition(": ")
        if sep and key in HEADER_KEYS:
            if key in found:
                return None, f"routing header repeats {key}"
            found[key] = value.strip()
    missing = [k for k in HEADER_KEYS if not found.get(k)]
    if missing:
        return None, "routing header needs non-empty " + ", ".join(missing)
    if found["TW-Class"] not in TASK_CLASSES:
        return None, "routing header TW-Class is not an effortmining class"
    risks = [r.strip() for r in found["TW-Risk"].split(",")]
    if risks != ["none"] and not (set(risks) <= RISKS and len(set(risks)) == len(risks)):
        return None, "routing header TW-Risk must be none or distinct values from " + ", ".join(sorted(RISKS))
    long = [k for k in HEADER_KEYS if len(found[k]) > VALUE_MAX]
    if long:
        return None, f"routing header value over {VALUE_MAX} characters: " + ", ".join(long)
    return found, ""


def header_text(fields: dict, cap: int = 256) -> str:
    def cut(v: str) -> str:
        return v if len(v) <= cap else f"{v[:cap]}…[+{len(v) - cap}]"
    return "\n".join(f"{k}: {cut(fields[k])}" for k in HEADER_KEYS)
```

5. **Rewrite** `decide`:

```python
def decide(harness: str, envelope: dict, routes: dict) -> Decision:
    inp = envelope.get("tool_input")
    if not isinstance(inp, dict):
        return Decision(False, "missing tool_input")
    roles = routes["harnesses"][harness]["roles"]
    model = inp.get("model")
    model = model if isinstance(model, str) else None
    brief = inp.get("message" if harness == "codex" else "prompt")
    fields = None
    if harness == "codex" and envelope.get("tool_name") == "collaborationspawn_agent":
        # v2 brief is ciphertext: route from the visible model only; Astra = review or ideation, role unknown.
        route = next((r for r in ("worker", "leaf", "independent-review") if model in roles[r]["models"]), None)
        if route is None:
            return Decision(False, "model is not allowed for namespaced Codex dispatch", None, model)
        role = None if route == "independent-review" else route
    else:
        role, problem = first_role(brief)
        if not problem:
            fields, problem = header_fields(brief)
        if problem:
            return Decision(False, problem, role, model)
        route = role
        if role in ("independent-review", "ideation") and not review_details(brief):
            return Decision(False, f"{role} brief needs TW-Authorization and TW-Scope lines", role, model)
    pol = roles[route]
    if harness == "codex":
        if model is None:
            return Decision(False, "explicit model is required; inherited/omitted model is disallowed", role)
        if inp.get("agent_type") not in (None, "default"):
            return Decision(False, "custom agent_type is outside this route", role, model)
        if model not in pol["models"]:
            return Decision(False, f"model is not allowed for {route}", role, model)
        tier = inp.get("reasoning_effort")
        if tier not in pol["tiers"]:
            return Decision(False, f"reasoning_effort must be one of {', '.join(pol['tiers'])} for {route}", role, model)
        if not valid_codex_fork(inp.get("fork_turns")):
            return Decision(False, "fork_turns must be explicit 'none' or a bounded positive count", role, model)
    else:
        st = inp.get("subagent_type")
        match = AGENT_NAME.fullmatch(st) if isinstance(st, str) else None
        if not match or match.group(1) != role:
            return Decision(False, f"subagent_type must be tw-{role}-<tier>", role, model)
        tier = match.group(2)
        if tier not in pol["tiers"]:
            return Decision(False, f"tier {tier} is outside {role}'s tiers {pol['tiers']}", role, model)
        if model is not None and model not in pol["models"]:
            return Decision(False, f"per-call model {model} differs from the {role} agent's model", role, model)
        if inp.get("fork_context") or inp.get("fork"):
            return Decision(False, "Claude inherited-model fork is outside fresh dispatch", role, model)
    return Decision(True, "admitted-request-only", role, model, tier, fields)
```

6. **Activation.** In `activation()`, validate only `schema == 1`, `harness`, `session_id`, and
   `type(obj.get("store_bodies", False)) is bool`. Old records with review/luna/sonnet/ideation fields stay
   valid; those fields are ignored. Also:
   - `activate(home, harness, session, store_bodies=False)` writes
     `{"schema": 1, "harness", "session_id", "store_bodies", "activated_at"}`.
   - `status` prints `activation`, `harness`, `session_id` and `store_bodies`, plus the three `unknown`
     fields.
   - In `main()`, the `activate` parser drops `--review`, `--luna`, `--sonnet` and `--ideation` and adds
     `p.add_argument("--store-bodies", action="store_true")`. Pass `args.store_bodies` through.
7. **`receipt(home, harness, session, envelope, d: Decision)`:**
   - `header = header_text(d.fields) if d.fields else None`;
   - replace `requested_model`/`requested_effort` with `"requested_model": small(d.model), "tier": d.tier`;
   - `decision`, `reason` and `role` come from `d`.

   In `hook`:
   - the early-deny calls become `receipt(..., Decision(False, "invalid-state"))`, and likewise
     `invalid-event` and `resume-key-on-fresh-dispatch`;
   - the main path is `d = decide(harness, envelope, load_routes())`, then
     `receipt(home, harness, session, envelope, d)`, then `if not d.admitted: denial(d.reason)`.

   `hook` no longer passes the activation record to `decide`.

`scripts/test_tw_routes.py`:

```python
"""Role policy comes from routes.json: Claude tier agents tw-<role>-<tier>, Codex model + effort tiers.
Run: python test_tw_routes.py"""
import tw

R = tw.load_routes()
HDR = "TW-Class: C-coding\nTW-Deliverable: patch\nTW-Accept: tests pass\nTW-Risk: none\n"
AUTH = "TW-Authorization: t\nTW-Scope: t\n"
W = "TW-Role: worker\n" + HDR + "x"
LEAF = "TW-Role: leaf\n" + HDR + "x"
REV = "TW-Role: independent-review\n" + AUTH + HDR + "x"
IDEA = "TW-Role: ideation\n" + AUTH + HDR + "x"


def claude(brief, st, model=None, **extra):
    inp = {"subagent_type": st, "prompt": brief, **extra}
    if model:
        inp["model"] = model
    return tw.decide("claude", {"tool_input": inp}, R)


def codex(brief, model, effort=None, v2=False):
    inp = {"message": brief, "model": model, "fork_turns": "none"}
    if effort:
        inp["reasoning_effort"] = effort
    return tw.decide("codex", {"tool_name": "collaborationspawn_agent" if v2 else "spawn_agent",
                               "tool_input": inp}, R)


CASES = [
    ("claude worker tier agent, no model", claude(W, "tw-worker-low").admitted, True),
    ("claude tier recorded", claude(W, "tw-worker-xhigh").tier, "xhigh"),
    ("claude matching per-call model", claude(W, "tw-worker-high", "opus").admitted, True),
    ("claude per-call model mismatch", claude(W, "tw-worker-high", "sonnet").admitted, False),
    ("no max tier", claude(W, "tw-worker-max").admitted, False),
    ("role/agent mismatch", claude(W, "tw-leaf-low").admitted, False),
    ("leaf tier outside role", claude(LEAF, "tw-leaf-high").admitted, False),
    ("leaf medium", claude(LEAF, "tw-leaf-medium").admitted, True),
    ("old hand-written agent refused", claude(W, "thinker-worker-opus", "opus").admitted, False),
    ("miners are not a route", claude(W, "effortmining:miner-high", "opus").admitted, False),
    ("review tier agent", claude(REV, "tw-independent-review-high").admitted, True),
    ("review below its floor", claude(REV, "tw-independent-review-medium").admitted, False),
    ("ideation needs auth/scope", claude(IDEA.replace(AUTH, ""), "tw-ideation-high").admitted, False),
    ("ideation on opus refused", claude(IDEA, "tw-ideation-high", "opus").admitted, False),
    ("fork refused", claude(W, "tw-worker-high", fork=True).admitted, False),
    ("role line split on \\n only", claude("TW-Role: worker\u2028" + HDR + "x", "tw-worker-high").admitted, False),
    ("codex worker sol high", codex(W, "gpt-6-sol", "high").admitted, True),
    ("codex worker terra", codex(W, "gpt-5.6-terra", "medium").admitted, True),
    ("codex max refused", codex(W, "gpt-6-sol", "max").admitted, False),
    ("codex worker effort required", codex(W, "gpt-6-sol").admitted, False),
    ("codex review effort required", codex(REV, "gpt-6-astra").admitted, False),
    ("codex review low below floor", codex(REV, "gpt-6-astra", "low").admitted, False),
    ("codex ideation medium", codex(IDEA, "gpt-6-astra", "medium").admitted, True),
    ("codex ideation on sol", codex(IDEA, "gpt-6-sol", "high").admitted, False),
    ("codex leaf luna low", codex(LEAF, "gpt-6-luna", "low").admitted, True),
    ("v2 astra needs effort", codex("<cipher>", "gpt-6-astra", v2=True).admitted, False),
    ("v2 astra high, role null", codex("<cipher>", "gpt-6-astra", "high", v2=True)[:3:2], (True, None)),
    ("v2 unknown model", codex("<cipher>", "gpt-9", "high", v2=True).admitted, False),
]

if __name__ == "__main__":
    bad = [(name, got, want) for name, got, want in CASES if got != want]
    for b in bad:
        print("FAIL", b)
    assert not bad
    print(f"PASS {len(CASES)} route-policy cases")
```

Test edits:
- **`test_tw_header.py`:**
  - `REC = …` → `R = tw.load_routes()`.
  - `verdict(brief, st="tw-worker-high")` builds `{"subagent_type": st, "prompt": brief}` and returns
    `tw.decide("claude", env, R)[:2]`.
  - Replace the case `("header over 600 chars", …, False)` with `("value of 1000 chars", …replace("patch to f.py", "p" * 1000)…, True)`
    and `("value over 1000 chars", …"p" * 1001…, False)`.
  - The main loop picks `st = "tw-independent-review-high" if "independent-review" in brief else "tw-worker-high"`
    and drops `model`.
- **`test_tw_hook.py`:** the envelope's `tool_input` becomes `{"subagent_type": "tw-worker-high", "prompt": …}`.
- **`test_tw_receipt.py`:**
  - The admitted dispatch uses `{"subagent_type": "tw-worker-medium", "prompt": "TW-Role: worker\n" + HDR + BODY}`
    and asserts `admit["subagent_type"] == "tw-worker-medium" and admit["tier"] == "medium"`.
  - The denied one uses `"tw-worker-high"` with the header-less brief and asserts
    `deny["subagent_type"] == "tw-worker-high"`.
  - The Codex block activates without `--review` and adds `"reasoning_effort": "high"` to the v2 input.
- **`test_tw_outcome.py`:** the hook input becomes `{"subagent_type": "tw-worker-high", "prompt": "TW-Role: worker\n" + HDR + "x"}`.
- **`test_tw_portable.py`:** line 70 `envelope("thinker-worker-opus")` → `envelope("tw-worker-high")`;
  line 125 `"subagent_type": "thinker-worker-opus"` → `"tw-worker-high"`. Leave `"model": "opus"`; it is
  allowed.
- **`git rm scripts/test_tw_miner.py scripts/test_tw_ideation.py`.** Their surviving cases are in
  `test_tw_routes.py`. Their removed behaviors are by design (§4.7): miners as a route, `TW-Opus-Reason`,
  per-role activation flags, and Codex review/ideation effort omission.

Check: `cd thinker-worker/scripts && $PY test_tw_routes.py` → `PASS 28 route-policy cases`. Then the full
suite passes, except `test_tw_install.py`, which still expects the hand-written agents until T2. Say so in
the progress line.

Commit: `git add thinker-worker/routes.json thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md && git commit -m "thinker-worker: routes.json role policy; data-driven gate; tier agents tw-<role>-<tier>; Codex review/ideation effort >= medium; Terra; miners/Opus-reason/role flags removed (Windows)" -- thinker-worker/routes.json thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 2: generated tier agents

Files: `scripts/tw.py`, `scripts/test_tw_agents.py` (new), `scripts/test_tw_install.py`; delete
`claude-agents/`.

Interfaces consumed: `load_routes`, `agent_name`. Produced: `agent_files(routes) -> dict[str, bytes]`.

`tw.py` edits:
1. `SKILL_FILES = ("SKILL.md", "routes.json", "references/codex.md", "references/claude.md", "scripts/tw.py")`;
   delete `AGENT_FILES`.
2. Add:

```python
AGENT_TEXT = {  # role -> (description, body); bodies carried over from the retired hand-written agents
    "worker": ("Bounded execution for thinker/worker mode; coordinator owns framing and acceptance.",
               "Execute the coordinator's bounded assignment. Preserve other agents' edits. Checkpoint meaningful "
               "progress, run proportional checks, and report exact artifacts, results, and uncertainties. Escalate a "
               "changed objective or consequential assumption to the coordinator. Do not dispatch children without "
               "explicit bounded authorization."),
    "leaf": ("Short, objectively checkable leaf for an opted-in thinker/worker session.",
             "Complete only the coordinator's bounded leaf assignment. Use supplied rules for extraction, inventory, or "
             "simple reconciliation; report exact artifacts and checks. Escalate ambiguity or judgment calls to the "
             "coordinator. Preserve other agents' edits and do not dispatch children."),
    "independent-review": ("Bounded independent review when the coordinator cites authorization.",
                           "Review the assigned artifact adversarially. Identify unsupported, incorrect, fragile, or "
                           "overbuilt parts with exact source references; run a check yourself when it settles a claim. "
                           "Report findings; do not edit the files under review. Stay within the bounded assignment. Do "
                           "not treat the request's model name as evidence of the effective runtime model."),
    "ideation": ("Bounded ideation (divergent) when the coordinator cites authorization.",
                 "Propose at most the requested number of ranked directions. Label each speculative and state what "
                 "would confirm or kill it; cite prior art you find. Do not edit project files. Stay within the bounded "
                 "assignment."),
}


def agent_files(routes: dict) -> dict[str, bytes]:
    out = {}
    for role, pol in routes["harnesses"]["claude"]["roles"].items():
        desc, body = AGENT_TEXT[role]
        for tier in pol["tiers"]:
            name = agent_name(role, tier)
            head = ["---", f"name: {name}", f"description: {desc} Effort {tier}.",
                    f"model: {pol['models'][0]}", f"effort: {tier}"]
            if pol.get("tools"):
                head.append("tools: " + ", ".join(pol["tools"]))
            out[f"{name}.md"] = ("\n".join(head + ["---", "", body, ""])).encode("utf-8")
    return out
```

3. In `source_items`, replace the `AGENT_FILES` loop with
   `for name, data in agent_files(load_routes(root / "routes.json")).items(): out[f".claude/agents/{name}"] = data`.
4. `git rm -r thinker-worker/claude-agents`.

`scripts/test_tw_agents.py`:

```python
"""install generates one Claude agent per (role, tier) in routes.json, with matching effort and model.
Run: python test_tw_agents.py"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import tw

TW = str(Path(__file__).with_name("tw.py"))

if __name__ == "__main__":
    routes = tw.load_routes()
    want = {tw.agent_name(r, t) for r, p in routes["harnesses"]["claude"]["roles"].items() for t in p["tiers"]}
    assert len(want) == 10, want
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = subprocess.run([sys.executable, TW, "install", "--home", tmp, "--python", sys.executable,
                            "--harness", "claude"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        files = {p.stem for p in (home / ".claude" / "agents").glob("*.md")}
        assert files == want, files ^ want
        for name in want:
            text = (home / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            role, tier = tw.AGENT_NAME.fullmatch(name).groups()
            assert f"\neffort: {tier}\n" in text and f"\nname: {name}\n" in text, name
            assert f"\nmodel: {routes['harnesses']['claude']['roles'][role]['models'][0]}\n" in text, name
            assert "tools:" not in text, name               # tools: null = full access (Arian 2026-09-26)
            assert not re.search(r"effort: (max|ultra)", text), name
        assert subprocess.run([sys.executable, TW, "uninstall", "--home", tmp], capture_output=True).returncode == 0
        assert not list((home / ".claude" / "agents").glob("tw-*.md"))
    print("PASS 10 generated tier agents; effort/model match routes.json; uninstall removes them")
```

`test_tw_install.py:25`: `"thinker-worker-opus.md"` → `"tw-worker-high.md"`.

Check: `$PY test_tw_agents.py` → `PASS 10 generated tier agents…`. The full suite passes, including
`test_tw_install.py`.

Commit: `git commit -m "thinker-worker: install generates tw-<role>-<tier> agents from routes.json; hand-written agents removed (Windows)" -- thinker-worker/scripts thinker-worker/claude-agents thinker-worker/ROUTING-PROGRESS.md`

### Task 3: `route()` in shadow — coordinator and table backends, route rows, ticket, body store, `route` CLI

Files: `scripts/tw.py`, `scripts/test_tw_route.py` (new), `scripts/test_tw_portable.py`.

Interfaces consumed: `Decision`, `load_routes`, `header_text`. Produced:
- `ticket(brief) -> (str12, digest)`
- `route(routes, harness, role, fields, brief, coord_tier) -> dict` with keys `tier`, `probs`, `confidence`,
  `source`, `ms`, `body_chars_sent`, `ticket`, `digest`, `mode`, `explore`
- `BACKENDS: dict[str, callable]`
- route rows `{"kind": "route", …, "action": None}` (T5 fills `action` and `guard`)

`tw.py` additions:

```python
def ticket(brief: str) -> tuple[str, str]:
    norm = "\n".join(x.rstrip() for x in brief.split("\n") if not x.startswith("TW-Route:")).strip()
    digest = sha(norm.encode("utf-8"))
    return digest[:12], digest


def clamp(tier: str, tiers: list[str]) -> str:
    i = TIERS.index(tier)
    return min(tiers, key=lambda t: (abs(TIERS.index(t) - i), TIERS.index(t)))


def backend_table(cfg: dict, pol: dict, fields: dict, brief: str) -> dict:
    cal = json.loads(Path(os.path.expanduser(cfg["path"])).read_text(encoding="utf-8"))
    tier = clamp(cal["classes"][fields["TW-Class"]]["recommended_tier"], pol["tiers"])
    return {"tier": tier, "probs": {t: float(t == tier) for t in pol["tiers"]}, "confidence": 0.0,
            "body_chars_sent": 0}


BACKENDS = {"table": backend_table}  # phase 2 adds the resident HTTP scorers


def valid_route(out: object, tiers: list[str]) -> bool:
    if not isinstance(out, dict) or out.get("tier") not in tiers or not isinstance(out.get("probs"), dict):
        return False
    probs = out["probs"]
    return (set(probs) <= set(tiers) and all(isinstance(v, (int, float)) and v >= 0 for v in probs.values())
            and abs(sum(probs.values()) - 1) < 1e-6
            and isinstance(out.get("confidence"), (int, float)) and 0 <= out["confidence"] <= 1)


def class_mode(routes: dict, cls: str | None) -> tuple[str, float]:
    classes = routes["router"]["classes"]
    c = classes.get(cls) or classes["*"]
    return c["mode"], float(c.get("explore", 0.0))


def route(routes: dict, harness: str, role: str, fields: dict, brief: str, coord_tier: str) -> dict:
    cfg = routes["router"]
    pol = routes["harnesses"][harness]["roles"][role]
    result: dict = {}
    start = time.monotonic()

    def work() -> None:
        for name in cfg["backends"]:
            fn = BACKENDS.get(name)
            if fn is None:
                continue
            try:
                out = fn(cfg.get(name, {}), pol, fields, brief)
            except Exception:
                continue
            if valid_route(out, pol["tiers"]):
                result.update(out, source=name)
                return

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(cfg["budget_s"])
    found = dict(result) if result.get("source") else None  # copy: the thread may still be running
    if found is None:
        found = {"tier": coord_tier, "probs": {coord_tier: 1.0}, "confidence": 0.0, "source": "coordinator",
                 "body_chars_sent": 0}
    tick, digest = ticket(brief)
    mode, explore = class_mode(routes, fields["TW-Class"])
    return {**found, "ms": round((time.monotonic() - start) * 1000), "ticket": tick, "digest": digest,
            "mode": mode, "explore": explore}
```

In `hook`, after an admitted Claude or plaintext-Codex decision (skip Codex v2: `d.role is None` or
`tool_name == "collaborationspawn_agent"`; its join is phase 2):

```python
    brief = inp.get("message" if harness == "codex" else "prompt")
    r = route(load_routes(), harness, d.role, d.fields, brief, d.tier)
    row = {"kind": "route", "at": now(), "harness": harness, "session_id": session,
           "tool_use_id": envelope.get("tool_use_id"), "class": d.fields["TW-Class"],
           "coordinator_tier": d.tier, "router_tier": r["tier"], "probs": r["probs"],
           "confidence": r["confidence"], "source": r["source"], "mode": r["mode"], "ms": r["ms"],
           "body_chars_sent": r["body_chars_sent"], "ticket": r["ticket"], "digest": r["digest"],
           "action": None, "guard": None}
    if record.get("store_bodies"):
        body = state_root(home) / "bodies" / sha(session.encode("utf-8")) / f"{r['ticket']}.md"
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(brief, encoding="utf-8")
    append_receipt(home, harness, session, row)
```

`route` CLI (Codex v2 coordinator, or an opt-in on Claude). In `main()`, add `"route"` to the command list
with `--harness`, `--role` (choices: the four roles) and `--brief-file` (Path). Then:

```python
        elif args.command == "route":
            routes = load_routes()
            brief = args.brief_file.read_text(encoding="utf-8")
            fields, problem = header_fields(brief)
            if problem:
                raise Conflict(problem)
            default = routes["harnesses"][args.harness]["roles"][args.role]["default"]
            r = route(routes, args.harness, args.role, fields, brief, default)
            print(json.dumps({k: r[k] for k in ("tier", "probs", "confidence", "source", "ticket", "mode")}))
```

The CLI writes no receipt: `ponytail: the v2 join by task_name is phase 2`.

`scripts/test_tw_route.py`:

```python
"""route(): table backend clamps to the role's tiers, falls back to the coordinator on any failure or overrun;
the hook appends a route row (no body) after an admitted dispatch; opt-in body store; ticket ignores TW-Route.
Run: python test_tw_route.py"""
import json
import tempfile
import time
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import HDR, SESSION, hook, receipts

BRIEF = "TW-Role: worker\n" + HDR + "SECRET-BODY do it"


def routes_with(cal_path, backends=("table",), budget=2.0):
    r = tw.load_routes()
    r["router"] = {**r["router"], "backends": list(backends), "budget_s": budget, "table": {"path": str(cal_path)}}
    return r


if __name__ == "__main__":
    fields, _ = tw.header_fields(BRIEF)
    with tempfile.TemporaryDirectory() as tmp:
        cal = Path(tmp) / "calibration.json"
        cal.write_text(json.dumps({"classes": {"C-coding": {"recommended_tier": "xhigh"}}}), encoding="utf-8")
        r = tw.route(routes_with(cal), "claude", "worker", fields, BRIEF, "high")
        assert (r["source"], r["tier"], r["confidence"], r["mode"]) == ("table", "xhigh", 0.0, "shadow"), r
        r = tw.route(routes_with(cal), "claude", "leaf", fields, BRIEF, "low")
        assert r["tier"] == "medium", r                                   # clamped into leaf tiers
        r = tw.route(routes_with(Path(tmp) / "missing.json"), "claude", "worker", fields, BRIEF, "high")
        assert (r["source"], r["tier"], r["confidence"]) == ("coordinator", "high", 0.0), r
        tw.BACKENDS["bad"] = lambda *a: {"tier": "low", "probs": {"low": 0.7}, "confidence": 0.9}
        assert tw.route(routes_with(cal, ("bad",)), "claude", "worker", fields, BRIEF, "high")["source"] == "coordinator"
        tw.BACKENDS["slow"] = lambda *a: time.sleep(3) or {"tier": "low", "probs": {"low": 1.0}, "confidence": 1.0}
        t0 = time.monotonic()
        r = tw.route(routes_with(cal, ("slow",), budget=0.2), "claude", "worker", fields, BRIEF, "high")
        assert r["source"] == "coordinator" and time.monotonic() - t0 < 1.0, r
    assert tw.ticket(BRIEF) == tw.ticket(BRIEF.replace(HDR, HDR + "TW-Route: abc\n"))

    for store in (False, True):
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION]
                     + (["--store-bodies"] if store else []))
            hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": BRIEF})
            hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": "TW-Role: worker\nno header"})
            rows = receipts(home, "claude")
            assert [x["kind"] for x in rows] == ["dispatch", "route", "dispatch"], rows   # no route row on deny
            assert rows[1]["coordinator_tier"] == "high" and rows[1]["action"] is None, rows[1]
            raw = next(Path(home).rglob("receipts/claude/*.jsonl")).read_text(encoding="utf-8")
            assert "SECRET-BODY" not in raw
            bodies = list(Path(home).rglob("bodies/*/*.md"))
            assert (len(bodies) == 1 and "SECRET-BODY" in bodies[0].read_text(encoding="utf-8")) if store else not bodies

    long = "TW-Role: worker\n" + HDR.replace("TW-Deliverable: patch", "TW-Deliverable: " + "p" * 300) + "x"
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        hook(home, "claude", "Agent", {"subagent_type": "tw-worker-high", "prompt": long})
        assert "…[+44]" in receipts(home, "claude")[0]["header"]
        f = Path(home) / "b.md"
        f.write_text(BRIEF, encoding="utf-8")
        code, out = run_main(["route", "--harness", "claude", "--role", "worker", "--brief-file", str(f)])
        assert code == 0 and json.loads(out)["ticket"] == tw.ticket(BRIEF)[0], out
    print("PASS route: table clamp, coordinator fallback (missing/invalid/overrun), route rows, no body, body store, header truncation, CLI")
```

`test_tw_portable.py:72`: the receipt line count `== 4` → `== 6`. Each admitted dispatch now appends a
route row, and there are two admitted dispatches per install run.

Check: `$PY test_tw_route.py` → `PASS route: …`. Then the full suite passes.

Commit: `git commit -m "thinker-worker: route() in shadow (table + coordinator fallback, 2 s budget), route rows, ticket digest, opt-in body store, route CLI (Windows)" -- thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 4: context-mode guard (`competing_agent_writer`, `claude_process_start`)

Files: `scripts/tw.py`, `scripts/test_tw_guard.py` (new).

Interfaces produced:
- `claude_process_start() -> float | None` (epoch seconds of the nearest `claude(.exe)` ancestor)
- `competing_agent_writer(home) -> str | None` (a reason to act advisory, or None)

```python
def _win_claude_start() -> float | None:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("ppid", wintypes.DWORD), ("prio", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", ctypes.c_wchar * 260)]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    e = Entry()
    e.dwSize = ctypes.sizeof(Entry)
    procs = {}
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        procs[e.pid] = (e.ppid, e.exe.lower())
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    pid = os.getpid()
    for _ in range(12):
        ppid, exe = procs.get(pid, (0, ""))
        if exe == "claude.exe":
            handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            times = [wintypes.FILETIME() for _ in range(4)]
            k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
            k32.CloseHandle(handle)
            ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return (ft - 116444736000000000) / 1e7 if ft else None
        if not ppid:
            return None
        pid = ppid
    return None


def _posix_claude_start() -> float | None:
    # ponytail: Mac CLI shows as "claude" or "node"; unverified on the Mac until the T9 live check there.
    import subprocess
    pid = os.getpid()
    for _ in range(12):
        parts = subprocess.run(["ps", "-o", "ppid=,etime=,comm=", "-p", str(pid)],
                               capture_output=True, text=True, timeout=2).stdout.split(None, 2)
        if len(parts) < 3:
            return None
        ppid, etime, comm = parts
        if os.path.basename(comm.strip()) in ("claude", "node"):
            d, _, hms = etime.rpartition("-")
            secs = sum(int(x) * m for x, m in zip(reversed(hms.split(":")), (1, 60, 3600)))
            return time.time() - secs - int(d or 0) * 86400
        pid = int(ppid)
    return None


def claude_process_start() -> float | None:
    try:
        return _win_claude_start() if os.name == "nt" else _posix_claude_start()
    except Exception:
        return None


def competing_agent_writer(home: Path) -> str | None:
    """A reason the router must not return updatedInput on Agent this session, or None (design §4.6)."""
    try:
        settings = read_json(home / ".claude" / "settings.json", {})
        if not (settings.get("enabledPlugins") or {}).get("context-mode@context-mode"):
            return None
        plugins = read_json(home / ".claude" / "plugins" / "installed_plugins.json", {}).get("plugins") or {}
        entries = plugins.get("context-mode@context-mode") or []
        if not entries:
            return None
        hooks_json = Path(entries[0]["installPath"]) / "hooks" / "hooks.json"
        pre = (read_json(hooks_json, {}).get("hooks") or {}).get("PreToolUse") or []
        for entry in pre:
            matcher = entry.get("matcher") or ""
            try:
                hit = matcher in ("", "*") or re.fullmatch(matcher, "Agent") is not None
            except re.error:
                hit = matcher == "Agent"
            if hit:
                return "context-mode PreToolUse Agent hook is registered"
        start = claude_process_start()
        if start is None:
            return "Claude Code process start unknown"
        if hooks_json.stat().st_mtime >= start - 1:
            return "context-mode hooks.json changed after this session loaded its hooks"
        return None
    except Exception as exc:  # unreadable state: stay advisory, never race
        return f"guard could not read context-mode state: {type(exc).__name__}"
```

`scripts/test_tw_guard.py`:

```python
"""Guard: advisory whenever context-mode's Agent hook may be live in this session (design §4.6).
Run: python test_tw_guard.py"""
import json
import os
import tempfile
import time
from pathlib import Path

import tw

START = 1_790_000_000.0


def setup(home, enabled=True, agent=False, mtime=START - 100, installed=True):
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"context-mode@context-mode": enabled}}))
    cm = home / "cm"
    (cm / "hooks").mkdir(parents=True)
    pre = [{"matcher": "Bash", "hooks": []}] + ([{"matcher": "Agent", "hooks": []}] if agent else [])
    hj = cm / "hooks" / "hooks.json"
    hj.write_text(json.dumps({"hooks": {"PreToolUse": pre}}))
    os.utime(hj, (mtime, mtime))
    plugins = {"context-mode@context-mode": [{"installPath": str(cm)}]} if installed else {}
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": plugins}))


def verdict(start=START, **kw):
    tw.claude_process_start = lambda: start
    with tempfile.TemporaryDirectory() as tmp:
        setup(Path(tmp), **kw)
        return tw.competing_agent_writer(Path(tmp))


CASES = [
    ("plugin disabled", verdict(enabled=False, agent=True), None),
    ("not installed", verdict(installed=False), None),
    ("clean and old", verdict(), None),
    ("Agent entry live", verdict(agent=True) is not None, True),
    ("patched after start (heal ran this session)", verdict(mtime=START + 1.5) is not None, True),
    ("patched within 1 s before start", verdict(mtime=START - 0.5) is not None, True),
    ("start unknown", verdict(start=None) is not None, True),
]

if __name__ == "__main__":
    bad = [(n, g, w) for n, g, w in CASES if g != w]
    for b in bad:
        print("FAIL", b)
    assert not bad
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        setup(home)
        (home / "cm" / "hooks" / "hooks.json").write_text("{not json")
        assert tw.competing_agent_writer(home).startswith("guard could not read"), "malformed -> advisory"
    print(f"PASS {len(CASES) + 1} guard cases")
```

Live check (Windows, from a Bash tool call in any Claude session, so a `claude.exe` ancestor exists):
`cd thinker-worker/scripts && $PY -c "import tw,time; s=tw.claude_process_start(); print(s and time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(s)))"`
It prints a timestamp earlier than the session transcript's first record. The 2026-09-26 probe got
`23:40:18Z` against the first record at `23:40:25Z`, in 11 ms.

Check: `$PY test_tw_guard.py` → `PASS 8 guard cases`, and the live check prints a timestamp (not `None`).

Commit: `git commit -m "thinker-worker: context-mode guard (Agent entry or hooks.json mtime >= claude process start - 1 s -> advisory) (Windows)" -- thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 5: act modes — advisory, active, exploration, override

Files: `scripts/tw.py`, `scripts/test_tw_act.py` (new).

Interfaces consumed: `route()` result, `Decision`, `competing_agent_writer`. Produced:
`act(home, harness, session, envelope, d, r, routes) -> (output_dict | None, action | None, guard | None)`;
route rows carry `action` ∈ {None, "advise", "rewrite"} and `guard`; the session advisory flag file is
`state/<harness>/<sha(session)>.advisory` (written in T6, read here).

```python
def advisory_flag(home: Path, harness: str, session: str) -> Path:
    return state_root(home) / "state" / harness / f"{sha(session.encode('utf-8'))}.advisory"


def act(home, harness, session, envelope, d: Decision, r: dict, routes: dict):
    if r["mode"] == "shadow" or r["source"] == "coordinator":
        return None, None, None
    inp = envelope["tool_input"]
    brief = inp.get("message" if harness == "codex" else "prompt")
    if any(x.startswith("TW-Override: ") and x[13:].strip() for x in brief.split("\n")[1:]):
        return None, None, None
    pol = routes["harnesses"][harness]["roles"][d.role]
    target = r["tier"]
    risky = {x.strip() for x in d.fields["TW-Risk"].split(",")} & {"destructive", "physics"}
    if risky and target == pol["tiers"][0]:
        return None, None, None  # risk-flagged briefs never route to the role's cheapest tier
    lower = TIERS.index(target) < TIERS.index(d.tier)
    disagree = target != d.tier and r["confidence"] >= routes["router"]["cutoff"]
    explored = lower and r["explore"] > 0 and int(r["ticket"], 16) / 16 ** 12 < r["explore"]
    if not (disagree or explored):
        return None, None, None
    guard = None
    if r["mode"] == "active" and harness == "claude":
        guard = competing_agent_writer(home)
        if guard is None and advisory_flag(home, harness, session).exists():
            guard = "lost race recorded earlier this session"
        if guard is None:
            new = {**inp, "subagent_type": agent_name(d.role, target)}
            return ({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                            "updatedInput": new}}, "rewrite", None)
    why = "exploration" if explored and not disagree else f"p={r['confidence']:.2f}"
    reason = (f"router picks {target} ({why}); dispatch {agent_name(d.role, target) if harness == 'claude' else 'reasoning_effort=' + target}"
              f" or add `TW-Override: <reason>` to keep {d.tier}" + (f" [active held: {guard}]" if guard else ""))
    return ({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": f"{OWNER}: {reason}"}}, "advise", guard)
```

In `hook`, after `r = route(…)`, call `out, action, guard = act(home, harness, session, envelope, d, r, routes)`.
Set `row["action"], row["guard"] = action, guard` before `append_receipt`. Then `if out: print(json.dumps(out))`.
`routes` is the dict already loaded for `decide`: load once per hook call and pass it to both.

`scripts/test_tw_act.py`:

```python
"""Act modes: shadow silent; advisory denies with the router's pick; active rewrites subagent_type unless the
guard or a lost-race flag holds it to advisory; override, risk floor, cutoff, exploration.
Run: python test_tw_act.py"""
import json
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import HDR, SESSION, receipts

BASE = tw.load_routes()


def run(mode, pick="low", conf=0.95, explore=0.0, brief_extra="", guard=None, flag=False, risk="none",
        st="tw-worker-high"):
    routes = json.loads(json.dumps(BASE))
    routes["router"].update(backends=["stub"], classes={"*": {"mode": mode, "explore": explore}})
    tw.BACKENDS["stub"] = lambda *a: {"tier": pick, "probs": {pick: 1.0}, "confidence": conf, "body_chars_sent": 0}
    tw.load_routes = lambda path=None: routes
    tw.competing_agent_writer = lambda home: guard
    brief = "TW-Role: worker\n" + HDR.replace("TW-Risk: destructive", f"TW-Risk: {risk}") + brief_extra + "x"
    with tempfile.TemporaryDirectory() as home:
        run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
        if flag:
            tw.advisory_flag(Path(home), "claude", SESSION).write_text("", encoding="utf-8")
        env = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION,
               "tool_use_id": "toolu_x", "tool_input": {"subagent_type": st, "prompt": brief}}
        _, out = run_main(["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))
        row = [x for x in receipts(home, "claude") if x["kind"] == "route"][0]
        return (json.loads(out)["hookSpecificOutput"] if out else None), row


if __name__ == "__main__":
    out, row = run("shadow")
    assert out is None and row["action"] is None and row["router_tier"] == "low"
    out, row = run("advisory")
    assert out["permissionDecision"] == "deny" and "tw-worker-low" in out["permissionDecisionReason"]
    assert row["action"] == "advise"
    assert run("advisory", brief_extra="TW-Override: needs high\n")[0] is None
    assert run("advisory", conf=0.5)[0] is None                          # under cutoff
    assert run("advisory", risk="physics")[0] is None                    # never the cheapest tier
    assert run("advisory", pick="medium", risk="physics")[0]["permissionDecision"] == "deny"
    out, row = run("active")
    assert out["permissionDecision"] == "allow" and out["updatedInput"]["subagent_type"] == "tw-worker-low"
    assert out["updatedInput"]["prompt"].startswith("TW-Role: worker") and row["action"] == "rewrite"
    out, row = run("active", guard="context-mode PreToolUse Agent hook is registered")
    assert out["permissionDecision"] == "deny" and row["action"] == "advise" and row["guard"].startswith("context-mode")
    out, row = run("active", flag=True)
    assert out["permissionDecision"] == "deny" and "lost race" in row["guard"]
    assert run("advisory", conf=0.1, explore=1.0)[0]["permissionDecisionReason"].count("exploration") == 1
    assert run("advisory", conf=0.1, explore=0.0)[0] is None
    assert run("advisory", pick="xhigh", conf=0.1, explore=1.0)[0] is None   # exploration only goes lower
    print("PASS act: shadow, advisory, override, cutoff, risk floor, active rewrite, guard/flag hold, exploration")
```

`HDR` in `test_tw_receipt.py` carries `TW-Risk: destructive`. The `risk=` parameter replaces it, so the
default case is `none`.

Check: `$PY test_tw_act.py` → `PASS act: …`. Then the full suite passes.

Commit: `git commit -m "thinker-worker: act modes (advisory deny with pick, active rewrite behind guard, override, risk floor, exploration) (Windows)" -- thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 6: SubagentStop — cost rows, lost-race tripwire, installer entry

Files: `scripts/tw.py`, `scripts/test_tw_stop.py` (new), `scripts/test_tw_install.py`.

Interfaces consumed: `advisory_flag`, route rows with `action`. Produced:
- `subagent_stop(home, harness, envelope)`
- rows `{"kind": "cost", "tool_use_id", "agent_type", "api_calls", "input_tokens",
  "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"}` and
  `{"kind": "lost-race", "tool_use_id"}`
- manifest key `"stop_hooks": {"claude": entry}`

```python
COST_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def subagent_stop(home: Path, harness: str, envelope: dict) -> None:
    """Never prints: SubagentStop output could block the child's stop."""
    try:
        session = session_value(envelope.get("session_id"))
        if activation(home, harness, session) is None:
            return
        path = Path(envelope["agent_transcript_path"])
        tool_use_id = read_json(path.with_suffix(".meta.json"), {}).get("toolUseId")
        usage, first_user = {}, None
        for line in path.read_text(encoding="utf-8").splitlines():
            obj = json.loads(line)
            msg = obj.get("message") or {}
            if first_user is None and obj.get("type") == "user":
                first_user = json.dumps(msg.get("content"), ensure_ascii=False)
            if obj.get("type") == "assistant" and msg.get("id") and msg.get("usage"):
                usage[msg["id"]] = msg["usage"]  # last row per message.id carries the final counts
        append_receipt(home, harness, session, {
            "kind": "cost", "at": now(), "harness": harness, "session_id": session, "tool_use_id": tool_use_id,
            "agent_type": envelope.get("agent_type"), "api_calls": len(usage),
            **{k: sum(u.get(k, 0) for u in usage.values()) for k in COST_KEYS}})
        rows = receipts_path(home, harness, session).read_text(encoding="utf-8").splitlines()
        rewritten = any(json.loads(x).get("kind") == "route" and json.loads(x).get("tool_use_id") == tool_use_id
                        and json.loads(x).get("action") == "rewrite" for x in rows if x.strip())
        if rewritten and first_user and "<context_window_protection>" in first_user:
            append_receipt(home, harness, session, {"kind": "lost-race", "at": now(), "harness": harness,
                                                    "session_id": session, "tool_use_id": tool_use_id})
            advisory_flag(home, harness, session).write_text(now(), encoding="utf-8")
    except Exception:
        return
```

In `hook`, before the tool-name filter:
`if envelope.get("hook_event_name") == "SubagentStop": subagent_stop(home, harness, envelope); return`.

Installer, with the same command for both events. `tw.py hook` reads the event from stdin:
- `hook_entry(…, event="PreToolUse")`: for `event == "SubagentStop"`, return `{"hooks": [handler]}` (no
  matcher). Otherwise return as today.
- `owned_entries(doc, event="PreToolUse")`, `add_entry(doc, entry, event="PreToolUse")` and
  `remove_entry(doc, entry, event="PreToolUse")` replace the literal `"PreToolUse"` with `event`.
  `remove_entry` deletes an emptied event list, and `hooks` when it is empty.
- `install`: when `"claude" in harnesses`, `stop = hook_entry("claude", home, python, portable, python_cmd, "SubagentStop")`.
  - If `owned_entries(doc, "SubagentStop") == [stop]`: nothing to add (adopted).
  - Elif it is non-empty: raise the same Conflict text as for PreToolUse.
  - Else: apply `add_entry(…, stop, "SubagentStop")` on top of the claude revision. If the PreToolUse
    entry was adopted but the stop entry is missing, create a revision.
  - Record `"stop_hooks": {"claude": stop}` in the manifest.
- `check`: when the manifest has `stop_hooks`, require `owned_entries(doc, "SubagentStop") == [manifest["stop_hooks"]["claude"]]`.
  Old manifests lack the key and are skipped.
- `uninstall`: wherever the claude PreToolUse entry is removed, also remove the stop entry if present.
  Where the PreToolUse entry is kept for another machine's ledger, keep the stop entry too.

`scripts/test_tw_stop.py`:

```python
"""SubagentStop: cost row = sum of the last usage row per message.id; lost-race row + advisory flag when a
rewritten child's prompt carries context-mode's block; never prints; installed alongside PreToolUse.
Run: python test_tw_stop.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import tw
from test_tw_hook import run_main
from test_tw_receipt import SESSION, receipts

TW = str(Path(__file__).with_name("tw.py"))


def transcript(folder, block):
    t = Path(folder) / "agent-a1.jsonl"
    prompt = "TW-Role: worker\n..." + ("\n<context_window_protection>x</context_window_protection>" if block else "")
    rows = [{"type": "user", "message": {"content": prompt}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 5}}},
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 40}}},
            {"type": "assistant", "message": {"id": "m2", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100,
                                                                    "output_tokens": 7}}}]
    t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (Path(folder) / "agent-a1.meta.json").write_text(json.dumps({"toolUseId": "toolu_x"}), encoding="utf-8")
    return str(t)


def stop(home, path):
    env = {"hook_event_name": "SubagentStop", "session_id": SESSION, "agent_type": "tw-worker-low",
           "agent_transcript_path": path}
    return run_main(["hook", "--home", home, "--harness", "claude", "--owner", tw.OWNER], json.dumps(env))


if __name__ == "__main__":
    for block, rewrite in ((False, True), (True, True), (True, False)):
        with tempfile.TemporaryDirectory() as home:
            run_main(["activate", "--home", home, "--harness", "claude", "--session", SESSION])
            tw.append_receipt(Path(home), "claude", SESSION, {"kind": "route", "tool_use_id": "toolu_x",
                                                              "action": "rewrite" if rewrite else None})
            code, out = stop(home, transcript(home, block))
            assert code == 0 and out == "", out
            rows = receipts(home, "claude")
            cost = [r for r in rows if r["kind"] == "cost"][0]
            assert (cost["api_calls"], cost["output_tokens"], cost["input_tokens"], cost["cache_read_input_tokens"]) == (2, 47, 3, 100), cost
            lost = [r for r in rows if r["kind"] == "lost-race"]
            flag = tw.advisory_flag(Path(home), "claude", SESSION).exists()
            assert (bool(lost), flag) == ((True, True) if block and rewrite else (False, False)), (block, rewrite)
    with tempfile.TemporaryDirectory() as tmp:            # installer writes and removes the SubagentStop entry
        home = Path(tmp)
        assert subprocess.run([sys.executable, TW, "install", "--home", tmp, "--python", sys.executable,
                               "--harness", "claude"], capture_output=True).returncode == 0
        hooks = tw.read_json(home / ".claude" / "settings.json", {})["hooks"]
        assert len(tw.owned_entries({"hooks": hooks}, "SubagentStop")) == 1
        assert subprocess.run([sys.executable, TW, "check", "--home", tmp], capture_output=True).returncode == 0
        assert subprocess.run([sys.executable, TW, "uninstall", "--home", tmp], capture_output=True).returncode == 0
        assert "hooks" not in tw.read_json(home / ".claude" / "settings.json", {})
    print("PASS stop: cost sums last row per message.id, tripwire only on rewrite+block, silent, installer round trip")
```

Check: `$PY test_tw_stop.py` → `PASS stop: …`. Then the full suite passes. `test_tw_install.py`,
`test_tw_portable.py` and `test_tw_ledger.py` must still pass unchanged apart from the earlier edits. If a
ledger test compares whole manifests or entries, update it to include `stop_hooks` and record that in the
progress file.

Commit: `git commit -m "thinker-worker: SubagentStop cost rows + lost-race tripwire; installer adds/removes the SubagentStop entry (Windows)" -- thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 7: promotion script

Files: `scripts/tw.py`, `scripts/test_tw_promote.py` (new).

Interfaces consumed: route, outcome and receipt rows. Produced: `promote(home, harness, cls=None) -> dict`
and the CLI `tw.py promote --harness <h> [--class <c>]`.

Rule (design §5): let k be the accepted count out of n router-arm dispatches. Then
`p_router ~ Beta(1+k, 1+n−k)`, and the same form holds for the coordinator arm. Promote when
`P(p_router − p_coord ≥ −0.15) > 0.8`, demote when it is `< 0.2`, and hold otherwise. The arms are:
- **Router arm:** labeled route rows that ran at a lower router tier. That is either an `active` rewrite
  whose `router_tier < coordinator_tier`, or a re-dispatch of an advised-lower ticket whose
  `coordinator_tier` equals the advised tier.
- **Coordinator arm:** labeled route rows with `action is None` whose ticket was never advised.

```python
def promote(home: Path, harness: str, cls: str | None = None, margin: float = 0.15,
            draws: int = 200_000, seed: int = 7) -> dict:
    rows = []
    for path in (state_root(home) / "receipts" / harness).glob("*.jsonl"):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    label = {r["tool_use_id"]: r["accepted"] for r in rows if r.get("kind") == "outcome"}
    routes = [r for r in rows if r.get("kind") == "route" and (cls is None or r.get("class") == cls)]
    advised = {r["ticket"]: r["router_tier"] for r in routes if r.get("action") == "advise"
               and TIERS.index(r["router_tier"]) < TIERS.index(r["coordinator_tier"])}
    router, coord = [], []
    for r in routes:
        ok = label.get(r.get("tool_use_id"))
        if ok is None:
            continue
        rewrite_lower = (r.get("action") == "rewrite"
                         and TIERS.index(r["router_tier"]) < TIERS.index(r["coordinator_tier"]))
        complied = r.get("action") is None and advised.get(r["ticket"]) == r["coordinator_tier"]
        if rewrite_lower or complied:
            router.append(ok)
        elif r.get("action") is None and r["ticket"] not in advised:
            coord.append(ok)
    k, n, kc, nc = sum(router), len(router), sum(coord), len(coord)
    rng = random.Random(seed)
    hit = sum(rng.betavariate(1 + k, 1 + n - k) - rng.betavariate(1 + kc, 1 + nc - kc) >= -margin
              for _ in range(draws))
    p = hit / draws
    return {"class": cls, "k_router": k, "n_router": n, "k_coord": kc, "n_coord": nc, "p": round(p, 3),
            "verdict": "promote" if p > 0.8 else "demote" if p < 0.2 else "hold"}
```

CLI: add `"promote"` with `--harness` and optional `--class`, then `print(json.dumps(promote(home, args.harness, args.cls)))`.
Use `dest="cls"` for `--class`.

`scripts/test_tw_promote.py`:

```python
"""Promotion rule reproduces the design's count table (coordinator arm 850/1000 ~ known 0.85).
Run: python test_tw_promote.py"""
import tempfile
from pathlib import Path

import tw

S = "55555555-6666-7777-8888-999999999999"


def verdict(k, n=10):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for i in range(n):  # router arm: active rewrites to a lower tier
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"r{i}", "ticket": f"t{i}",
                                                  "class": "C-coding", "action": "rewrite",
                                                  "router_tier": "low", "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"r{i}", "accepted": i < k})
        for i in range(1000):  # coordinator arm
            tw.append_receipt(home, "claude", S, {"kind": "route", "tool_use_id": f"c{i}", "ticket": f"u{i}",
                                                  "class": "C-coding", "action": None,
                                                  "router_tier": "high", "coordinator_tier": "high"})
            tw.append_receipt(home, "claude", S, {"kind": "outcome", "tool_use_id": f"c{i}", "accepted": i < 850})
        return tw.promote(home, "claude")


if __name__ == "__main__":
    got = {k: verdict(k)["verdict"] for k in (9, 8, 6, 5)}
    assert got == {9: "promote", 8: "hold", 6: "hold", 5: "demote"}, got
    print("PASS promotion rule matches design §5 table at n=10 (promote k>=9, demote k<=5)")
```

The expected values were checked on 2026-09-26 with the same sampler, seed 7 and 200k draws:
P = 0.888, 0.690, 0.212 and 0.079 for k = 9, 8, 6 and 5.

Check: `$PY test_tw_promote.py` → `PASS promotion rule …`.

Commit: `git commit -m "thinker-worker: promote (Beta posterior over receipts, hold band) (Windows)" -- thinker-worker/scripts thinker-worker/ROUTING-PROGRESS.md`

### Task 8: context-mode side (home repo) — heal removes the Agent hook, SubagentStart nudge, re-probe

Files:
- `C:\Users\Arian\.claude\hooks\plugin-patch-heal.mjs`
- `C:\Users\Arian\.claude\hooks\ctx-subagent-nudge.mjs` (new)
- `C:\Users\Arian\.claude\settings.json`
- `~/obsidian-vault/02-solutions/local-plugin-patches.md`

Destructive boundary: this task edits files in the context-mode plugin cache (`hooks.json` only, via the
heal) and the user's `settings.json`. Nothing else.

**Stop condition:** before editing `settings.json`, run `git -C ~ diff --stat -- .claude/settings.json`. If
it shows foreign uncommitted changes (it did on 2026-09-26), make the edit but **do not commit
settings.json**. Report the diff to Arian and let him commit it.

Steps:
1. **Heal.** In `plugin-patch-heal.mjs`:
   - add `writeFileSync` to the `node:fs` import;
   - insert this block immediately before the final `if (warnings.length || infos.length)`. First confirm
     that `infos` and `cfgDir` exist above it. Both were present on 2026-09-26.

```js
// context-mode Agent-hook removal (2026-09-26, effort-routing design §4.6). context-mode's
// PreToolUse:Agent hook returns a full updatedInput and races the thinker-worker router (last to finish
// wins). Remove that entry from every cached version's hooks.json. Takes effect NEXT session: plugin hooks
// load before SessionStart runs; tw.py's guard keeps the router advisory until then.
try {
  const cxBase = join(cfgDir(), "plugins", "cache", "context-mode", "context-mode");
  if (existsSync(cxBase)) {
    for (const v of readdirSync(cxBase)) {
      const hj = join(cxBase, v, "hooks", "hooks.json");
      if (!existsSync(hj)) continue;
      const doc = JSON.parse(readFileSync(hj, "utf8"));
      const pre = doc?.hooks?.PreToolUse;
      if (!Array.isArray(pre)) continue;
      const kept = pre.filter((e) => e?.matcher !== "Agent");
      if (kept.length === pre.length) continue;
      doc.hooks.PreToolUse = kept;
      writeFileSync(hj, JSON.stringify(doc, null, 2) + "\n");
      infos.push(`removed context-mode PreToolUse Agent hook from ${v} (effective next session)`);
    }
  }
} catch { /* fail-open */ }
```

2. **Nudge.** `ctx-subagent-nudge.mjs`:

```js
#!/usr/bin/env node
// SubagentStart: one-line pointer to context-mode's tools while the plugin is enabled. Replaces the
// plugin's ~1.2k-token Agent-prompt block (effort-routing design §4.6). Never fails the subagent.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
try {
  const dir = process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude");
  const s = JSON.parse(readFileSync(join(dir, "settings.json"), "utf8"));
  if (s.enabledPlugins?.["context-mode@context-mode"]) {
    const t = "mcp__plugin_context-mode_context-mode__";
    const additionalContext =
      `For URL fetches or large command/file output, context-mode tools keep raw bytes out of context. ` +
      `Load them with ToolSearch select:${t}ctx_fetch_and_index,${t}ctx_execute,${t}ctx_execute_file,${t}ctx_search ` +
      `and call them as tools, not as shell commands.`;
    process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: "SubagentStart", additionalContext } }));
  }
} catch { /* never block */ }
```

3. **Register.** Add to `settings.json` → `hooks.SubagentStart` (create the key if absent):
   `{"hooks": [{"type": "command", "command": "node \"$HOME/.claude/hooks/ctx-subagent-nudge.mjs\""}]}`.
   This is the same command form as the existing `plugin-patch-heal.mjs` entry.
4. **Apply now.** Run `node ~/.claude/hooks/plugin-patch-heal.mjs`. It is what every SessionStart runs.
   Expect `removed context-mode PreToolUse Agent hook from 1.0.169` in its output. Then run
   `grep -c '"matcher": "Agent"' ~/.claude/plugins/cache/context-mode/context-mode/*/hooks/hooks.json`,
   which should give 0 for every version. A second run prints no removal line.
5. **Nudge checks:**
   - `echo {} | node ~/.claude/hooks/ctx-subagent-nudge.mjs` prints JSON whose `additionalContext`
     contains `ToolSearch select:`.
   - With a temp `CLAUDE_CONFIG_DIR` holding `{"enabledPlugins": {"context-mode@context-mode": false}}`, it
     prints nothing.
6. **Re-probe** (`claude -p` runs load hooks fresh, so no restart of the executing session is needed; about
   $0.65 per run):

```bash
cd /c/Users/Arian/AppData/Local/Temp/tw-probe/order
for r in O7a O7b O7c; do
  cp settings-O4b.json settings-$r.json; bash run.sh $r; $PY inspect.py $r
  S=$($PY -c "import json; print(json.load(open('run-$r.json'))['session_id'])")
  grep -c "context_window_protection" /c/Users/Arian/.claude/projects/*/$S/subagents/agent-*.jsonl
  grep -c "ToolSearch select:mcp__plugin_context-mode" /c/Users/Arian/.claude/projects/*/$S/subagents/agent-*.jsonl
done
```

   Expected: 3/3 runs show `agentType: effortmining:miner-xhigh` and child `EFFORT=xhigh`. Each run's own
   child transcript, found by that run's `session_id` rather than by recency (other sessions dispatch
   concurrently), has a `context_window_protection` count of 0 and a nudge count of at least 1. O4b gave
   `low` and a cwp count of 2 before the patch, so this check can fail.
7. **Vault.** Read `~/obsidian-vault/CLAUDE.md` for the frontmatter schema, then add an entry to
   `02-solutions/local-plugin-patches.md`. It covers what is removed, why (§4.6 of the design doc), that the
   heal auto-reapplies it, that it takes effect the next session, and how to undo it (restore `hooks.json`
   from the plugin's marketplace clone).

Check: step 6 passes 3/3.

Commit (home repo):
`git -C ~ commit -m "hooks: heal removes context-mode's PreToolUse Agent hook; SubagentStart ctx nudge (effort-routing §4.6) (Windows)" -- .claude/hooks/plugin-patch-heal.mjs .claude/hooks/ctx-subagent-nudge.mjs`
Add `.claude/settings.json` only if the stop condition allows it. Commit the vault separately in its own
repo, by pathspec.

### Task 9: docs, reinstall, live checks

Files: `thinker-worker/SKILL.md`, `references/claude.md`, `references/codex.md`, `README.md`
(thinker-worker section, lines 41–58 on 2026-09-26).

Steps:
1. **Docs** (edit in place; delete every stale claim):
   - Claude briefs dispatch `tw-<role>-<tier>` with no `model` argument, and the tier is the effort.
   - Codex review and ideation need an explicit `reasoning_effort` of medium or above. There is no
     max/ultra. Terra is an allowed worker and is being phased out.
   - Activation is a single command with no role flags. `--store-bodies` is opt-in.
   - The header per-value cap is 1000. Receipts truncate at 256.
   - Routing modes (shadow, advisory, active) come from `routes.json` `router.classes`. `TW-Override:` keeps
     the coordinator's tier.
   - `tw.py route`, `tw.py promote` and `tw.py outcome` are described.
   - Delete the miner, `TW-Opus-Reason`, `--review/--luna/--sonnet/--ideation`, `thinker-worker-opus/sonnet/fable-review/dreamer`
     and "600 characters" text.
   - Check with `rg -n "thinker-worker-(opus|sonnet|fable-review|dreamer)|miner|TW-Opus-Reason|--sonnet|--luna|--review|--ideation|600 char" thinker-worker README.md`.
     It should report no hits, apart from `INSTALLER-PROGRESS.md` history.
2. **Reinstall** (needs Arian's OK at execution time: it rewrites `~/.claude/settings.json` and
   `~/.codex/hooks.json`). Run `tw.py machines` to read this machine's recorded flags, then run the printed
   `uninstall && install …` command. Codex then needs `/hooks` trust renewed for the changed definition.
3. **Live check** in a new Claude session:
   - activate the session;
   - dispatch a `tw-worker-low` child with a valid header and a trivial task;
   - the receipts must show `dispatch` → `route` (source `table`, mode `shadow`) → `cost`.
4. **Flush check** (design §4.4 step 4). After the child finishes, recount its transcript's last-row-per-id
   `output_tokens` and compare with the `cost` row. If they differ, SubagentStop fires before the final flush:
   record that in `ROUTING-PROGRESS.md` and stop for Arian's decision. Two options exist then:
   - recompute the cost at the next dispatch;
   - accept the drift.
5. The five-session HOLD stays in place. Lifting it waits for phase 2 backends and is Arian's call.

Check: step 3 shows the three row kinds, and step 4 matches or has been escalated.

Commit: `git commit -m "thinker-worker: docs for routes.json, tier agents, act modes, route/promote CLIs (Windows)" -- thinker-worker/SKILL.md thinker-worker/references README.md thinker-worker/ROUTING-PROGRESS.md`

## Execution

- **Order is strict:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9. T1–T7 all edit `tw.py`, so there are no
  parallel workers.
- **T8** touches a different repo and can run any time after T4. The guard must exist before the heal
  starts rewriting `hooks.json`.
- **Executor:** Opus, inline or as one Opus worker per task (Arian: Opus executes, Fable reviews). Each
  brief carries:
  - the write scope (the task's file list);
  - the destructive boundary (no edits outside the scope; no `rm -rf` on computed paths; kill only PIDs you
    launched);
  - the checkpoint (a `ROUTING-PROGRESS.md` line);
  - the stop condition: the task's check passes and is committed, or a test cannot be made to pass without
    changing the design, in which case stop and report.
- **Review:** after T3, after T6 and after T9, send the diff range to the Fable session for adversarial
  review before continuing.

## Not in this plan (phase 2, separate plan after an API survey)

- `tw.py serve` and the resident scorers `semif4b` (with AnyJev L0), `kev`, `eos` and `laya` as `BACKENDS`
  entries, plus the Stage-1 offline bench over effortmining grids that picks `backends[0]`. This needs each
  project's `choice`/logit API read first; this plan has not read them.
- The Codex v2 `task_name` join. First probe whether `task_name` reaches the hook unchanged, then have the
  `route` CLI write a route row keyed by ticket.
- Codex rewrite (design §6: waits on the Codex hook-rewrite probe).
- Lifting the five-session HOLD and re-baselining the real install against phase-2 backends.

## Self-review

1. **Coverage against the design:**
   - §4.1 components: all but `serve` (phase 2).
   - §4.2 routes: T1.
   - §4.3 route(): T3; backends beyond `table` are phase 2.
   - §4.4 steps 1–5: T1/T3/T5/T6, and `outcome` exists.
   - §4.5 fail modes: T3 budget and fallback.
   - §4.6 steps 1–5: T8 (patch, heal, nudge), T4 (guard) and T6 (tripwire). The step-5 measurement is the
     week-later re-run of the split, after T9; it is not a task.
   - §4.7 deletions: T1/T2.
   - §4.8 checks (1)–(7): T3 covers 1 and 3–4, T5 covers 5–6, T2 covers 7. Check (2), the stub-server
     logits, is phase 2.
   - §5 promotion: T7.
   - §7 rulings: T1 and T2.
   - Gaps: all listed under phase 2.
2. **Placeholder scan:** none. `…` inside `test_tw_header.py` edit descriptions stands for the existing
   surrounding expression, which is quoted in full in the file.
3. **Name and signature consistency:**
   - `Decision`, `route`, `act`, `advisory_flag`, `competing_agent_writer`, `claude_process_start`,
     `subagent_stop`, `promote`, `agent_name` and `AGENT_NAME` are used identically in every task that
     consumes them.
   - Route row keys (`coordinator_tier`, `router_tier`, `action`, `guard`, `ticket`, `class`) are written in
     T3/T5 and read in T6/T7.
