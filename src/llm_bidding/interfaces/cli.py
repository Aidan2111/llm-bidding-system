"""Command-line interface: llm-bid bid / report / stats / agents."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Mapping

from ..application.auctioning import run_auction
from ..application.patch_proposals import (
    build_patch_prompt,
    read_context_files,
    request_patch_proposal,
)
from ..domain.models import AuctionResult, OutcomeReport
from ..infrastructure.autonomy_scoring import (
    BANDS,
    ScoringCompatibilityError,
    detect_scope_drift,
    score_result_diff,
)
from ..infrastructure.configuration import BiddingConfig, ConfigError, load_config
from ..infrastructure.history_store import HistoryError, HistoryStore
from ..providers import BidProvider, BidProviderError, build_providers

MAX_INTENT_BYTES = 100_000
MAX_DIFF_BYTES = 2_000_000

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

    show = subparsers.add_parser("show", help="Show a stored auction in full.")
    show.add_argument("--auction-id", required=True)

    history = subparsers.add_parser("history", help="List recent auctions.")
    history.add_argument("--limit", type=int, default=20)

    export = subparsers.add_parser("export", help="Export all history as JSONL.")
    export.add_argument("--output", help="Write to a file instead of stdout.")

    prune = subparsers.add_parser("prune", help="Delete auctions older than N days.")
    prune.add_argument("--keep-days", type=int, required=True)

    propose = subparsers.add_parser(
        "propose",
        help="Ask a supervised coding actor to propose a patch for review.",
    )
    task_group = propose.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Path to a task text file ('-' for stdin).")
    task_group.add_argument("--task-text", help="Task text inline.")
    propose.add_argument("--agent", required=True, help="Configured actor agent name.")
    propose.add_argument(
        "--context",
        action="append",
        default=[],
        help="Repository file to include as explicit actor context. Repeatable.",
    )
    propose.add_argument("--auction-summary", help="Optional auction summary to include.")
    propose.add_argument(
        "--supervisor",
        default="Codex",
        help="Name of the reviewer/supervisor that will apply and test the patch.",
    )
    propose.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the actor prompt without calling the live model.",
    )
    propose.add_argument("--output", help="Write the prompt/proposal to a file.")

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
        f"Supervision: {result.intent.recommended_mode}",
        "",
        f"{'agent':<16}{'conf':>6}{'cal':>6}{'cost $':>9}{'quality':>9}"
        f"{'price':>7}{'fit':>6}{'utility':>9}",
    ]
    for scored in result.bids:
        if scored.is_valid:
            marker = ""
            if result.winner and scored.agent_name == result.winner.agent_name:
                marker = "  <- WINNER"
            elif not scored.eligible:
                marker = f"  INELIGIBLE: {scored.ineligible_reason}"
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
            f" calibration offset {row['calibration_offset']:+.3f},"
            f" cost ratio {row['cost_ratio']:.2f}x, scope drifts {row['drifts']}"
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
        if args.command == "propose":
            return _cmd_propose(args, config, active_env)

        with HistoryStore(db_path) as store:
            if args.command == "bid":
                return _cmd_bid(args, config, store, providers, active_env)
            if args.command == "report":
                return _cmd_report(args, store)
            if args.command == "stats":
                return _cmd_stats(args, config, store)
            if args.command == "agents":
                return _cmd_agents(args, config, store)
            if args.command == "show":
                return _cmd_show(args, store)
            if args.command == "history":
                return _cmd_history(args, store)
            if args.command == "export":
                return _cmd_export(args, store)
            if args.command == "prune":
                return _cmd_prune(args, store)
    except ScoringCompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:
        # Downstream consumer (e.g. `llm-bid export | head`) closed the pipe.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return EXIT_OK
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


def _cmd_propose(
    args: argparse.Namespace,
    config: BiddingConfig,
    env: Mapping[str, str],
) -> int:
    if args.task_text is not None:
        task_text = args.task_text
        if not task_text.strip():
            raise ValueError("--task-text is empty.")
        if len(task_text.encode("utf-8")) > MAX_INTENT_BYTES:
            raise ValueError(f"Task input exceeds the {MAX_INTENT_BYTES} byte limit.")
    else:
        task_text = _read_input(args.task, max_bytes=MAX_INTENT_BYTES, label="Task")

    agent = config.agent(args.agent)
    context_entries = read_context_files(args.context)
    prompt = build_patch_prompt(
        task_text=task_text,
        context_entries=context_entries,
        actor_name=agent.name,
        supervisor_name=args.supervisor,
        auction_summary=args.auction_summary,
    )
    output = prompt if args.dry_run else request_patch_proposal(
        agent=agent, prompt=prompt, env=env
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(output)
            if not output.endswith("\n"):
                handle.write("\n")
        print(f"Wrote actor {'prompt' if args.dry_run else 'proposal'} to {args.output}.")
    else:
        print(output, end="" if output.endswith("\n") else "\n")
    return EXIT_OK


def _cmd_report(args: argparse.Namespace, store: HistoryStore) -> int:
    diff_score = None
    scope_drift = None
    gate_score = None
    intent_score = None
    if args.diff:
        diff_text = _read_input(args.diff, max_bytes=MAX_DIFF_BYTES, label="Diff")
        diff_result = score_result_diff(diff_text)
        diff_score = diff_result.score
        # Drift is judged against the intent stored at auction time.
        auction = store.get_auction(args.auction_id)
        intent_score = auction["intent_score"]
        scope_drift = detect_scope_drift(
            intent_score, auction["intent_band"], diff_result.score, diff_result.band
        )
        gate_score = max(intent_score, diff_result.score)
    report = OutcomeReport(
        auction_id=args.auction_id,
        success=bool(args.success),
        reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        notes=args.notes,
        diff_score=diff_score,
        actual_cost_usd=args.actual_cost,
        scope_drift=scope_drift,
        gate_score=gate_score,
    )
    store.record_outcome(report)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        outcome = "success" if report.success else "failure"
        extra = f", diff score {diff_score}" if diff_score is not None else ""
        if scope_drift:
            extra += f", SCOPE DRIFT (intent {intent_score} -> diff {diff_score})"
        print(f"Recorded {outcome} for auction {report.auction_id}{extra}.")
    return EXIT_OK


def _cmd_show(args: argparse.Namespace, store: HistoryStore) -> int:
    record = store.get_auction(args.auction_id)
    if args.format == "json":
        print(json.dumps(record, indent=2, sort_keys=True))
        return EXIT_OK
    lines = [
        f"Auction {record['id']}  ({record['created_at']})",
        f"Task: {record['task_text']}",
        f"Intent: score {record['intent_score']} | {record['intent_band']} | "
        + (", ".join(record["intent_signals"]) or "no signals"),
        f"Supervision: {record['recommended_mode'] or 'unknown'}"
        f"  (scored by agent-autonomy-score {record['scoring_version'] or 'unknown'})",
        f"Winner: {record['winner_agent'] or 'none'}",
        "",
    ]
    for bid in record["bids"]:
        if bid["error"]:
            lines.append(f"  {bid['agent_name']:<16}FAILED: {bid['error']}")
        else:
            line = (
                f"  {bid['agent_name']:<16}conf {bid['confidence']:.2f}"
                f"  cost ${bid['estimated_cost_usd']:.4f}  utility {bid['utility']:.3f}"
            )
            if bid["won"]:
                line += "  <- WINNER"
            elif bid["eligible"] == 0:
                line += f"  INELIGIBLE: {bid['ineligible_reason']}"
            lines.append(line)
    outcome = record["outcome"]
    if outcome is None:
        lines += ["", "Outcome: not reported yet"]
    else:
        status = "success" if outcome["success"] else "failure"
        lines += ["", f"Outcome: {status} ({outcome['reported_at']})"]
        if outcome["notes"]:
            lines.append(f"  notes: {outcome['notes']}")
        if outcome["diff_score"] is not None:
            drift = ""
            if outcome["scope_drift"]:
                drift = (
                    f"  SCOPE DRIFT (intent {record['intent_score']}"
                    f" -> diff {outcome['diff_score']})"
                )
            lines.append(
                f"  diff score {outcome['diff_score']},"
                f" gate score {outcome['gate_score']}{drift}"
            )
        if outcome["actual_cost_usd"] is not None:
            lines.append(f"  actual cost ${outcome['actual_cost_usd']:.4f}")
    print("\n".join(lines))
    return EXIT_OK


def _cmd_history(args: argparse.Namespace, store: HistoryStore) -> int:
    rows = store.list_recent(args.limit)
    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
        return EXIT_OK
    if not rows:
        print("No auctions recorded.")
        return EXIT_OK
    lines = [f"{'auction':<14}{'created':<27}{'band':<13}{'winner':<16}{'outcome'}"]
    for row in rows:
        outcome = "-" if row["outcome"] is None else ("ok" if row["outcome"] else "FAIL")
        lines.append(
            f"{row['auction_id']:<14}{row['created_at']:<27}"
            f"{row['intent_band']:<13}{row['winner'] or '-':<16}{outcome}"
        )
    print("\n".join(lines))
    return EXIT_OK


def _cmd_export(args: argparse.Namespace, store: HistoryStore) -> int:
    lines = (json.dumps(row, sort_keys=True) for row in store.export_rows())
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            count = 0
            for line in lines:
                handle.write(line + "\n")
                count += 1
        print(f"Exported {count} rows to {args.output}.")
    else:
        for line in lines:
            print(line)
    return EXIT_OK


def _cmd_prune(args: argparse.Namespace, store: HistoryStore) -> int:
    deleted = store.prune(args.keep_days)
    print(f"Deleted {deleted} auction(s) older than {args.keep_days} day(s).")
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
