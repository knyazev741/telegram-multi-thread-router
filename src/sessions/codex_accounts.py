"""Codex multi-account fallback chain.

Supports multiple Codex CLI accounts (each with its own ~/.codex-<name> directory
and auth.json). Accounts are tried in order; the first one that exists on disk is used.

Configuration via CODEX_ACCOUNTS env var (comma-separated):
  CODEX_ACCOUNTS=a4,a3,a2,a1,default

Shorthands:
  "a4"      → ~/.codex-a4
  "default" → ~/.codex   (the global installation)
  "/path"   → literal absolute path

If CODEX_ACCOUNTS is empty or unset, behaves as if only "default" is configured
(i.e. no CODEX_HOME override, uses whatever codex picks up normally).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_CODEX_HOME = Path.home() / ".codex"


def expand_account_name(name: str) -> Path:
    """Expand a short account name to its CODEX_HOME path.

    >>> expand_account_name("a4")
    PosixPath('/root/.codex-a4')
    >>> expand_account_name("default")
    PosixPath('/root/.codex')
    >>> expand_account_name("/custom/path")
    PosixPath('/custom/path')
    """
    name = name.strip()
    if name == "default":
        return _DEFAULT_CODEX_HOME
    if name.startswith("/"):
        return Path(name)
    # Shorthand: "a4" → ~/.codex-a4
    return Path.home() / f".codex-{name}"


def validate_account(path: Path) -> bool:
    """Check that an account directory exists and has auth.json."""
    if not path.is_dir():
        return False
    if not (path / "auth.json").exists():
        logger.debug("Codex account %s has no auth.json, skipping", path)
        return False
    return True


def get_codex_account_chain(codex_accounts_setting: str = "") -> list[Path | None]:
    """Return an ordered list of CODEX_HOME paths to try.

    Each entry is a Path to set as CODEX_HOME, or None meaning
    "don't override CODEX_HOME" (use the system default).

    Args:
        codex_accounts_setting: Value of CODEX_ACCOUNTS from settings.
            If empty, returns [None] (system default only).

    Returns:
        List of valid account paths (filtered to those that exist on disk),
        with None appended as ultimate fallback if not explicitly included.
    """
    raw = codex_accounts_setting.strip()
    if not raw:
        # No config → just use system default (no CODEX_HOME override)
        return [None]

    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return [None]

    chain: list[Path | None] = []
    has_default = False

    for name in names:
        path = expand_account_name(name)

        if name == "default" or path == _DEFAULT_CODEX_HOME:
            has_default = True
            # For the default codex home, we use None (no override)
            # so it works even if ~/.codex doesn't follow our expected structure
            chain.append(None)
            continue

        if validate_account(path):
            chain.append(path)
        else:
            logger.info(
                "Codex account '%s' (%s) not found on this machine, skipping",
                name,
                path,
            )

    # Always ensure there's a fallback to system default if not explicitly listed
    if not has_default and None not in chain:
        chain.append(None)

    if not chain:
        chain.append(None)

    return chain
