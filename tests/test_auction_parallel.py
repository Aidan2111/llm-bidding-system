import dataclasses
import threading
import unittest

from llm_bidding.auction import FAST_PATH_APPROACH_PREFIX, run_auction
from llm_bidding.history import HistoryStore
from llm_bidding.providers import MockBidProvider
from llm_bidding.providers.base import MissingApiKeyError

from helpers import CONFIG, RISKY_TASK, SAFE_TASK


def _providers(provider):
    return {"anthropic": provider, "openai": provider}


class FakeSleeper:
    def __init__(self):
        self.sleeps = []

    def __call__(self, seconds):
        self.sleeps.append(seconds)


class BlockingBidProvider:
    """Never returns until released; used to exercise the timeout path."""

    def __init__(self):
        self.release = threading.Event()

    def request_bid(self, agent, request):
        self.release.wait()
        raise AssertionError("should not be reached in timeout tests")


class FailingKeyProvider:
    def __init__(self):
        self.calls = 0

    def request_bid(self, agent, request):
        self.calls += 1
        raise MissingApiKeyError("no key")


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def test_transient_failure_is_retried_and_succeeds(self):
        provider = MockBidProvider(transient_failures={"claude-opus": 1})
        sleeper = FakeSleeper()
        result = run_auction(
            SAFE_TASK, CONFIG, _providers(provider), self.store, sleeper=sleeper
        )
        opus = next(b for b in result.bids if b.agent_name == "claude-opus")
        self.assertTrue(opus.is_valid)
        self.assertEqual(sleeper.sleeps, [CONFIG.providers.retry_backoff_seconds])
        # 3 first-wave calls + 1 retry call
        self.assertEqual(len(provider.calls), 4)

    def test_retries_exhausted_becomes_permanent_failure(self):
        provider = MockBidProvider(transient_failures={"claude-opus": 10})
        sleeper = FakeSleeper()
        result = run_auction(
            SAFE_TASK, CONFIG, _providers(provider), self.store, sleeper=sleeper
        )
        opus = next(b for b in result.bids if b.agent_name == "claude-opus")
        self.assertFalse(opus.is_valid)
        self.assertIn("after 2 attempts", opus.error)
        self.assertIsNotNone(result.winner)  # others still won

    def test_non_retryable_error_is_not_retried(self):
        provider = FailingKeyProvider()
        sleeper = FakeSleeper()
        result = run_auction(
            SAFE_TASK, CONFIG, _providers(provider), self.store, sleeper=sleeper
        )
        self.assertIsNone(result.winner)
        self.assertEqual(provider.calls, 3)  # one call per agent, no retries
        self.assertEqual(sleeper.sleeps, [])


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def test_hung_provider_times_out_without_blocking_others(self):
        blocking = BlockingBidProvider()
        self.addCleanup(blocking.release.set)  # let the abandoned thread exit
        fast_config = dataclasses.replace(
            CONFIG,
            providers=dataclasses.replace(CONFIG.providers, timeout_seconds=0.05),
        )
        result = run_auction(
            SAFE_TASK,
            fast_config,
            {"anthropic": blocking, "openai": MockBidProvider()},
            self.store,
            sleeper=FakeSleeper(),
        )
        timed_out = [b for b in result.bids if not b.is_valid]
        self.assertEqual({b.agent_name for b in timed_out}, {"claude-opus", "claude-sonnet"})
        for bid in timed_out:
            self.assertIn("timed out", bid.error)
        self.assertIsNotNone(result.winner)
        self.assertEqual(result.winner.agent_name, "gpt")


class FastPathTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)
        self.fast_config = dataclasses.replace(
            CONFIG,
            fast_path=dataclasses.replace(
                CONFIG.fast_path, skip_bids_for_low_risk=True
            ),
        )

    def test_low_risk_task_skips_llm_calls(self):
        provider = MockBidProvider()
        result = run_auction(
            SAFE_TASK, self.fast_config, _providers(provider), self.store
        )
        self.assertEqual(provider.calls, [])
        self.assertIsNotNone(result.winner)
        for bid in result.bids:
            self.assertTrue(bid.bid.approach.startswith(FAST_PATH_APPROACH_PREFIX))
            # Cold start: statistical confidence equals the neutral prior.
            self.assertEqual(bid.bid.confidence, 0.5)
            self.assertEqual(
                bid.bid.estimated_input_tokens,
                self.fast_config.fast_path.default_input_tokens,
            )

    def test_high_risk_task_still_calls_providers(self):
        provider = MockBidProvider()
        run_auction(RISKY_TASK, self.fast_config, _providers(provider), self.store)
        self.assertEqual(len(provider.calls), 3)

    def test_flag_off_means_no_fast_path(self):
        provider = MockBidProvider()
        run_auction(SAFE_TASK, CONFIG, _providers(provider), self.store)
        self.assertEqual(len(provider.calls), 3)


class ParallelDeterminismTests(unittest.TestCase):
    def test_parallel_runs_are_deterministic(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        kwargs = dict(
            record=False,
            clock=lambda: "2026-06-10T00:00:00+00:00",
            id_factory=lambda: "fixed-id",
            sleeper=FakeSleeper(),
        )
        provider = MockBidProvider(seed=3)
        first = run_auction(RISKY_TASK, CONFIG, _providers(provider), store, **kwargs)
        second = run_auction(RISKY_TASK, CONFIG, _providers(provider), store, **kwargs)
        self.assertEqual(first.to_json(), second.to_json())


if __name__ == "__main__":
    unittest.main()
