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

if __name__ == "__main__":
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
