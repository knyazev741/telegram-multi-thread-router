"""Codex account usage fetcher.

Reads OAuth credentials from each account's auth.json and fetches live
5-hour + weekly rate-limit windows from the ChatGPT backend API.

Results are cached per account for CACHE_TTL seconds (default 5 min) to avoid
hammering the API on every session-creation request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# How long (seconds) to cache per-account usage data.
CACHE_TTL = 300  # 5 minutes

# Timeout for each HTTP request to the usage API.
REQUEST_TIMEOUT = 10  # seconds

# ChatGPT OAuth client_id used by the macOS Codex app.
_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class CodexWindowInfo:
    """One rate-limit window (5 h or weekly)."""

    used_percent: float          # 0–100; percentage of the window already consumed
    reset_at: datetime | None    # UTC datetime when the window resets
    window_seconds: int          # 18000 for 5 h, 604800 for weekly

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.used_percent)

    @property
    def resets_in_minutes(self) -> float | None:
        """Minutes until this window resets. None if reset_at is unknown."""
        if self.reset_at is None:
            return None
        now = datetime.now(tz=timezone.utc)
        delta = (self.reset_at - now).total_seconds() / 60.0
        return max(0.0, delta)


@dataclass
class CodexAccountUsage:
    """Usage snapshot for one Codex account."""

    account_name: str            # short label: "a4", "a3", "default", …
    codex_home: Path | None      # None  →  system default (~/.codex)
    primary: CodexWindowInfo | None    # 5-hour window
    secondary: CodexWindowInfo | None  # weekly window
    credits_balance: float | None      # USD balance, or None if unknown
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    error: str | None = None     # set when the fetch failed

    @property
    def has_data(self) -> bool:
        return self.error is None and (self.primary is not None or self.secondary is not None)


# ── Module-level cache ────────────────────────────────────────────────────────

# account_name → (CodexAccountUsage, monotonic timestamp)
_cache: dict[str, tuple[CodexAccountUsage, float]] = {}
_cache_lock = asyncio.Lock()


def invalidate_cache(account_name: str) -> None:
    """Remove a cached entry (call when a new session starts on this account)."""
    _cache.pop(account_name, None)


def clear_cache() -> None:
    """Wipe the entire usage cache (useful in tests)."""
    _cache.clear()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _auth_path(codex_home: Path | None) -> Path:
    base = codex_home if codex_home is not None else Path.home() / ".codex"
    return base / "auth.json"


def _config_base_url(codex_home: Path | None) -> str:
    """Read chatgpt_base_url from config.toml if present."""
    base = codex_home if codex_home is not None else Path.home() / ".codex"
    config = base / "config.toml"
    if config.exists():
        try:
            for line in config.read_text().splitlines():
                if "chatgpt_base_url" in line and "=" in line:
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        return val.rstrip("/")
        except Exception:
            pass
    return "https://chatgpt.com"


def _parse_window(raw: dict | None) -> CodexWindowInfo | None:
    if not raw:
        return None
    try:
        used_pct = float(raw.get("used_percent", 0))
        reset_ts = raw.get("reset_at")
        reset_dt = (
            datetime.fromtimestamp(reset_ts, tz=timezone.utc) if reset_ts else None
        )
        window_secs = int(raw.get("limit_window_seconds", 18000))
        return CodexWindowInfo(
            used_percent=used_pct,
            reset_at=reset_dt,
            window_seconds=window_secs,
        )
    except Exception as exc:
        logger.debug("Failed to parse window %r: %s", raw, exc)
        return None


def _http_get_json(url: str, headers: dict[str, str]) -> dict:
    """Synchronous GET → parsed JSON dict. Raises on HTTP / parse errors."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _http_post_json(url: str, body: dict, headers: dict[str, str] | None = None) -> dict:
    """Synchronous POST with JSON body → parsed JSON dict."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


# ── Token refresh ─────────────────────────────────────────────────────────────


def _refresh_token_sync(codex_home: Path | None, auth_data: dict) -> str | None:
    """Try to refresh the access token. Returns new access_token or None."""
    tokens = auth_data.get("tokens", {})
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None
    try:
        new_tokens = _http_post_json(
            "https://auth.openai.com/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _OAUTH_CLIENT_ID,
            },
        )
        new_access = new_tokens.get("access_token")
        if not new_access:
            return None

        # Persist updated tokens
        tokens["access_token"] = new_access
        if "refresh_token" in new_tokens:
            tokens["refresh_token"] = new_tokens["refresh_token"]
        auth_data["tokens"] = tokens
        auth_path = _auth_path(codex_home)
        auth_path.write_text(json.dumps(auth_data, indent=2))
        logger.info("Refreshed access token for codex_home=%s", codex_home)
        return new_access
    except Exception as exc:
        logger.warning("Token refresh failed for codex_home=%s: %s", codex_home, exc)
        return None


# ── Core fetch (sync, runs in thread pool) ────────────────────────────────────


def _fetch_usage_sync(codex_home: Path | None, account_name: str) -> CodexAccountUsage:
    """Fetch usage synchronously (called via asyncio.to_thread)."""
    ap = _auth_path(codex_home)
    if not ap.exists():
        return CodexAccountUsage(
            account_name=account_name,
            codex_home=codex_home,
            primary=None,
            secondary=None,
            credits_balance=None,
            error=f"No auth.json at {ap}",
        )

    try:
        auth_data = json.loads(ap.read_text())
    except Exception as exc:
        return CodexAccountUsage(
            account_name=account_name,
            codex_home=codex_home,
            primary=None,
            secondary=None,
            credits_balance=None,
            error=f"Cannot read auth.json: {exc}",
        )

    tokens = auth_data.get("tokens", {})
    access_token = tokens.get("access_token") or auth_data.get("access_token")
    account_id = tokens.get("account_id")

    if not access_token:
        return CodexAccountUsage(
            account_name=account_name,
            codex_home=codex_home,
            primary=None,
            secondary=None,
            credits_balance=None,
            error="No access_token in auth.json",
        )

    base_url = _config_base_url(codex_home)
    usage_url = f"{base_url}/backend-api/wham/usage"

    headers: dict[str, str] = {"Authorization": f"Bearer {access_token}"}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    # ── First attempt ──
    try:
        data = _http_get_json(usage_url, headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            # Try token refresh once
            new_token = _refresh_token_sync(codex_home, auth_data)
            if new_token:
                headers["Authorization"] = f"Bearer {new_token}"
                try:
                    data = _http_get_json(usage_url, headers)
                except Exception as exc2:
                    return CodexAccountUsage(
                        account_name=account_name,
                        codex_home=codex_home,
                        primary=None,
                        secondary=None,
                        credits_balance=None,
                        error=f"HTTP error after token refresh: {exc2}",
                    )
            else:
                return CodexAccountUsage(
                    account_name=account_name,
                    codex_home=codex_home,
                    primary=None,
                    secondary=None,
                    credits_balance=None,
                    error="HTTP 401: token expired, refresh failed",
                )
        else:
            return CodexAccountUsage(
                account_name=account_name,
                codex_home=codex_home,
                primary=None,
                secondary=None,
                credits_balance=None,
                error=f"HTTP {exc.code}",
            )
    except Exception as exc:
        return CodexAccountUsage(
            account_name=account_name,
            codex_home=codex_home,
            primary=None,
            secondary=None,
            credits_balance=None,
            error=str(exc),
        )

    # ── Parse response ──
    rate_limit = data.get("rate_limit", {})
    primary_raw = rate_limit.get("primary_window") or rate_limit.get("primary")
    secondary_raw = rate_limit.get("secondary_window") or rate_limit.get("secondary")
    credits_raw = data.get("credits", {})

    balance: float | None = None
    if isinstance(credits_raw, dict):
        raw_bal = credits_raw.get("balance")
        if raw_bal is not None:
            try:
                balance = float(raw_bal)
            except (TypeError, ValueError):
                pass

    return CodexAccountUsage(
        account_name=account_name,
        codex_home=codex_home,
        primary=_parse_window(primary_raw),
        secondary=_parse_window(secondary_raw),
        credits_balance=balance,
    )


# ── Public async API ──────────────────────────────────────────────────────────


async def fetch_account_usage(
    codex_home: Path | None,
    account_name: str = "default",
) -> CodexAccountUsage:
    """Fetch (or return cached) usage for one Codex account.

    Args:
        codex_home: Path to the CODEX_HOME directory, or None for system default.
        account_name: Human-readable label for cache keying and logging.
    """
    async with _cache_lock:
        cached = _cache.get(account_name)
        if cached is not None:
            usage, ts = cached
            if (time.monotonic() - ts) < CACHE_TTL:
                logger.debug("Cache hit for codex account '%s'", account_name)
                return usage

    # Fetch in thread pool to avoid blocking the event loop
    usage = await asyncio.to_thread(_fetch_usage_sync, codex_home, account_name)

    async with _cache_lock:
        _cache[account_name] = (usage, time.monotonic())

    if usage.error:
        logger.warning("Codex usage fetch failed for '%s': %s", account_name, usage.error)
    else:
        logger.info(
            "Codex usage for '%s': 5h=%.0f%% remaining, weekly=%.0f%% remaining",
            account_name,
            usage.primary.remaining_percent if usage.primary else float("nan"),
            usage.secondary.remaining_percent if usage.secondary else float("nan"),
        )

    return usage


async def fetch_all_accounts_usage(
    account_chain: list[Path | None],
    account_names: list[str],
) -> list[CodexAccountUsage]:
    """Fetch usage for all accounts in parallel.

    Args:
        account_chain: Ordered list of CODEX_HOME paths (None = system default).
        account_names: Matching list of short labels ("a4", "default", …).
    """
    tasks = [
        fetch_account_usage(path, name)
        for path, name in zip(account_chain, account_names)
    ]
    return list(await asyncio.gather(*tasks))


def path_to_account_name(path: Path | None) -> str:
    """Derive a short label from a CODEX_HOME path.

    Examples:
        Path("/root/.codex-a4") → "a4"
        Path("/root/.codex")    → "default"
        None                    → "default"
    """
    if path is None:
        return "default"
    name = path.name  # e.g. ".codex-a4" or ".codex"
    if name == ".codex":
        return "default"
    if name.startswith(".codex-"):
        return name[len(".codex-"):]
    return str(path)
