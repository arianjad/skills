"""class_count stops counting where the class's exploration schedule reaches its floor, and that cap leaves ε
unchanged. Run: python test_tw_class_count.py"""
import json
import tempfile
from pathlib import Path

import tw_core as tw


def routes(explore):
    doc = json.loads(json.dumps(tw.load_routes(tw.source_root() / "routes.json")))
    doc["router"]["classes"] = {"*": {"mode": "advisory", "explore": explore}}
    return doc


def check_cap():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for s in range(2):  # 10 counted rows over two sessions, plus rows that never count
            for i in range(5):
                tw.append_receipt(home, "claude", f"s{s}", {"kind": "route", "class": "C-coding", "pinned": False})
            tw.append_receipt(home, "claude", f"s{s}", {"kind": "route", "class": "C-coding", "pinned": True})
            tw.append_receipt(home, "claude", f"s{s}", {"kind": "route", "class": "T1-mechanical"})
            tw.append_receipt(home, "claude", f"s{s}", {"kind": "dispatch", "class": "C-coding"})
        sched = {"c": 1.0, "power": 1.0, "floor": 0.25}  # ε reaches its floor at t = 4
        n = tw.class_count(home, "claude", "C-coding", routes(sched))
        assert n == 4, n
        assert tw.epsilon(sched, 1 + n) == tw.epsilon(sched, 1 + 10) == 0.25
        assert tw.class_count(home, "claude", "C-coding", routes({**sched, "floor": 0.0})) == 10  # no floor: no cap
        assert tw.class_count(home, "claude", "C-coding", routes({**sched, "floor": 1e-9, "power": 1e-3})) == 10
        assert tw.class_count(home, "claude", "C-coding", routes({**sched, "power": 0.0})) == 0   # constant ε
        assert tw.class_count(home, "claude", "C-coding", routes(0.5)) == 0
        shipped = tw.load_routes(tw.source_root() / "routes.json")["router"]["classes"]["*"]["explore"]
        assert tw.epsilon(shipped, 10_000) == shipped["floor"], tw.epsilon(shipped, 10_000)  # the shipped cap
    print("PASS class_count: capped where ε hits its floor; uncapped without one")


if __name__ == "__main__":
    check_cap()
