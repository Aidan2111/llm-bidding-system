"""Command-line interface: llm-bid bid / report / stats / agents."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Mapping

from autonomy_score import score_change
from autonomy_score.diff_parser import parse_unified_diff

from .auction import run_auction
from .config import BiddingConfig, ConfigError, load_config
from .history import HistoryError, HistoryStore
from .models import AuctionResult, OutcomeReport
from .providers import BidProvider, BidProviderError, build_providers

MAX_INTENT_BYTES = 100_000
MAX_DIFF_BYTES = 2_000_000

BANDS = ("Low Risk", "Medium Risk", "High Risk")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_WINNER = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-bid",
        description=(
            "Run work auctions between LLM agents. Bids combine a live model"
            " self-assessment, the task's deterministic autonomy-score risk, and"
            " each agent's historical track record."
        ),
    )
    parser.add_argument("--config", help="Path to a llm-bidding config JSON file.")
    parser.add_argument(
        "--db", help="Path to the history database (overrides config and LLM_BIDDING_DB)."
    )
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bid = subparsers.add_parser("bid", help="Run an auction on a task description.")
    intent_group = bid.add_mutually_exclusive_group(required=True)
    intent_group.add_argument("--intent", help="Path to a task/intent text file ('-' for stdin).")
    intent_group.add_argument("--intent-text", help="Task/intent text inline.")
    bid.add_argument(
        "--agents", help="Comma-separated agent names to include (default: all enabled)."
    )
    bid.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic mock providers and do not persist the auction.",
    )

    report = subparsers.add_parser("report", help="Record the outcome of a past auction.")
    report.add_argument("--auction-id", required=True)
    outcome_group = report.add_mutually_exclusive_group(required=True)
    outcome_group.add_argument("--success", action="store_true")
    outcome_group.add_argument("--failure", action="store_true")
    report.add_argument("--notes", default="")
    report.add_argument(
        "--diff", help="Optional unified diff of the delivered work ('-' for stdin);"
        " scored with autonomy-score and stored with the outcome."
    )
    report.add_argument("--actual-cost", type=float, help="Actual spend in USD, if known.")

    stats = subparsers.add_parser("stats", help="Show per-agent historical stats.")
    stats.add_argument("--agent", help="Limit to one agent.")
    stats.add_argument("--band", choices=BANDS, help="Limit to one risk band.")

    agents = subparsers.add_parser("agents", help="Inspect configured agents.")
    agents.add_argument("action", choices=("list",))

    return parser


def _read_input(path_or_dash: str, *, max_bytes: int, label: str) -> str:
    if path_or_dash == "-":
        data = sys.stdin.read()
    else:
        data = Path(path_or_dash).read_text(encoding="utf-8")
    if len(data.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} input exceeds the {max_bytes} byte limit.")
    if not data.strip():
        raise ValueError(f"{label} input is empty.")
    return data


def _resolve_db_path(args: argparse.Namespace, config: BiddingConfig, env: Mapping[str, str]) -> str:
    if args.db:
        return args.db
    if env.get("LLM_BIDDING_DB"):
        return env["LLM_BIDDING_DB"]
    return config.history_db


def _format_auction_text(result: AuctionResult) -> str:
    lines = [
        f"Auction {result.auction_id}  ({result.created_at})",
        f"Intent: score {result.intent.score} | {result.intent.band} | "
        + (", ".join(s.name for s in result.intent.signals) or "no signals"),
        "",
        f"{'agent':<16}{'conf':>6}{'cal':>6}{'cost $':>9}{'quality':>9}"
        f"{'price':>7}{'fit':>6}{'utility':>9}",
    ]
    for scored in result.bids:
        if scored.is_valid:
            marker = "  <- WINNER" if (
                result.winner and scored.agent_name == result.winner.agent_name
            ) else ""
            lines.append(
                f"{scored.agent_name:<16}"
                f"{scored.bid.confidence:>6.2f}"
                f"{scored.calibrated_confidence:>6.2f}"
                f"{scored.estimated_cost_usd:>9.4f}"
                f"{scored.quality_score:>9.3f}"
                f"{scored.price_score:>7.3f}"
                f"{scored.risk_fit_score:>6.3f}"
                f"{scored.utility:>9.3f}"
                + marker
            )
        else:
            lines.append(f"{scored.agent_name:<16}FAILED: {scored.error}")
    lines += ["", result.summary]
    if result.winner:
        lines.append(f"Approach: {result.winner.bid.approach}")
        lines.append(
            f"Report the outcome later with: llm-bid report --auction-id"
            f" {result.auction_id} --success|--failure"
        )
    return "\n".join(lines)


def _format_stats_rows(
    store: HistoryStore, config: BiddingConfig, agent_names: list[str], band: str | None
) -> list[dict[str, object]]:
    rows = []
    for name in agent_names:
        stats = store.agent_stats(name, config.calibration, band=band)
        row = stats.to_dict()
        if band is None:
            row["bands"] = {
                b: store.agent_stats(name, config.calibration, band=b).to_dict()
                for b in BANDS
            }
        rows.append(row)
    return rows


def _format_stats_text(rows: list[dict[str, object]]) -> str:
    lines = []
    for row in rows:
        lines.append(
            f"{row['agent_name']}"
            + (f" [{row['band']}]" if row.get("band") else "")
        )
        brier = row["brier_score"]
        lines.append(
            f"  entered {row['auctions_entered']}, wins {row['wins']}"
            f" (win rate {row['win_rate']:.2f}), outcomes {row['outcomes_reported']},"
            f" successes {row['successes']} (success rate {row['success_rate']:.3f})"
        )
        lines.append(
            f"  brier {brier if brier is None else format(brier, '.3f')},"
            f" calibration offset {row['calibration_offset']:+.3f}"
        )
        for band_name, band_row in (row.get("bands") or {}).items():
            lines.append(
                f"    {band_name:<12} entered {band_row['auctions_entered']},"
                f" wins {band_row['wins']}, outcomes {band_row['outcomes_reported']},"
                f" success rate {band_row['success_rate']:.3f}"
            )
    return "\n".join(lines) if lines else "No agents."


def run(
    argv: list[str] | None = None,
    *,
    providers: Mapping[str, BidProvider] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    active_env = env if env is not None else os.environ

    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    db_path = _resolve_db_path(args, config, active_env)

    try:
        with HistoryStore(db_path) as store:
            if args.command == "bid":
                return _cmd_bid(args, config, store, providers, active_env)
            if args.command == "report":
                return _cmd_report(args, store)
            if args.command == "stats":
                return _cmd_stats(args, config, store)
            if args.command == "agents":
                return _cmd_agents(args, config, store)
    except (ConfigError, HistoryError, BidProviderError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_ERROR  # pragma: no cover - argparse enforces a known command


def _cmd_bid(
    args: argparse.Namespace,
    config: BiddingConfig,
    store: HistoryStore,
    providers: Mapping[str, BidProvider] | None,
    env: Mapping[str, str],
) -> int:
    if args.intent_text is not None:
        task_text = args.intent_text
        if not task_text.strip():
            raise ValueError("--intent-text is empty.")
        if len(task_text.encode("utf-8")) > MAX_INTENT_BYTES:
            raise ValueError(f"Intent input exceeds the {MAX_INTENT_BYTES} byte limit.")
    else:
        task_text = _read_input(args.intent, max_bytes=MAX_INTENT_BYTES, label="Intent")

    agent_names = None
    if args.agents:
        agent_names = [name.strip() for name in args.agents.split(",") if name.strip()]

    active_providers = providers
    if active_providers is None:
        active_providers = build_providers(config, dry_run=args.dry_run, env=env)

    result = run_auction(
        task_text,
        config,
        active_providers,
        store,
        agent_names=agent_names,
        record=not args.dry_run,
    )
    if args.format == "json":
        print(result.to_json())
    else:
        print(_format_auction_text(result))
    return EXIT_OK if result.winner else EXIT_NO_WINNER


def _cmd_report(args: argparse.Namespace, store: HistoryStore) -> int:
    diff_score = None
    if args.diff:
        diff_text = _read_input(args.diff, max_bytes=MAX_DIFF_BYTES, label="Diff")
        changed_files = parse_unified_diff(diff_text)
        diff_score = score_change(changed_files).score
    report = OutcomeReport(
        auction_id=args.auction_id,
        success=bool(args.success),
        reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        notes=args.notes,
        diff_score=diff_score,
        actual_cost_usd=args.actual_cost,
    )
    store.record_outcome(report)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        outcome = "success" if report.success else "failure"
        extra = f", diff score {diff_score}" if diff_score is not None else ""
        print(f"Recorded {outcome} for auction {report.auction_id}{extra}.")
    return EXIT_OK


def _cmd_stats(args: argparse.Namespace, config: BiddingConfig, store: HistoryStore) -> int:
    if args.agent:
        config.agent(args.agent)  # validates the name
        agent_names = [args.agent]
    else:
        agent_names = [profile.name for profile in config.agents]
    rows = _format_stats_rows(store, config, agent_names, args.band)
    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print(_format_stats_text(rows))
    return EXIT_OK


def _cmd_agents(args: argparse.Namespace, config: BiddingConfig, store: HistoryStore) -> int:
    rows = []
    for profile in config.agents:
        stats = store.agent_stats(profile.name, config.calibration)
        rows.append(
            {
                **profile.to_dict(),
                "auctions_entered": stats.auctions_entered,
                "wins": stats.wins,
            }
        )
    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        lines = [
            f"{'name':<16}{'provider':<11}{'model':<22}{'in $/M':>8}{'out $/M':>9}"
            f"{'enabled':>9}{'entered':>9}{'wins':>6}"
        ]
        for row in rows:
            lines.append(
                f"{row['name']:<16}{row['provider']:<11}{row['model_id']:<22}"
                f"{row['input_cost_per_mtok']:>8.2f}{row['output_cost_per_mtok']:>9.2f}"
                f"{str(row['enabled']):>9}{row['auctions_entered']:>9}{row['wins']:>6}"
            )
        print("\n".join(lines))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
