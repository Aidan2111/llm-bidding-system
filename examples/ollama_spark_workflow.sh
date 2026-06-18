#!/usr/bin/env bash
# Manual local Spark actor workflow through Ollama. Not run in CI.
#
# Requires:
#   Ollama running with qwen3-coder:30b
#   Optional: export OLLAMA_BASE_URL=http://spark.local:11434
set -euo pipefail

CONFIG="${CONFIG:-examples/ollama-spark.config.json}"
TASK="${1:-Improve the README quickstart while keeping claims honest.}"
PYTHON="${PYTHON:-python3}"
BASE_URL="$("$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

base_url = os.environ.get("OLLAMA_BASE_URL")
if not base_url:
    raw_path = os.environ.get(
        "VSCODE_CHAT_MODELS_PATH",
        "~/Library/Application Support/Code/User/chatLanguageModels.json",
    )
    path = Path(raw_path).expanduser()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = []
        entries = payload if isinstance(payload, list) else []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("vendor") == "ollama":
                url = entry.get("url")
                if isinstance(url, str) and url.strip():
                    base_url = url
                    break
if not base_url:
    base_url = "http://localhost:11434"
base_url = base_url.rstrip("/")
if base_url.endswith("/api"):
    base_url = base_url[:-4]
print(base_url)
PY
)"
WORKDIR="$(mktemp -d)"
DB="$WORKDIR/ollama-spark-history.db"
PROPOSAL="$WORKDIR/spark-proposal.md"

echo "== checking Ollama at $BASE_URL =="
curl -fsS "$BASE_URL/api/tags" >/dev/null

echo "== spark live auction =="
OUTPUT=$(OLLAMA_BASE_URL="$BASE_URL" llm-bid --config "$CONFIG" --db "$DB" \
  --format json bid --intent-text "$TASK" --agents spark)
echo "$OUTPUT"

AUCTION_ID=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['auction_id'])")
SUMMARY=$(echo "$OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['summary'])")

echo "== spark patch proposal =="
OLLAMA_BASE_URL="$BASE_URL" llm-bid --config "$CONFIG" propose \
  --agent spark \
  --task-text "$TASK" \
  --auction-summary "$SUMMARY" \
  --context README.md \
  --context pyproject.toml \
  --context src/llm_bidding/cli.py \
  --output "$PROPOSAL"

echo "Proposal written to $PROPOSAL"
echo "Review it, apply only acceptable changes, run tests, then record the outcome:"
echo "llm-bid --config \"$CONFIG\" --db \"$DB\" report --auction-id \"$AUCTION_ID\" --success --notes \"supervised Spark patch accepted\""
