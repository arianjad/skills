"""Disabled decision models must not act through historical cache. No network/model calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tw
from test_tw_routes import narrowed

BRIEF = "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: artifact\nTW-Accept: checked\nTW-Risk: none\nDo the task"
FIELDS, _ = tw.header_fields(BRIEF)
BASE = tw.load_routes(tw.source_root() / "routes.json")


def config(enabled=False, explore=0, narrow=False):
    cfg = narrowed(BASE) if narrow else copy.deepcopy(BASE)   # narrowed: leaf low..high, so a cached xhigh clamps
    cfg["router"].update(backends=["kev"] if enabled else [],
                         classes={"*": {"mode": "active", "explore": explore}})
    return cfg


def old(source="bayes", **extra):
    return {"kind": "route", "ticket": tw.ticket(BRIEF)[0], "source": source,
            "router_tier": "xhigh", "probs": {"xhigh": 1.0}, "confidence": 1.0,
            **extra}


def run(cfg, prior, brief=BRIEF, role="worker"):
    fields, _ = tw.header_fields(brief)
    with patch.object(tw, "backend_fn", side_effect=AssertionError("inference forbidden")) as backend:
        answer = tw.route(cfg, "claude", role, fields, brief, "high", prior)
        backend.assert_not_called()
    return answer


class DisabledCache(unittest.TestCase):
    def test_disabled_bayes_and_repeated_cached_prefixes(self):
        for source in ["bayes", "cached:bayes", "cached:cached:bayes"]:
            with self.subTest(source=source):
                r = run(config(), old(source))
                self.assertEqual((r["source"], r["tier"]), ("coordinator", "high"))
                self.assertEqual(r["backends"], {})

    def test_model_derived_exploration(self):
        cases = [old("explore", gate="pass"),
                 old("cached:cached:explore", provenance="jev http://localhost"),
                 old("cached:explore", model_derived=True),
                 old("cached:explore")]  # orphan legacy cache has lost its origin: conservative bypass
        for row in cases:
            with self.subTest(row=row):
                self.assertEqual(run(config(), row)["source"], "coordinator")

    def test_exploration_only_cache_and_clamp(self):
        for row in [old("explore", gate="margin", provenance=None),
                    old("cached:cached:explore", model_derived=False)]:
            r = run(config(narrow=True), row, role="leaf")
            self.assertEqual((r["source"], r["tier"]), ("cached:explore", "high"))
            self.assertFalse(r["model_derived"])
            self.assertEqual(r["eps"], 0)
            r = run(config(), row, role="leaf")                  # the shipped leaf ladder has xhigh: kept
            self.assertEqual((r["source"], r["tier"]), ("cached:explore", "xhigh"))

    def test_enabled_cache_keeps_behavior(self):
        r = run(config(enabled=True, narrow=True), old("cached:cached:bayes"), role="leaf")
        self.assertEqual((r["source"], r["tier"]), ("cached:bayes", "high"))
        self.assertTrue(r["model_derived"])

    def test_disabled_restarts_normal_exploration_and_pin(self):
        r = run(config(explore=1), old())
        self.assertEqual((r["source"], r["tier"]), ("explore", "medium"))
        self.assertFalse(r["model_derived"])
        pinned = BRIEF.replace("Do the task", "TW-Pin: user high\nDo the task")
        r = run(config(explore=1), old(), pinned)
        self.assertEqual((r["source"], r["tier"], r["eps"]), ("coordinator", "high", 0))

    def test_lookup_skips_model_history_but_keeps_later_exploration(self):
        rows = [old(), old("cached:bayes"), old("explore", model_derived=False, router_tier="medium")]
        snapshot = copy.deepcopy(rows)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            p = tw.receipts_path(home, "claude", "session")
            p.parent.mkdir(parents=True)
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            before = p.read_bytes()
            for supplied in [None, rows]:
                chosen = tw.prior_route(home, "claude", "session", tw.ticket(BRIEF)[0],
                                        supplied, allow_models=False)
                self.assertEqual(chosen, rows[2])
            self.assertEqual(tw.prior_route(home, "claude", "session", tw.ticket(BRIEF)[0]), rows[0])
            self.assertEqual(p.read_bytes(), before)
        self.assertEqual(rows, snapshot)

    def test_fresh_provenance_survives_cache_and_receipt(self):
        cfg = config(enabled=True, explore=1)
        answer = {"tier": "xhigh", "probs": {"xhigh": 1.0}, "confidence": 1.0, "body_chars_sent": 1}
        with patch.object(tw, "ask_backends", return_value={"kev": answer}):
            r = tw.route(cfg, "claude", "worker", FIELDS, BRIEF, "high")
        self.assertEqual(r["source"], "explore")
        self.assertTrue(r["model_derived"])
        prior = {**r, "router_tier": r["tier"]}
        cached = run(cfg, prior)
        self.assertTrue(cached["model_derived"])
        self.assertEqual(run(config(), {**cached, "router_tier": cached["tier"]})["source"], "coordinator")

    def test_routed_persists_attribution_and_reuses_new_exploration(self):
        cfg = config(explore=1)
        d = tw.Decision(True, "ok", "worker", "opus", "high", FIELDS)
        envelope = {"tool_input": {"subagent_type": "tw-worker-high", "prompt": BRIEF}, "tool_use_id": "stub"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(tw, "competing_agent_writer", return_value=None), \
                patch.object(tw, "quota", return_value={}), \
                patch.object(tw, "backend_fn", side_effect=AssertionError("inference forbidden")) as backend:
            home = Path(tmp)
            _, first = tw.routed(home, "claude", "session", envelope, d, cfg, {}, rows=[old()])
            self.assertEqual(first["source"], "explore")
            self.assertFalse(first["model_derived"])
            _, second = tw.routed(home, "claude", "session", envelope, d, cfg, {}, rows=[old(), first])
            self.assertEqual(second["source"], "cached:explore")
            self.assertFalse(second["model_derived"])
            saved = tw.read_rows(tw.receipts_path(home, "claude", "session"))
            self.assertTrue(all(r["model_derived"] is False for r in saved))
            backend.assert_not_called()

    def test_override_pin_and_risk_floor_still_act(self):
        for extra in ["TW-Override: preserve requested tier", "TW-Pin: user high"]:
            brief = BRIEF.replace("Do the task", extra + "\nDo the task")
            cfg = config(explore=1)
            r = run(cfg, old(), brief)
            fields, _ = tw.header_fields(brief)
            d = tw.Decision(True, "ok", "worker", "sonnet", "high", fields)
            envelope = {"tool_input": {"subagent_type": "tw-worker-high", "prompt": brief}}
            with tempfile.TemporaryDirectory() as tmp:
                result = tw.act(Path(tmp), "claude", "session", envelope, d, r, cfg,
                                tw.flagged(brief, "TW-Pin"))
            self.assertIsNone(result[1])
        cfg = config(explore=1)
        cfg["router"]["risk_floor"]["physics"] = "high"
        brief = BRIEF.replace("TW-Risk: none", "TW-Risk: physics")
        fields, _ = tw.header_fields(brief)
        r = run(cfg, old(), brief)
        d = tw.Decision(True, "ok", "worker", "sonnet", "high", fields)
        with tempfile.TemporaryDirectory() as tmp:
            result = tw.act(Path(tmp), "claude", "session", {"tool_input": {"prompt": brief, "subagent_type": "tw-worker-high"}}, d, r, cfg, False)
        self.assertEqual(result[4], "high")
        self.assertIsNone(result[1])


if __name__ == "__main__":
    unittest.main()
