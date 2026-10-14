# Anti-bloat auditor: two focused refinements

**Goal:** Make useful abstraction exceptions a user decision, and replace hash-based validation with checks of the actual conditions that matter, plus three small structure and wording fixes (section 3).

**Design:** User decisions in chat, 2026-10-14. The proposed replacement-cost criterion was rejected and will not be added.

**Scope:** This is a plan only. Leave the skill unchanged until implementation is requested. Preserve its existing audit categories, read-only discovery boundary, scientific correctness requirements, and unrelated wording.

## File map

- Modify on implementation: `anti-bloat-auditor/SKILL.md` — the category guidance and both standalone prompt templates must express the same decisions.
- Sync after validation: `C:/Users/Arian/.codex/skills/anti-bloat-auditor/SKILL.md` — the installed copy, after checking it has no independent edits. Do not change other installations or global configuration.
- This plan is the checkpoint; no helper scripts, frameworks, or new dependencies are needed.

## 1. Make useful abstraction exceptions a user decision

Update **Abstractions and configuration churn**, the **Read-only audit prompt**, and the Rule of Three paragraph in the **Implementation prompt**.

Keep the rule-of-three default. Replace the conflict between “candidates, not automatic deletion verdicts” and unconditional removal with this instruction:

> When an abstraction below the rule-of-three threshold has a demonstrated benefit or protects an existing requirement, provide the user with its source location, actual callers, purpose, concrete benefit, and simpler alternative. Explain what retaining or replacing it would change, give a recommendation, and ask for direction before changing that abstraction. Do not silently retain it as an exception or automatically delete it. Honor an already explicit user decision; continue unaffected authorized work.

In an audit, include the context and decision question in the report and stop without edits. In an implementation, leave the affected abstraction unchanged until the user answers. Do not turn every routine simplification into a permission request.

**Check:** Walk through two cases against both templates: a one-implementation Protocol with a demonstrated checking benefit must produce a contextual question; an unused forwarding factory with no demonstrated benefit remains an ordinary flattening candidate. Neither template may force deletion of the first case or silently grant it an exception.

## 2. Replace hash validation with meaningful direct checks

Update **Integrity and coordination ceremony** and both standalone prompt templates. Remove or narrow language that could preserve a hash-based validation gate merely by calling it provenance or recovery.

Use this instruction:

> For each hash-based check, identify the actual condition it is intended to establish. Replace the hash comparison with a direct check of that condition, using the relevant parameters, state, schema, content, or invariant. Report the concrete mismatch and expected versus observed values where applicable. Hash equality or inequality is not a substitute for that validation. Preserve the underlying records needed to perform and explain the check.

Make the replacement specific to the requirement rather than substituting another proxy such as modification time. Where the condition is byte-for-byte identity, compare the actual content; where it is restart compatibility, check the relevant state and parameter constraints. Do not invent which scientific changes are compatible: expose an unresolved requirement for a user decision.

Example to include briefly: a plot-color change should not fail a restart-compatibility check; a changed required state-array shape should report the actual shape mismatch. Do not prescribe a universal policy for timestep changes.

Audit hashes used for validation under this rule. Hashes used only as identifiers (commit SHAs, cache keys, names in a run manifest) are fine and not a finding. Any comparison of a hash against an expected value is validation, including warn-only comparisons that keep running: replace it with the direct check and drop the comparison (user decision, 2026-10-14). This distinction must not become an exemption for a hash that actually gates correctness or compatibility.

**Check:** Walk through the plot-color and incompatible-state-shape cases. The proposed direct check must accept the irrelevant change and detect the relevant mismatch without relying on a digest or mtime. Check that neither standalone prompt still permits a provenance label to excuse hash-based validation.

## 3. Smaller fixes from the Claude review

User approved these in chat, 2026-10-14. Wording and structure only; no new policy.

1. **One return item per category.** In the **Read-only audit prompt**, give each of the five categories its own numbered return item (integrity ceremony, hot loops, abstractions, O(N) scans, telemetry), keeping stack/data flow, literal schemas, and the deletion table as the other items. Telemetry must not sit only in the "Also report" line.
2. **Checkable wording.** Replace "unsolicited" (category 1 and the implementation prompt) with "not traceable to a documented requirement". Replace "the user's Rule of Three" with "the Rule of Three default"; this paragraph is also rewritten by section 1, so apply both together.
3. **Narrow the trigger.** In the frontmatter description, replace "optimize scientific and simulation loops" with audit phrasing such as "audit scientific and simulation hot loops for performance costs". The skill audits; it does not take over general optimization requests.

**Check:** `grep -n -i -E "unsolicited|user's rule|optimize" anti-bloat-auditor/SKILL.md` returns nothing (it matches lines 3, 34, 120, 122 before the edit). Count the read-only prompt's return items and confirm a one-to-one mapping onto the five categories.

## 4. Validate and synchronize the focused change

1. Read the complete edited skill and each prompt independently. Confirm the two decisions survive when either prompt is copied without the surrounding skill.
2. Run `python C:/Users/Arian/.codex/skills/.system/skill-creator/scripts/quick_validate.py anti-bloat-auditor` and `git diff --check -- anti-bloat-auditor/SKILL.md`. Both should pass; these are structural checks, not behavioral proof.
3. Inspect the final diff. Confirm no replacement-cost criterion, new dependencies, broad rewrite, or unrelated policy changes were introduced.
4. Recheck the installed copy against the pre-edit source. If it is unchanged, synchronize the approved skill and compare the resulting text directly. If it has independent edits, preserve them and resolve the discrepancy before overwriting.
5. Commit only the scoped repository change as `Refine anti-bloat audit decisions and direct validation`. Report the changed artifacts, checks, and limits. Do not push.

**Completion:** The category guidance and both prompts agree; useful abstraction exceptions ask for informed user direction; validation checks the actual conditions; the read-only prompt reports each category separately; the section 3 grep is empty; the rejected replacement-cost addition is absent; the installed copy matches the accepted source.
