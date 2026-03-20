# Telegram Multi-Thread Router

## Owner
**Knyaz** — developer, Bali (UTC+8). Communicate in Russian.

---

## Server Access

**Personal server**: `167.235.155.73` (Hetzner, Ubuntu)
- SSH alias: `ssh personal-server` (configured in `~/.ssh/config`)
- User: `root`
- SSH key auth (no password)

---

## Deployment

### Prerequisites on server
- Python 3.11+
- systemd for service management
- `.env` file with secrets (NEVER commit to repo)

### Deploy steps

1. **Clone repo on server**:
```bash
ssh personal-server
cd /root
git clone https://git.knyazevai.work/knyaz/telegram-multi-thread-router.git
cd telegram-multi-thread-router
```

2. **Create `.env`** (on server, never in repo):
```bash
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_API_ID=<from my.telegram.org>
TELEGRAM_API_HASH=<from my.telegram.org>
EOF
chmod 600 .env
```

3. **Install dependencies**:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. **Create systemd service**:
```bash
cat > /etc/systemd/system/telegram-multi-thread-router.service << 'EOF'
[Unit]
Description=Telegram Multi-Thread Router Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/telegram-multi-thread-router
ExecStart=/root/telegram-multi-thread-router/venv/bin/python main.py
EnvironmentFile=/root/telegram-multi-thread-router/.env
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

5. **Start**:
```bash
systemctl daemon-reload
systemctl enable telegram-multi-thread-router
systemctl start telegram-multi-thread-router
```

### Manage
```bash
# Status
systemctl status telegram-multi-thread-router

# Logs
journalctl -u telegram-multi-thread-router -f

# Restart (after deploy)
systemctl restart telegram-multi-thread-router
```

### Update code on server
```bash
ssh personal-server "cd /root/telegram-multi-thread-router && git pull gitea main && systemctl restart telegram-multi-thread-router"
```

---

## Gitea

- **Repo**: https://git.knyazevai.work/knyaz/telegram-multi-thread-router.git
- **Remote name**: `gitea`
- Push: `git push gitea main`

---

## Security
- All secrets in `.env` (gitignored), chmod 600
- No credentials in source code
- Server SSH key-only access
