"""SQLite-backed auction history and per-agent statistics."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .calibration import brier_score, calibration_offset, shrunk_success_rate
from .config import CalibrationParams
from .models import AgentStats, AuctionResult, OutcomeReport


class HistoryError(RuntimeError):
    """Raised for invalid history operations (unknown auction, duplicate outcome)."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS auctions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    task_text TEXT NOT NULL,
    intent_score INTEGER NOT NULL,
    intent_band TEXT NOT NULL,
    intent_signals TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    winner_agent TEXT
);

CREATE TABLE IF NOT EXISTS bids (
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

CREATE TABLE IF NOT EXISTS outcomes (
    auction_id TEXT PRIMARY KEY REFERENCES auctions(id),
    success INTEGER NOT NULL,
    reported_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    diff_score INTEGER,
    actual_cost_usd REAL
);
"""

_SCHEMA_VERSION = 1


class HistoryStore:
    """Records auctions, bids, and reported outcomes; answers stats queries."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            db_path = Path(self.path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(db_path)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.executescript(_SCHEMA)
            row = self._connection.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,)
                )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record_auction(self, result: AuctionResult) -> None:
        signals = json.dumps([signal.name for signal in result.intent.signals])
        winner = result.winner.agent_name if result.winner else None
        with self._connection:
            self._connection.execute(
                "INSERT INTO auctions (id, created_at, task_text, intent_score,"
                " intent_band, intent_signals, weights_json, winner_agent)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.auction_id,
                    result.created_at,
                    result.task_text,
                    result.intent.score,
                    result.intent.band,
                    signals,
                    json.dumps(result.weights, sort_keys=True),
                    winner,
                ),
            )
            for scored in result.bids:
                bid = scored.bid
                self._connection.execute(
                    "INSERT INTO bids (auction_id, agent_name, model_id, confidence,"
                    " approach, estimated_cost_usd, quality, price, risk_fit, utility,"
                    " won, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.auction_id,
                        scored.agent_name,
                        bid.model_id if bid else None,
                        bid.confidence if bid else None,
                        bid.approach if bid else None,
                        scored.estimated_cost_usd,
                        scored.quality_score,
                        scored.price_score,
                        scored.risk_fit_score,
                        scored.utility,
                        1 if winner == scored.agent_name else 0,
                        scored.error,
                    ),
                )

    def record_outcome(self, report: OutcomeReport) -> None:
        auction = self._connection.execute(
            "SELECT winner_agent FROM auctions WHERE id = ?", (report.auction_id,)
        ).fetchone()
        if auction is None:
            raise HistoryError(f"No auction with id {report.auction_id!r}.")
        if auction["winner_agent"] is None:
            raise HistoryError(
                f"Auction {report.auction_id!r} had no winner; there is no outcome to report."
            )
        existing = self._connection.execute(
            "SELECT 1 FROM outcomes WHERE auction_id = ?", (report.auction_id,)
        ).fetchone()
        if existing is not None:
            raise HistoryError(
                f"An outcome is already recorded for auction {report.auction_id!r}."
            )
        with self._connection:
            self._connection.execute(
                "INSERT INTO outcomes (auction_id, success, reported_at, notes,"
                " diff_score, actual_cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report.auction_id,
                    1 if report.success else 0,
                    report.reported_at,
                    report.notes,
                    report.diff_score,
                    report.actual_cost_usd,
                ),
            )

    def agent_stats(
        self,
        agent_name: str,
        params: CalibrationParams,
        band: str | None = None,
    ) -> AgentStats:
        band_clause = "" if band is None else " AND auctions.intent_band = ?"
        band_args: tuple[object, ...] = () if band is None else (band,)

        counts = self._connection.execute(
            "SELECT COUNT(*) AS entered, COALESCE(SUM(bids.won), 0) AS wins"
            " FROM bids JOIN auctions ON auctions.id = bids.auction_id"
            " WHERE bids.agent_name = ? AND bids.error IS NULL" + band_clause,
            (agent_name, *band_args),
        ).fetchone()
        entered = counts["entered"]
        wins = counts["wins"]

        outcome_rows = self._connection.execute(
            "SELECT bids.confidence AS confidence, outcomes.success AS success"
            " FROM bids"
            " JOIN auctions ON auctions.id = bids.auction_id"
            " JOIN outcomes ON outcomes.auction_id = bids.auction_id"
            " WHERE bids.agent_name = ? AND bids.won = 1" + band_clause,
            (agent_name, *band_args),
        ).fetchall()
        pairs = [
            (float(row["confidence"]), bool(row["success"]))
            for row in outcome_rows
            if row["confidence"] is not None
        ]
        outcomes_reported = len(outcome_rows)
        successes = sum(1 for row in outcome_rows if row["success"])

        return AgentStats(
            agent_name=agent_name,
            band=band,
            auctions_entered=entered,
            wins=wins,
            outcomes_reported=outcomes_reported,
            successes=successes,
            win_rate=(wins / entered) if entered else 0.0,
            success_rate=shrunk_success_rate(successes, outcomes_reported, params),
            brier_score=brier_score(pairs),
            calibration_offset=calibration_offset(pairs, params),
        )

    def signal_stats(
        self, agent_name: str, signal_name: str, params: CalibrationParams
    ) -> AgentStats:
        """Stats restricted to auctions whose intent carried a given signal."""
        rows = self._connection.execute(
            "SELECT auctions.intent_signals AS signals, bids.won AS won,"
            " bids.confidence AS confidence, outcomes.success AS success"
            " FROM bids"
            " JOIN auctions ON auctions.id = bids.auction_id"
            " LEFT JOIN outcomes ON outcomes.auction_id = bids.auction_id"
            " WHERE bids.agent_name = ? AND bids.error IS NULL",
            (agent_name,),
        ).fetchall()
        entered = wins = outcomes_reported = successes = 0
        pairs: list[tuple[float, bool]] = []
        for row in rows:
            if signal_name not in json.loads(row["signals"]):
                continue
            entered += 1
            if row["won"]:
                wins += 1
                if row["success"] is not None:
                    outcomes_reported += 1
                    success = bool(row["success"])
                    if success:
                        successes += 1
                    if row["confidence"] is not None:
                        pairs.append((float(row["confidence"]), success))
        return AgentStats(
            agent_name=agent_name,
            band=None,
            auctions_entered=entered,
            wins=wins,
            outcomes_reported=outcomes_reported,
            successes=successes,
            win_rate=(wins / entered) if entered else 0.0,
            success_rate=shrunk_success_rate(successes, outcomes_reported, params),
            brier_score=brier_score(pairs),
            calibration_offset=calibration_offset(pairs, params),
        )

    def list_recent(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT auctions.id, auctions.created_at, auctions.intent_score,"
            " auctions.intent_band, auctions.winner_agent, outcomes.success"
            " FROM auctions LEFT JOIN outcomes ON outcomes.auction_id = auctions.id"
            " ORDER BY auctions.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "auction_id": row["id"],
                "created_at": row["created_at"],
                "intent_score": row["intent_score"],
                "intent_band": row["intent_band"],
                "winner": row["winner_agent"],
                "outcome": None if row["success"] is None else bool(row["success"]),
            }
            for row in rows
        ]
