# Telegram Multi-Thread Router

Run multiple Claude Code sessions through Telegram bot topics. Each topic = isolated Claude agent you can talk to directly in the bot chat.

```
Bot Chat (private, with you)
├── General Topic        → Bot management commands (/new, /list, /sessions)
├── Topic "backend"      → Claude Code session working on backend
├── Topic "frontend"     → Claude Code session working on frontend
└── Topic "devops"       → Claude Code session working on infra
```

## Features

- **Multi-session**: Run many Claude Code instances, each bound to a bot topic
- **Voice messages**: Automatic transcription via faster-whisper
- **Typing indicator**: Shows "typing..." while Claude works
- **Delivery confirmation**: 👀 reaction when message reaches the session
- **File support**: Send/receive photos and documents
- **Remote sessions**: Run Claude Code locally or on a server — both connect to the same proxy
- **Auto-reconnect**: Sessions reconnect automatically if connection drops
- **Session notifications**: Proxy automatically sends `✅ Session connected` to the topic when a session registers
- **Terminal commands**: Send `/clear`, `/compact`, `/reset` in a topic — forwarded to tmux without AI processing
- **Orchestration**: Run a dedicated Claude Code session that manages all other sessions on demand
- **Session metadata**: Topics registry tracks server, workdir, and Claude conversation ID per session

## Architecture

```
┌─────────────┐     TCP/9600     ┌─────────────────┐     Telegram API
│ Claude Code  │◄───────────────►│  Proxy (server)  │◄──────────────►  Telegram
│  + Plugin    │                 │  - Bot           │
│  (session 1) │                 │  - IPC Server    │
├─────────────┤                 │  - Transcriber   │
│  (session 2) │◄───────────────►│                  │
└─────────────┘                 └─────────────────┘
        ▲
        │  (optional)
┌─────────────┐
│ Orchestrator │  ← Claude Code session that manages other sessions
│   session    │    Creates topics, launches sessions on demand
└─────────────┘
```

## Prerequisites

- **Server** (for the Proxy): Linux with [Bun](https://bun.sh), Python 3.11+, ffmpeg
- **Local** (for Claude Code sessions): [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code), [Bun](https://bun.sh)
- Telegram Bot token (from [@BotFather](https://t.me/BotFather))

## Setup

### 1. Create Bot and Enable Topics

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → save the token
2. Open the **BotFather Mini App** (not the text commands — the mini app UI)
3. Select your bot → enable **Topics** mode for private chats
4. Optionally disable "Allow users to create topics" if you want only the bot to manage topics
5. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot)

> **Note**: Bot topics (Bot API 9.3+) work directly in the private chat between you and the bot. No group needed.

### 2. Deploy Proxy on Server

```bash
git clone https://github.com/knyazev741/telegram-multi-thread-router.git
cd telegram-multi-thread-router

# Create .env
cp .env.example .env
# Edit .env — set BOT_TOKEN, OWNER_USER_ID, AUTH_TOKEN, PUBLIC_HOST

# Install proxy dependencies
cd proxy && bun install && cd ..

# Install faster-whisper for voice transcription
pip3 install faster-whisper

# Make sure bun is in system PATH (needed for plugin subprocess)
which bun || ln -sf ~/.bun/bin/bun /usr/local/bin/bun

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
# Register the marketplace and install plugin (once)
claude plugin add --marketplace /path/to/telegram-multi-thread-router
```

After installing, the plugin appears in `/mcp` as `plugin:telegram-multi:telegram-multi`.

### 4. Configure Plugin

Create `~/.claude/channels/telegram-multi/.env` on each machine that will run sessions:

```bash
mkdir -p ~/.claude/channels/telegram-multi
cat > ~/.claude/channels/telegram-multi/.env << 'EOF'
TELEGRAM_PROXY_HOST=YOUR_SERVER_IP
TELEGRAM_PROXY_PORT=9600
TELEGRAM_AUTH_TOKEN=same-token-as-proxy
EOF
```

If running sessions on the same server as the proxy, `TELEGRAM_PROXY_HOST` defaults to `127.0.0.1`.

> **Mac behind NAT**: If your Mac shares an IP with other machines, multiple sessions will conflict on the proxy. Fix: add `-L 9600:localhost:9600` to your SSH reverse tunnel so Mac sessions connect via `127.0.0.1`. Then set `TELEGRAM_PROXY_HOST=127.0.0.1` in the plugin config.

### 5. Launch a Session

Open your bot in Telegram. In the **General Topic**, send:

```
/new My Session
```

The bot creates a topic and shows the launch command in monospace (ready to copy).

Run it in your terminal:

```bash
TELEGRAM_THREAD_ID=42 claude \
  --dangerously-load-development-channels plugin:telegram-multi@telegram-multi-thread \
  --dangerously-skip-permissions
```

Now send messages in that topic — Claude will respond!

## Usage

### Bot Commands (in General Topic)

| Command | Description |
|---|---|
| `/new <name>` | Create a new topic + show launch command |
| `/list` | Show all topics with connection status (🟢/🔴) |
| `/sessions` | Show active sessions with uptime |
| `/close <thread_id>` | Kill session, delete topic, clean registry |
| `/help` | Show help |

### Terminal Commands (in any topic)

Send these directly in a topic — the proxy forwards them to the tmux session without AI processing:

| Command | Effect |
|---|---|
| `/clear` | Clear Claude's conversation history |
| `/compact` | Compact/summarize the conversation |
| `/reset` | Reset the session |
| `/doctor` | Run Claude diagnostics |

The proxy reacts with 👌 on success or ❌ on failure.

### Message Types

| Type | Handling |
|---|---|
| Text | Sent directly to Claude |
| Voice | Transcribed via faster-whisper, sent as text |
| Photo | Downloaded to server, path passed to Claude |
| Document | Downloaded to server, path passed to Claude |

### Status Indicators

- **👀 reaction** on your message = delivered to Claude session
- **"typing..."** animation = Claude is processing
- **✅ Session connected** in topic = session just registered with proxy
- **🟢** in `/list` = session connected
- **🔴** in `/list` = no active session

## Orchestration

Run a dedicated Claude Code session as an **orchestrator** — it manages all other sessions on demand, across multiple servers.

The orchestrator is just a regular Claude Code session launched in `orchestrator/` with `orchestrator/CLAUDE.md` as its instructions. It can:
- Create Telegram topics and launch sessions on any server via SSH
- Monitor session health and restart crashed sessions
- Close sessions (kill tmux + delete topic + clean registry)

### Setting up the Orchestrator

1. Create a topic for the orchestrator (via `/new Orchestrator` in General Topic)
2. Customize `orchestrator/CLAUDE.md` with your servers and repos
3. Launch Claude Code in the `orchestrator/` directory:

```bash
TELEGRAM_THREAD_ID=<thread_id> claude \
  --dangerously-load-development-channels plugin:telegram-multi@telegram-multi-thread \
  --dangerously-skip-permissions
```

### start-session.sh

The `scripts/start-session.sh` script starts Claude Code in a named tmux session and auto-confirms startup prompts:

```bash
# Usage: start-session.sh <thread_id> [workdir] [session_name] [model]
./scripts/start-session.sh 42 /path/to/repo my-session opus
```

### Session Metadata

The proxy tracks metadata for each session in `proxy/data/topics.json`:

```json
{
  "threadId": 42,
  "name": "backend",
  "server": "remote-server",
  "workdir": "/root/backend",
  "sessionId": "uuid-of-claude-conversation"
}
```

Use `scripts/get-session-id.sh <workdir>` to find the Claude conversation ID after launch.

## RAM & Swap

If sessions run heavy workloads (e.g. C++ compilation), add swap to prevent OOM kills (exit 137):

```bash
fallocate -l 8G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## Troubleshooting

### Plugin shows "failed" in `/mcp`

`bun` is not in the system PATH. Fix:
```bash
ln -sf ~/.bun/bin/bun /usr/local/bin/bun
```

### `--dangerously-skip-permissions` fails with root

Allow tools explicitly in `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash", "Read", "Write", "Edit", "Glob", "Grep",
              "mcp__plugin_telegram-multi_telegram-multi__*"]
  }
}
```

### Voice transcription is slow

Adjust model in `proxy/scripts/transcribe.py`:

| Model | Size | Speed (CPU) | Quality |
|---|---|---|---|
| `base` | 150MB | Fast | OK for English |
| `small` | 500MB | Medium | Decent |
| `medium` | 1.5GB | Slow | Good for most languages |
| `large-v3` | 3GB | Very slow | Best quality |

### Sessions keep disconnecting

1. Check firewall: `ufw allow 9600/tcp`
2. Check proxy: `systemctl status telegram-multi-proxy`
3. Plugin auto-reconnects every 3 seconds
4. If exit 137 — add swap (see RAM section)

### Bot doesn't see topics / messages

- Enable **Topics mode** in BotFather Mini App
- Verify `OWNER_USER_ID` matches your Telegram user ID
- Check logs: `journalctl -u telegram-multi-proxy -f`

## Project Structure

```
telegram-multi-thread-router/
├── proxy/                      # Central Telegram proxy (runs on server)
│   ├── src/
│   │   ├── index.ts            # Entry point, env config
│   │   ├── bot.ts              # Telegram bot, message routing, typing/reactions
│   │   ├── commands.ts         # /new, /list, /sessions, /close, /help
│   │   ├── ipc-server.ts       # TCP server for Claude Code sessions
│   │   ├── topics-registry.ts  # Persistent topic storage (JSON)
│   │   ├── file-handler.ts     # Download files from Telegram CDN
│   │   └── types.ts            # TypeScript types
│   └── scripts/
│       └── transcribe.py       # Voice → text (faster-whisper)
├── plugin/telegram-multi/      # Claude Code MCP channel plugin
│   ├── server.ts               # MCP server, TCP client to proxy
│   ├── .mcp.json               # MCP server config
│   └── .claude-plugin/
│       └── plugin.json         # Plugin metadata
├── orchestrator/
│   └── CLAUDE.md               # Instructions for the orchestrator session
├── scripts/
│   ├── start-proxy.sh          # Start proxy
│   ├── start-session.sh        # Start Claude Code session in tmux
│   └── get-session-id.sh       # Get Claude conversation ID for a workdir
├── .env.example                # Environment template
└── CLAUDE.md
```

## License

MIT
