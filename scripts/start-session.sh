#!/bin/bash
# Start a Claude Code session bound to a specific thread
# Usage: ./start-session.sh <thread_id> [workdir]

THREAD_ID="$1"
WORKDIR="${2:-.}"

if [ -z "$THREAD_ID" ]; then
  echo "Usage: $0 <thread_id> [working_directory]"
  echo "Example: $0 42 /home/user/projects/api"
  exit 1
fi

cd "$WORKDIR" || exit 1

echo "Starting Claude Code session for thread=$THREAD_ID in $(pwd)..."
TELEGRAM_THREAD_ID="$THREAD_ID" claude --channels plugin:telegram-multi@knyaz-private
