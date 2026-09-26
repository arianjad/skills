"""Guard requires a routing header on every plaintext role; receipts turn it into labeled routing data.
Run: python test_tw_header.py"""
import tw

REC = {"review": True, "luna": False, "sonnet": True}
AUTH = "TW-Authorization: t\nTW-Scope: t\n"
HDR = ("TW-Class: T3-moderate-reasoning\nTW-Deliverable: patch to f.py\n"
       "TW-Accept: python test_f.py passes\nTW-Risk: none\n")


def verdict(brief, st="thinker-worker-opus", model="opus"):
    env = {"tool_input": {"subagent_type": st, "model": model, "prompt": brief}}
    return tw.decide("claude", env, REC)[:2]


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
    ("header over 600 chars", "TW-Role: worker\n" + HDR.replace("patch to f.py", "p" * 600) + "task", False),
    ("header after line 12", "TW-Role: worker\n" + "\n" * 12 + HDR + "task", False),
    ("review with auth + header", "TW-Role: independent-review\n" + AUTH + HDR + "task", True),
    ("review without header", "TW-Role: independent-review\n" + AUTH + "task", False),
]

if __name__ == "__main__":
    bad = []
    for name, brief, want in CASES:
        st, model = (("thinker-worker-fable-review", "fable") if "independent-review" in brief
                     else ("thinker-worker-opus", "opus"))
        ok, reason = verdict(brief, st, model)
        if ok != want:
            bad.append((name, want, reason))
    for b in bad:
        print("FAIL", b)
    assert not bad
    ok, reason = verdict("TW-Role: worker\ntask")
    assert "routing header" in reason, reason
    print(f"PASS {len(CASES)} header cases")
