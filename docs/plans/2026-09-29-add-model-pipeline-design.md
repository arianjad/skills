# thinker-worker: add/update/archive a model (design, 2026-09-29)

Scope: the Claude/Codex dispatch router in `thinker-worker/scripts/tw.py` only. kev/laya decision backends never
see the model (`ask_backends` sends header, brief, tier options); Hermes/Qwen GVS5H routing is untouched.

## Decisions (Arian, 2026-09-29)
- Per-model priors live in the shipped `routes.json` (`router.model_priors`); the local override file may also set
  them, and `routes.json` states that an override exists and what it may set.
- A superseded model stays admitted, loses default status; a model no longer offered is archived (`archived` block,
  dated), not deleted. `model set` on an archived model restores it.
- A script edits `routes.json` (validate-before-write, canonical format), not hand edits.
- Priors for a new model: Arian gives them, or a cited search (Sonnet leaf, facts only) → coordinator proposal → yes.

## Seams (approved 2026-09-29)
- S1 `tw.prior(routes, harness, role, cls, model)` + `tw.py route --model`: model_priors[model][cls] > model_priors[model]["*"] > router.priors, clamped to the model's tiers.
- S2 `tw.load_routes(path)`: rejects bad model_priors; override may set router.model_priors; the routes.json override note's key list equals `OVERRIDABLE`.
- S3 `tw.py models --harness h`: one JSON line per (role, model): tiers, priors with source (installed/override), default.
- S4 `tw.py model set|archive --routes <path>`: literal expected doc; set is idempotent; invalid request writes nothing.
- S5 shipped `routes.json` equals its canonical form.

## Progress
- [ ] S1/S2 model_priors + override
- [ ] S3 models listing
- [ ] S4/S5 set/archive + canonical format
- [ ] sentinel denied model in tests; docs point at `tw.py models`; `references/add-model.md`
- [ ] /simplify pass; upgrade; first real run (gpt-6.1-sol)
