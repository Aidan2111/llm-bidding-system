import unittest

from llm_bidding.auction import run_auction
from llm_bidding.config import ConfigError
from llm_bidding.history import HistoryStore
from llm_bidding.providers import MockBidProvider

from helpers import CONFIG, RISKY_TASK, SAFE_TASK


def _providers(provider: MockBidProvider) -> dict:
    return {"anthropic": provider, "openai": provider}


class AuctionTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def test_staged_winner(self):
        provider = MockBidProvider(
            confidence_overrides={"claude-opus": 0.95, "claude-sonnet": 0.5, "gpt": 0.5}
        )
        result = run_auction(SAFE_TASK, CONFIG, _providers(provider), self.store)
        self.assertIsNotNone(result.winner)
        self.assertEqual(result.winner.agent_name, "claude-opus")
        self.assertEqual(result.bids[0].agent_name, "claude-opus")

    def test_provider_failure_does_not_kill_the_auction(self):
        provider = MockBidProvider(fail_agents={"claude-opus"})
        result = run_auction(SAFE_TASK, CONFIG, _providers(provider), self.store)
        self.assertIsNotNone(result.winner)
        self.assertNotEqual(result.winner.agent_name, "claude-opus")
        failed = [b for b in result.bids if not b.is_valid]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].agent_name, "claude-opus")

    def test_all_failures_yield_no_winner(self):
        provider = MockBidProvider(fail_agents={"claude-opus", "claude-sonnet", "gpt"})
        result = run_auction(SAFE_TASK, CONFIG, _providers(provider), self.store)
        self.assertIsNone(result.winner)
        self.assertIn("No valid bids", result.summary)

    def test_record_persists_auction(self):
        provider = MockBidProvider()
        result = run_auction(RISKY_TASK, CONFIG, _providers(provider), self.store)
        rows = self.store.list_recent()
        self.assertEqual(rows[0]["auction_id"], result.auction_id)
        stats = self.store.agent_stats(result.winner.agent_name, CONFIG.calibration)
        self.assertEqual(stats.wins, 1)

    def test_record_false_persists_nothing(self):
        provider = MockBidProvider()
        run_auction(RISKY_TASK, CONFIG, _providers(provider), self.store, record=False)
        self.assertEqual(self.store.list_recent(), [])

    def test_agent_subset_and_unknown_agent(self):
        provider = MockBidProvider()
        result = run_auction(
            SAFE_TASK, CONFIG, _providers(provider), self.store,
            agent_names=["claude-sonnet"],
        )
        self.assertEqual([b.agent_name for b in result.bids], ["claude-sonnet"])
        with self.assertRaises(ConfigError):
            run_auction(
                SAFE_TASK, CONFIG, _providers(provider), self.store,
                agent_names=["nope"],
            )

    def test_deterministic_output_with_injected_seams(self):
        provider = MockBidProvider(seed=3)
        kwargs = dict(
            record=False,
            clock=lambda: "2026-06-10T00:00:00+00:00",
            id_factory=lambda: "fixed-id",
        )
        first = run_auction(RISKY_TASK, CONFIG, _providers(provider), self.store, **kwargs)
        second = run_auction(RISKY_TASK, CONFIG, _providers(provider), self.store, **kwargs)
        self.assertEqual(first.to_json(), second.to_json())

    def test_missing_provider_type_is_a_recorded_failure(self):
        result = run_auction(
            SAFE_TASK, CONFIG, {"anthropic": MockBidProvider()}, self.store
        )
        gpt_bid = next(b for b in result.bids if b.agent_name == "gpt")
        self.assertFalse(gpt_bid.is_valid)
        self.assertIn("No provider configured", gpt_bid.error)


if __name__ == "__main__":
    unittest.main()
