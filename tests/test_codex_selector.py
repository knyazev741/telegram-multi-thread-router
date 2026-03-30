"""Unit tests for the Codex smart account selector."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.sessions.codex_usage import CodexAccountUsage, CodexWindowInfo
from src.sessions.codex_selector import (
    ACTIVE_SESSION_PENALTY,
    DRAIN_STRENGTH,
    DRAIN_THRESHOLD_PCT,
    MIN_5H_HEADROOM,
    MIN_WEEKLY_REMAINING,
    SOON_RESET_MINUTES,
    URGENCY_WEIGHT,
    AccountScore,
    _elapsed_fraction,
    score_account,
    score_accounts,
    select_best,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _future(minutes: float) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)


def _window(remaining_pct: float, resets_in_minutes: float | None = 120) -> CodexWindowInfo:
    reset_at = _future(resets_in_minutes) if resets_in_minutes is not None else None
    return CodexWindowInfo(used_percent=100.0 - remaining_pct, reset_at=reset_at, window_seconds=18000)


def _weekly(remaining_pct: float, resets_in_minutes: float | None = 6000) -> CodexWindowInfo:
    reset_at = _future(resets_in_minutes) if resets_in_minutes is not None else None
    return CodexWindowInfo(used_percent=100.0 - remaining_pct, reset_at=reset_at, window_seconds=604800)


def _usage(
    name: str,
    *,
    fiveh_remaining: float = 80.0,
    fiveh_resets_in: float | None = 120,
    weekly_remaining: float = 90.0,
    weekly_resets_in: float | None = 6000,
    codex_home: Path | None = None,
    error: str | None = None,
) -> CodexAccountUsage:
    if error:
        return CodexAccountUsage(
            account_name=name, codex_home=codex_home,
            primary=None, secondary=None, credits_balance=None, error=error,
        )
    return CodexAccountUsage(
        account_name=name, codex_home=codex_home,
        primary=_window(fiveh_remaining, fiveh_resets_in),
        secondary=_weekly(weekly_remaining, weekly_resets_in),
        credits_balance=15.0,
    )


# ── _elapsed_fraction ─────────────────────────────────────────────────────────

class TestElapsedFraction:
    def test_just_reset(self):
        assert _elapsed_fraction(300.0, 300.0) == pytest.approx(0.0)

    def test_about_to_reset(self):
        assert _elapsed_fraction(0.0, 300.0) == pytest.approx(1.0)

    def test_halfway(self):
        assert _elapsed_fraction(150.0, 300.0) == pytest.approx(0.5)

    def test_none_returns_neutral(self):
        assert _elapsed_fraction(None, 300.0) == pytest.approx(0.5)

    def test_clamped_at_zero(self):
        assert _elapsed_fraction(400.0, 300.0) == pytest.approx(0.0)

    def test_clamped_at_one(self):
        assert _elapsed_fraction(-5.0, 300.0) == pytest.approx(1.0)


# ── score_account — base behaviour ────────────────────────────────────────────

class TestScoreAccount:
    def test_healthy_account_no_active_sessions(self):
        u = _usage("a4", fiveh_remaining=80, weekly_remaining=90)
        s = score_account(u, active_count=0)
        assert s.is_qualified
        assert s.disqualify_reason is None
        assert s.score > 0

    def test_active_session_reduces_adjusted_5h(self):
        u = _usage("a3", fiveh_remaining=80, weekly_remaining=90)
        s = score_account(u, active_count=1)
        assert s.adjusted_5h == pytest.approx(80.0 - ACTIVE_SESSION_PENALTY)

    def test_adjusted_5h_never_negative(self):
        u = _usage("a1", fiveh_remaining=10, weekly_remaining=90)
        s = score_account(u, active_count=10)
        assert s.adjusted_5h == 0.0

    def test_disqualified_when_5h_headroom_too_low(self):
        u = _usage("a4", fiveh_remaining=20, weekly_remaining=90, fiveh_resets_in=180)
        s = score_account(u, active_count=1)
        assert not s.is_qualified
        assert "5h headroom" in s.disqualify_reason

    def test_disqualified_when_weekly_below_min(self):
        u = _usage("a4", fiveh_remaining=80, weekly_remaining=0.5)
        s = score_account(u, active_count=0)
        assert not s.is_qualified
        assert "weekly" in s.disqualify_reason

    def test_low_weekly_still_qualified_above_min(self):
        """1.5% weekly > MIN_WEEKLY_REMAINING(1%) → still qualified, drain bonus active."""
        u = _usage("a4", fiveh_remaining=80, weekly_remaining=1.5)
        s = score_account(u, active_count=0)
        assert s.is_qualified
        assert s.drain_bonus > 0

    def test_soon_to_reset_treated_as_full(self):
        u = _usage("a3", fiveh_remaining=5, fiveh_resets_in=20, weekly_remaining=90)
        s = score_account(u, active_count=0)
        assert s.effective_5h == pytest.approx(100.0)
        assert s.is_qualified

    def test_soon_reset_urgency_5h_zeroed(self):
        u = _usage("a3", fiveh_remaining=5, fiveh_resets_in=20, weekly_remaining=90)
        s = score_account(u, active_count=0)
        assert s.urgency_5h == pytest.approx(0.0)

    def test_error_account_gets_unknown_score(self):
        u = _usage("a1", error="HTTP 500")
        s = score_account(u, active_count=0)
        assert s.is_qualified
        assert s.score == pytest.approx(30.0)  # UNKNOWN_DATA_SCORE


# ── Drain bonus ───────────────────────────────────────────────────────────────

class TestDrainBonus:
    def test_no_drain_above_threshold(self):
        """Above DRAIN_THRESHOLD_PCT, drain_bonus is 0."""
        u = _usage("a4", fiveh_remaining=80, weekly_remaining=DRAIN_THRESHOLD_PCT + 1)
        s = score_account(u, active_count=0)
        assert s.drain_bonus == pytest.approx(0.0)

    def test_drain_zero_at_exact_threshold(self):
        """At exactly DRAIN_THRESHOLD_PCT, drain_position=0 → drain_bonus=0."""
        u = _usage("a4", fiveh_remaining=80, weekly_remaining=DRAIN_THRESHOLD_PCT)
        s = score_account(u, active_count=0)
        assert s.drain_bonus == pytest.approx(0.0)

    def test_drain_grows_as_weekly_decreases(self):
        u_20 = _usage("a4", fiveh_remaining=80, weekly_remaining=20)
        u_10 = _usage("a4", fiveh_remaining=80, weekly_remaining=10)
        u_5  = _usage("a4", fiveh_remaining=80, weekly_remaining=5)

        s_20 = score_account(u_20, 0)
        s_10 = score_account(u_10, 0)
        s_5  = score_account(u_5,  0)

        assert s_20.drain_bonus < s_10.drain_bonus < s_5.drain_bonus

    def test_drain_formula(self):
        """drain_bonus = DRAIN_STRENGTH × adjusted_5h × (1 − weekly/DRAIN_THRESHOLD)"""
        adj_5h = 80.0
        weekly = 20.0
        u = _usage("a4", fiveh_remaining=adj_5h, weekly_remaining=weekly)
        s = score_account(u, active_count=0)

        drain_position = 1.0 - weekly / DRAIN_THRESHOLD_PCT
        expected = DRAIN_STRENGTH * adj_5h * drain_position
        assert s.drain_bonus == pytest.approx(expected, abs=1.0)

    def test_drain_shrinks_with_less_5h_headroom(self):
        """Drain bonus is proportional to 5h headroom — no point draining if 5h is empty."""
        u_high = _usage("a4", fiveh_remaining=80, weekly_remaining=10)
        u_low  = _usage("a4", fiveh_remaining=30, weekly_remaining=10)
        assert score_account(u_high, 0).drain_bonus > score_account(u_low, 0).drain_bonus

    def test_drain_causes_depleted_account_to_beat_fresh(self):
        """Core requirement: 20% weekly account beats fresh 80% when drain kicks in."""
        depleted = _usage("a4", fiveh_remaining=80, weekly_remaining=20,
                          fiveh_resets_in=200, weekly_resets_in=2000)
        fresh    = _usage("a3", fiveh_remaining=80, weekly_remaining=80,
                          fiveh_resets_in=200, weekly_resets_in=8000)

        s_dep   = score_account(depleted, 0)
        s_fresh = score_account(fresh, 0)

        assert s_dep.score > s_fresh.score, (
            f"depleted({s_dep.score:.1f}) should beat fresh({s_fresh.score:.1f})"
        )

    def test_drain_to_near_zero_still_preferred(self):
        """An account at 3% should be picked over 80% fresh to drain the last scraps."""
        scraps = _usage("a4", fiveh_remaining=80, weekly_remaining=3,
                        fiveh_resets_in=200, weekly_resets_in=3000)
        fresh  = _usage("a3", fiveh_remaining=80, weekly_remaining=80,
                        fiveh_resets_in=200, weekly_resets_in=8000)

        scores = score_accounts([scraps, fresh], active_counts={})
        best = select_best(scores)
        assert best is not None
        assert best.account_name == "a4"

    def test_fully_empty_account_disqualified(self):
        """Account at 0% (below MIN_WEEKLY_REMAINING) gets disqualified."""
        empty = _usage("a4", fiveh_remaining=80, weekly_remaining=0.5)
        s = score_account(empty, 0)
        assert not s.is_qualified


# ── Urgency bonus ─────────────────────────────────────────────────────────────

class TestUrgencyBonus:
    def test_urgency_weekly_high_when_about_to_reset(self):
        u = _usage("a4", fiveh_remaining=80, fiveh_resets_in=200,
                   weekly_remaining=80, weekly_resets_in=30)
        s = score_account(u, active_count=0)
        assert s.urgency_weekly > 75.0

    def test_urgency_weekly_low_when_just_reset(self):
        u = _usage("a4", fiveh_remaining=80, fiveh_resets_in=200,
                   weekly_remaining=80, weekly_resets_in=10079)
        s = score_account(u, active_count=0)
        assert s.urgency_weekly < 0.1

    def test_urgency_causes_correct_ranking(self):
        usages = [
            _usage("a4", fiveh_remaining=80, fiveh_resets_in=200,
                   weekly_remaining=80, weekly_resets_in=9000),
            _usage("a3", fiveh_remaining=80, fiveh_resets_in=200,
                   weekly_remaining=80, weekly_resets_in=60),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a3"

    def test_urgency_weight_zero_no_urgency_contribution(self, monkeypatch):
        monkeypatch.setattr("src.sessions.codex_selector.URGENCY_WEIGHT", 0.0)
        u = _usage("a4", fiveh_remaining=80, fiveh_resets_in=60,
                   weekly_remaining=50, weekly_resets_in=60)
        s = score_account(u, active_count=0)
        # No urgency, no drain (weekly=50 > threshold=40)
        assert s.score == pytest.approx(80.0 * 0.50, abs=0.5)


# ── score_accounts ─────────────────────────────────────────────────────────────

class TestScoreAccounts:
    def test_sorted_best_first(self):
        usages = [
            _usage("a1", fiveh_remaining=20, weekly_remaining=50),
            _usage("a4", fiveh_remaining=90, weekly_remaining=90),
            _usage("a3", fiveh_remaining=60, weekly_remaining=70),
        ]
        scores = score_accounts(usages, active_counts={})
        assert scores[0].account_name == "a4"

    def test_qualified_before_disqualified(self):
        usages = [
            _usage("a4", fiveh_remaining=90, weekly_remaining=0.5),  # disqualified
            _usage("a3", fiveh_remaining=30, weekly_remaining=80),
        ]
        scores = score_accounts(usages, active_counts={})
        assert scores[0].account_name == "a3"

    def test_active_counts_mapped_by_db_key(self):
        home = Path("/root/.codex-a4")
        usages = [_usage("a4", fiveh_remaining=80, weekly_remaining=90, codex_home=home)]
        scores = score_accounts(usages, active_counts={str(home): 2})
        assert scores[0].adjusted_5h == pytest.approx(max(0.0, 80.0 - 2 * ACTIVE_SESSION_PENALTY))

    def test_empty_returns_empty(self):
        assert score_accounts([], {}) == []


# ── select_best ────────────────────────────────────────────────────────────────

class TestSelectBest:
    def test_none_for_empty(self):
        assert select_best([]) is None

    def test_picks_highest_score(self):
        usages = [
            _usage("a1", fiveh_remaining=20, weekly_remaining=50),
            _usage("a4", fiveh_remaining=90, weekly_remaining=90),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a4"

    def test_all_disqualified_picks_soonest_5h_reset(self):
        usages = [
            _usage("a4", fiveh_remaining=5, fiveh_resets_in=120, weekly_remaining=90),
            _usage("a3", fiveh_remaining=5, fiveh_resets_in=45,  weekly_remaining=90),
            _usage("a2", fiveh_remaining=5, fiveh_resets_in=200, weekly_remaining=90),
        ]
        scores = score_accounts(usages, {})
        assert all(not s.is_qualified for s in scores)
        best = select_best(scores)
        assert best is not None
        assert best.account_name == "a3"


# ── Integration / real-world scenarios ────────────────────────────────────────

class TestRealWorldScenarios:
    def test_four_accounts_typical(self):
        a2_home = Path("/root/.codex-a2")
        usages = [
            _usage("a4", fiveh_remaining=80, fiveh_resets_in=240, weekly_remaining=70),
            _usage("a3", fiveh_remaining=30, fiveh_resets_in=60,  weekly_remaining=90),
            _usage("a2", fiveh_remaining=40, fiveh_resets_in=180, weekly_remaining=50,
                   codex_home=a2_home),
            _usage("a1", fiveh_remaining=10, fiveh_resets_in=30,  weekly_remaining=60),
        ]
        scores = score_accounts(usages, active_counts={str(a2_home): 2})

        a2_score = next(s for s in scores if s.account_name == "a2")
        assert not a2_score.is_qualified  # 2 active → adjusted=0 < MIN_5H_HEADROOM

        a1_score = next(s for s in scores if s.account_name == "a1")
        assert a1_score.effective_5h == pytest.approx(100.0)  # soon-reset

        best = select_best(scores)
        assert best is not None
        assert best.account_name != "a2"

    def test_drain_beats_fresh_mid_cycle(self):
        """Account at 20% beats fresh 80% when mid-week (drain bonus active)."""
        usages = [
            _usage("a4", fiveh_remaining=80, weekly_remaining=20,
                   fiveh_resets_in=200, weekly_resets_in=2000),
            _usage("a3", fiveh_remaining=80, weekly_remaining=80,
                   fiveh_resets_in=200, weekly_resets_in=8000),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a4"

    def test_urgency_drain_before_weekly_reset(self):
        """About-to-expire account with same % beats fresh one (urgency wins)."""
        usages = [
            _usage("a3", fiveh_remaining=80, weekly_remaining=80, weekly_resets_in=120),
            _usage("a4", fiveh_remaining=80, weekly_remaining=80, weekly_resets_in=8640),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a3"

    def test_scraps_3pct_preferred_over_fresh(self):
        """3% remaining should be drained before touching a fresh account."""
        usages = [
            _usage("a4", fiveh_remaining=80, weekly_remaining=3,
                   fiveh_resets_in=200, weekly_resets_in=3000),
            _usage("a3", fiveh_remaining=80, weekly_remaining=80,
                   fiveh_resets_in=200, weekly_resets_in=8000),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a4"

    def test_empty_account_skipped(self):
        """Account at 0.5% (below MIN_WEEKLY_REMAINING) is skipped; fresh account used."""
        usages = [
            _usage("a4", fiveh_remaining=80, weekly_remaining=0.5),
            _usage("a3", fiveh_remaining=80, weekly_remaining=80),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a3"

    def test_prefers_high_weekly_among_fresh(self):
        """Among fresh accounts (all above threshold), prefer highest weekly."""
        usages = [
            _usage("a4", fiveh_remaining=80, weekly_remaining=50),
            _usage("a3", fiveh_remaining=80, weekly_remaining=90),
            _usage("a2", fiveh_remaining=80, weekly_remaining=70),
        ]
        best = select_best(score_accounts(usages, {}))
        assert best is not None
        assert best.account_name == "a3"
