"""Offline tests for retention and interval boundaries."""

import pytest

from mist_connection import clip_to_retention_window, interval_for_duration


def test_retention_window_does_not_clip_exact_boundary():
    """Keep a requested start exactly at the earliest retained instant."""
    end = 2_000_000_000
    earliest = end - 14 * 86_400

    assert clip_to_retention_window(earliest, end) == (earliest, False, "")


def test_retention_window_clips_start_before_boundary():
    """Clamp a request one second before the retention boundary."""
    end = 2_000_000_000
    earliest = end - 14 * 86_400

    start, clipped, notice = clip_to_retention_window(earliest - 1, end)

    assert start == earliest
    assert clipped is True
    assert "14-day" in notice


def test_interval_mapping_uses_subhour_samples_for_one_hour():
    """Use ten-minute samples only for the one-hour chart window."""
    assert interval_for_duration("1h") == ("10m", 600)
    assert interval_for_duration("6h") == ("1h", 3600)


def test_invalid_duration_is_rejected():
    """Reject arbitrary durations rather than silently choosing a window."""
    from mist_connection import duration_to_seconds

    with pytest.raises(ValueError, match="duration must be one of"):
        duration_to_seconds("30d")
