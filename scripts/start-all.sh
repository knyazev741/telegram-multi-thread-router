#!/bin/bash
# Start Proxy + all configured sessions in tmux
# Edit the SESSIONS array below to match your setup.
#
# Format: "thread_id|name|workdir"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_DIR="$SCRIPT_DIR/../proxy"

# ── Configure your sessions here ──
SESSIONS=(
  # "42|backend-api|/root/projects/api"
  # "87|frontend|/root/projects/web"
  # "93|devops|/root/infra"
)

# ── Start Proxy ──
tmux new-session -d -s claude-proxy -c "$PROXY_DIR" "bun run start"
echo "✅ Proxy started"
sleep 2

# ── Start Sessions ──
for entry in "${SESSIONS[@]}"; do
  IFS='|' read -r thread_id name workdir <<< "$entry"
  tmux new-window -t claude-proxy -n "$name" \
    "cd $workdir && TELEGRAM_THREAD_ID=$thread_id claude --dangerously-load-development-channels plugin:telegram-multi@knyaz-private"
  echo "✅ Session '$name' started (thread: $thread_id, dir: $workdir)"
  sleep 1
done

echo ""
echo "All started. Attach with: tmux attach -t claude-proxy"
