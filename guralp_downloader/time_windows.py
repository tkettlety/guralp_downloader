from __future__ import annotations

import argparse
import datetime
import math

from obspy import UTCDateTime

from .models import DownloadJob, DownloadWindow


TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SECONDS_PER_DAY = 86400


def parse_utc_timestamp(timestamp_str: str) -> UTCDateTime:
    """Parse a UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format."""
    try:
        parsed = datetime.datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid UTC timestamp '{timestamp_str}'. Use YYYY-MM-DDTHH:MM:SSZ."
        ) from exc

    return UTCDateTime(parsed.replace(tzinfo=datetime.timezone.utc))


def get_default_download_window(now: UTCDateTime | None = None) -> DownloadWindow:
    """Return the default rolling backfill window."""
    reference = now if now is not None else UTCDateTime.now()
    midnight_today = UTCDateTime(math.floor(float(reference) / SECONDS_PER_DAY) * SECONDS_PER_DAY)
    end = midnight_today - SECONDS_PER_DAY
    start = end - (14 * SECONDS_PER_DAY)
    return DownloadWindow(start=start, end=end)


def resolve_download_window(
    start: UTCDateTime | None = None,
    end: UTCDateTime | None = None,
    now: UTCDateTime | None = None,
) -> DownloadWindow:
    """Resolve an explicit or default download window."""
    if start is None and end is None:
        return get_default_download_window(now=now)
    if start is None or end is None:
        raise ValueError("Both --start and --end must be provided together.")
    if start >= end:
        raise ValueError("--start must be earlier than --end.")
    return DownloadWindow(start=start, end=end)


def get_next_midnight(timestamp: UTCDateTime) -> UTCDateTime:
    """Return the next midnight UTC after the supplied timestamp."""
    current_day = datetime.datetime(
        timestamp.year,
        timestamp.month,
        timestamp.day,
        tzinfo=datetime.timezone.utc,
    )
    return UTCDateTime(current_day + datetime.timedelta(days=1))


def build_download_jobs(window: DownloadWindow, channels: tuple[str, ...] | list[str]) -> list[DownloadJob]:
    """Build a chronological list of jobs across the requested window."""
    jobs: list[DownloadJob] = []
    chunk_start = window.start

    while chunk_start < window.end:
        chunk_end = min(get_next_midnight(chunk_start), window.end)
        for channel in channels:
            jobs.append(
                DownloadJob(
                    channel=channel,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                )
            )
        chunk_start = chunk_end

    return jobs
