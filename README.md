# llm-bidding-system

An auction router for LLM work. Multiple LLM agents (e.g. Claude Opus, Claude
Sonnet, a GPT model) **bid** on a piece of work, and a configurable utility
function picks the winner. Each bid combines three ingredients:

1. **A live self-assessment** — each model is shown the task and asked for a
   structured bid: confidence (0–1), a brief approach, estimated tokens, and an
   effort class.
2. **Deterministic risk context** from
   [agent-autonomy-score](https://github.com/aidan2111/agent-autonomy-score) —
   the task's intent is scored 1–10 into a risk band (Low / Medium / High Risk)
   with named signals; the bidders see it, and it drives the risk-fit term.
3. **Historical track record** — every auction, bid, and reported outcome is
   stored in SQLite. Win rates, calibration-adjusted confidence, and per-band
   success rates feed back into future auctions.

This repo is an **auction-only router**: it picks the winner and tells you why.
Execution happens elsewhere; you report the outcome back, which closes the
feedback loop.

```
              ┌────────────────────────────────────────────────┐
 task text ──▶│ score_intent()  (agent-autonomy-score)         │
              └──────────────┬─────────────────────────────────┘
                             │ risk band + signals
              ┌──────────────▼──────────────┐
              │ each agent bids (LLM call)  │  confidence, approach,
              │ claude-opus / sonnet / gpt  │  est. tokens, effort
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐     ┌──────────────────┐
              │ utility scoring             │◀───▶│ history (SQLite) │
              │ quality / price / risk-fit  │     │ auctions, bids,  │
              └──────────────┬──────────────┘     │ outcomes         │
                             │ winner              └────────▲────────┘
                             ▼                              │
                  you run the work elsewhere ── report ─────┘
```

## Install

```bash
pip install -e .                 # core (pulls agent-autonomy-score from GitHub)
pip install -e ".[anthropic]"    # + Anthropic SDK for live Claude bids
pip install -e ".[openai]"       # + OpenAI SDK for live GPT bids
pip install -e ".[all]"          # both
```

For local development against a sibling checkout of the scoring repo:

```bash
pip install -e ../agent-autonomy-score
pip install -e . --no-deps
```

## Quick start (no API keys needed)

`--dry-run` swaps every provider for a deterministic offline mock and persists
nothing, so you can see the full mechanics immediately:

```bash
llm-bid bid --intent-text "Refactor the global auth token persistence \
architecture with a destructive migration" --dry-run
```

```
Auction 3f2c61a09b7e  (2026-06-10T17:21:09+00:00)
Intent: score 9 | High Risk | intent:critical-domain, intent:state-or-persistence, ...

agent             conf   cal   cost $  quality  price   fit  utility
claude-sonnet     0.74  0.74   0.0142    0.644  0.993 0.500    0.671  <- WINNER
claude-opus       0.62  0.62   0.0303    0.572  0.985 0.500    0.633
gpt               0.55  0.55   0.0098    0.530  0.995 0.500    0.614

claude-sonnet wins with utility 0.671 (confidence 0.74, ...) on a High Risk task (intent score 9).
```

## Live auctions and the feedback loop

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...

# 1. Run a real auction (recorded to ~/.llm-bidding/history.db)
llm-bid bid --intent task.md
llm-bid bid --intent task.md --format json          # machine-readable, full breakdown
llm-bid bid --intent task.md --agents claude-sonnet,gpt

# 2. Do the work with the winning model, then report how it went.
#    Optionally hand back the diff — it gets scored with score_change()
#    and stored alongside the outcome.
llm-bid report --auction-id 3f2c61a09b7e --success --diff pr.diff --actual-cost 0.42
llm-bid report --auction-id 9911aa22bb33 --failure --notes "rolled back"

# 3. Inspect what history has learned
llm-bid stats
llm-bid stats --agent claude-opus --band "High Risk"
llm-bid agents list

# 4. Operate the history database
llm-bid show --auction-id 3f2c61a09b7e     # full stored auction + outcome
llm-bid history --limit 20                  # recent auctions at a glance
llm-bid export --output history.jsonl      # everything as JSONL
llm-bid prune --keep-days 90               # delete old auctions
```

Exit codes: `0` winner selected, `2` no winner (no valid bids, or the policy
abstained), `1` error.

## How the winner is picked

Every component is normalized to 0–1 and surfaced in `--format json`, so a
decision is always auditable:

```
quality  = 0.6 * calibrated_confidence + 0.4 * success_rate
price    = 1 - min(estimated_cost_usd / cost_ceiling_usd, 1)
risk_fit = success rate within the task's risk band
           (falls back to the overall rate below 3 band samples)

utility  = 0.5 * quality + 0.2 * price + 0.3 * risk_fit
```

- **`calibrated_confidence`** is the stated confidence shifted by the agent's
  calibration offset: `mean(outcome − stated confidence)` over auctions it won,
  clamped to ±0.2 and applied only after 3 reported outcomes. Agents that bid
  high and fail get pushed down.
- **`success_rate`** is shrunk toward a neutral prior of 0.5
  (`(successes + 2) / (outcomes + 4)`), so a brand-new agent starts neutral —
  never punished, never favored.
- **Cost** comes from the bid's token estimates priced against the per-model
  price table in the config.
- Ties break deterministically: lower cost, then agent name.

All weights, the quality mix, the cost ceiling, the price table, and the
calibration constants live in [`llm-bidding.config.json`](llm-bidding.config.json)
(pass yours with `--config`). Prices in the default config are examples — keep
them in sync with your providers' current pricing.

### Cost calibration

Models are unreliable estimators of their own token usage, so reported actual
costs feed back into pricing: each agent's actual/estimated cost ratio (mean
over reported outcomes, shrunk toward a neutral 1.0 and clamped to
`[0.25, 4.0]`) multiplies its future cost estimates before the price score.
An agent that habitually estimates 3x under its real cost stops winning on
price. Cold start is exactly 1.0 — estimates pass through untouched until you
report `--actual-cost` values.

### Decision policy (optional, off by default)

On top of utility scoring, the `policy` config section adds award rules:

- **High Risk floor** — on High Risk tasks, an agent must clear
  `min_band_success_rate` (its proven track record in that band) *or*
  `min_calibrated_confidence` to be eligible to win. Ineligible bids stay in
  the output, marked `INELIGIBLE` with the failed checks.
- **Abstain** — if the best eligible utility is below `min_award_utility`,
  no winner is declared (exit 2 with the reason). Useful when "send it to a
  human" beats "award it to a mediocre bid".
- **`selection_mode: "cheapest_adequate"`** — instead of argmax utility, pick
  the *cheapest* eligible bid whose quality clears `adequacy_min_quality`.
  This is the "don't buy the flagship model by default" mode: quality is a
  bar to clear, not a score to maximize.

### Supervision recommendation

Every auction also surfaces agent-autonomy-score's recommended supervision
mode for the task (`Unsupervised` / `Guided Autonomy` / `Pair Programming`),
so the router tells you not just *who* should do the work but *how closely
to watch them*.

### Can an agent game it?

An agent that always bids confidence 1.0 wins early (history starts neutral),
but every reported failure simultaneously drags down its shrunk success rate
and its calibration offset. After `min_calibration_samples` outcomes an
overconfident agent is bidding with a −0.2 confidence penalty and a sub-neutral
history — honesty is the stable strategy. The loop only works if you actually
report outcomes.

## Using it as a library

```python
from llm_bidding import HistoryStore, load_config, run_auction
from llm_bidding.providers import build_providers

config = load_config()  # or load_config("my-config.json")
providers = build_providers(config, dry_run=True)  # dry_run=False for live bids

with HistoryStore(":memory:") as store:
    result = run_auction("Migrate the auth schema", config, providers, store)
    print(result.summary)
    for bid in result.bids:
        print(bid.agent_name, bid.utility, bid.error)
```

`run_auction` accepts injectable `clock` and `id_factory` seams, and any object
implementing `request_bid(agent, request) -> Bid` works as a provider, so the
whole system is testable offline.

## Robustness layers

- **Scoring integration is firewalled.** `llm_bidding/scoring.py` is the only
  module that imports `autonomy_score` — every band name, signal name, and
  scoring call goes through it. On first use it runs a compatibility probe
  against the installed dependency (API surface + band/mode vocabulary) and
  raises a loud `ScoringCompatibilityError` if the pinned dep has drifted,
  instead of silently mis-bucketing history. Each auction records the scoring
  version it was scored under, so history stays auditable across dependency
  bumps. A custom `autonomy_score_config` must come from a write-protected
  source (its terms drive risk banding); a warning is emitted if the file is
  group/world-writable.
- **Bids run in parallel** with a shared per-wave timeout
  (`providers.timeout_seconds`); a hung provider becomes a recorded timeout
  failure, never a hung auction. Transient errors (429/5xx/connection drops)
  are retried with backoff (`providers.retries`); auth, dependency, and
  validation errors fail immediately.
- **Statistical fast path** (`fast_path.skip_bids_for_low_risk`): Low Risk
  tasks can skip LLM bid calls entirely — bids are synthesized from each
  agent's historical success rate, making routine tasks free to route.
- **Scope drift detection**: when a reported diff scores ≥3 points above the
  original intent (or escalates a risk band), the outcome is flagged
  `SCOPE DRIFT` and counted in `stats`. It is informational — penalizing
  drift stays a human judgment via `--failure` — because drift is sometimes
  legitimate discovered complexity.
- **Schema migrations**: the SQLite store versions its schema and upgrades
  v1 databases in place; old rows keep working (new columns read as NULL).
  WAL mode + busy timeout handle concurrent CLI invocations.

## History schema

A single SQLite file (default `~/.llm-bidding/history.db`, overridable via
`--db`, `LLM_BIDDING_DB`, or the config). Schema v2:

- `auctions` — id, timestamp, task text, intent score/band, **signal names as
  JSON** (so future risk-fit can move from band-level to signal-level without a
  migration), utility weights used, winner, scoring version, recommended
  supervision mode.
- `bids` — per-agent confidence, approach, cost estimate, utility component
  breakdown, won flag, eligibility (+ reason), or the provider error if the
  bid failed.
- `outcomes` — one per auction: success/failure, notes, optional
  `score_change()` diff score, gate score and scope-drift flag, optional
  actual cost.

## Development

```bash
PYTHONPATH=src:../agent-autonomy-score/src python -m unittest discover -s tests
```

The suite is fully offline: deterministic mock providers, in-memory SQLite, no
API keys. `examples/live_smoke.sh` is an optional manual smoke test that does
hit real APIs.

## License

MIT
