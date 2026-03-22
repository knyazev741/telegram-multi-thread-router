#!/bin/bash
# Get the latest Claude conversation ID for a given working directory
# Usage: get-session-id.sh <workdir>
WORKDIR="${1:-.}"
WORKDIR="$(cd "$WORKDIR" 2>/dev/null && pwd)"

# Claude stores sessions in ~/.claude/projects/<encoded-path>/
# Encoded path replaces / with - and strips leading /
ENCODED=$(echo "$WORKDIR" | sed 's|^/||; s|/|-|g')
SESSION_DIR="$HOME/.claude/projects/-$ENCODED"

if [ ! -d "$SESSION_DIR" ]; then
  # Try without leading dash
  SESSION_DIR="$HOME/.claude/projects/$ENCODED"
fi

if [ ! -d "$SESSION_DIR" ]; then
  echo ""
  exit 0
fi

# Get most recently modified .jsonl file
LATEST=$(ls -t "$SESSION_DIR"/*.jsonl 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo ""
  exit 0
fi

# Extract session ID from filename
basename "$LATEST" .jsonl
