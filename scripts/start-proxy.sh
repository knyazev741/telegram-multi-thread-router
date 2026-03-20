#!/bin/bash
# Start the Telegram Multi-Thread Proxy
# Usage: ./start-proxy.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_DIR="$SCRIPT_DIR/../proxy"

cd "$PROXY_DIR" || exit 1

if ! command -v bun &>/dev/null; then
  echo "Error: bun is not installed. Install with: curl -fsSL https://bun.sh/install | bash"
  exit 1
fi

echo "Starting Telegram Multi-Thread Proxy..."
bun run start
