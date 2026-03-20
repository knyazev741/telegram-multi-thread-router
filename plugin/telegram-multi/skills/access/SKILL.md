---
name: telegram-multi:access
description: Access control is handled by the central Proxy. This skill shows how to configure it.
allowed_tools:
  - Read
---

# /telegram-multi:access

Access control for Telegram Multi-Thread is handled at the Proxy level.

## How it works

The Proxy checks `OWNER_USER_ID` from its `.env` file. Only messages from this Telegram user ID are accepted and routed to sessions.

## Configuration

Edit the Proxy's `.env` file (on the server where the Proxy runs):

```
BOT_TOKEN=123456789:AAH...
OWNER_USER_ID=123456789
```

To find your Telegram user ID, message @userinfobot on Telegram.

## No pairing needed

Unlike the standard Telegram plugin, this multi-thread version doesn't use a pairing flow. The Proxy filters by owner ID before any message reaches a session.
