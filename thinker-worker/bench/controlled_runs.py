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

DATA = Path(__file__).resolve().parents[2] / "scratchpad" / "controlled" / "otb" / "otl_bench.jsonl"
OUT = Path(__file__).resolve().parents[2] / "scratchpad" / "controlled" / "runs"
SUFFIX = " Answer the final answer in \\boxed{}"  # OTB generate.py, verbatim
NO_TOOLS = "\n\nAnswer directly from reasoning. Do not use tools, run code, or read files."
SYSTEM = "You are a careful problem solver."  # ponytail: short fixed system prompt; the default one is ~tens of k tokens
TIMEOUT_S = 900


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


def extract(text: str, task: str) -> str:  # OTB evals/underthink_eval.py: first \boxed{, cut at first }
    try:
        text = text.split("\\boxed{")[1].split("}")[0]
    except Exception:
        pass
    if task == "ab":
        text = re.sub(r"[^#AB]", " ", text).replace("  ", " ")
    return text.replace("\\ ", " ").replace("\\ ", " ")


def score(row: dict, response: str) -> float:
    md = json.loads(row["metadata"])
    task = md["source_dataset"]
    entry = {**md, "answer": row["answer"], "metadata": md}
    return SCORERS[task](extract(response, task), entry)


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
    return [shutil.which("codex") or "codex", "exec", "-m", m, "-c", f"model_reasoning_effort={e}", "-s", "read-only",
            "--ephemeral", "--json", "--skip-git-repo-check", "-C", str(work), "-o", str(work / "last.md"), "-"]


def parse(h: str, stdout: str, work: Path | None) -> dict:
    """Answer text + usage. Claude: the single `--output-format json` result. Codex: `--json` events (tw.py's
    codex_evidence reads the same turn.completed usage; duplicated here because tw.py is under concurrent edit)."""
    if h == "claude":
        try:
            j = json.loads(stdout)
        except ValueError:
            return {"text": "", "parse_error": True}
        u = j.get("usage") or {}
        return {"text": j.get("result") or "", "is_error": j.get("is_error"), "cost_usd": j.get("total_cost_usd"),
                "num_turns": j.get("num_turns"), "model_usage": j.get("modelUsage"),
                **{k: u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                            "cache_read_input_tokens", "output_tokens")}}
    ev = {"text": "", "tool_events": 0, **{k: 0 for k in ("input_tokens", "cached_input_tokens", "output_tokens",
                                                          "reasoning_output_tokens")}}
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        t, item = row.get("type"), row.get("item") or {}
        if t == "turn.completed":
            for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                ev[k] += (row.get("usage") or {}).get(k) or 0
        elif t == "item.completed" and item.get("type") == "agent_message":
            ev["text"] = item.get("text") or ev["text"]
        elif t == "item.started" and item.get("type") not in (None, "agent_message", "reasoning"):
            ev["tool_events"] += 1  # a command or tool the no-tools line asked it not to use
    if not ev["text"] and work and (work / "last.md").exists():
        ev["text"] = (work / "last.md").read_text(encoding="utf-8", errors="replace")
    return ev


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
        label = "unknown" if s is None or rc not in (0,) else ("pass" if s == 1.0 else "fail")
        rec = {"item": iid, "pair": pair, "rep": r, "label": label, "score": s, "rc": rc, "wall_s": wall,
               "extracted": extract(ev.get("text", ""), iid.split(":")[0])[:200], "gold": row["answer"][:200],
               "raw": str(raw), **{k: v for k, v in ev.items() if k != "text"}}
        with res.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        shutil.rmtree(work, ignore_errors=True)
        print(f"{iid:28s} {pair:28s} r{r} {label:7s} score={s} wall={wall}s rc={rc}")


def selftest() -> None:
    """Each ported scorer passes the gold answer and fails a perturbed one; extraction follows OTB."""
    items = load_items(",".join(f"{t}:0" for t in sorted(SCORERS)), None, 0, 0)
    for iid, row in items:
        gold = row["answer"]
        assert score(row, f"work... \\boxed{{{gold}}}") == 1.0, (iid, gold)
        wrong = {"ab": "#A", "bitwise_arithmetic": "0x0" if gold != "0x0" else "0x1"}.get(iid.split(":")[0], gold + "9")
        assert score(row, f"\\boxed{{{wrong}}}") < 1.0, (iid, wrong)
    assert extract("x \\boxed{A# #B} y", "ab") == "A# #B"
    assert parse("claude", '{"result": "\\\\boxed{1}", "usage": {"output_tokens": 5}}', None)["output_tokens"] == 5
    ev = parse("codex", '{"type":"item.completed","item":{"type":"agent_message","text":"\\\\boxed{2}"}}\n'
                        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}', None)
    assert ev["text"] == "\\boxed{2}" and ev["input_tokens"] == 10, ev
    print(f"selftest ok ({len(items)} scorers, gold pass + perturbed fail)")


def reparse(out: Path) -> None:
    """Rebuild results.jsonl from raw/ (no spend), e.g. after a parser fix."""
    rows = [json.loads(l) for l in (out / "results.jsonl").open(encoding="utf-8")]
    items = {}
    for d in rows:
        t, i = d["item"].split(":")
        items[d["item"]] = load_items(f"{t}:{i}", None, 0, 0)[0][1]
    new = []
    for d in rows:
        h = d["pair"].split(":")[0]
        ev = parse(h, Path(d["raw"]).read_text(encoding="utf-8").split("\n--- stderr ---\n")[0], None)
        s = score(items[d["item"]], ev["text"]) if ev.get("text") else None
        d.update({k: v for k, v in ev.items() if k != "text"}, score=s,
                 extracted=extract(ev.get("text", ""), d["item"].split(":")[0])[:200],
                 label="unknown" if s is None or d["rc"] != 0 else ("pass" if s == 1.0 else "fail"))
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
