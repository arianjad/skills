"""Guard admits effortmining miners for worker/leaf roles only; model checks still apply.
Run: python test_tw_miner.py"""
import tw

REC = {"review": True, "luna": False, "sonnet": True}
REVIEW_HDR = "TW-Authorization: t\nTW-Scope: t\n"


def admitted(st, model, role):
    hdr = REVIEW_HDR if role == "independent-review" else ""
    env = {"tool_input": {"subagent_type": st, "model": model, "prompt": f"TW-Role: {role}\n{hdr}TW-Class: T1-mechanical\nTW-Deliverable: d\nTW-Accept: a\nTW-Risk: none\nx"}}
    return tw.decide("claude", env, REC)[0]


CASES = [
    ("thinker-worker-opus", "opus", "worker", True),
    ("effortmining:miner-medium", "opus", "worker", True),
    ("effortmining:miner-xhigh", "claude-opus-5-5", "worker", True),
    ("miner-xhigh", "opus", "worker", False),  # bare name could be shadowed by a repo-local agent
    ("Effortmining:miner-low", "opus", "worker", False),
    ("effortmining:miner-low ", "opus", "worker", False),
    ("effortmining:miner-low", "sonnet", "leaf", True),
    ("effortmining:miner-low", "sonnet", "worker", False),  # worker model stays Opus
    ("thinker-worker-fable-review", "fable", "independent-review", True),
    ("effortmining:miner-high", "fable", "independent-review", False),  # reviews stay fable-review
    ("general-purpose", "opus", "worker", False),
    ("effortmining:miner-huge", "opus", "worker", False),
]

if __name__ == "__main__":
    bad = [c for c in CASES if admitted(*c[:3]) != c[3]]
    for c in bad:
        print("FAIL", c)
    assert not bad
    print(f"PASS {len(CASES)}")
