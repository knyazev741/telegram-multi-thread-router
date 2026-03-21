#!/bin/bash
# Start the orchestrator session — creates a dedicated topic if needed
# and launches Claude Code bound to it.
#
# Usage: ./start-orchestrator.sh [thread_id]
# If thread_id is not provided, creates a new "Orchestrator" topic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
fi

THREAD_ID="${1:-}"

if [ -z "$THREAD_ID" ]; then
  echo "Creating Orchestrator topic..."
  RESPONSE=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/createForumTopic" \
    -d "chat_id=${OWNER_USER_ID}" \
    -d "name=🎛 Orchestrator")

  THREAD_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['message_thread_id'])")
  echo "Created topic: thread_id=$THREAD_ID"

  # Send initial message to make topic visible
  curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${OWNER_USER_ID}" \
    -d "message_thread_id=$THREAD_ID" \
    -d "text=Оркестратор запускается..." > /dev/null
fi

echo "Starting orchestrator session (thread_id=$THREAD_ID)..."
echo "ORCHESTRATOR_THREAD_ID=$THREAD_ID" >> "$REPO_DIR/.env" 2>/dev/null || true

cd "$REPO_DIR/orchestrator"
exec "$SCRIPT_DIR/start-session.sh" "$THREAD_ID" "$REPO_DIR/orchestrator" "tg-$THREAD_ID" "sonnet"
