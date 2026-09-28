"""Controlled runs for two-sided (model, effort) labels on OptimalThinkingBench's UnderthinkingBench.

Plan: docs/plans/2026-09-28-controlled-runs-plan.md. Data: `otl_bench.jsonl` from HF `facebook/optimal_thinking_bench`
(CC BY-NC 4.0, sha 949ee6b5), kept untracked under scratchpad/controlled/otb/.

Each (item, pair, repeat) is one headless call: Claude via `claude -p`, Codex via `codex exec`. The prompt is OTB's
(`question + " Answer the final answer in \\boxed{}"`, RAM projects/otb/generate.py) plus a no-tools line. The answer is
scored by scorers ported verbatim from reasoning_gym v0.1.23 (the version OTB pins); label = pass iff score == 1.0.
Rows append to <out>/results.jsonl, keyed (item, pair, rep), so a rerun resumes. Raw stdout is kept per call, so
`--reparse` can rebuild rows without spending.

  python controlled_runs.py --selftest
  python controlled_runs.py --dry-run --items ab:0,bitwise_arithmetic:0 --pairs claude:sonnet:low,codex:gpt-6-sol:high
  python controlled_runs.py --items ... --pairs ... --k 1 --out <dir>
"""
from __future__ import annotations
import argparse, json, os, random, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tw  # noqa: E402  codex_cmd, codex_evidence (usage + executed identity from the rollout)

DATA = Path(__file__).resolve().parents[2] / "scratchpad" / "controlled" / "otb" / "otl_bench.jsonl"
OUT = Path(__file__).resolve().parents[2] / "scratchpad" / "controlled" / "runs"
SUFFIX = " Answer the final answer in \\boxed{}"  # OTB generate.py, verbatim
NO_TOOLS = "\n\nAnswer directly from reasoning. Do not use tools, run code, or read files."
SYSTEM = "You are a careful problem solver."  # ponytail: short fixed system prompt; the default one is ~tens of k tokens
TIMEOUT_S = 900
HOME = Path.home()  # Codex rollouts: HOME/.codex/sessions/**/rollout-*<thread_id>.jsonl


# ---- scorers: reasoning_gym v0.1.23, ported verbatim (reasoning_gym is not installed here) ----------------------------
def _default(answer, entry):  # ProceduralDataset.score_answer (dataset.py)
    oracle, reward = entry["answer"], 0.0
    if isinstance(answer, str) and len(answer) > 0:
        if answer == oracle:
            reward = 1.0
        elif oracle in answer:
            reward = len(oracle) / len(answer)
    return reward


def _ab(answer, entry):  # algorithmic/ab.py
    return 1.0 if answer == entry["answer"] else 0.0


def _bitwise(answer, entry):  # arithmetic/bitwise_arithmetic.py (verify_solution)
    if isinstance(answer, str):
        try:
            if eval(entry["metadata"]["problem"]) == int(str(answer), 0):  # problem is dataset-authored, as upstream
                return 1.0
        except Exception:
            pass
    return 0.0


def _extract_fraction(answer):  # arithmetic/fraction_simplification.py
    try:
        cleaned = answer.strip().strip("$").strip()
        m = re.match(r"\\(?:frac|dfrac)\s*{\s*(\d+)\s*}\s*{\s*(\d+)\s*}", cleaned, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
        if "/" in cleaned:
            n, d = map(str.strip, cleaned.split("/", 1))
            return int(n), int(d)
    except Exception:
        return None


def _fraction(answer, entry):
    md = entry["metadata"]
    try:
        n, d = _extract_fraction(answer)
        if n == md["simplified_numerator"] and d == md["simplified_denominator"]:
            return 1.0
        if n == md["numerator"] or d == md["denominator"]:
            return 0.1
        return 0.05 if len(answer.strip()) > 0 else 0.01
    except Exception:
        return 0.01


SCORERS = {"ab": _ab, "bitwise_arithmetic": _bitwise, "fraction_simplification": _fraction,
           "letter_counting": _default, "maze": _default}
# ponytail: 5 of 11 tasks; knight_swap, puzzle24, tsumego, advanced_geometry, quantum_lock, propositional_logic
# need their v0.1.23 scorers ported (sympy/numpy for two) before they can run.


def boxed(text: str) -> str | None:
    """Balanced contents of the first \\boxed{...}; None when absent or unclosed."""
    i = text.find("\\boxed{")
    depth, j = 0, i + len("\\boxed{")
    for k in range(j, len(text) if i >= 0 else j):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth < 0:
            return text[j:k]
    return None


def extract(text: str, task: str, norm: bool = False) -> str:  # OTB evals/underthink_eval.py: first \boxed{, cut at first }
    if norm:  # right answers OTB's extraction scores 0 (smoke 2026-09-28): `\#A\ B\#`, `\boxed{\mathrm{0xFD..}}`,
        # `\boxed{\frac{1}{2}}` (OTB cuts at the first `}`; the label takes the balanced box, Astra 2026-09-28 F8)
        text = re.sub(r"\\(?:mathrm|text|texttt|mathtt)\{([^{}]*)\}", r"\1", text.replace("\\#", "#"))
    try:
        b = boxed(text) if norm else None
        text = b if b is not None else text.split("\\boxed{")[1].split("}")[0]
    except Exception:
        pass
    if task == "ab":
        text = re.sub(r"[^#AB]", " ", text).replace("  ", " ")
    text = text.replace("\\ ", " ").replace("\\ ", " ")
    return " ".join(text.split()) if norm and task == "ab" else text


def score(row: dict, response: str, norm: bool = True) -> float:
    """norm=False is OTB's scoring verbatim; norm=True (used for the label) also undoes LaTeX `\\#` escapes."""
    md = json.loads(row["metadata"])
    task = md["source_dataset"]
    entry = {**md, "answer": row["answer"], "metadata": md}
    return SCORERS[task](extract(response, task, norm), entry)


# ---- items and pairs ------------------------------------------------------------------------------------------------
def load_items(spec: str | None, tasks: str | None, n: int, seed: int) -> list[tuple[str, dict]]:
    rows = [json.loads(l) for l in DATA.open(encoding="utf-8")]
    by = {}
    for r in rows:
        if r["subset"] == "underthinkingbench":
            md = json.loads(r["metadata"])
            by.setdefault(md["source_dataset"], []).append(r)
    if spec:  # task:index,task:index (index = position within the task's 50)
        pick = [(t, int(i)) for t, i in (s.split(":") for s in spec.split(","))]
    else:
        rng = random.Random(seed)
        pick = [(t, i) for t in (tasks.split(",") if tasks else sorted(SCORERS)) for i in sorted(rng.sample(range(len(by[t])), n))]
    for t, _ in pick:
        if t not in SCORERS:
            raise SystemExit(f"no ported scorer for {t}")
    return [(f"{t}:{i}", by[t][i]) for t, i in pick]


def parse_pairs(spec: str) -> list[tuple[str, str, str]]:
    out = []
    for p in spec.split(","):
        h, m, e = p.split(":")
        assert h in ("claude", "codex"), p
        out.append((h, m, e))
    return out


def command(h: str, m: str, e: str, work: Path) -> list[str]:
    if h == "claude":
        return [shutil.which("claude") or "claude", "-p", "--model", m, "--effort", e, "--output-format", "json",
                "--no-session-persistence", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
                "--disable-slash-commands", "--system-prompt", SYSTEM]
    # no --ephemeral: the rollout's turn_context is the only record of the executed model/effort (the stream has none)
    return tw.codex_cmd(shutil.which("codex") or "codex", m, e, work, work / "last.md", sandbox="read-only", search=False)


def parse(h: str, stdout: str, work: Path | None) -> dict:
    """Answer text + usage + executed identity. Claude: the single `--output-format json` result; executed model =
    modelUsage keys (effort is not reported: null). Codex: `--json` events; thread id, usage and executed model/effort
    (the rollout's last turn_context) from tw.codex_evidence; text, is_error and tool_events from the events here."""
    if h == "claude":
        try:
            j = json.loads(stdout)
        except ValueError:
            return {"text": "", "parse_error": True, "executed": {"model": None, "effort": None}}
        u = j.get("usage") or {}
        keys = sorted(j.get("modelUsage") or {})
        return {"text": j.get("result") or "", "is_error": j.get("is_error"), "cost_usd": j.get("total_cost_usd"),
                "num_turns": j.get("num_turns"), "model_usage": j.get("modelUsage"),
                # ponytail: tools are disabled, so a second turn or a permission denial is the only tool trace in -p json
                "tool_events": len(j.get("permission_denials") or []) + max(0, (j.get("num_turns") or 1) - 1),
                "executed": {"model": keys[0] if len(keys) == 1 else keys or None, "effort": None},
                **{k: u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                            "cache_read_input_tokens", "output_tokens")}}
    cx = tw.codex_evidence(HOME, stdout)
    ev = {"text": "", "tool_events": 0, "is_error": False, "thread_id": cx["thread_id"],
          "executed": {"model": cx["model"], "effort": cx["effort"]}, **{k: cx[k] for k in tw.CODEX_USAGE}}
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        t, item = row.get("type"), row.get("item") or {}
        if t in ("turn.failed", "error"):
            ev["is_error"] = True
        elif t == "item.completed" and item.get("type") == "agent_message":
            ev["text"] = item.get("text") or ev["text"]
        elif t == "item.started" and item.get("type") not in (None, "agent_message", "reasoning"):
            ev["tool_events"] += 1  # a command or tool the no-tools line asked it not to use
    if not ev["text"] and work and (work / "last.md").exists():
        ev["text"] = (work / "last.md").read_text(encoding="utf-8", errors="replace")
    return ev


def same_model(req: str, exe: str) -> bool:
    """Exact id, or a bare alias (`sonnet`) that is a dash-delimited token of the executed id (`claude-sonnet-5`)."""
    return exe == req or ("-" not in req and req in exe.split("-"))


def gate(rec: dict, m: str, e: str) -> tuple[str, str | None, str]:
    """(label, reason, model_label). label is pass/fail only when the answer was produced by the requested pair under
    the no-tools protocol; anything unverified is unknown with its reason (Astra 2026-09-28 F9, re-review F3, design D6).
    model_label keeps the model-only observation: pass/fail when the model is verified and the protocol clean."""
    ex = rec.get("executed") or {}
    models = [ex["model"]] if isinstance(ex.get("model"), str) else ex.get("model") or []
    reason = ("no-answer" if rec["score"] is None else f"rc={rec['rc']}" if rec["rc"] != 0
              else "is-error" if rec.get("is_error") else "tool-events" if rec.get("tool_events")
              else "executed-model-unknown" if not models
              else "executed-model-differs" if not all(same_model(m, x) for x in models)
              else "executed-effort-unknown" if ex.get("effort") is None
              else "executed-effort-differs" if ex["effort"] != e else None)
    graded = "pass" if rec["score"] == 1.0 else "fail"
    return ("unknown" if reason else graded), reason, \
        graded if reason in (None, "executed-effort-unknown", "executed-effort-differs") else "unknown"


def run(args) -> None:
    items, pairs = load_items(args.items, args.tasks, args.n, args.seed), parse_pairs(args.pairs)
    out = Path(args.out)
    plan = [(iid, row, p, r) for iid, row in items for p in pairs for r in range(args.k)]
    print(f"{len(items)} items x {len(pairs)} pairs x K={args.k} = {len(plan)} dispatches")
    if args.dry_run:
        for iid, row, (h, m, e), r in plan:
            print(f"  {iid} {h}:{m}:{e} rep{r}: {subprocess.list2cmdline(command(h, m, e, Path('<tmp>')))}  < prompt({len(row['question']) + len(SUFFIX) + len(NO_TOOLS)} chars)")
        return
    out.mkdir(parents=True, exist_ok=True)
    res = out / "results.jsonl"
    done = {(d["item"], d["pair"], d["rep"]) for d in map(json.loads, res.open(encoding="utf-8"))} if res.exists() else set()
    for iid, row, (h, m, e), r in plan:
        pair = f"{h}:{m}:{e}"
        if (iid, pair, r) in done:
            continue
        work = Path(tempfile.mkdtemp(prefix="ctrl-", dir=out))  # empty cwd: nothing for the model to read
        prompt = row["question"] + SUFFIX + NO_TOOLS
        t0 = time.time()
        try:
            p = subprocess.run(command(h, m, e, work), input=prompt.encode("utf-8"), capture_output=True,
                               timeout=TIMEOUT_S, cwd=work)
            stdout, rc = p.stdout.decode("utf-8", errors="replace"), p.returncode
            stderr = p.stderr.decode("utf-8", errors="replace")[-2000:]
        except subprocess.TimeoutExpired:
            stdout, rc, stderr = "", "timeout", ""
        wall = round(time.time() - t0, 1)
        raw = out / "raw" / f"{iid.replace(':', '_')}__{pair.replace(':', '_')}__r{r}.out"
        raw.parent.mkdir(exist_ok=True)
        raw.write_text(stdout + "\n--- stderr ---\n" + stderr, encoding="utf-8")
        ev = parse(h, stdout, work)
        s = score(row, ev["text"]) if ev.get("text") else None
        rec = {"item": iid, "pair": pair, "rep": r, "label": None, "reason": None, "score": s, "rc": rc, "wall_s": wall,
               "requested": {"model": m, "effort": e},
               "otb_score": score(row, ev["text"], norm=False) if ev.get("text") else None,
               "extracted": extract(ev.get("text", ""), iid.split(":")[0], True)[:200], "gold": row["answer"][:200],
               "raw": str(raw), **{k: v for k, v in ev.items() if k != "text"}}
        rec["label"], rec["reason"], rec["model_label"] = gate(rec, m, e)
        with res.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        shutil.rmtree(work, ignore_errors=True)
        print(f"{iid:28s} {pair:28s} r{r} {rec['label']:7s} score={s} wall={wall}s rc={rc} {rec['reason'] or ''}")


def selftest() -> None:
    """Each ported scorer passes the gold answer and fails a perturbed one; extraction follows OTB."""
    items = load_items(",".join(f"{t}:0" for t in sorted(SCORERS)), None, 0, 0)
    for iid, row in items:
        gold = row["answer"]
        assert score(row, f"work... \\boxed{{{gold}}}") == 1.0, (iid, gold)
        wrong = {"ab": "#A", "bitwise_arithmetic": "0x0" if gold != "0x0" else "0x1"}.get(iid.split(":")[0], gold + "9")
        assert score(row, f"\\boxed{{{wrong}}}") < 1.0, (iid, wrong)
    assert extract("x \\boxed{A# #B} y", "ab") == "A# #B"
    ab = items[0][1]  # the smoke's escaped-but-right answer: OTB verbatim fails it, the label passes it
    esc = "\\boxed{" + "\\ ".join(tok.replace("#", "\\#") for tok in ab["answer"].split()) + "}"
    assert score(ab, esc, norm=False) == 0.0 and score(ab, esc) == 1.0, extract(esc, "ab", True)
    bw = items[1][1]
    wrapped = "\\boxed{\\mathrm{" + bw["answer"].upper().replace("0X", "0x") + "}}"
    assert score(bw, wrapped, norm=False) == 0.0 and score(bw, wrapped) == 1.0, extract(wrapped, "bitwise_arithmetic", True)
    assert parse("claude", '{"result": "\\\\boxed{1}", "usage": {"output_tokens": 5}}', None)["output_tokens"] == 5
    ev = parse("codex", '{"type":"item.completed","item":{"type":"agent_message","text":"\\\\boxed{2}"}}\n'
                        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}', None)
    assert ev["text"] == "\\boxed{2}" and ev["input_tokens"] == 10, ev
    # F8 (Astra 2026-09-28): nested LaTeX inside \boxed{} is extracted with balanced braces for the label only
    half = {"answer": "1/2", "metadata": json.dumps({"source_dataset": "fraction_simplification", "numerator": 2,
            "denominator": 4, "simplified_numerator": 1, "simplified_denominator": 2})}
    assert score(half, r"\boxed{\frac{1}{2}}") == 1.0 and score(half, r"\boxed{\frac{1}{2}}", norm=False) == 0.01
    assert score(half, r"so $\boxed{\dfrac{1}{2}}$ {done}") == 1.0 and score(half, r"\boxed{\frac{2}{4}}") == 0.1
    assert extract(r"\boxed{\frac{1}{2}", "fraction_simplification", True) == r"\frac{1"   # unbalanced: OTB's cut
    fr = dict(items)["fraction_simplification:0"]
    n, d = fr["answer"].strip("$").split("/")
    assert score(fr, rf"\boxed{{\frac{{{n}}}{{{d}}}}}") == 1.0, fr["answer"]
    _selftest_run(dict(items)["ab:0"]["answer"])
    print(f"selftest ok ({len(items)} scorers, gold pass + perturbed fail; nested boxes; run/reparse label gates)")


def _selftest_run(gold: str) -> None:
    """F9 (Astra 2026-09-28): run() and reparse() with a mocked subprocess; no CLI or model is called."""
    from types import SimpleNamespace
    from unittest import mock
    global HOME
    ans = f"work \\boxed{{{gold}}}"
    claude = lambda model_usage, is_error=False, **kw: json.dumps({"result": ans, "is_error": is_error, "num_turns": 1,
                                                                   "modelUsage": model_usage, "usage": {}, **kw})
    tid = "01a0e6b0-0000-7000-8000-000000000001"
    codex = lambda *extra: "\n".join([json.dumps({"type": "thread.started", "thread_id": tid}), *extra,
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": ans}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}})])
    tool = json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "python -c 1"}})
    cases = [  # (pair, stdout, rollout turn_context or None, expected label)
        ("claude:sonnet:low", claude({"actually-another-model": {}}, True), None, "unknown"),   # Astra's counterexample
        ("claude:sonnet:low", claude({"actually-another-model": {}}), None, "unknown"),
        ("claude:sonnet:low", claude({"claude-sonnet-5": {}}, True), None, "unknown"),
        ("claude:sonnet:low", claude(None), None, "unknown"),
        ("claude:sonnet:low", claude({"claude-sonnet-5": {}}, num_turns=3), None, "unknown"),
        ("claude:sonnet:low", claude({"claude-sonnet-5": {}}), None, "unknown"),   # re-review F3: Claude effort is never reported
        ("codex:gpt-6-sol:low", codex(tool), {"model": "gpt-6-sol", "effort": "low"}, "unknown"),   # Astra's counterexample
        ("codex:gpt-6-sol:low", codex(), None, "unknown"),
        ("codex:gpt-6-sol:low", codex(), {"model": "gpt-5.6-terra", "effort": "low"}, "unknown"),
        ("codex:gpt-6-sol:low", codex(), {"model": "gpt-6-sol", "effort": "high"}, "unknown"),
        ("codex:gpt-6-sol:low", codex(), {"model": "gpt-6-sol"}, "unknown"),   # re-review F3: rollout names no effort
        ("codex:gpt-6-sol:low", codex(), {"model": "gpt-6-sol", "effort": "low"}, "pass")]
    reasons = ["is-error", "executed-model-differs", "is-error", "executed-model-unknown", "tool-events", "executed-effort-unknown",
               "tool-events", "executed-model-unknown", "executed-model-differs", "executed-effort-differs",
               "executed-effort-unknown", None]
    # model-only observation: kept when the model is verified and the protocol clean, whatever the effort evidence
    model_labels = ["unknown"] * 5 + ["pass"] + ["unknown"] * 3 + ["pass"] * 3
    old = HOME
    try:
        for (pair, stdout, ctx, want), why, mwant in zip(cases, reasons, model_labels, strict=True):
            with tempfile.TemporaryDirectory() as td:
                HOME = Path(td) / "home"
                if ctx:
                    ro = HOME / ".codex" / "sessions" / "2026" / "09" / "28" / f"rollout-2026-09-28T00-00-00-{tid}.jsonl"
                    ro.parent.mkdir(parents=True)
                    ro.write_text(json.dumps({"type": "turn_context", "payload": ctx}) + "\n", encoding="utf-8")
                fake = lambda *a, **k: SimpleNamespace(stdout=stdout.encode(), stderr=b"", returncode=0)
                args = SimpleNamespace(items="ab:0", tasks=None, n=0, seed=0, pairs=pair, k=1, out=str(Path(td) / "o"),
                                       dry_run=False)
                with mock.patch.object(subprocess, "run", fake):
                    run(args)
                res = Path(args.out) / "results.jsonl"
                row = json.loads(res.read_text(encoding="utf-8"))
                h, m, e = pair.split(":")
                assert row["label"] == want and row["requested"] == {"model": m, "effort": e} and "executed" in row, (pair, want, row)
                assert row["reason"] == why, (pair, why, row)
                assert row.get("model_label") == mwant, (pair, mwant, row)
                reparse(Path(args.out))
                again = json.loads(res.read_text(encoding="utf-8"))
                keys = ("label", "reason", "model_label", "executed")
                assert [again.get(k) for k in keys] == [row.get(k) for k in keys], (row, again)
    finally:
        HOME = old
    assert "--ephemeral" not in command("codex", "gpt-6-sol", "low", Path("w"))  # the rollout must exist to be read


def reparse(out: Path) -> None:
    """Rebuild results.jsonl from raw/ (no spend), e.g. after a parser fix."""
    rows = [json.loads(l) for l in (out / "results.jsonl").open(encoding="utf-8")]
    items = {}
    for d in rows:
        t, i = d["item"].split(":")
        items[d["item"]] = load_items(f"{t}:{i}", None, 0, 0)[0][1]
    new = []
    for d in rows:
        h, m, e = d["pair"].split(":")
        ev = parse(h, Path(d["raw"]).read_text(encoding="utf-8").split("\n--- stderr ---\n")[0], None)
        s = score(items[d["item"]], ev["text"]) if ev.get("text") else None
        d.update({k: v for k, v in ev.items() if k != "text"}, score=s, requested={"model": m, "effort": e},
                 otb_score=score(items[d["item"]], ev["text"], norm=False) if ev.get("text") else None,
                 extracted=extract(ev.get("text", ""), d["item"].split(":")[0], True)[:200])
        d["label"], d["reason"], d["model_label"] = gate(d, m, e)
        new.append(d)
    (out / "results.jsonl").write_text("".join(json.dumps(d) + "\n" for d in new), encoding="utf-8")
    print(f"reparsed {len(new)} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", help="task:index,... (index within the task's 50 rows)")
    ap.add_argument("--tasks", help="comma list; with --n and --seed samples n items per task")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pairs", default="claude:sonnet:low,codex:gpt-6-sol:high", help="harness:model:effort,...")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reparse", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.reparse:
        reparse(Path(a.out))
    else:
        run(a)
