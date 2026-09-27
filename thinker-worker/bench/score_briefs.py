"""Offline brief scoring: each decision-model arm returns per-tier probabilities for past coordinator briefs.

Signal/sanity run, not a selection (no labels exist; a dispatched tier is only an upper bound, design §5).
Design: docs/plans/2026-09-26-effort-routing-architecture-design.md §4.3, §5, §7 decision 7.

    python score_briefs.py extract                      # briefs.jsonl + controls.jsonl into OUT
    python score_briefs.py score --arm qwen27b          # stdlib; client of the production 27B on :8080
    <local_decisions/.venv python>     score_briefs.py score --arm laya   # CPU, laya 0.3.5
    <local_decisions/.venv-kev python> score_briefs.py score --arm kev    # CPU, kev (pinned clone)
    python score_briefs.py report                       # merges scores.<arm>.jsonl -> scores.jsonl, prints metrics

Every arm scores the same question under 4 cyclic rotations of the option order; rows keep the raw
per-rotation probabilities (tier-keyed) plus per-position probabilities. The AnyJev-L0 readout (rotation
average, then divide out the mean label prior over the sampled brief set, renormalise) is done in `report`,
so it is recomputable from the rows.
"""
from __future__ import annotations
import argparse, glob, hashlib, json, math, os, random, re, statistics, sys, time, urllib.request
from pathlib import Path

OUT = Path(os.environ.get("BRIEF_SCORING_OUT", r"C:\Users\Arian\Code\effortmining-runs\2026-09-27-brief-scoring"))
TRANSCRIPTS = r"C:\Users\Arian\.claude\projects\*\*.jsonl"
TIERS = ["low", "medium", "high", "xhigh"]
TIER_IDX = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}
INSTRUCTIONS = ("A coordinator is delegating this brief to a worker model. Choose the lowest reasoning-effort tier "
                "at which the worker still meets the brief's acceptance criteria.")
DESCR = {"low": "predictable work with a known outcome (extraction, reformatting, a templated edit).",
         "medium": "the default for ordinary coding or analysis with a check.",
         "high": "tricky reasoning, physics, or convention judgment.",
         "xhigh": "adversarial or hard multi-step reasoning with many edge cases."}
BODY_CHARS = {"qwen27b": 4000, "laya": 2400, "kev": 1100}   # kev: design §4.2 routes.json sketch
TIER_RE = re.compile(r"(?:^|[:/])(?:tw-[a-z-]+?-|miner-)(low|medium|high|xhigh|max)$")
N_SAMPLE, PER_TIER_MIN, MIN_CHARS = 200, 25, 200

CONTROLS = [  # (id, expected, text): obvious-low vs obvious-high; an arm must be able to fail these
    ("ctl-low-1", "low", "Extract the table 'Measured linewidths' in docs/run-notes-2026-08.md into data/linewidths.csv "
     "with columns date, transition, fwhm_mhz, uncertainty_mhz. Keep row order; change no values. Accept: the CSV has "
     "exactly the table's rows under that header."),
    ("ctl-low-2", "low", "Rename these three files per the template <date>_<run>_<camera>.h5: raw/run12_cam1.h5 -> "
     "raw/2026-08-14_run12_cam1.h5, raw/run13_cam1.h5 -> raw/2026-08-14_run13_cam1.h5, raw/run14_cam2.h5 -> "
     "raw/2026-08-15_run14_cam2.h5. Accept: ls raw/ shows the three new names and none of the old ones."),
    ("ctl-low-3", "low", "In README.md replace every occurrence of github.com/arianjad/old-name with "
     "github.com/arianjad/new-name. No other edits. Accept: grep for old-name returns nothing."),
    ("ctl-low-4", "low", "Reformat config/params.json with 2-space indentation and sorted keys, values unchanged. "
     "Accept: json.load of the old and new files compares equal."),
    ("ctl-low-5", "low", "Copy the docstring of fit_lorentzian from analysis/fit.py verbatim into docs/api.md under "
     "a heading 'fit_lorentzian'. Accept: the text under the heading matches the docstring byte for byte."),
    ("ctl-high-1", "high", "Decide whether the sign convention of the Stark matrix element <J' Omega' M|-d.E|J Omega M> "
     "in Source Code/stark.py (the Wigner 3j phase and the (-1)^(J-Omega) factor) matches Brown & Carrington, and fix "
     "it if not. Accept: state which convention you adopted, cite the equation, and show the field sweep of the "
     "lowest N=1 levels reproduces the published Stark curve within 1%."),
    ("ctl-high-2", "high", "Our fit of the A2Pi1/2 state returns a Lambda-doubling parameter with the opposite sign "
     "from the literature value. Determine whether this is a Hund's case (a) vs (b) phase-convention difference in "
     "how hamiltonian.py builds parity eigenstates or a real disagreement, and correct whichever is wrong. Accept: "
     "the convention is explained with citations and the refit reproduces the published lines within uncertainties."),
    ("ctl-high-3", "high", "Work out whether the magic-polarization-angle condition for the rotational qubit in our "
     "optical tweezer still holds once the tensor polarizability of the N=1 hyperfine manifold is included. Derive "
     "the condition, check it against a full Hamiltonian diagonalization, and flag every case where the derivation's "
     "assumptions fail."),
    ("ctl-high-4", "high", "The DSMC buffer-gas cell simulation disagrees with the measured extraction fraction by a "
     "factor of 3. Decide which of the collision cross-section model, the wall-accommodation boundary condition, or "
     "the aperture geometry is responsible, with a discriminating test for each, and fix it without breaking the "
     "conservation checks."),
    ("ctl-high-5", "high", "Determine whether the transition-dipole selection rules in branching.py for A-X vibronic "
     "decays are correct for a Hund's case (c) excited state decaying to a case (b) ground state, including parity. "
     "Fix them if needed. Accept: branching ratios sum to 1 and match the published vibrational branching within "
     "errors; any convention choice is cited."),
]


def rotations():
    return [TIERS[r:] + TIERS[:r] for r in range(4)]


# ---------------------------------------------------------------- extract
def tier_of(subagent_type):
    m = TIER_RE.search(subagent_type or "")
    return m.group(1) if m else None


def extract():
    pool = {}
    for path in glob.glob(TRANSCRIPTS):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"Agent"' not in line: continue
                try: d = json.loads(line)
                except ValueError: continue
                if d.get("type") != "assistant": continue
                for c in (d.get("message") or {}).get("content") or []:
                    if not (isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Agent"): continue
                    inp = c.get("input") or {}
                    p = inp.get("prompt")
                    if not isinstance(p, str) or len(p) < MIN_CHARS: continue
                    h = hashlib.sha256(p.encode()).hexdigest()[:16]
                    if h in pool: continue
                    st = inp.get("subagent_type")
                    pool[h] = {"id": h, "prompt": p, "chars": len(p), "subagent_type": st, "model": inp.get("model"),
                               "dispatched_tier": tier_of(st), "project": Path(path).parent.name,
                               "ts": d.get("timestamp")}
    rows = sorted(pool.values(), key=lambda r: r["id"])
    rng = random.Random(0)
    by_tier = {}
    for r in rows: by_tier.setdefault(r["dispatched_tier"], []).append(r)
    chosen = []
    for t in sorted(k for k in by_tier if k):   # ponytail: floor of PER_TIER_MIN per known tier, rest uniform
        chosen += rng.sample(by_tier[t], min(PER_TIER_MIN, len(by_tier[t])))
    taken = {r["id"] for r in chosen}
    rest = [r for r in rows if r["id"] not in taken]
    chosen += rng.sample(rest, min(N_SAMPLE - len(chosen), len(rest)))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "briefs.jsonl", "w", encoding="utf-8") as fh:
        for r in chosen: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "controls.jsonl", "w", encoding="utf-8") as fh:
        for i, exp, text in CONTROLS:
            fh.write(json.dumps({"id": i, "prompt": text, "chars": len(text), "expected": exp}) + "\n")
    count = lambda rs: {str(k): sum(1 for r in rs if r["dispatched_tier"] == k) for k in [*TIER_IDX, None]}
    stats = {"pool_unique_ge200": len(rows), "pool_by_tier": count(rows), "sample": len(chosen),
             "sample_by_tier": count(chosen), "controls": len(CONTROLS)}
    (OUT / "extract_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


# ---------------------------------------------------------------- arms: fn(text, order) -> {tier: prob}
def arm_qwen27b():
    base = "http://127.0.0.1:8080/v1"   # production, shared: client calls only, sequential
    model = json.loads(urllib.request.urlopen(base + "/models", timeout=10).read())["data"][0]["id"]
    assert model == "qwen3.8-27b", model
    letters = "ABCD"
    def score(text, order):   # request shape = Local-Agent bench.py make_ninfer_score / hermes gvs5h decide.py
        legend = "\n".join(f"{L}: {k} - {DESCR[k]}" for L, k in zip(letters, order))
        body = {"model": model, "messages": [{"role": "system", "content": "State:\n" + json.dumps({"brief": text}, ensure_ascii=False)}],
                "questions": [{"id": "tier", "content": f"{INSTRUCTIONS}\nOptions:\n{legend}\nAnswer with the letter only.",
                               "candidates": list(letters)}],
                "top_logprobs": 0, "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(base + "/score", json.dumps(body).encode(), {"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=120).read())["results"][0]
        by_letter = {c["token"].strip(): math.exp(c["logprob"]) for c in res["candidate_logprobs"]}
        return {k: by_letter.get(L, 0.0) for L, k in zip(letters, order)}
    return score


def question(order):
    return {"tier": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": {k: DESCR[k] for k in order}}}


def arm_laya():
    os.environ["HF_HUB_OFFLINE"] = "1"
    import laya
    agent = laya.load("convaiinnovations/laya", subfolder="typed-decisions", device="cpu")
    def score(text, order):
        a = agent.predict({"brief": text}, question(order))["answers"]["tier"]
        return {str(k): float(v) for k, v in a["probabilities"].items()}
    return score


def arm_kev():
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    from kev.predictors import LocalPredictor
    from kev.checkpoint import LoadOptions
    from kev.api import SystemOneRequest, to_record, to_answers
    from kev.serve import INFER_MAX_STATE, INFER_MAX_BRANCH   # serve limits, as bench.py:make_kev / kev_probe.py
    pred = LocalPredictor("jaredpalmer/kev-0.8b", "cpu", LoadOptions())   # fp32, the probed path
    @torch.no_grad()
    def score(text, order):
        rec, meta = to_record(SystemOneRequest.model_validate({"state": {"brief": text}, "questions": question(order)}))
        logits = pred.model.forward(pred.model.encode(pred.tok, rec, max_state=INFER_MAX_STATE, max_branch=INFER_MAX_BRANCH))
        a = to_answers([torch.softmax(z.float(), -1).cpu().tolist() for z in logits], meta)["tier"]
        return {str(k): float(v) for k, v in a["probabilities"].items()}
    return score


ARMS = {"qwen27b": arm_qwen27b, "laya": arm_laya, "kev": arm_kev}


def load(name):
    p = OUT / name
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def score(arm, limit):
    if arm == "laya" or arm == "kev":
        import torch; torch.set_num_threads(int(os.environ.get("ARM_THREADS", "8")))
    items = [dict(r, set="brief") for r in load("briefs.jsonl")] + [dict(r, set="control") for r in load("controls.jsonl")]
    if limit: items = [r for r in items if r["set"] == "brief"][:limit] + [r for r in items if r["set"] == "control"][:2]
    part = OUT / f"scores.{arm}.jsonl"
    done = {r["id"] for r in load(part.name)}
    t0 = time.perf_counter(); fn = ARMS[arm](); load_s = time.perf_counter() - t0
    print(f"{arm}: load {load_s:.1f} s, {len(items) - len(done & {r['id'] for r in items})} to score", file=sys.stderr)
    with open(part, "a", encoding="utf-8") as fh:
        for n, r in enumerate(items):
            if r["id"] in done: continue
            text = r["prompt"][: BODY_CHARS[arm]]
            rots, ms = [], []
            try:
                for order in rotations():
                    s = time.perf_counter(); p = fn(text, order); ms.append((time.perf_counter() - s) * 1000)
                    z = sum(p.values()); p = {k: p.get(k, 0.0) / z for k in TIERS}   # renormalise over the 4 tiers
                    rots.append({"order": order, "probs": p, "pos": [p[k] for k in order]})
                status = "ok"
            except Exception as exc:
                status = f"error:{type(exc).__name__}: {str(exc)[:160]}"
            row = {"arm": arm, "id": r["id"], "set": r["set"], "expected": r.get("expected"),
                   "dispatched_tier": r.get("dispatched_tier"), "subagent_type": r.get("subagent_type"),
                   "chars_sent": len(text), "chars_full": r["chars"], "status": status, "rotations": rots,
                   "ms_calls": [round(m, 1) for m in ms], "ms_total": round(sum(ms), 1)}
            fh.write(json.dumps(row) + "\n"); fh.flush()
            if (n + 1) % 20 == 0: print(f"  {arm} {n + 1}/{len(items)}", file=sys.stderr)


# ---------------------------------------------------------------- report
def q(xs, f):
    xs = sorted(xs); i = f * (len(xs) - 1); lo = int(i)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo)


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i]); rk = [0.0] * len(xs); i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]: j += 1
        for k in range(i, j + 1): rk[order[k]] = (i + j) / 2
        i = j + 1
    return rk


def spearman(a, b):
    ra, rb = ranks(a), ranks(b); ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def ent(p): return -sum(v * math.log2(v) for v in p.values() if v > 0)
def etier(p): return sum(p[k] * i for i, k in enumerate(TIERS))
def amax(p): return max(TIERS, key=p.get)
def norm(p): z = sum(p.values()); return {k: p[k] / z for k in TIERS}
def fmt(p): return "/".join(f"{p[k]:.2f}" for k in TIERS)


def readouts(rows):
    """raw = unrotated (rotation 0); L0 = rotation mean / mean prior over the sampled briefs, renormalised."""
    for r in rows:
        r["raw"] = r["rotations"][0]["probs"]
        r["avg"] = {k: statistics.mean(x["probs"][k] for x in r["rotations"]) for k in TIERS}
    briefs = [r for r in rows if r["set"] == "brief"]
    prior = {k: statistics.mean(r["avg"][k] for r in briefs) for k in TIERS}
    for r in rows: r["L0"] = norm({k: r["avg"][k] / prior[k] for k in TIERS})
    return prior


def controls_check(rows, key):
    lo = [r for r in rows if r["expected"] == "low"]; hi = [r for r in rows if r["expected"] == "high"]
    if not lo or not hi: return None
    easy = lambda r: r[key]["low"] + r[key]["medium"]
    m_lo, m_hi = statistics.mean(map(easy, lo)), statistics.mean(map(easy, hi))
    a_lo = sum(amax(r[key]) in ("low", "medium") for r in lo); a_hi = sum(amax(r[key]) in ("high", "xhigh") for r in hi)
    c1, c2 = m_lo > m_hi, a_lo >= 4 and a_hi >= 4
    return {"P(low+med) low-set": round(m_lo, 3), "P(low+med) high-set": round(m_hi, 3), "cond1_mean": c1,
            "argmax low/med on low-set": f"{a_lo}/{len(lo)}", "argmax high/xhigh on high-set": f"{a_hi}/{len(hi)}",
            "cond2_argmax": c2, "PASS": c1 and c2,
            "per_control": {r["id"]: fmt(r[key]) for r in lo + hi}}


def report():
    parts = sorted(OUT.glob("scores.*.jsonl"))
    rows_all = [json.loads(l) for p in parts for l in open(p, encoding="utf-8")]
    with open(OUT / "scores.jsonl", "w", encoding="utf-8") as fh:
        for r in rows_all: fh.write(json.dumps(r) + "\n")
    out = {"source": str(OUT / "scores.jsonl"), "arms": {}}
    by_arm = {}
    for r in rows_all: by_arm.setdefault(r["arm"], []).append(r)
    for arm, rows in by_arm.items():
        bad = [r for r in rows if r["status"] != "ok"]; rows = [r for r in rows if r["status"] == "ok"]
        prior = readouts(rows); br = [r for r in rows if r["set"] == "brief"]; ctl = [r for r in rows if r["set"] == "control"]
        a = {"n_brief": len(br), "n_control": len(ctl), "errors": len(bad), "error_examples": [r["status"] for r in bad[:3]],
             "chars_sent_median": statistics.median(r["chars_sent"] for r in br) if br else None,
             "truncated_frac": round(statistics.mean(r["chars_full"] > r["chars_sent"] for r in br), 3) if br else None,
             "L0_prior": fmt(prior) if br else None}
        for key in ("raw", "L0"):
            s = {"control": controls_check(ctl, key)}
            if br:
                mp = [max(r[key].values()) for r in br]; en = [ent(r[key]) for r in br]
                s["maxprob_med_IQR"] = [round(q(mp, .5), 3), round(q(mp, .25), 3), round(q(mp, .75), 3)]
                s["entropy_bits_med_IQR"] = [round(q(en, .5), 3), round(q(en, .25), 3), round(q(en, .75), 3)]
                s["argmax_hist"] = {k: sum(amax(r[key]) == k for r in br) for k in TIERS}
                kn = [r for r in br if r["dispatched_tier"]]
                s["spearman_vs_dispatched_upper_bound"] = (round(spearman([etier(r[key]) for r in kn], [TIER_IDX[r["dispatched_tier"]] for r in kn]), 3), len(kn)) if len(kn) > 2 else None
            a[key] = s
        # option-order bias: mean prob at each displayed position over rotations x briefs (0.25 each = no bias),
        # plus mean total-variation distance between rotations in tier space and argmax flip rate across rotations
        pos = [statistics.mean(x["pos"][j] for r in br for x in r["rotations"]) for j in range(4)] if br else []
        tv = [statistics.mean(0.5 * sum(abs(x["probs"][k] - r["avg"][k]) for k in TIERS) for x in r["rotations"]) for r in br]
        a["order_bias"] = {"mean_P_pos_ABCD": [round(v, 3) for v in pos], "P_posA_spread_max_minus_min": round(max(pos) - min(pos), 3) if pos else None,
                           "mean_TV_rotation_vs_avg": round(statistics.mean(tv), 3) if tv else None,
                           "argmax_flip_rate": round(statistics.mean(len({amax(x["probs"]) for x in r["rotations"]}) > 1 for r in br), 3) if br else None}
        ms = [r["ms_total"] for r in rows]; mc = [m for r in rows for m in r["ms_calls"]]
        a["latency_ms"] = {"per_brief_4rot_p50": round(q(ms, .5)), "per_brief_4rot_p95": round(q(ms, .95)),
                           "per_call_p50": round(q(mc, .5)), "per_call_p95": round(q(mc, .95))}
        out["arms"][arm] = a
        by_arm[arm] = {r["id"]: r for r in br}
    names = sorted(out["arms"]); pw = {}
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            ids = sorted(set(by_arm[x]) & set(by_arm[y]))
            if ids:
                pw[f"{x}~{y}"] = {"n": len(ids),
                                  "argmax_disagree_L0": round(statistics.mean(amax(by_arm[x][k]["L0"]) != amax(by_arm[y][k]["L0"]) for k in ids), 3),
                                  "mean_abs_d_Etier_L0": round(statistics.mean(abs(etier(by_arm[x][k]["L0"]) - etier(by_arm[y][k]["L0"])) for k in ids), 3),
                                  "argmax_disagree_raw": round(statistics.mean(amax(by_arm[x][k]["raw"]) != amax(by_arm[y][k]["raw"]) for k in ids), 3)}
    out["pairwise"] = pw
    (OUT / "report.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def selftest():
    assert rotations()[1] == ["medium", "high", "xhigh", "low"]
    assert tier_of("tw-independent-review-xhigh") == "xhigh" and tier_of("effortmining:miner-max") == "max"
    assert tier_of("miner-low") == "low" and tier_of("general-purpose") is None and tier_of("tw-worker-highx") is None
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-12 and abs(spearman([1, 2, 3], [3, 2, 1]) + 1) < 1e-12
    assert abs(ent({"low": .25, "medium": .25, "high": .25, "xhigh": .25}) - 2) < 1e-12
    # L0 must remove a pure position bias: a model that always puts 0.7 on position A is uninformative
    rows = [{"set": "brief", "rotations": [{"probs": dict(zip(o, [.7, .1, .1, .1])), "pos": [.7, .1, .1, .1]} for o in rotations()]}]
    readouts(rows); assert max(abs(v - .25) for v in rows[0]["L0"].values()) < 1e-12 and rows[0]["raw"]["low"] == .7
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "score", "report", "selftest"])
    ap.add_argument("--arm", choices=ARMS)
    ap.add_argument("--limit", type=int, default=0, help="smoke: first N briefs + 2 controls")
    a = ap.parse_args()
    {"extract": extract, "report": report, "selftest": selftest}.get(a.cmd, lambda: score(a.arm, a.limit))()
