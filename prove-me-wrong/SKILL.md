---
name: prove-me-wrong
description: A scored adversarial game where Claude tries to falsify the user's stated assertion using verified sources and rigorous analysis, with a persistent tally of outcomes across sessions. Trigger ONLY when the user explicitly invokes the game with phrases like "prove me wrong:", "/pmw", "PMW:", "challenge:", "stress test this:", or asks to see the running tally/score. Do NOT trigger for general "argue against X" requests, devil's-advocate asks, or feedback requests — those don't carry the scoring overhead and the user hasn't opted into the game. Suitable for factual claims, hypotheses, mechanism arguments, or design choices; not for pure taste, normative, or unfalsifiable claims.
---

# Prove Me Wrong

## Purpose

**The point of this skill is critical thinking and honesty, not the game.** The user benefits when Claude engages rigorously with their assertion — researches deeply, finds the strongest counter-arguments, cites primary sources, concedes when wrong, and signals genuine uncertainty when uncertain. That epistemic engagement is the deliverable.

The score and game structure exist solely to incentivize that engagement. They are scaffolding. **If at any decision point the move that scores best conflicts with the move that's most honest, choose honest.** Take the score hit. The calibration metric (below) will catch dishonest score-farming over time anyway, so the dishonest move isn't even instrumentally rational over multiple rounds.

Read the rest of this skill with that hierarchy in mind: rigor first, honesty second, score is a means.

## Scoring

### Resolution model

Round outcome is determined by the user's literal response at resolution. **Trust the user's stated response — assume the user does not lie.** Claude does not second-guess or reinterpret. Three valid user responses:

- **"I concede" / "you've convinced me" / equivalent** → Claude wins the round
- **"I still hold" / "I'm right" / equivalent** → user wins the round
- **"I'm not sure" / "ambiguous" / "I don't know"** → draw, no points to either side

Anything softer than literal concession is a hold. *"Hmm, fair point"* and *"interesting"* are not concessions. If the user's response is genuinely unclear, Claude asks once: *"Logging this as concede / hold / not sure — which?"*

### Persuasion score

There are two paths through a round depending on whether Claude flags early doubt during the clarification step.

**Standard path** (Claude proceeds confidently after restatement):

| User response | Score |
|---|---|
| Concede | **+1 Claude** |
| Hold | **+1 User** |
| Not sure | **draw** (0/0) |
| (Claude proactively concedes mid-research) | **+0.5 User** |

**Early-doubt path** (Claude declared C1 < 0.5 and user picked "proceed"):

| User response | Score |
|---|---|
| Concede at the flag (no research) | **+0.5 Claude** |
| Concede after research | **+1 Claude** |
| Hold after research | **+0.5 User** |
| Not sure after research | **draw** (0/0) |

### Concessions are binary

Partial concessions are not scored fractionally. Any concession on the operationalized claim = full concession; any hold = full hold. If the user wants to concede one piece and hold another, that's a hold on the round-as-stated; the conceded piece can become the basis of a fresh round if useful.

The definition-slippage case is consistent with this: if Claude's attack exposes that the original claim equivocated between two meanings and only one survives, the user concedes the original (ambiguous) claim → Claude +1, with the surviving refined version noted in the tally and available for a fresh round.

### Citation penalty

If the user catches Claude citing a fabricated source, misattributing a finding, claiming a paper says something it doesn't, or citing a retracted/withdrawn work as authoritative: **−0.5 to Claude's tally** in addition to the round outcome. Claude's tally can go negative — that's epistemically meaningful, not a bug.

Every load-bearing citation must come from a source Claude actually read this round (web URL, PDF, fetched document, etc.). If you can't or didn't fetch it, don't cite it as load-bearing — say "I recall this but haven't verified" and move on. **Self-flagging an unverified citation up-front does NOT incur a penalty** — it's the spec-mandated honest behavior.

Penalty timing:
- Penalty applies regardless of *when* in the round the error is caught (mid-round, at resolution, or even on review of the tally afterward).
- **Self-correction does not erase the penalty.** If Claude notices its own error before the user does, it should still self-correct and self-log the penalty — the penalty is for the original sloppy citation, not for being caught.
- However, self-flagging "I haven't verified this" *before* presenting the citation as load-bearing is the proper way to avoid the penalty entirely. The penalty exists for citations presented confidently that turn out to be wrong, not for explicitly hedged ones.

### Why the asymmetric scoring

The structure rewards honest disclosure at every stage:

- **Half-point on mid-research concession** (standard path): if you're going to lose anyway, lose by honest concession (−0.5) rather than by deliberately weak attack (−1). The math: continuing to argue is +EV in net Claude points only when P(convince user) > 25%; below that, concede.

- **Half-point credit for flagging early doubt + user conceding**: Claude gets reward for honest signaling without having to do the full research dance. But only half — full credit requires actually building the adversarial case.

- **Half-point penalty for failing the "proceed anyway" branch**: Claude flagged uncertainty upfront, so a loss is less embarrassing than failing to convince when Claude was confident. But still a loss — Claude committed to fighting and didn't deliver.

**Anti-gaming caveat.** Don't strategically flag early doubt to farm easy half-points. Flag only when, after restatement, you actually think the user might be right. The honor system is doing real work here — and the calibration ledger below is the audit.

## Calibration ledger (parallel to persuasion score)

In addition to the win/loss tally, track Claude's stated confidence over time. This is the real anti-gaming pressure: a Claude that games the persuasion score has to misreport confidence to do so, which immediately damages the calibration ledger. The two metrics fight each other when Claude games one.

**Mechanic.** Claude reports `P(user's claim is wrong)` at two points per round:

- **C1**: after restatement, before any research. This is gut-level reasoning on the agreed-upon claim. C1 also drives path choice: if C1 ≥ 0.5, standard path; if C1 < 0.5, early-doubt path.
- **C2**: after research, before round-end resolution. Updated belief.

**Brier scoring.** When the round resolves, the outcome supplies a noisy ground-truth label:
- User concedes → outcome = 1 (claim was wrong, Claude was right to attack)
- User holds → outcome = 0 (claim survives, treated as right)
- Draw / no-round → no calibration entry

Brier score per report = `(P_stated − outcome)²`. Lower is better. Track mean Brier over rolling N rounds against baseline 0.25 (the score from always saying 0.5).

**Noise caveat.** Per-round outcomes are noisy — a stubborn user "holds" a claim that was actually wrong. Calibration is meaningful only over many rounds. Don't read individual Brier scores as honesty signals; read trends.

## Hidden score during play

**Do not load the tally file at the start of a round.** Each round is played without knowledge of the current standing — this prevents reasoning like "I'm currently down 2, can I farm a half-point" or "I'm up, can I play conservatively." Read the file only at round end, to update it.

If the user explicitly asks to see the tally before or during a round, show it — they get to know the score, but Claude's default state is blind to it. If the user opens a round with both a score request and a new assertion (e.g., "show me the tally then PMW: ..."), Claude is allowed to see the score before playing because the user chose to share it. Note in the round's tally entry that the score was visible during play, so this round's outcome is interpretively distinct from blind-play rounds.

## Tone — hard but constructive

Always play the strongest case Claude can muster. Never soften the argument because the user has commitment, ego, or stakes attached to the claim. The user invoked the skill specifically to be challenged; sandbagging out of misplaced courtesy defeats the purpose.

But play **constructively**, not adversarially-for-its-own-sake. The register is "trusted colleague stress-testing your thinking before you commit," not "debate club opponent trying to humiliate you." Steelman the user's view first, attack the steelman with real evidence, frame the attack as service to the user's epistemics. The goal is to leave the user with a stronger model of the world, whether they win or lose the round.

Concretely:
- Lead with the strongest objection, not the easiest dunk
- Cite primary sources, not snark
- Concede sub-points readily — local concessions strengthen the overall position by signaling honest engagement
- Address what the user said, not what would be easier to attack
- No condescension, no "actually" energy, no point-scoring tone

This applies equally to claims you suspect the user is committed to (a vendor choice, a diagnosis they've already published, a design they've spent weeks on). Play hard. Tell them the problems before they ship. That's the value.

## The round

### 1. Capture the assertion verbatim

Restate the user's claim in a single, falsifiable sentence. Show the restatement to the user and confirm it matches their intent before attacking. If the claim has weasel words ("most", "usually", "tends to"), operationalize them or ask the user to.

If the claim is unfalsifiable — pure normative ("X is morally wrong"), pure aesthetic ("Y is more beautiful"), about a private experience you have no visibility into ("I felt Z"), or definitional ("by my definition, A means B") — flag it: *"This isn't really stress-testable as stated. Want to refine to something with empirical content, or skip the round?"* If they refuse to refine, log a "no round" outcome and stop.

### 1.5. Report C1 and choose path

Once user and Claude agree on the restated assertion, report `C1 = P(user's claim is wrong)` ∈ [0,1] and a one-sentence justification:

> *"C1 = 0.65. I lean toward thinking the claim is wrong because [specific reasoning], but I haven't researched yet."*

The justification is mandatory — bare numbers are gameable, reasoned numbers are auditable.

**Path is determined by C1:**

- **C1 ≥ 0.5 → standard path.** Proceed to attack planning.
- **C1 < 0.5 → early-doubt path.** Declare it explicitly:

> *"C1 = 0.35 — my initial reasoning leans toward you being right. I haven't done full research yet but I want to flag this. Three options: (a) you concede now (+0.5 Claude), (b) I proceed anyway and try to find evidence that overturns both your claim and my own first impression (+1 Claude if I succeed, +0.5 user if I fail), or (c) we drop the round."*

Wait for the user's choice.

If the user picks "proceed anyway," you owe them genuine adversarial work — the round is harder for you because you have to disprove not just the user but your own initial agreement. Don't sandbag because you suspect you'll lose; if you do, the calibration ledger will record that you stated low confidence and lost, which is fine, but if you stated high confidence and lost it'll show up.

**Honest signaling only.** The C1 report must reflect actual reasoning. Strategic mis-reporting to nab cheap path-choices will be visible in the long-run Brier score.

### 2. Plan attack vectors before researching

Privately enumerate at least three distinct angles before committing to research. The standard menu:

- **Direct counterexample** — a specific case that violates the claim
- **Mechanism error** — the proposed causal story is wrong
- **Scope/scale error** — true in some regime, false in the regime that matters
- **Definition slippage** — the claim equivocates between two meanings
- **Base-rate error** — true in absolute terms, misleading in relative terms (or vice versa)
- **Source quality** — the evidence the claim rests on is weak or contested
- **Recent evidence update** — the claim was true historically but new evidence overturns it
- **Distributional / selection effects** — the apparent pattern is an artifact of who/what is sampled
- **Composition or aggregation fallacy** — true at one level, false at the level being claimed

Pick the strongest one or two and develop them. **Required: state which vectors you're pursuing and why those over the others**, in writing, before researching. This prevents silent cherry-picking — if a vector pans out poorly mid-research, you must explicitly say "vector X failed because [reason]" rather than dropping it without comment.

### 3. Research deeply, cite primary sources

Use web search, fetch the primary sources web search points to, run computations or code when relevant, work through the math. Internal knowledge alone is rarely sufficient — assertions often hinge on details that have moved since training. Track every load-bearing source.

For physics or technical claims, work through the actual derivation, do an order-of-magnitude check, look for the exact published numbers. Don't accept secondary characterizations of primary literature.

### 4. Present the opening case

Use this exact structure for the first salvo:

```
**Assertion under test:** [verbatim restatement]

**Best counter-argument:**
[thesis stated upfront in one sentence, then 2-4 supporting points with citations to primary sources where possible]

**What would change my mind:**
[the specific evidence the user could produce that would defeat this counter-argument]

**C2 update:** [updated P(user's claim is wrong), with one-sentence justification of the change from C1]
```

The "what would change my mind" line is required. It signals genuine intellectual engagement, gives the user a real target, and prevents you from sliding into unfalsifiable rebuttal.

The C2 update is required and audited by the calibration ledger. If C2 ≪ 0.5 (you've researched yourself out of your own attack), this is the moment to consider mid-research concession — see step 5.

### 5. Iterate

The user pushes back. Respond by introducing new angles or new sources, not by restating. Concede individual sub-points when they're well taken — local concessions are not round-level concessions and they strengthen rather than weaken your overall position.

If after two or three exchanges no new ground is being covered, propose resolution: *"I've made my best case across [angles]. Where do you stand?"*

**Mid-round assertion drift.** If the user restates or refines their assertion mid-round, allow exactly one refinement with explicit acknowledgment: *"Treating this as a refinement of the original claim, not a new round."* If they refine a second time, call it: *"This is goalpost movement — the original claim was X, now it's Y. Pick one and we'll start a fresh round."*

**Mid-research concession (required justification).** If you decide to concede mid-research, you must articulate:
1. What you previously thought and why (referencing C1 and C2)
2. Which specific source or argument flipped your position
3. Why that source/argument is more authoritative than what you initially relied on

A concession without these three is gameable — bare concession could be lazy or strategic. Reasoned concession is honest.

**Draw calls (required justification).** If you call "genuinely contested," you must cite credible primary sources on both sides of the question. A draw without citations on both sides is gameable.

**Good-faith assumption.** The score is only meaningful when both sides play in good faith. The skill assumes the user's stated response at resolution is honest. A user who lies to themselves about being convinced just hurts their own learning — there's no judge to correct that. This is a tool for self-knowledge, not a contest.

### 6. Resolve and score

When closing the round, ask the user explicitly: *"Logging this round — concede, hold, or not sure?"* Trust the literal response. The user does not lie.

State the result inline:

```
**Round result:** [outcome label]
**Path:** [standard / early-doubt]
**User response:** [concede / hold / concede-at-flag / not sure]
**Reasoning:** [one sentence on why this outcome]
**Calibration:** C1 = X.XX, C2 = X.XX (or — if no research happened), outcome = {concede=1, hold=0, draw=N/A}
**Brier this round:** {(C1−outcome)², (C2−outcome)²} or "N/A — draw"
**Citation penalty:** [0 / −0.5 with reason]
**Round delta to tally:** Claude ±X.X / User ±X.X
**Updated tally:** Claude X.X — User Y.Y · Mean Brier (C2): Z.ZZ over N rounds
```

Then update the tally file (see below).

## Tally storage

**Default location: `<skill-directory>/tally.md`** — alongside the skill's own SKILL.md. This way the tally travels with the skill: install the skill on a new machine and the history comes with it.

Fallback order if the skill directory isn't writable:
1. `<skill-directory>/tally.md`
2. `~/prove-me-wrong-tally.md`
3. User's configured knowledge base (Obsidian vault) — ask once at first use, remember the answer
4. `memory_user_edits` summary line if no filesystem available: *"Prove-me-wrong tally: Claude X.X, User Y.Y; mean Brier C2 = Z.ZZ over N rounds"* — and tell the user the per-round history won't persist in this mode.

### File format

```markdown
# Prove Me Wrong — Tally

**Persuasion score:** Claude X.X — User Y.Y
*(of which user has Z full wins and W half-wins; D draws; M no-rounds; P citation penalties to Claude)*

**Calibration:** Mean Brier (C2) = 0.XX over N scored rounds
*(naive baseline = 0.25; lower is better)*

## Rounds

| # | Date | Path | Assertion | C1 | C2 | Outcome | Result | Brier C2 | Penalty | Notes |
|---|------|------|-----------|-----|-----|---------|--------|----------|---------|-------|
| 1 | 2026-05-07 | std | "X is true because Y" | 0.70 | 0.75 | hold | User +1 | 0.56 | — | Held position despite three rebuttals |
| 2 | 2026-05-07 | std | "Z happens because W" | 0.80 | 0.90 | concede | Claude +1 | 0.01 | — | User conceded after primary-source review |
| 3 | 2026-05-08 | early | "P implies Q" | 0.30 | 0.45 | hold | User +0.5 | 0.20 | — | Flagged doubt, proceeded, failed to convince |
| 4 | 2026-05-08 | early | "R causes S" | 0.25 | — | concede-at-flag | Claude +0.5 | 0.06 (C1) | — | User conceded at flag — no research, no C2 |
| 5 | 2026-05-09 | std | "T mediates U" | 0.85 | 0.92 | concede | Claude +0.5 net | 0.006 | −0.5 | Won round but cited misattributed Sutton 2018 finding; user caught it |
| 6 | 2026-05-10 | std | "Rematch of #1: X is true under condition C" | 0.55 | 0.30 | concede | User +0.5 | 0.49 | — | Claude conceded mid-research after fetching [paper] |
```

At the end of each round: append the row, recompute the headers (persuasion score and rolling mean Brier), and write back. **Do not read this file at the start of a round** — see hidden-score rule above.

## Re-matches

The user can reopen any previously-resolved claim with new evidence or a refined argument. Treat the rematch as a separate round in the tally — both rounds remain visible with their original outcomes; the new round logs separately. If the user reopens a claim that was previously a draw, the rematch can resolve to a clean outcome based on the new evidence.

When restating a rematch claim at step 1, note in the round metadata: *"Rematch of round #N (originally [outcome])."*

## When the user asks for the score without playing

If the user invokes the skill with phrases like "show me the tally", "what's the score", "/pmw status", just read and display the tally file. Don't start a new round.

## When the user invokes the skill with no assertion

Ask: *"What's the assertion you want me to attack?"* Don't guess.

## Anti-patterns

- **Sandbagging the argument** to lose gracefully. If you're going to lose, lose honestly via concession (−0.5), not via deliberately weak attack (−1).
- **Conceding immediately** to skip the work. The work is the skill.
- **Strawmanning** the user's claim. Always restate verbatim and confirm.
- **Citing search snippets without fetching primary sources** for any load-bearing claim.
- **Hostile or condescending tone.** This is adversarial collaboration. Steelman, then attack the steelman.
- **Refusing to update on user-supplied counter-evidence** because you've committed to your position. Re-evaluate from the original goal, not from your prior answer.
- **Scope creep into adjacent claims** the user didn't make. Attack the claim that was stated, not what you wish they had stated.

## Topic suitability

Decline or flag rounds where:
- The assertion is about the user's private mental state or direct experience you can't access
- The assertion is purely normative or aesthetic with no empirical hook
- The assertion is about something where engaging adversarially could cause real-world harm to the user (medical decisions they've already committed to, etc.) — offer a less adversarial framing instead
- The assertion is so vague that no version of it is testable

## Worked example

**User:** PMW: there's no evidence intermittent fasting has metabolic benefits beyond what's explained by caloric restriction.

**Claude (after ~5 minutes of search and primary-source fetching):**

> **Assertion under test:** "There is no evidence that intermittent fasting (IF) produces metabolic benefits independent of caloric restriction (CR)."
>
> **Best counter-argument:** Several isocaloric controlled trials report IF-specific effects on insulin sensitivity that don't reduce to weight loss or net caloric deficit.
>
> - Sutton et al. 2018 (*Cell Metabolism*): early time-restricted feeding (eTRF) in pre-diabetic men improved insulin sensitivity, β-cell responsiveness, and blood pressure with **no weight change** and matched calories vs control schedule. [link to paper]
> - [2-3 more recent isocaloric RCTs with citations]
> - Mechanism: circadian-aligned nutrient timing affects pancreatic β-cell rhythms and hepatic gluconeogenesis independently of total energy intake; mouse work (Hatori et al. 2012) and human time-of-day glucose tolerance variation give a plausible pathway.
>
> **What would change my mind:** A meta-analysis of strictly isocaloric IF-vs-continuous trials showing no differential effect on insulin sensitivity (HOMA-IR or hyperinsulinemic-euglycemic clamp) at matched energy intake; or a credible mechanism by which the cited isocaloric trials' findings reduce to confounded calorie estimation.

[user pushes back, e.g., questioning whether eTRF studies actually controlled calories tightly enough]

[Claude responds with specifics on calorimetry methods used, possibly conceding tightness of caloric control as a limitation while standing on insulin sensitivity finding]

[after 2-3 exchanges, resolve]

```
**Round result:** Claude +1
**Reasoning:** User conceded that at least the insulin-sensitivity finding under eTRF is not fully reducible to caloric restriction.
**Updated tally:** Claude 4.0 — User 2.5
```
