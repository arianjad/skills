"""Guard requires a routing header on every plaintext role; receipts turn it into labeled routing data.
Run: python test_tw_header.py"""
import tw

R = tw.load_routes(tw.source_root() / "routes.json")  # explicit path: never a user override file
AUTH = "TW-Authorization: t\nTW-Scope: t\n"
HDR = ("TW-Class: T3-moderate-reasoning\nTW-Deliverable: patch to f.py\n"
       "TW-Accept: python test_f.py passes\nTW-Risk: none\n")


def verdict(brief, st="tw-worker-high"):
    env = {"tool_input": {"subagent_type": st, "prompt": brief}}
    return tw.decide("claude", env, R)[:2]


CASES = [
    ("valid header", "TW-Role: worker\n" + HDR + "task", True),
    ("no header", "TW-Role: worker\ntask", False),
    ("blank line before header", "TW-Role: worker\n\n" + HDR + "task", True),
    ("unknown class", "TW-Role: worker\n" + HDR.replace("T3-moderate-reasoning", "T9-easy") + "task", False),
    ("empty deliverable", "TW-Role: worker\n" + HDR.replace("patch to f.py", " ") + "task", False),
    ("missing accept", "TW-Role: worker\n" + HDR.replace("TW-Accept: python test_f.py passes\n", "") + "task", False),
    ("multi risk", "TW-Role: worker\n" + HDR.replace("TW-Risk: none", "TW-Risk: destructive, physics") + "task", True),
    ("unknown risk", "TW-Role: worker\n" + HDR.replace("TW-Risk: none", "TW-Risk: spicy") + "task", False),
    ("none mixed with a risk", "TW-Role: worker\n" + HDR.replace("TW-Risk: none", "TW-Risk: none, external") + "task", False),
    ("duplicate class", "TW-Role: worker\n" + HDR + "TW-Class: T1-mechanical\ntask", False),
    ("value of 1000 chars", "TW-Role: worker\n" + HDR.replace("patch to f.py", "p" * 1000) + "task", True),
    ("value over 1000 chars", "TW-Role: worker\n" + HDR.replace("patch to f.py", "p" * 1001) + "task", False),
    ("header after line 12", "TW-Role: worker\n" + "\n" * 12 + HDR + "task", False),
    ("review with auth + header", "TW-Role: independent-review\n" + AUTH + HDR + "task", True),
    ("review without header", "TW-Role: independent-review\n" + AUTH + "task", False),
]

# TW-Output: <path>, optional. Claude Code refuses a native subagent's Write to some basenames ("Subagents should
# return findings as text"); expected verdicts are the 2026-09-28 probe of real Writes by a native child (nsdpv
# session handoff 2026-09-28-tw-report-block-fix.md), not the regex. The Codex pipeline's children are unaffected.
REFUSED = ["REPORT.md", "report.md", "RePoRt.MD", "reports.md", "reporting.md", "summary.md", "summary-1.md",
           "findings.md", "analysis.md"]
WRITTEN = ["x-report.md", "report.txt", "report.md.txt", "worker-notes.md", "PROVENANCE-SPOTCHECK.md",
           "REPORT.md/worker-notes.md"]
out = lambda path: "TW-Role: worker\n" + HDR + f"TW-Output: C:/t/{path}\ntask"
CASES += [(f"TW-Output {p} (refused by Claude Code)", out(p), False) for p in REFUSED]
CASES += [(f"TW-Output {p} (written)", out(p), True) for p in WRITTEN]
CASES += [("TW-Output backslash path", out("x").replace("C:/t/x", "C:\\t\\findings.md"), False),
          ("empty TW-Output", out("x").replace("C:/t/x", " "), False),
          ("deliverable prose naming report.md, no TW-Output",
           "TW-Role: worker\n" + HDR.replace("patch to f.py", "a table summarizing /t/report.md") + "task", True)]

if __name__ == "__main__":
    ok, reason = verdict(out("REPORT.md"))
    assert not ok and "worker-notes.md" in reason and "TW-Output" in reason, reason     # the denial says how to fix it
    pipeline = {"tool_name": "codex", "tool_input": {"subagent_type": "tw-worker-high", "prompt": out("REPORT.md"),
                                                     "model": "gpt-6-sol"}}
    assert tw.decide("claude", pipeline, R)[0], "a tw.py codex child can write REPORT.md: stays admitted"
    bad = []
    for name, brief, want in CASES:
        st = "tw-independent-review-high" if "independent-review" in brief else "tw-worker-high"
        ok, reason = verdict(brief, st)
        if ok != want:
            bad.append((name, want, reason))
    for b in bad:
        print("FAIL", b)
    assert not bad
    ok, reason = verdict("TW-Role: worker\ntask")
    assert "routing header" in reason, reason
    print(f"PASS {len(CASES)} header cases")
