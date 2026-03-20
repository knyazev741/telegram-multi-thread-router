# Telegram Multi-Thread Router

Run multiple Claude Code sessions through Telegram forum topics. Each topic = isolated Claude agent you can talk to via Telegram.

```
Telegram Forum Group
├── General Topic        → Bot management commands (/new, /list, /sessions)
├── Topic "backend"      → Claude Code session working on backend
├── Topic "frontend"     → Claude Code session working on frontend
└── Topic "devops"       → Claude Code session working on infra
```

## Features

- **Multi-session**: Run many Claude Code instances, each bound to a forum topic
- **Voice messages**: Automatic transcription via faster-whisper
- **Typing indicator**: Shows "typing..." while Claude works
- **Delivery confirmation**: 👀 reaction when message reaches the session
- **File support**: Send/receive photos and documents
- **Remote sessions**: Run Claude Code locally or on a server — both connect to the same proxy
- **Auto-reconnect**: Sessions reconnect automatically if connection drops

## Architecture

```
┌─────────────┐     TCP/9600     ┌─────────────────┐     Telegram API
│ Claude Code  │◄───────────────►│  Proxy (server)  │◄──────────────►  Telegram
│  + Plugin    │                 │  - Bot           │
│  (session 1) │                 │  - IPC Server    │
├─────────────┤                 │  - Transcriber   │
│  (session 2) │◄───────────────►│                  │
└─────────────┘                 └─────────────────┘
```

## Prerequisites

- **Server** (for the Proxy): Linux with Node.js/Bun, Python 3.11+, ffmpeg
- **Local** (for Claude Code sessions): [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code), Bun
- Telegram Bot token (from [@BotFather](https://t.me/BotFather))
- Telegram group with **Forum Topics enabled**

## Setup

### 1. Create Telegram Bot & Group

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → save the token
2. Create a Telegram group, enable **Topics** (Group Settings → Topics)
3. Add your bot to the group as **admin**
4. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot)

### 2. Deploy Proxy on Server

```bash
git clone https://github.com/YOUR_USERNAME/telegram-multi-thread-router.git
cd telegram-multi-thread-router

# Create .env
cp .env.example .env
# Edit .env — set BOT_TOKEN, OWNER_USER_ID, AUTH_TOKEN, PUBLIC_HOST

# Install proxy dependencies
cd proxy && bun install && cd ..

# Install faster-whisper for voice transcription
pip3 install faster-whisper

# Make sure bun is in PATH for the plugin subprocess
which bun || ln -s $(find / -name bun -type f 2>/dev/null | head -1) /usr/local/bin/bun

# Start proxy
cd proxy && bun run start
```

#### Environment variables (.env)

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `OWNER_USER_ID` | Yes | Your Telegram user ID (only you can use the bot) |
| `AUTH_TOKEN` | Yes | Shared secret for session authentication |
| `IPC_PORT` | No | TCP port for sessions (default: 9600) |
| `PUBLIC_HOST` | No | Server's public IP — shown in launch commands for remote sessions |
| `PLUGIN_NAME` | No | Plugin identifier (default: `telegram-multi@telegram-multi-thread`) |

#### Run as systemd service (recommended)

```bash
cat > /etc/systemd/system/telegram-multi-proxy.service << 'EOF'
[Unit]
Description=Telegram Multi-Thread Router Proxy
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/telegram-multi-thread-router/proxy
ExecStart=/usr/local/bin/bun run start
EnvironmentFile=/path/to/telegram-multi-thread-router/.env
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now telegram-multi-proxy
```

### 3. Install Plugin on Claude Code

```bash
# Register the marketplace (once)
claude plugin add --marketplace /path/to/telegram-multi-thread-router

# Or install from GitHub
claude plugin add --marketplace https://github.com/YOUR_USERNAME/telegram-multi-thread-router
```

### 4. Configure Plugin

Create `~/.claude/channels/telegram-multi/.env`:

```bash
mkdir -p ~/.claude/channels/telegram-multi
cat > ~/.claude/channels/telegram-multi/.env << 'EOF'
TELEGRAM_PROXY_HOST=YOUR_SERVER_IP
TELEGRAM_PROXY_PORT=9600
TELEGRAM_AUTH_TOKEN=same-token-as-proxy
EOF
```

### 5. Launch a Session

In the Telegram group's **General Topic**, send `/new My Session` — the bot creates a topic and shows the launch command.

Copy and run it:

```bash
TELEGRAM_THREAD_ID=42 claude --dangerously-load-development-channels plugin:telegram-multi@telegram-multi-thread --dangerously-skip-permissions
```

Now send messages in that Telegram topic — Claude will respond!

## Usage

### Bot Commands (General Topic)

| Command | Description |
|---|---|
| `/new <name>` | Create a new topic + show launch command |
| `/list` | Show all topics with connection status |
| `/sessions` | Show active sessions with uptime |
| `/help` | Show help |

### Message Types

- **Text**: Sent directly to Claude
- **Voice**: Transcribed via faster-whisper, then sent as text
- **Photos**: Downloaded and passed to Claude with file path
- **Documents**: Downloaded and passed to Claude with file path

### Running Multiple Sessions

Use tmux on the server:

```bash
# Edit scripts/start-all.sh with your sessions
SESSIONS=(
  "42|backend|/home/user/backend"
  "87|frontend|/home/user/frontend"
)

# Start everything
./scripts/start-all.sh
```

Or use the helper script:

```bash
./scripts/start-session.sh <thread_id> [working_directory]
```

## Troubleshooting

### Plugin shows "failed" in /mcp

**Bun not in PATH**: Claude Code starts the plugin as a subprocess. If `bun` isn't in the system PATH, it fails silently.

```bash
# Fix: create symlink
ln -sf ~/.bun/bin/bun /usr/local/bin/bun
```

### `--dangerously-skip-permissions` fails with root

This flag is blocked when running as root. Instead, allow tools in `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash", "Read", "Write", "Edit", "Glob", "Grep",
      "mcp__plugin_telegram-multi_telegram-multi__*"
    ]
  }
}
```

### Voice transcription slow

The default model is `medium` (good for Russian and most languages). For faster transcription, edit `proxy/scripts/transcribe.py` and change `MODEL_SIZE` to `"base"` or `"small"`. For better quality, use `"large-v3"`.

### Sessions disconnect

TCP keepalive is enabled. If sessions still drop:
- Check firewall allows port 9600
- Check proxy is running: `systemctl status telegram-multi-proxy`
- Plugin auto-reconnects every 3 seconds

### Plugin not receiving messages

Check proxy logs for session registration:
```bash
journalctl -u telegram-multi-proxy -f
# Should show: [IPC] Session registered: thread=42
```

## Project Structure

```
├── proxy/                  # Central Telegram proxy (runs on server)
│   ├── src/
│   │   ├── index.ts        # Entry point
│   │   ├── bot.ts          # Telegram bot + message routing
│   │   ├── commands.ts     # /new, /list, /sessions, /help
│   │   ├── ipc-server.ts   # TCP server for session connections
│   │   ├── topics-registry.ts  # Persistent topic storage
│   │   ├── file-handler.ts # Telegram file downloads
│   │   └── types.ts        # Shared types
│   └── scripts/
│       └── transcribe.py   # Voice transcription (faster-whisper)
├── plugin/telegram-multi/  # Claude Code plugin (MCP channel)
│   ├── server.ts           # Plugin MCP server
│   ├── .mcp.json           # MCP config
│   └── skills/             # /configure, /access skills
├── scripts/                # Helper scripts
│   ├── start-proxy.sh
│   ├── start-session.sh
│   └── start-all.sh
├── .env.example            # Environment template
└── CLAUDE.md               # Project instructions
```

## License

MIT
