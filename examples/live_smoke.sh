#!/usr/bin/env bash
# Manual smoke test against live provider APIs. Not run in CI.
#
# Requires:
#   pip install -e ".[all]"
#   export ANTHROPIC_API_KEY=...
#   export OPENAI_API_KEY=...
set -euo pipefail

TASK="Add a password reset migration to the auth service, including a rollback plan."
DB="$(mktemp -d)/smoke.db"

echo "== live auction (claude-sonnet vs gpt) =="
OUTPUT=$(llm-bid --db "$DB" --format json bid --intent-text "$TASK" --agents claude-sonnet,gpt)
echo "$OUTPUT"

AUCTION_ID=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['auction_id'])")
WINNER=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['winner']['agent_name'])")
echo "== winner: $WINNER (auction $AUCTION_ID) =="

echo "== reporting a success outcome =="
llm-bid --db "$DB" report --auction-id "$AUCTION_ID" --success --notes "smoke test"

echo "== stats =="
llm-bid --db "$DB" stats --agent "$WINNER"

echo "smoke test passed"
