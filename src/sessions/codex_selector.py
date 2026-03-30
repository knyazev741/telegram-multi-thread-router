"""Smart Codex account selector.

Scores each available account based on four factors:

  1. 5h window headroom  — can we start a session right now?
  2. Active-session penalty — discount for already-busy accounts
  3. Urgency bonus — extra score when a window is about to expire
     (budget × elapsed_fraction = "% at risk of being wasted")
  4. Drain bonus — extra score for accounts that are partially depleted
     so we finish them off rather than leaving a few percent unused

Urgency intuition
-----------------
If 80% weekly is left and the window resets in 2 hours we *must* use it
now or lose that budget.

    elapsed_fraction = (window_minutes - resets_in_minutes) / window_minutes
    urgency = remaining_pct × elapsed_fraction   →  "budget at risk"

Drain intuition
---------------
Without a drain bonus the base formula (score = 5h × weekly/100) always
prefers fresh 100% accounts over a partially-depleted 20% account, so the
system spreads load evenly and every account sits at ~20–30% — nobody
drains to 0.

The drain bonus kicks in below DRAIN_THRESHOLD_PCT and grows as the account
approaches 0 %:

    drain_position = 1 − (weekly_remaining / DRAIN_THRESHOLD_PCT)   # 0→1
    drain_bonus    = DRAIN_STRENGTH × adjusted_5h × drain_position

Effect: an account at 15% weekly beats a fresh 100% account once drain_bonus
is large enough to overcome the lower base score.  After the account is
drained to ~0% it becomes disqualified (MIN_WEEKLY_REMAINING) and the system
moves on to the next one.

Usage
-----
    from src.sessions.codex_selector import score_accounts, select_best

    scores = score_accounts(usages, active_counts)
    best   = select_best(scores)
    chosen_home = best.codex_home
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.sessions.codex_usage import CodexAccountUsage

logger = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────

# Cost subtracted from effective 5h headroom for each session that was active
# on this account in the last 30 minutes.
ACTIVE_SESSION_PENALTY: float = 25.0

# Minimum adjusted 5h headroom below which an account is "disqualified".
MIN_5H_HEADROOM: float = 15.0

# Minimum weekly remaining % below which an account is "disqualified".
# Kept deliberately low (1%) so drain logic can push accounts to near-zero
# before disqualifying them.
MIN_WEEKLY_REMAINING: float = 1.0

# If the 5h window resets within this many minutes, treat it as fully available.
SOON_RESET_MINUTES: float = 30.0

# Score used for accounts whose usage data could not be fetched.
UNKNOWN_DATA_SCORE: float = 30.0

# How strongly urgency (budget-about-to-expire) boosts the score.
# urgency_bonus = URGENCY_WEIGHT × (weekly_urgency + fiveh_urgency)
URGENCY_WEIGHT: float = 0.5

# Weekly remaining % below which the drain bonus activates.
# At 40% or below, the system starts preferring the account to finish it off.
DRAIN_THRESHOLD_PCT: float = 40.0

# How strongly the drain bonus is applied.
# drain_bonus = DRAIN_STRENGTH × adjusted_5h × drain_position
# where drain_position ∈ [0, 1] (0 at threshold, 1 at 0%).
# With 1.5 an account at 20% weekly will beat a fresh 80% account when
# both have equal 5h headroom.
DRAIN_STRENGTH: float = 1.5


# ── AccountScore ──────────────────────────────────────────────────────────────


@dataclass
class AccountScore:
    """Scoring result for one Codex account."""

    account_name: str
    codex_home: Path | None

    # Intermediate values (useful for the usage-report MCP tool)
    raw_5h_remaining: float
    effective_5h: float              # after soon-reset correction
    adjusted_5h: float               # after active-session penalty
    weekly_remaining: float
    active_count: int
    resets_in_minutes: float | None          # 5h window
    weekly_resets_in_minutes: float | None

    # Score components
    urgency_5h: float       # 5h budget at risk of expiry (0-100)
    urgency_weekly: float   # weekly budget at risk of expiry (0-100)
    drain_bonus: float      # drain encouragement (0 when above threshold)

    # Final verdict
    score: float
    is_qualified: bool
    disqualify_reason: str | None

    def summary(self) -> str:
        """One-line human-readable summary."""
        q = "✅" if self.is_qualified else "❌"
        reset_str = (
            f"{self.resets_in_minutes:.0f}min" if self.resets_in_minutes is not None else "?"
        )
        reason = f" [{self.disqualify_reason}]" if self.disqualify_reason else ""
        extras: list[str] = []
        if self.urgency_weekly > 5 or self.urgency_5h > 5:
            extras.append(f"urgency=5h:{self.urgency_5h:.0f}+wk:{self.urgency_weekly:.0f}")
        if self.drain_bonus > 1:
            extras.append(f"drain={self.drain_bonus:.0f}")
        extra_str = (" " + " ".join(extras)) if extras else ""
        return (
            f"{q} {self.account_name}: score={self.score:.1f} "
            f"5h={self.adjusted_5h:.0f}%(resets in {reset_str}) "
            f"weekly={self.weekly_remaining:.0f}% "
            f"active={self.active_count}{extra_str}{reason}"
        )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _elapsed_fraction(resets_in_minutes: float | None, window_minutes: float) -> float:
    """Fraction of the window that has already elapsed (0 = just reset, 1 = about to reset).

    Returns 0.5 (neutral) when reset time is unknown.
    """
    if resets_in_minutes is None:
        return 0.5
    elapsed = window_minutes - resets_in_minutes
    return max(0.0, min(1.0, elapsed / window_minutes))


# ── Scoring logic ─────────────────────────────────────────────────────────────


def score_account(usage: CodexAccountUsage, active_count: int) -> AccountScore:
    """Compute an AccountScore for a single account."""
    # ── No data / error path ──────────────────────────────────────────────────
    if not usage.has_data:
        return AccountScore(
            account_name=usage.account_name,
            codex_home=usage.codex_home,
            raw_5h_remaining=50.0,
            effective_5h=50.0,
            adjusted_5h=max(0.0, 50.0 - active_count * ACTIVE_SESSION_PENALTY),
            weekly_remaining=50.0,
            active_count=active_count,
            resets_in_minutes=None,
            weekly_resets_in_minutes=None,
            urgency_5h=0.0,
            urgency_weekly=0.0,
            drain_bonus=0.0,
            score=UNKNOWN_DATA_SCORE,
            is_qualified=True,
            disqualify_reason=None,
        )

    # ── 5h window ────────────────────────────────────────────────────────────
    resets_in: float | None = None
    if usage.primary is not None:
        raw_5h = usage.primary.remaining_percent
        resets_in = usage.primary.resets_in_minutes
        if resets_in is not None and resets_in <= SOON_RESET_MINUTES:
            effective_5h = 100.0
        else:
            effective_5h = raw_5h
    else:
        raw_5h = 50.0
        effective_5h = 50.0

    # ── Active-session penalty ────────────────────────────────────────────────
    adjusted_5h = max(0.0, effective_5h - active_count * ACTIVE_SESSION_PENALTY)

    # ── Weekly window ─────────────────────────────────────────────────────────
    weekly_resets_in: float | None = None
    if usage.secondary is not None:
        weekly_remaining = usage.secondary.remaining_percent
        weekly_resets_in = usage.secondary.resets_in_minutes
    else:
        weekly_remaining = 50.0

    # ── Urgency bonus ─────────────────────────────────────────────────────────
    if effective_5h == 100.0 and resets_in is not None and resets_in <= SOON_RESET_MINUTES:
        urgency_5h = 0.0  # already maxed via soon-reset
    else:
        frac_5h = _elapsed_fraction(resets_in, window_minutes=300.0)
        urgency_5h = adjusted_5h * frac_5h

    frac_weekly = _elapsed_fraction(weekly_resets_in, window_minutes=10080.0)
    urgency_weekly = weekly_remaining * frac_weekly

    urgency_bonus = URGENCY_WEIGHT * (urgency_weekly + urgency_5h)

    # ── Drain bonus ───────────────────────────────────────────────────────────
    # Activates below DRAIN_THRESHOLD_PCT and grows linearly toward 0 %.
    # This ensures we finish off a partially-depleted account rather than
    # abandoning it and leaving a few percent unused.
    if 0 < weekly_remaining < DRAIN_THRESHOLD_PCT:
        drain_position = 1.0 - (weekly_remaining / DRAIN_THRESHOLD_PCT)
        drain_bonus = DRAIN_STRENGTH * adjusted_5h * drain_position
    else:
        drain_bonus = 0.0

    # ── Final score ───────────────────────────────────────────────────────────
    base_score = adjusted_5h * (weekly_remaining / 100.0)
    score = base_score + urgency_bonus + drain_bonus

    # ── Disqualification ─────────────────────────────────────────────────────
    disqualify_reason: str | None = None
    if weekly_remaining < MIN_WEEKLY_REMAINING:
        disqualify_reason = (
            f"weekly nearly depleted ({weekly_remaining:.1f}% left)"
        )
    elif adjusted_5h < MIN_5H_HEADROOM:
        reset_str = (
            f"resets in {resets_in:.0f}min" if resets_in is not None else "reset time unknown"
        )
        disqualify_reason = (
            f"5h headroom too low ({adjusted_5h:.0f}%, {reset_str})"
        )

    return AccountScore(
        account_name=usage.account_name,
        codex_home=usage.codex_home,
        raw_5h_remaining=raw_5h,
        effective_5h=effective_5h,
        adjusted_5h=adjusted_5h,
        weekly_remaining=weekly_remaining,
        active_count=active_count,
        resets_in_minutes=resets_in,
        weekly_resets_in_minutes=weekly_resets_in,
        urgency_5h=urgency_5h,
        urgency_weekly=urgency_weekly,
        drain_bonus=drain_bonus,
        score=score,
        is_qualified=disqualify_reason is None,
        disqualify_reason=disqualify_reason,
    )


def score_accounts(
    usages: list[CodexAccountUsage],
    active_counts: dict[str, int],
) -> list[AccountScore]:
    """Score all accounts and return the list sorted best-first."""
    results: list[AccountScore] = []
    for usage in usages:
        db_key = str(usage.codex_home) if usage.codex_home is not None else "default"
        cnt = active_counts.get(db_key, 0)
        results.append(score_account(usage, cnt))

    results.sort(key=lambda s: (not s.is_qualified, -s.score))

    for s in results:
        logger.debug("Codex account scored: %s", s.summary())

    return results


def select_best(scores: list[AccountScore]) -> AccountScore | None:
    """Pick the best account from a pre-scored list."""
    if not scores:
        return None

    qualified = [s for s in scores if s.is_qualified]
    if qualified:
        best = qualified[0]
        logger.info(
            "Selected Codex account '%s' (score=%.1f, 5h=%.0f%%, weekly=%.0f%%, "
            "drain=%.0f, urgency=5h:%.0f+wk:%.0f, active=%d)",
            best.account_name, best.score, best.adjusted_5h, best.weekly_remaining,
            best.drain_bonus, best.urgency_5h, best.urgency_weekly, best.active_count,
        )
        return best

    logger.warning("All Codex accounts disqualified; picking best fallback")
    with_reset = [s for s in scores if s.resets_in_minutes is not None]
    if with_reset:
        fallback = min(with_reset, key=lambda s: s.resets_in_minutes)  # type: ignore[arg-type]
    else:
        fallback = scores[0]

    logger.warning(
        "Fallback Codex account '%s' (score=%.1f, reason: %s)",
        fallback.account_name, fallback.score, fallback.disqualify_reason,
    )
    return fallback
