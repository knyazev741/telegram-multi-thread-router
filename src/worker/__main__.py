"""Worker entry point: python -m src.worker

Reads configuration from environment variables and starts the WorkerClient
reconnect loop. The worker connects to the central bot's IPC server, authenticates,
and manages local Claude sessions.

Required env vars:
  AUTH_TOKEN   — shared secret with the bot (must match bot's AUTH_TOKEN)
  WORKER_ID    — unique name for this worker (e.g. "server-paris")

Optional env vars:
  IPC_HOST     — bot IPC host (default: 127.0.0.1)
  IPC_PORT     — bot IPC port (default: 9800)
"""

import asyncio
import logging
import os
import sys


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    host = os.environ.get("IPC_HOST", "127.0.0.1")
    port = int(os.environ.get("IPC_PORT", "9800"))
    auth_token = os.environ.get("AUTH_TOKEN")
    worker_id = os.environ.get("WORKER_ID")

    if not auth_token:
        print("AUTH_TOKEN env var required", file=sys.stderr)
        sys.exit(1)
    if not worker_id:
        print("WORKER_ID env var required", file=sys.stderr)
        sys.exit(1)

    from src.worker.client import WorkerClient

    client = WorkerClient(
        host=host,
        port=port,
        auth_token=auth_token,
        worker_id=worker_id,
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass


main()
