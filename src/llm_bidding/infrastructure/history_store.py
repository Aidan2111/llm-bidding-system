"""SQLite-backed auction history and per-agent statistics."""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

from ..domain.calibration import (
    brier_score,
    calibration_offset,
    shrunk_cost_ratio,
    shrunk_success_rate,
)
from ..domain.models import AgentStats, AuctionResult, OutcomeReport
from .configuration import CalibrationParams


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

_LATEST_SCHEMA_VERSION = 3

# Each entry upgrades from version N-1 to N. New columns must be nullable so
# rows recorded under older schemas keep working (NULL means "pre-upgrade").
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        "ALTER TABLE auctions ADD COLUMN scoring_version TEXT",
        "ALTER TABLE auctions ADD COLUMN recommended_mode TEXT",
        "ALTER TABLE bids ADD COLUMN eligible INTEGER",
        "ALTER TABLE bids ADD COLUMN ineligible_reason TEXT",
        "ALTER TABLE outcomes ADD COLUMN scope_drift INTEGER",
        "ALTER TABLE outcomes ADD COLUMN gate_score INTEGER",
    ),
    # raw_estimated_cost_usd is the model's pre-calibration estimate; the cost
    # ratio must be measured against it, not the ratio-adjusted estimate that
    # feeds the price score (otherwise calibration is self-referential).
    3: ("ALTER TABLE bids ADD COLUMN raw_estimated_cost_usd REAL",),
}


def _parse_created_at(value: object) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        created = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    return created.astimezone(datetime.timezone.utc)


_MAX_UTC_DATETIME = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


def _created_at_sort_key(row: sqlite3.Row) -> tuple[int, datetime.datetime, str, str]:
    created = _parse_created_at(row["created_at"])
    return (
        1 if created is None else 0,
        created or _MAX_UTC_DATETIME,
        str(row["created_at"]),
        str(row["id"]),
    )


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
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(_SCHEMA)
            row = self._connection.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO schema_version (version) VALUES (1)"
                )
                current = 1
            else:
                current = row["version"]
        for version in range(current + 1, _LATEST_SCHEMA_VERSION + 1):
            with self._connection:
                for statement in _MIGRATIONS[version]:
                    self._connection.execute(statement)
                self._connection.execute(
                    "UPDATE schema_version SET version = ?", (version,)
                )

    @property
    def schema_version(self) -> int:
        row = self._connection.execute("SELECT version FROM schema_version").fetchone()
        return row["version"]

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
                " intent_band, intent_signals, weights_json, winner_agent,"
                " scoring_version, recommended_mode)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.auction_id,
                    result.created_at,
                    result.task_text,
                    result.intent.score,
                    result.intent.band,
                    signals,
                    json.dumps(result.weights, sort_keys=True),
                    winner,
                    result.scoring_version or None,
                    result.intent.recommended_mode,
                ),
            )
            for scored in result.bids:
                bid = scored.bid
                self._connection.execute(
                    "INSERT INTO bids (auction_id, agent_name, model_id, confidence,"
                    " approach, estimated_cost_usd, raw_estimated_cost_usd, quality,"
                    " price, risk_fit, utility, won, error, eligible, ineligible_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.auction_id,
                        scored.agent_name,
                        bid.model_id if bid else None,
                        bid.confidence if bid else None,
                        bid.approach if bid else None,
                        scored.estimated_cost_usd,
                        scored.raw_estimated_cost_usd,
                        scored.quality_score,
                        scored.price_score,
                        scored.risk_fit_score,
                        scored.utility,
                        1 if winner == scored.agent_name else 0,
                        scored.error,
                        1 if scored.eligible else 0,
                        scored.ineligible_reason,
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
                " diff_score, actual_cost_usd, scope_drift, gate_score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report.auction_id,
                    1 if report.success else 0,
                    report.reported_at,
                    report.notes,
                    report.diff_score,
                    report.actual_cost_usd,
                    None if report.scope_drift is None else int(report.scope_drift),
                    report.gate_score,
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
            "SELECT bids.confidence AS confidence, outcomes.success AS success,"
            " COALESCE(bids.raw_estimated_cost_usd, bids.estimated_cost_usd)"
            " AS estimated_cost,"
            " outcomes.actual_cost_usd AS actual_cost,"
            " outcomes.scope_drift AS scope_drift"
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
        cost_ratios = [
            float(row["actual_cost"]) / float(row["estimated_cost"])
            for row in outcome_rows
            if row["actual_cost"] is not None
            and row["estimated_cost"] is not None
            and row["estimated_cost"] > 0
        ]
        drifts = sum(1 for row in outcome_rows if row["scope_drift"])

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
            cost_ratio=shrunk_cost_ratio(cost_ratios, params),
            drifts=drifts,
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
            " auctions.intent_band, auctions.recommended_mode,"
            " auctions.winner_agent, outcomes.success"
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
                "recommended_mode": row["recommended_mode"],
                "winner": row["winner_agent"],
                "outcome": None if row["success"] is None else bool(row["success"]),
            }
            for row in rows
        ]

    def count_auctions(self, band: str | None = None) -> int:
        """Number of recorded auctions, optionally scoped to one risk band."""
        if band is None:
            row = self._connection.execute("SELECT COUNT(*) AS n FROM auctions").fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM auctions WHERE intent_band = ?", (band,)
            ).fetchone()
        return row["n"]

    def list_unreported(self, limit: int = 20) -> list[dict[str, object]]:
        """Auctions that awarded a winner but never had an outcome reported.

        Oldest first — these are the debts that starve calibration.
        """
        rows = self._connection.execute(
            "SELECT auctions.id, auctions.created_at, auctions.intent_band,"
            " auctions.winner_agent"
            " FROM auctions LEFT JOIN outcomes ON outcomes.auction_id = auctions.id"
            " WHERE auctions.winner_agent IS NOT NULL AND outcomes.auction_id IS NULL"
            " ORDER BY auctions.id ASC",
        ).fetchall()
        rows = sorted(rows, key=_created_at_sort_key)[:limit]
        return [
            {
                "auction_id": row["id"],
                "created_at": row["created_at"],
                "intent_band": row["intent_band"],
                "winner": row["winner_agent"],
            }
            for row in rows
        ]

    def get_auction(self, auction_id: str) -> dict[str, object]:
        """Full stored record for one auction: row, bids, and any outcome."""
        auction = self._connection.execute(
            "SELECT * FROM auctions WHERE id = ?", (auction_id,)
        ).fetchone()
        if auction is None:
            raise HistoryError(f"No auction with id {auction_id!r}.")
        bids = self._connection.execute(
            "SELECT * FROM bids WHERE auction_id = ?"
            " ORDER BY utility DESC, estimated_cost_usd ASC, agent_name ASC",
            (auction_id,),
        ).fetchall()
        outcome = self._connection.execute(
            "SELECT * FROM outcomes WHERE auction_id = ?", (auction_id,)
        ).fetchone()
        record = dict(auction)
        record["intent_signals"] = json.loads(record["intent_signals"])
        record["weights"] = json.loads(record.pop("weights_json"))
        record["bids"] = [dict(row) for row in bids]
        record["outcome"] = dict(outcome) if outcome is not None else None
        return record

    def export_rows(self):
        """Yield every auction, bid, and outcome as a typed flat dict (JSONL-ready)."""
        for row in self._connection.execute(
            "SELECT * FROM auctions ORDER BY created_at ASC, id ASC"
        ):
            data = dict(row)
            data["intent_signals"] = json.loads(data["intent_signals"])
            data["weights"] = json.loads(data.pop("weights_json"))
            yield {"type": "auction", **data}
        for row in self._connection.execute(
            "SELECT * FROM bids ORDER BY auction_id ASC, agent_name ASC"
        ):
            yield {"type": "bid", **dict(row)}
        for row in self._connection.execute(
            "SELECT * FROM outcomes ORDER BY auction_id ASC"
        ):
            yield {"type": "outcome", **dict(row)}

    def prune(self, keep_days: int, *, now: str | None = None) -> int:
        """Delete auctions (and their bids/outcomes) older than keep_days."""
        if keep_days < 0:
            raise HistoryError("keep_days must be >= 0.")
        reference = (
            datetime.datetime.fromisoformat(now)
            if now
            else datetime.datetime.now(datetime.timezone.utc)
        )
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=datetime.timezone.utc)
        cutoff = reference - datetime.timedelta(days=keep_days)
        with self._connection:
            # Parse timestamps rather than comparing strings: mixed offsets or
            # naive values would make a lexicographic comparison mis-prune.
            # Rows with unparseable timestamps are kept, never deleted.
            ids = []
            for row in self._connection.execute("SELECT id, created_at FROM auctions"):
                created = _parse_created_at(row["created_at"])
                if created is None:
                    continue
                if created < cutoff:
                    ids.append(row["id"])
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            # No ON DELETE CASCADE in the schema; cascade manually.
            self._connection.execute(
                f"DELETE FROM outcomes WHERE auction_id IN ({placeholders})", ids
            )
            self._connection.execute(
                f"DELETE FROM bids WHERE auction_id IN ({placeholders})", ids
            )
            self._connection.execute(
                f"DELETE FROM auctions WHERE id IN ({placeholders})", ids
            )
        return len(ids)
