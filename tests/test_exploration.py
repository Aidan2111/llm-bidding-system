"""Cold-start exploration: every Nth auction in a band routes to an
under-proven agent so the cheapest early winner doesn't monopolize history."""

import dataclasses
import datetime
import unittest

from llm_bidding.auction import run_auction
from llm_bidding.history import HistoryStore
from llm_bidding.infrastructure.configuration import ExplorationParams, load_config
from llm_bidding.models import OutcomeReport
from llm_bidding.policy import PolicyParams
from llm_bidding.providers import MockBidProvider

from helpers import CONFIG, RISKY_TASK, SAFE_TASK


# claude-opus always posts the highest confidence, so it wins normal rounds.
OVERRIDES = {"claude-opus": 0.95, "claude-sonnet": 0.6, "gpt": 0.55}


def _providers():
    provider = MockBidProvider(confidence_overrides=OVERRIDES)
    return {"anthropic": provider, "openai": provider}


def _report(store, auction_id, success=True):
    store.record_outcome(
        OutcomeReport(
            auction_id=auction_id,
            success=success,
            reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    )


def _explore_config(every_nth, min_band_outcomes=1, base=None):
    return dataclasses.replace(
        base or CONFIG,
        exploration=ExplorationParams(
            every_nth=every_nth, min_band_outcomes=min_band_outcomes
        ),
    )


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def test_disabled_by_default(self):
        self.assertEqual(CONFIG.exploration.every_nth, 0)
        result = run_auction(SAFE_TASK, CONFIG, _providers(), self.store)
        self.assertFalse(result.exploration_round)
        self.assertEqual(result.winner.agent_name, "claude-opus")

    def test_every_nth_auction_routes_to_under_proven_agent(self):
        config = _explore_config(every_nth=2, min_band_outcomes=1)

        # Auction 1 (band count 0 -> normal round): utility winner.
        first = run_auction(SAFE_TASK, config, _providers(), self.store)
        self.assertFalse(first.exploration_round)
        self.assertEqual(first.winner.agent_name, "claude-opus")
        _report(self.store, first.auction_id)

        # Auction 2 (band count 1 -> exploration round): opus is proven now,
        # so selection is restricted to the under-proven agents.
        second = run_auction(SAFE_TASK, config, _providers(), self.store)
        self.assertTrue(second.exploration_round)
        self.assertNotEqual(second.winner.agent_name, "claude-opus")
        self.assertIn("Exploration round", second.summary)

        # Auction 3 (band count 2 -> normal round again): back to utility.
        third = run_auction(SAFE_TASK, config, _providers(), self.store)
        self.assertFalse(third.exploration_round)
        self.assertEqual(third.winner.agent_name, "claude-opus")

    def test_rotation_proves_out_the_whole_field_then_stops(self):
        config = _explore_config(every_nth=1, min_band_outcomes=1)
        winners = []
        for _ in range(3):
            result = run_auction(SAFE_TASK, config, _providers(), self.store)
            winners.append(result.winner.agent_name)
            _report(self.store, result.auction_id)
        # Every agent won once while under-proven.
        self.assertEqual(set(winners), {"claude-opus", "claude-sonnet", "gpt"})
        # Field fully proven: exploration finds nobody and falls back to utility.
        fourth = run_auction(SAFE_TASK, config, _providers(), self.store)
        self.assertFalse(fourth.exploration_round)
        self.assertEqual(fourth.winner.agent_name, "claude-opus")

    def test_exploration_respects_the_high_risk_floor(self):
        # A floor nobody clears: exploration must not resurrect ineligible bids.
        config = dataclasses.replace(
            _explore_config(every_nth=1, min_band_outcomes=1),
            policy=PolicyParams(high_risk_min_band_success_rate=0.99),
        )
        result = run_auction(RISKY_TASK, config, _providers(), self.store)
        self.assertFalse(result.exploration_round)
        self.assertIsNone(result.winner)
        self.assertIn("High Risk floor", result.summary)

    def test_exploration_counts_are_band_scoped(self):
        config = _explore_config(every_nth=2, min_band_outcomes=1)
        # Two Low Risk auctions advance only the Low Risk counter.
        first = run_auction(SAFE_TASK, config, _providers(), self.store)
        _report(self.store, first.auction_id)
        run_auction(SAFE_TASK, config, _providers(), self.store)
        # High Risk band count is still 0 -> its first auction is a normal round.
        risky = run_auction(RISKY_TASK, config, _providers(), self.store)
        self.assertFalse(risky.exploration_round)

    def test_config_validation(self):
        from llm_bidding.config import ConfigError

        import json
        import tempfile
        from pathlib import Path

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump({"exploration": {"every_nth": -1}}, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaises(ConfigError):
            load_config(handle.name)


if __name__ == "__main__":
    unittest.main()
