"""Mine pass/fail/unknown labels for past Claude Code subagent dispatches from hard transcript evidence.

Rule (Astra review, agreed by Arian): only hard evidence counts; missing evidence is `unknown`.
  pass: a check tied to the child's artifact ran after the child's last write (child side) or after the
        child's result (parent side), and its output shows success.
  fail: the last such check failed; a parent check on the artifact failed and the parent then edited the
        child's files; or a near-identical brief was re-dispatched after a completed result.
  unknown: everything else, with a category (usage-limit, api-error, cancelled, no-result, no-check, ...).

    python mine_labels.py [--n 150] [--out DIR]     # writes labels.jsonl + summary.json into DIR
    python mine_labels.py selftest

Transcripts are read-only; outputs carry private content and stay out of git.
"""
from __future__ import annotations
import argparse, collections, difflib, glob, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "scripts")]
import tw                      # noqa: E402  cost_row(): join + effective child model
from score_briefs import tier_of   # noqa: E402

HOME = Path.home()
PARENTS = str(HOME / ".claude" / "projects" / "*" / "*.jsonl")
OUT = Path(r"C:\Users\Arian\Code\skills\scratchpad\labels")

CHECK_CMD = re.compile(r"pytest|unittest|\btest_\w*\.py|\w+_test\.py|selftest|self-test|runtests|npm (?:run )?test"
                       r"|cargo test|Pkg\.test|\bverify\w*\.(?:py|sh)|\bcheck\w*\.(?:py|sh)|\bgates?\w*\.py", re.I)
GENERIC_RUNNER = re.compile(r"pytest|unittest|npm (?:run )?test|cargo test|Pkg\.test", re.I)
# markers are line-anchored (runner summaries, [PASS]/[FAIL] probe lines) so prose like "(FAIL at 2 %)" is not one
OK_OUT = re.compile(r"\b[1-9]\d* passed\b|(?-i:^OK\b|^OK \(|^\s*\[?PASS(?:ED)?\b|\bALL PASS\b|\bSELFTEST PASS\b)"
                    r"|selftest ok|all tests pass|All checks passed", re.I | re.M)
ENV_OUT = re.compile(r"ModuleNotFoundError|No module named|command not found|is not recognized as")
NOT_RUN = re.compile(r"(?:cat|grep|rg|sed|awk|head|tail|ls|wc|git|echo|printf|cp|mv|rm|diff|find|sha256sum|type|tee|less|stat|file)\b")
BLOCKED = re.compile(r"hook error|Blocked by security policy|permission to use|was blocked", re.I)
CODE_EXT = (".py", ".jl", ".js", ".mjs", ".ts", ".sh", ".ps1", ".rs", ".c", ".cpp", ".h", ".tex")
SCRATCH = re.compile(r"[\\/](?:Temp|tmp|scratchpad)[\\/]", re.I)
BAD_OUT = re.compile(r"\b[1-9]\d* (?:failed|errors?)\b|^FAILED\b|^\s*\[?FAIL(?:ED)?\b|^\S*\bFAIL:|^Traceback \(most recent"
                     r"|^\w*Error\b", re.M)   # the harness's "Exit code N" prefix is is_error, judged in verdict()
MUTATE = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
OUTAGE = [("usage-limit", re.compile(r"hit your (?:monthly spend|session|weekly|usage) limit|extra usage|usage limit|rate limit", re.I)),
          ("model-error", re.compile(r"issue with the selected model", re.I)),
          ("api-error", re.compile(r"API Error|terminated early due to an API error|Connection closed", re.I)),
          ("cancelled", re.compile(r"stopped by user|didn't finish before the previous session ended|interrupted by user"
                                   r"|\[Request interrupted", re.I)),
          ("permission-denied", re.compile(r"permission.{0,40}(?:denied|rejected)|user (?:denied|rejected|doesn't want)", re.I))]
HUMAN_SKIP = ("<task-notification", "<command-", "<local-command", "<system-reminder", "Caveat:", "[Request interrupted")
NEAR_DUP = 0.9
STOP_RX = re.compile(r"stop(?:ped)? (?:condition|rule)s?|hit the stop|stopped before|stopping (?:here|per)"
                     r"|waiting (?:for|on) (?:the )?(?:\w+ )?(?:background|subagents?|agents?|runs?)", re.I)  # halted or mid-flight
GENERIC_NAME = re.compile(r"(README|CHECKPOINT|PILOT|NOTES?|summary|report|results?|scratchpad|docs|tests?|scripts?)\b", re.I)
FIX_BRIEF = re.compile(r"\b(?:fix|apply|address|correct|repair)\w*\b[^.\n]{0,80}?\b(?:review|findings?|defects?|bugs?|errors?|mistakes?)\b"
                       r"|\b(?:review|findings?|defects?|bugs?)\b[^.\n]{0,80}?\b(?:fix|address|correct|repair)\w*\b"
                       r"|\bper (?:\w+ )?review\b|\breview to act on\b", re.I)


def rows_of(path):
    """(1-based line number, row) for each parseable JSONL line; line numbers are the audit anchors."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                out.append((n, d))
    return out


def blocks(d):
    c = (d.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return ""


def is_human(d):
    if d.get("type") != "user" or d.get("isMeta") or d.get("toolUseResult") is not None:
        return False
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return False
        c = text_of(c)
    return isinstance(c, str) and bool(c.strip()) and not c.lstrip().startswith(HUMAN_SKIP)


def family(agent_type):
    a = (agent_type or "general-purpose").split(":")[-1]
    return re.sub(r"-(low|medium|high|xhigh|max)$", "", a)


def header(prompt, key):
    m = re.search(rf"^{key}:\s*(.+)$", prompt or "", re.M)
    return m.group(1).strip() if m else None


def verdict(out, is_error, single=True):
    """The LAST pass/fail marker in the output decides (a summary line follows any logged traceback or [FAIL]
    probe). A non-zero exit is bad only when it cannot come from something else: no ok marker after the last bad
    one, and either a bad marker or a command that is a single check segment (a chained `ls`/`grep` exit is not)."""
    marks = [(m.start(), "ok") for m in OK_OUT.finditer(out)] + [(m.start(), "bad") for m in BAD_OUT.finditer(out)]
    last = max(marks)[1] if marks else None
    if last == "ok":   # "1 failed, 8 passed": a count of failures on the deciding summary line overrides it
        i = max(marks)[0]
        line = out[out.rfind("\n", 0, i) + 1: (out.find("\n", i) + 1 or len(out) + 1) - 1]
        last = "bad" if re.search(r"\b[1-9]\d* (?:failed|errors?)\b", line) else "ok"
    if is_error:
        last = "ambiguous" if last == "ok" or (last is None and not single) else "bad"
    if last == "bad" and ENV_OUT.search(out):   # missing module/tool: an environment stop, not a capability signal
        return "env"
    return last or "ambiguous"


def checks(rows, lo=0, hi=None):
    """Check-like shell runs in rows[lo:hi]: dicts with line, command, ok/bad verdict, output head/tail."""
    res = {}
    for n, d in rows[lo:hi]:
        for b in blocks(d):
            if b.get("type") == "tool_result" and b.get("tool_use_id") in res:
                out = text_of(b.get("content"))
                r = res[b["tool_use_id"]]
                if BLOCKED.search(out[:300]) and b.get("is_error"):   # a hook/permission block is not a check result
                    res.pop(b["tool_use_id"]); continue
                r.update(result_line=n, is_error=bool(b.get("is_error")), verdict=verdict(out, b.get("is_error"), single=len(re.split(r"&&|\|\||[;|\n]", r["command"])) == 1),
                         out_head=out[:240], out_tail=out[-240:] if len(out) > 240 else "")
            if b.get("type") == "tool_use" and b.get("name") in ("Bash", "PowerShell"):
                cmd = (b.get("input") or {}).get("command") or ""
                if check_segs(cmd):
                    res[b["id"]] = {"line": n, "command": cmd[:2000], "check": check_segs(cmd)[:400], "verdict": "no-result"}
    return list(res.values())


def writes(rows, lo=0, hi=None):
    """[(line, file_path)] for Edit/Write-family tool uses in rows[lo:hi]."""
    return [(n, (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path") or "")
            for n, d in rows[lo:hi] for b in blocks(d) if b.get("type") == "tool_use" and b.get("name") in MUTATE]


def tokens_for(paths, deliverable):
    toks = {Path(p.replace("\\", "/")).name for p in paths if p and not SCRATCH.search(p)}
    toks |= {Path(t).name for t in re.findall(r"[\w./\\-]+\.\w{1,5}\b", deliverable or "")}
    return {t for t in toks if len(Path(t).stem) >= 4}


def check_segs(cmd):
    """Shell segments that are themselves checks; relevance is judged on these, not on a chained git commit."""
    return " ; ".join(s.strip() for s in re.split(r"&&|\|\||[;|\n]", cmd) if CHECK_CMD.search(s) and not NOT_RUN.match(s.strip())
                      and not s.strip().startswith(("-", "*", "#", "`", "'", '"', "<", ">", "Claude-Session")))


def relevant(cmd, toks, generic_ok):
    cmd = check_segs(cmd)
    hit = sorted(t for t in toks if t in cmd or Path(t).stem in cmd)
    if hit:
        return "names " + ",".join(hit[:3])
    return "generic runner after writes" if generic_ok and GENERIC_RUNNER.search(cmd) else None


def outage(text):
    for cat, rx in OUTAGE:
        if rx.search(text or ""):
            return cat
    return None


def dispatches():
    """Every top-level Agent tool_use joined to a subagents/*.meta.json by toolUseId."""
    metas = {}
    for mp in glob.glob(str(HOME / ".claude" / "projects" / "*" / "*" / "subagents" / "agent-*.meta.json")):
        try:
            m = json.loads(Path(mp).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if m.get("toolUseId"):
            metas[m["toolUseId"]] = (m, mp)
    out, n_agent = {}, 0
    for p in glob.glob(PARENTS):
        with open(p, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if '"Agent"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                for b in blocks(d):
                    if b.get("type") == "tool_use" and b.get("name") == "Agent":
                        n_agent += 1
                        if b["id"] not in metas:
                            continue
                        child = metas[b["id"]][1][: -len(".meta.json")] + ".jsonl"
                        prev = out.get(b["id"])   # the same tool_use recurs in replayed/forked transcripts
                        own = Path(p).stem in child   # prefer the parent whose session dir holds the child
                        if prev is None or (own and Path(prev["parent"]).stem not in child):
                            out[b["id"]] = {"id": b["id"], "parent": p, "line": n, "ts": d.get("timestamp"),
                                            "session": Path(p).stem, "project": Path(p).parent.name,
                                            "input": b.get("input") or {}, "meta": metas[b["id"]][0], "child": child}
    return list(out.values()), n_agent, len(metas)


def wrote(d):
    """Artifact tokens (file names and parent dir names) a dispatch's child wrote; cached on the dispatch dict."""
    if "wrote" not in d:
        c = Path(d["child"])
        d["wrote"] = {t for _, p in writes(rows_of(c)) if p for t in (Path(p.replace("\\", "/")).name,
                      Path(p.replace("\\", "/")).parent.name)} if c.exists() else set()
    return d["wrote"]


def label(disp, prow, sess_disps):
    """Label one dispatch. prow: parsed parent rows; sess_disps: all joinable dispatches of this session."""
    tid, inp = disp["id"], disp["input"]
    prompt = inp.get("prompt") or ""
    ev, flags = [], {}
    cost = tw.cost_row(HOME, "claude", disp["session"], tid) or {}
    agent_type = disp["meta"].get("agentType") or inp.get("subagent_type")
    rec = {"id": tid, "project": disp["project"], "session": disp["session"], "ts": disp["ts"],
           "parent": disp["parent"], "dispatch_line": disp["line"], "child": disp["child"],
           "agent_type": agent_type, "family": family(agent_type), "effort": tier_of(agent_type) or "unknown",
           "model": cost.get("model") or "unknown", "requested_model": inp.get("model"),
           "description": inp.get("description"), "tw_accept": header(prompt, "TW-Accept"),
           "tw_deliverable": header(prompt, "TW-Deliverable"), "prompt_chars": len(prompt)}

    # -- the child's result in the parent: sync tool_result, or background task-notifications
    idx = next(i for i, (n, _) in enumerate(prow) if n == disp["line"])
    results, agent_id = [], None  # (row index, status, text)
    for i in range(idx + 1, len(prow)):
        n, d = prow[i]
        for b in blocks(d):
            if b.get("type") == "tool_result" and b.get("tool_use_id") == tid:
                t = text_of(b.get("content"))
                if t.startswith("Async agent launched"):
                    m = re.search(r"agentId: (\w+)", t)
                    agent_id = m and m.group(1)
                else:
                    results.append((i, "error" if b.get("is_error") else "completed", t))
        if d.get("type") in ("user", "attachment"):   # notifications arrive as user rows or queued_command attachments
            t = text_of((d.get("message") or {}).get("content")) if d["type"] == "user" else \
                text_of((d.get("attachment") or {}).get("prompt") or (d.get("attachment") or {}).get("content"))
            if f"<tool-use-id>{tid}</tool-use-id>" in t:
                m = re.search(r"<status>(\w+)</status>", t)
                results.append((i, m.group(1) if m else "?", t))
    flags["n_results"] = len(results)
    flags["sendmessage_resumes"] = sum(1 for _, d in prow[idx + 1:] for b in blocks(d) if b.get("type") == "tool_use"
                                       and b.get("name") == "SendMessage" and agent_id and (b.get("input") or {}).get("to") == agent_id)
    child = Path(disp["child"])
    crow = rows_of(child) if child.exists() else []

    def done(lbl, cat):
        rec.update(label=lbl, category=cat, evidence=ev, flags=flags)
        return rec

    if not results:
        return done("unknown", "no-result")
    ri, status, rtext = results[-1]
    ev.append({"src": "parent-result", "file": disp["parent"], "line": prow[ri][0], "text": f"status={status}: " + rtext[:300]})
    synth = [text_of((d.get("message") or {}).get("content")) for _, d in crow
             if d.get("type") == "assistant" and (d.get("message") or {}).get("model") == "<synthetic>"]
    cat = outage(rtext if status != "completed" else "") or (outage(synth[-1]) if synth else None)
    if status in ("failed", "error", "killed", "stopped") or cat:
        return done("unknown", cat or f"status-{status}")

    # -- child side: checks after the last write
    cw = writes(crow)
    toks = tokens_for([p for _, p in cw], rec["tw_deliverable"])
    # ponytail: a later .md/.txt note (checkpoint, README) does not invalidate a code check
    last_w = max((n for n, p in cw if not p.lower().endswith((".md", ".txt"))), default=0)
    cchecks = [c for c in checks(crow) if c["line"] > last_w and c["verdict"] != "no-result"]
    for c in cchecks:
        c["why"] = relevant(c["command"], toks, generic_ok=any(p.lower().endswith(CODE_EXT) and not SCRATCH.search(p) for _, p in cw))
    flags["env_stopped_checks"] = sum(c["verdict"] == "env" for c in cchecks)
    # the LAST relevant run decides; if its output carries no marker (e.g. redirected to a file) there is no evidence
    cchecks = [c for c in cchecks if c["why"]]
    flags["brief_stop"] = bool(STOP_RX.search(rtext))
    flags["child_writes"] = len(cw)

    # -- parent side: window from the first completed result to the next human prompt (cap 400 rows)
    first_ok = next(i for i, s, _ in results if s == "completed")
    end = next((j for j in range(first_ok + 1, min(len(prow), first_ok + 400)) if is_human(prow[j][1])),
               min(len(prow), first_ok + 400))
    pchecks = [c for c in checks(prow, first_ok, end) if c["verdict"] in ("ok", "bad")]
    for c in pchecks:
        c["why"] = relevant(c["command"], toks, generic_ok=False)   # parent suites run for many reasons; require the child's file by name
    pchecks = [c for c in pchecks if c["why"]]
    child_files = {Path(p.replace("\\", "/")).name.lower() for _, p in cw if p}
    pfix = [(n, p) for n, p in writes(prow, first_ok, end) if Path(p.replace("\\", "/")).name.lower() in child_files]

    # -- re-dispatch of a near-identical brief after this one's completed result
    redo = None
    for o in sess_disps:
        op = o["input"].get("prompt") or ""
        if o["id"] != tid and o["line"] > prow[first_ok][0] and op and prompt:
            sm = difflib.SequenceMatcher(None, prompt[:3000], op[:3000], autojunk=False)
            same_deliv = rec["tw_deliverable"] is not None and header(op, "TW-Deliverable") == rec["tw_deliverable"]   # a templated brief for another batch is not a retry
            if sm.real_quick_ratio() >= NEAR_DUP and sm.quick_ratio() >= NEAR_DUP and (r := sm.ratio()) >= NEAR_DUP and (same_deliv or r >= 0.98):
                redo = (o, round(sm.ratio(), 3))
                break

    # -- a later "fix per review/finding" dispatch naming this child's artifact (file or its directory)
    # artifact tokens: file names (and dated result dirs) this child wrote; attribution needs this child to be the
    # latest writer of the token among children dispatched before the fixer
    art = {t for _, p in cw if p and not SCRATCH.search(p) for t in (Path(p.replace("\\", "/")).name, Path(p.replace("\\", "/")).parent.name)
           if len(Path(t).stem) >= 10 and not GENERIC_NAME.match(t) and (Path(t).suffix or re.search(r"\d{4}-\d{2}-\d{2}", t))}
    fixer = None
    if not redo and "review" not in rec["family"]:
        for o in sess_disps:
            op = o["input"].get("prompt") or ""
            if o["line"] > prow[first_ok][0] and FIX_BRIEF.search(op) and not re.search(r"review|ideation", family(o["meta"].get("agentType"))):
                later = set().union(*(wrote(x) for x in sess_disps if disp["line"] < x["line"] < o["line"]))
                hit = sorted(t for t in art - later if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", op))
                if hit:
                    fixer = (o, hit)
                    break

    def cev(src, f, c):
        ev.append({"src": src, "file": f, "line": c["line"], "result_line": c.get("result_line"), "why": c["why"],
                   "text": f"check$ {c['check']}\n->{c['out_head']}" + (f" ... {c['out_tail']}" if c["out_tail"] else "")})

    pbad = [c for c in pchecks if c["verdict"] == "bad"]
    if pbad and pfix and any(n > pbad[0]["result_line"] for n, _ in pfix):
        cev("parent-check-failed", disp["parent"], pbad[0])
        n, p = next((n, p) for n, p in pfix if n > pbad[0]["result_line"])
        ev.append({"src": "parent-edit-child-file", "file": disp["parent"], "line": n, "text": p})
        return done("fail", "parent-check-failed-then-fixed")
    if redo:
        o, r = redo
        ev.append({"src": "re-dispatch", "file": disp["parent"], "line": o["line"],
                   "text": f"near-identical brief (ratio {r}) re-dispatched as {o['id']} ({o['input'].get('description')})"})
        flags["redispatch"] = o["id"]   # ponytail: probes/replicates/retests-after-a-tool-fix look identical -> candidate
    if fixer:
        o, hit = fixer
        m = FIX_BRIEF.search(o["input"]["prompt"])
        ev.append({"src": "fix-dispatch", "file": disp["parent"], "line": o["line"],
                   "text": f"{o['id']} ({o['input'].get('description')}) names {','.join(hit[:3])}; brief says: {m.group(0)!r}"})
        # ponytail: attribution (latest writer of a shared file) and "substantive" are unverified -> candidate, not fail
        flags["fix_dispatch"] = o["id"]
    if cchecks and cchecks[-1]["verdict"] == "bad":
        cev("child-final-check", disp["child"], cchecks[-1])
        if flags["brief_stop"]:   # the child reports a brief-sanctioned stop: an honest halt, not a capability signal
            ev.append({"src": "child-report", "file": disp["parent"], "line": prow[ri][0], "text": STOP_RX.search(rtext).group(0)})
            return done("unknown", "brief-stop-condition")
        return done("fail", "child-final-check-failed")
    pok = [c for c in pchecks if c["verdict"] == "ok"]
    if pok and not pbad:
        cev("parent-post-check", disp["parent"], pok[0])
        return done("pass", "parent-post-check")
    if cchecks and cchecks[-1]["verdict"] == "ok" and not pbad:
        cev("child-final-check", disp["child"], cchecks[-1])
        return done("pass", "child-final-check")
    flags["parent_edited_child_files"] = len(pfix)
    if redo:
        return done("unknown", "candidate-fail:re-dispatch")
    if fixer:
        return done("unknown", "candidate-fail:fix-dispatch")
    if pbad:
        cev("parent-check-failed", disp["parent"], pbad[0])
        return done("unknown", "parent-check-failed-no-fix")
    denied = [t for _, d in crow for b in blocks(d) if b.get("type") == "tool_result" and b.get("is_error")
              for t in [text_of(b.get("content"))] if outage(t) == "permission-denied"]
    if denied:
        ev.append({"src": "child-permission", "file": disp["child"], "line": None, "text": denied[-1][:200]})
        return done("unknown", "permission-denied")
    return done("unknown", "no-check-readonly" if not cw else "no-check")


def accept_stats(recs):
    acc = [r["tw_accept"] for r in recs if r["tw_accept"]]
    named = re.compile(r"`[^`]+`|pytest|unittest|test_\w+|selftest|\bgrep\b|exit 0|exit code|python \S+|\.py\b|\bpasses?\b", re.I)
    return {"n": len(recs), "with_tw_accept": len(acc),
            "accept_names_command_or_test": sum(bool(named.search(a)) for a in acc),
            "accept_names_test_runner": sum(bool(re.search(r"pytest|unittest|test_\w+|selftest", a, re.I)) for a in acc)}


def frac(rs):
    c = collections.Counter(r["label"] for r in rs)
    return {k: c[k] for k in ("pass", "fail", "unknown")} | {"n": len(rs), "labeled_frac": round((c["pass"] + c["fail"]) / len(rs), 3)}


def main(n, out):
    allds, n_agent, n_meta = dispatches()
    allds.sort(key=lambda r: r["ts"] or "")
    pilot = allds[-n:]
    by_sess = collections.defaultdict(list)
    for d in allds:
        by_sess[d["parent"]].append(d)
    cache, recs = {}, []
    for d in pilot:
        if d["parent"] not in cache:
            cache = {d["parent"]: rows_of(d["parent"])}   # ponytail: one parent in memory at a time
        recs.append(label(d, cache[d["parent"]], by_sess[d["parent"]]))
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "labels.jsonl", "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    grp = lambda key: {k: frac([r for r in recs if key(r) == k]) for k in sorted({key(r) for r in recs}, key=str)}
    s = {"agent_tool_uses_top_level": n_agent, "meta_files": n_meta, "joinable_total": len(allds), "pilot_n": len(recs),
         "pilot_ts_range": [pilot[0]["ts"], pilot[-1]["ts"]] if pilot else None,
         "overall": frac(recs), "categories": dict(collections.Counter(f"{r['label']}:{r['category']}" for r in recs).most_common()),
         "by_model_effort": grp(lambda r: f"{r['model']}|{r['effort']}"), "by_family": grp(lambda r: r["family"]),
         "tw_accept": accept_stats(recs)}
    (out / "summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    print(json.dumps({k: s[k] for k in ("joinable_total", "pilot_n", "overall", "categories", "tw_accept")}, indent=1))


def selftest():
    assert family("effortmining:miner-high") == "miner" and family("tw-worker-medium") == "tw-worker" and family(None) == "general-purpose"
    assert OK_OUT.search("12 passed in 0.3s") and not OK_OUT.search("0 passed") and BAD_OUT.search("1 failed, 3 passed")
    assert not BAD_OUT.search("0 failed") and OK_OUT.search("selftest ok")
    assert verdict("Traceback (most recent call last)\n...\n12 passed in 1s", False) == "ok"
    assert verdict("[PASS] a\n[FAIL] b\n1 FAIL", False) == "bad" and verdict("12 passed", True) == "ambiguous"
    assert verdict("Exit code 1", True) == "bad" and verdict("Exit code 2\nls: cannot access", True, single=False) == "ambiguous"
    assert verdict("SELFTEST PASS\nself-check PASS: a 3 % denser arm (FAIL at the 2 % tolerance)", False) == "ok"
    assert verdict("E   ModuleNotFoundError: No module named 'qutip'\n1 error in 0.14s", False) == "env"
    assert verdict("x\n1 failed, 8 passed, 14 warnings in 7.82s", False) == "bad" and verdict("8 passed in 1s", False) == "ok"
    assert verdict("ok\nexit=0", False) == "ambiguous" and verdict("Ran 4 tests\n\nOK", False) == "ok"
    assert check_segs("cat tests/test_a.py") == "" and check_segs("python tests/test_a.py") == "python tests/test_a.py"
    assert check_segs('git commit -m "x\n- `test_a.py`: 4 tests pass" && pytest -q') == "pytest -q"
    assert outage("You've hit your monthly spend limit") == "usage-limit" and outage("all good") is None
    assert relevant("python -m pytest tests/test_tw.py", {"test_tw.py"}, False) == "names test_tw.py"
    assert relevant("pytest -q", set(), True) and relevant("pytest -q", set(), False) is None
    assert header("TW-Role: worker\nTW-Accept: tests pass\n", "TW-Accept") == "tests pass"
    assert is_human({"type": "user", "message": {"content": "fix it"}}) and not is_human({"type": "user", "message": {"content": "<task-notification>x"}})
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "selftest"])
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    selftest() if a.cmd == "selftest" else main(a.n, a.out)
