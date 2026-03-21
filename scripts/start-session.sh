#!/bin/bash
# Start a Claude Code session bound to a specific thread in tmux
# Usage: ./start-session.sh <thread_id> [workdir] [session_name]
#
# The session runs in tmux and survives SSH disconnects.
# Auto-confirms the development channels prompt.

THREAD_ID="$1"
WORKDIR="${2:-.}"
SESSION_NAME="${3:-tg-$THREAD_ID}"
PLUGIN_NAME="${PLUGIN_NAME:-telegram-multi@knyaz-private}"

if [ -z "$THREAD_ID" ]; then
  echo "Usage: $0 <thread_id> [working_directory] [tmux_session_name]"
  echo "Example: $0 42 /home/user/projects/api"
  exit 1
fi

# Resolve workdir
WORKDIR="$(cd "$WORKDIR" 2>/dev/null && pwd)" || { echo "Directory not found: $2"; exit 1; }

# Kill existing session with same name
tmux kill-session -t "$SESSION_NAME" 2>/dev/null

echo "Starting Claude Code session:"
echo "  Thread:    $THREAD_ID"
echo "  Directory: $WORKDIR"
echo "  tmux:      $SESSION_NAME"
echo "  Plugin:    $PLUGIN_NAME"

# Start in tmux
tmux new-session -d -s "$SESSION_NAME" -c "$WORKDIR" \
  "TELEGRAM_THREAD_ID=$THREAD_ID claude --dangerously-load-development-channels plugin:$PLUGIN_NAME --dangerously-skip-permissions"

# Wait for the development channels confirmation prompt and auto-confirm
sleep 3
tmux send-keys -t "$SESSION_NAME" Enter 2>/dev/null

# Wait for effort level prompt and select medium (option 1) if it appears
sleep 5
PANE_CONTENT=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null)
if echo "$PANE_CONTENT" | grep -q "medium effort"; then
  tmux send-keys -t "$SESSION_NAME" Enter 2>/dev/null
  sleep 2
fi

# Verify session is running
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo ""
  echo "✅ Session started!"
  echo ""
  echo "Commands:"
  echo "  tmux attach -t $SESSION_NAME   # connect to session"
  echo "  tmux ls                        # list all sessions"
  echo "  Ctrl+B, D                      # detach from session"
  echo "  tmux kill-session -t $SESSION_NAME  # stop session"
else
  echo "❌ Session failed to start"
  exit 1
fi
