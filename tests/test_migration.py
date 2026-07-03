import sqlite3
import tempfile
import unittest
from pathlib import Path

from llm_bidding.history import HistoryStore

from helpers import CONFIG


# The exact v1 schema as shipped in v0.1.0, used to fabricate a pre-upgrade DB.
_V1_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version (version) VALUES (1);

CREATE TABLE auctions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    task_text TEXT NOT NULL,
    intent_score INTEGER NOT NULL,
    intent_band TEXT NOT NULL,
    intent_signals TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    winner_agent TEXT
);

CREATE TABLE bids (
    auction_id TEXT NOT NULL REFERENCES auctions(id),
    agent_name TEXT NOT NULL,
    model_id TEXT,
    confidence REAL,
    approach TEXT,
    estimated_cost_usd REAL NOT NULL,
    quality REAL NOT NULL,
    price REAL NOT NULL,
    risk_fit REAL NOT NULL,
    utility REAL NOT NULL,
    won INTEGER NOT NULL,
    error TEXT,
    PRIMARY KEY (auction_id, agent_name)
);

CREATE TABLE outcomes (
    auction_id TEXT PRIMARY KEY REFERENCES auctions(id),
    success INTEGER NOT NULL,
    reported_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    diff_score INTEGER,
    actual_cost_usd REAL
);

INSERT INTO auctions VALUES
  ('old1', '2026-01-01T00:00:00+00:00', 'old task', 7, 'Medium Risk',
   '["intent:state-or-persistence"]', '{}', 'claude-opus');
INSERT INTO bids VALUES
  ('old1', 'claude-opus', 'claude-opus-4-8', 0.8, 'plan', 0.03,
   0.6, 0.9, 0.5, 0.65, 1, NULL);
INSERT INTO outcomes VALUES
  ('old1', 1, '2026-01-02T00:00:00+00:00', '', NULL, 0.05);
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = str(Path(tmp.name) / "history.db")

    def _make_v1_db(self):
        connection = sqlite3.connect(self.db_path)
        connection.executescript(_V1_SCHEMA)
        connection.close()

    def test_v1_database_upgrades_to_latest(self):
        self._make_v1_db()
        with HistoryStore(self.db_path) as store:
            self.assertEqual(store.schema_version, 3)
            record = store.get_auction("old1")
            self.assertEqual(record["intent_band"], "Medium Risk")
            # Pre-upgrade rows read back with NULL new columns.
            self.assertIsNone(record["scoring_version"])
            self.assertIsNone(record["recommended_mode"])
            self.assertIsNone(record["bids"][0]["eligible"])
            self.assertIsNone(record["bids"][0]["raw_estimated_cost_usd"])
            self.assertIsNone(record["outcome"]["scope_drift"])
            # Stats still compute over old rows.
            stats = store.agent_stats("claude-opus", CONFIG.calibration)
            self.assertEqual(stats.wins, 1)
            self.assertEqual(stats.outcomes_reported, 1)

    def test_reopen_is_idempotent(self):
        self._make_v1_db()
        for _ in range(3):
            with HistoryStore(self.db_path) as store:
                self.assertEqual(store.schema_version, 3)

    def test_fresh_database_is_latest_version(self):
        with HistoryStore(self.db_path) as store:
            self.assertEqual(store.schema_version, 3)

    def test_file_database_uses_wal_and_busy_timeout(self):
        with HistoryStore(self.db_path) as store:
            journal = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(journal, "wal")
            busy = store._connection.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(busy, 5000)


class PruneTests(unittest.TestCase):
    def test_prune_cascades_and_returns_count(self):
        from llm_bidding.models import OutcomeReport
        from helpers import make_auction, make_scored_bid

        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        old_winner = make_scored_bid("a", utility=0.9)
        store.record_auction(
            make_auction("old", bids=(old_winner,), winner=old_winner,
                         created_at="2026-01-01T00:00:00+00:00")
        )
        store.record_outcome(
            OutcomeReport(auction_id="old", success=True,
                          reported_at="2026-01-02T00:00:00+00:00")
        )
        new_winner = make_scored_bid("a", utility=0.9)
        store.record_auction(
            make_auction("new", bids=(new_winner,), winner=new_winner,
                         created_at="2026-06-01T00:00:00+00:00")
        )

        deleted = store.prune(30, now="2026-06-10T00:00:00+00:00")
        self.assertEqual(deleted, 1)
        self.assertEqual([r["auction_id"] for r in store.list_recent()], ["new"])
        rows = list(store.export_rows())
        self.assertFalse(any(r.get("auction_id") == "old" or r.get("id") == "old"
                             for r in rows))

    def test_prune_nothing_to_delete(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        self.assertEqual(store.prune(30), 0)


if __name__ == "__main__":
    unittest.main()
