# Anti-bloat auditor: refinements

**Status:** Implemented 2026-10-14 in `48d91bb`. The Codex install was already a junction to the repo source (created 14:31 the same day, outside the implementing session), so step 5.4 needed no change.

**Goal:** Make useful abstraction exceptions a user decision, and replace hash-based validation with checks of the actual conditions that matter, plus three small structure and wording fixes (section 3) and one consolidated decision table for user questions (section 4).

**Design:** User decisions in chat, 2026-10-14. The proposed replacement-cost criterion was rejected and will not be added.

**Scope:** Preserve its existing audit categories, read-only discovery boundary, scientific correctness requirements, and unrelated wording.

## File map

- Modify on implementation: `anti-bloat-auditor/SKILL.md` — the category guidance and both standalone prompt templates must express the same decisions.
- Link after validation: `C:/Users/Arian/.codex/skills/anti-bloat-auditor/` is currently a plain copy. Replace it with a junction to `skills_public/anti-bloat-auditor`, matching the other Codex skills, so Claude (already a symlink) and Codex both read the repo source (user decision, 2026-10-14). Do not change other installations or global configuration.
- This plan is the checkpoint; no helper scripts, frameworks, or new dependencies are needed.

## 1. Make useful abstraction exceptions a user decision

Update **Abstractions and configuration churn**, the **Read-only audit prompt**, and the Rule of Three paragraph in the **Implementation prompt**.

Keep the rule-of-three default. Count only implementations used on real code paths; test fakes, mocks, and stubs do not count (user decision, 2026-10-14). Replace the conflict between “candidates, not automatic deletion verdicts” and unconditional removal with this instruction:

> When an abstraction below the rule-of-three threshold has a demonstrated benefit or protects an existing requirement, provide the user with its source location, actual callers, purpose, concrete benefit, and simpler alternative. Explain what retaining or replacing it would change, give a recommendation, and ask for direction before changing that abstraction. Do not silently retain it as an exception or automatically delete it. Honor an already explicit user decision; continue unaffected authorized work.

In an audit, include the context and decision question in the report and stop without edits. In an implementation, leave the affected abstraction unchanged until the user answers. Do not turn every routine simplification into a permission request.

**Check:** Walk through two cases against both templates: a one-implementation Protocol with a demonstrated checking benefit must produce a contextual question; an unused forwarding factory with no demonstrated benefit remains an ordinary flattening candidate. Neither template may force deletion of the first case or silently grant it an exception.

## 2. Replace hash validation with meaningful direct checks

Update **Integrity and coordination ceremony** and both standalone prompt templates. Remove or narrow language that could preserve a hash-based validation gate merely by calling it provenance or recovery.

Use this instruction:

> For each hash-based check, the default is to delete it. When in doubt, remove the check rather than replace it. Replace it only when it guards a nameable defect that has occurred or would plausibly recur. In that case, identify the actual condition it is intended to establish and replace the hash comparison with a direct check of that condition, using the relevant parameters, state, schema, content, or invariant. Report the concrete mismatch and expected versus observed values where applicable. Hash equality or inequality is not a substitute for that validation. Preserve the underlying records needed to perform and explain the check.

Make the replacement specific to the requirement rather than substituting another proxy such as modification time. Where the condition is byte-for-byte identity, compare the actual content; where it is restart compatibility, check the relevant state and parameter constraints. Do not invent which scientific changes are compatible: expose an unresolved requirement for a user decision.

Example to include briefly: a plot-color change should not fail a restart-compatibility check; a changed required state-array shape should report the actual shape mismatch. Do not prescribe a universal policy for timestep changes.

Audit hashes used for validation under this rule. Hashes used only as identifiers (commit SHAs, cache keys, names in a run manifest) are fine and not a finding. Any comparison of a hash against an expected value is validation, including warn-only comparisons that keep running: replace it with the direct check and drop the comparison (user decision, 2026-10-14). This distinction must not become an exemption for a hash that actually gates correctness or compatibility.

**Check:** Walk through three cases. A receipt-hash gate with no nameable defect behind it must be deleted, not replaced. For a restart check that guards a real state-shape defect, walk through the plot-color and incompatible-state-shape cases. The proposed direct check must accept the irrelevant change and detect the relevant mismatch without relying on a digest or mtime. Check that neither standalone prompt still permits a provenance label to excuse hash-based validation.

## 3. Smaller fixes from the Claude review

User approved these in chat, 2026-10-14. Wording and structure only; no new policy.

1. **One return item per category.** In the **Read-only audit prompt**, give each of the five categories its own numbered return item (integrity ceremony, hot loops, abstractions, O(N) scans, telemetry), keeping stack/data flow, literal schemas, and the deletion table as the other items. Telemetry must not sit only in the "Also report" line.
2. **Checkable wording.** Replace "unsolicited" (category 1 and the implementation prompt) with "not traceable to a documented requirement". Replace "the user's Rule of Three" with "the Rule of Three default"; this paragraph is also rewritten by section 1, so apply both together.
3. **Narrow the trigger.** In the frontmatter description, replace "optimize scientific and simulation loops" with audit phrasing such as "audit scientific and simulation hot loops for performance costs". The skill audits; it does not take over general optimization requests.

**Check:** `grep -n -i -E "unsolicited|user's rule|optimize" anti-bloat-auditor/SKILL.md` returns nothing (it matches lines 3, 34, 120, 122 before the edit). Count the read-only prompt's return items and confirm a one-to-one mapping onto the five categories.

## 4. Consolidate questions into one decision table

User decision, 2026-10-14. Applies to the questions raised by sections 1 and 2. Add it to the skill body and to both standalone prompts.

> Never ask decision questions inline. Collect them into one **decision table** at the end of the report. Group findings that share a pattern and a recommendation into one row per class, for example "12 receipt-hash gates in producers, no nameable defect: delete all?". Split a class only where instances differ in what keeping them buys. Columns: pattern class | instances (count + source anchors) | what keeping it buys | recommendation | effect if left unanswered (left unchanged). In an implementation, finish all unaffected authorized work first, then present the table once.

No cap on the number of rows.

**Check:** Walk through a case with 12 identical receipt-hash gates plus 1 Protocol with a demonstrated checking benefit. It must produce a two-row table at the end of the report, with no inline questions. Confirm that both standalone prompts carry the instruction.

## 5. Validate and synchronize the focused change

1. Read the complete edited skill and each prompt independently. Confirm the two decisions survive when either prompt is copied without the surrounding skill.
2. Run `python C:/Users/Arian/.codex/skills/.system/skill-creator/scripts/quick_validate.py anti-bloat-auditor` and `git diff --check -- anti-bloat-auditor/SKILL.md`. Both should pass; these are structural checks, not behavioral proof.
3. Inspect the final diff. Confirm no replacement-cost criterion, new dependencies, broad rewrite, or unrelated policy changes were introduced.
4. Recheck the Codex copy against the pre-edit source (`git show HEAD:anti-bloat-auditor/SKILL.md`). If it is unchanged, remove the copy and create the junction (`mklink /J`, as `skills_private/install.sh` does); then confirm `~/.codex/skills/anti-bloat-auditor/SKILL.md` reads the edited source. If it has independent edits, preserve them and resolve the discrepancy before replacing it.
5. Commit only the scoped repository change as `Refine anti-bloat audit decisions and direct validation`. Report the changed artifacts, checks, and limits. Do not push.

**Completion:** The category guidance and both prompts agree; useful abstraction exceptions ask for informed user direction; validation checks the actual conditions; the read-only prompt reports each category separately; the section 3 grep is empty; decision questions arrive as one end-of-report table grouped per class; the rejected replacement-cost addition is absent; Codex and Claude both link to the repo source.

## 6. Round 2, from the first live audit (C2V-Molecules, 2026-10-14)

User decisions in chat, 2026-10-14, after reviewing that audit's skill feedback. Applied to the skill body and both prompts.

1. **Side bugs noticed while tracing.** One line each (anchor, verified or not), placed just before the decision table, with an explicit instruction not to search for bugs. The audit's correctness finds (the missing `labels` column, the non-independent `v1_reference`, assert-free tests) had no slot. They stay a side list so the auditor keeps its focus on bloat.
2. **Requirement provenance.** A documented requirement must trace to the user or an external contract; unattributed agent-written rationale is a candidate and, if sound, a decision-table row.
3. **Pinned values and tolerances.** Treated like hash comparisons: state the condition the check is trying to establish, check it directly, and expose tolerances without a stated derivation. Published or measured references stay legitimate.
4. **Cache reuse (option B).** Reuse is decided by comparing the stored inputs directly and reporting which differs; a hash may only name the cache file. Option A (hash as key, audit its coverage) was rejected.
5. **Static tools allowed** in read-only discovery (text search, git history, byte comparison, AST-only parsing); inapplicable categories get one `N/A` line.
6. **String/dict/enum dispatch** counts as an abstraction; benchmark-only strategies go to the decision table.

Not changed: the literal-schemas section stays a full inventory (narrowing would defer to docs that may be stale); no new "duplicated surfaces" category until a second audit shows it; per-claim absence queries stay.
