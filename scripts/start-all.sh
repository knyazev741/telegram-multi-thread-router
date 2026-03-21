#!/bin/bash
# Start Proxy + all configured sessions in tmux
# Edit the SESSIONS array below to match your setup.
#
# Format: "thread_id|name|workdir"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_DIR="$SCRIPT_DIR/../proxy"
PLUGIN_NAME="${PLUGIN_NAME:-telegram-multi@knyaz-private}"

# ── Configure your sessions here ──
SESSIONS=(
  # "42|backend-api|/root/projects/api"
  # "87|frontend|/root/projects/web"
  # "93|devops|/root/infra"
)

# ── Start Proxy ──
tmux new-session -d -s claude-proxy -c "$PROXY_DIR" "bun run start"
echo "✅ Proxy started"
sleep 3

# ── Start Sessions ──
for entry in "${SESSIONS[@]}"; do
  IFS='|' read -r thread_id name workdir <<< "$entry"

  "$SCRIPT_DIR/start-session.sh" "$thread_id" "$workdir" "tg-$name"
  sleep 2
done

echo ""
echo "All started. tmux ls to see sessions."
