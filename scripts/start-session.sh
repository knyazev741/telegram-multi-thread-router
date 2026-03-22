#!/bin/bash
# Start a Claude Code session bound to a specific thread in tmux
# Usage: ./start-session.sh <thread_id> [workdir] [session_name] [model] [resume_id]
#
# The session runs in tmux and survives SSH disconnects.
# Auto-confirms the development channels prompt.

# Ensure common tool paths are available (needed for non-interactive SSH on macOS)
for dir in /opt/homebrew/bin "$HOME/.local/bin"; do
  [ -d "$dir" ] && export PATH="$dir:$PATH"
done

THREAD_ID="$1"
WORKDIR="${2:-.}"
SESSION_NAME="${3:-tg-$THREAD_ID}"
MODEL="${4:-opus}"
RESUME_ID="$5"
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
echo "  Model:     $MODEL"
echo "  tmux:      $SESSION_NAME"
echo "  Plugin:    $PLUGIN_NAME"
[ -n "$RESUME_ID" ] && echo "  Resume:    $RESUME_ID"

# Build claude command (--dangerously-skip-permissions not allowed as root)
CLAUDE_CMD="export PATH='$PATH' && TELEGRAM_THREAD_ID=$THREAD_ID claude --model $MODEL"
if [ -n "$RESUME_ID" ]; then
  CLAUDE_CMD="$CLAUDE_CMD --resume $RESUME_ID"
fi
CLAUDE_CMD="$CLAUDE_CMD --dangerously-load-development-channels plugin:$PLUGIN_NAME"
if [ "$(id -u)" -ne 0 ]; then
  CLAUDE_CMD="$CLAUDE_CMD --dangerously-skip-permissions"
fi

# Start in tmux (pass full PATH so child processes like bun are found)
tmux new-session -d -s "$SESSION_NAME" -c "$WORKDIR" "$CLAUDE_CMD"

# Wait for the development channels confirmation prompt and auto-confirm
# Poll until prompt appears (up to 30s) instead of fixed sleep
for i in $(seq 1 30); do
  sleep 1
  PANE_CONTENT=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null)
  if echo "$PANE_CONTENT" | grep -q "local development\|dangerously-load-development"; then
    tmux send-keys -t "$SESSION_NAME" Enter 2>/dev/null
    break
  fi
done

# Wait for effort level prompt and select medium if it appears
for i in $(seq 1 15); do
  sleep 1
  PANE_CONTENT=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null)
  if echo "$PANE_CONTENT" | grep -q "medium effort\|effort level"; then
    tmux send-keys -t "$SESSION_NAME" Enter 2>/dev/null
    break
  fi
  # Session is ready if we see the input prompt
  if echo "$PANE_CONTENT" | grep -q "for shortcuts\|❯"; then
    break
  fi
done

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
