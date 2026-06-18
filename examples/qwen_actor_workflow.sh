#!/usr/bin/env bash
# Manual Qwen Coder actor workflow through OpenRouter. Not run in CI.
#
# Requires:
#   pip install -e ".[openai]"
#   export OPENROUTER_API_KEY=...
set -euo pipefail

CONFIG="${CONFIG:-examples/qwen-openrouter.config.json}"
TASK="${1:-Improve the README quickstart while keeping claims honest.}"
WORKDIR="$(mktemp -d)"
DB="$WORKDIR/qwen-history.db"
PROPOSAL="$WORKDIR/qwen-proposal.md"

echo "== qwen-coder live auction =="
OUTPUT=$(llm-bid --config "$CONFIG" --db "$DB" --format json bid \
  --intent-text "$TASK" --agents qwen-coder)
echo "$OUTPUT"

AUCTION_ID=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['auction_id'])")
SUMMARY=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['summary'])")

echo "== qwen-coder patch proposal =="
llm-bid --config "$CONFIG" propose \
  --agent qwen-coder \
  --task-text "$TASK" \
  --auction-summary "$SUMMARY" \
  --context README.md \
  --context pyproject.toml \
  --context src/llm_bidding/cli.py \
  --output "$PROPOSAL"

echo "Proposal written to $PROPOSAL"
echo "Review it, apply only acceptable changes, run tests, then record the outcome:"
echo "llm-bid --config \"$CONFIG\" --db \"$DB\" report --auction-id \"$AUCTION_ID\" --success --notes \"supervised patch accepted\""
