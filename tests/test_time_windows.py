import argparse

import pytest
from obspy import UTCDateTime

from guralp_downloader.time_windows import (
    build_download_jobs,
    get_default_download_window,
    parse_utc_timestamp,
    resolve_download_window,
)


def test_parse_utc_timestamp_valid() -> None:
    timestamp = parse_utc_timestamp("2026-01-03T01:00:00Z")

    assert timestamp == UTCDateTime("2026-01-03T01:00:00Z")


def test_parse_utc_timestamp_invalid() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="Invalid UTC timestamp"):
        parse_utc_timestamp("2026-01-03 01:00:00")


def test_get_default_download_window_uses_fixed_now() -> None:
    window = get_default_download_window(now=UTCDateTime("2026-04-17T15:30:00Z"))

    assert window.start == UTCDateTime("2026-04-02T00:00:00Z")
    assert window.end == UTCDateTime("2026-04-16T00:00:00Z")


def test_resolve_download_window_rejects_partial_bounds() -> None:
    with pytest.raises(ValueError, match="Both --start and --end"):
        resolve_download_window(start=UTCDateTime("2026-01-03T01:00:00Z"))


def test_resolve_download_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="--start must be earlier than --end"):
        resolve_download_window(
            start=UTCDateTime("2026-01-03T02:00:00Z"),
            end=UTCDateTime("2026-01-03T01:00:00Z"),
        )


def test_build_download_jobs_splits_by_midnight_and_channel() -> None:
    window = resolve_download_window(
        start=UTCDateTime("2026-01-03T23:00:00Z"),
        end=UTCDateTime("2026-01-05T01:00:00Z"),
    )

    jobs = build_download_jobs(window, ("CHZ", "CHN"))

    assert len(jobs) == 6
    assert jobs[0].channel == "CHZ"
    assert jobs[0].chunk_start == UTCDateTime("2026-01-03T23:00:00Z")
    assert jobs[0].chunk_end == UTCDateTime("2026-01-04T00:00:00Z")
    assert jobs[2].chunk_start == UTCDateTime("2026-01-04T00:00:00Z")
    assert jobs[2].chunk_end == UTCDateTime("2026-01-05T00:00:00Z")
    assert jobs[-1].chunk_start == UTCDateTime("2026-01-05T00:00:00Z")
    assert jobs[-1].chunk_end == UTCDateTime("2026-01-05T01:00:00Z")
