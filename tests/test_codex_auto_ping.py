from __future__ import annotations

import sys
from argparse import Namespace
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import codex_auto_ping as cap


LOCAL_TZ = timezone(timedelta(hours=8))


def at(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=LOCAL_TZ)


def freeze_now(monkeypatch: pytest.MonkeyPatch, current: datetime) -> None:
    monkeypatch.setattr(cap, "now_local", lambda: current)


def make_args(**overrides: object) -> Namespace:
    defaults = {
        "offset_minutes": 1,
        "daily_start": None,
        "manual_at": None,
        "codex_bin": "codex",
        "limit_id": "codex",
        "app_server_start_timeout": 10,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_live_next_due_uses_mock_server_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 10, 0))
    state = cap.State()
    reset_at = at(2026, 5, 9, 14, 0, 42)
    monkeypatch.setattr(cap, "query_reset_at", lambda args: reset_at)

    due = cap.live_next_due(make_args(offset_minutes=1), state)

    assert due == at(2026, 5, 9, 14, 1, 42)
    assert state.last_known_reset_at == reset_at


def test_live_next_due_falls_back_to_last_success_when_mock_server_is_dormant(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 10, 0))
    state = cap.State(last_success_at=at(2026, 5, 9, 10, 0))

    def raise_no_reset(args: Namespace) -> datetime:
        raise RuntimeError("Primary rate limit window does not have resetsAt")

    monkeypatch.setattr(cap, "query_reset_at", raise_no_reset)

    due = cap.live_next_due(make_args(offset_minutes=1), state)

    assert due == at(2026, 5, 9, 15, 1)


def test_choose_next_due_waits_for_daily_start_during_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 8, 30))
    state = cap.State()
    args = make_args(daily_start=dt_time(10, 0))

    due, mode = cap.choose_next_due(args, state, manual_pending=False)

    assert due == at(2026, 5, 9, 10, 0)
    assert mode == "daily-start"


def test_choose_next_due_activates_immediately_when_day_started_but_server_is_dormant(monkeypatch: pytest.MonkeyPatch) -> None:
    current = at(2026, 5, 9, 10, 5)
    freeze_now(monkeypatch, current)
    state = cap.State()
    args = make_args(daily_start=dt_time(10, 0))

    def raise_no_reset(args: Namespace, state: cap.State) -> datetime:
        raise RuntimeError("Primary rate limit window does not have resetsAt")

    monkeypatch.setattr(cap, "live_next_due", raise_no_reset)

    due, mode = cap.choose_next_due(args, state, manual_pending=False)

    assert due == current
    assert mode == "daily-start"


def test_choose_next_due_keeps_back_to_back_within_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 15, 2))
    state = cap.State()
    args = make_args(daily_start=dt_time(10, 0))
    monkeypatch.setattr(cap, "live_next_due", lambda args, state: at(2026, 5, 9, 20, 1))

    due, mode = cap.choose_next_due(args, state, manual_pending=False)

    assert due == at(2026, 5, 9, 20, 1)
    assert mode == "periodic"


def test_choose_next_due_stops_overnight_and_waits_for_tomorrow_start(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 20, 2))
    state = cap.State()
    args = make_args(daily_start=dt_time(10, 0))
    monkeypatch.setattr(cap, "live_next_due", lambda args, state: at(2026, 5, 10, 1, 1))

    due, mode = cap.choose_next_due(args, state, manual_pending=False)

    assert due == at(2026, 5, 10, 10, 0)
    assert mode == "daily-start"


def test_parse_manual_short_time_rolls_to_next_day_when_today_has_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_now(monkeypatch, at(2026, 5, 9, 16, 0))

    parsed = cap.parse_manual_local_ts("15:09")

    assert parsed == at(2026, 5, 10, 15, 9)
