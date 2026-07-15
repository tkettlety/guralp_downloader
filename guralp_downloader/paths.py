from __future__ import annotations

from pathlib import Path

from obspy import UTCDateTime

from .models import DownloadJob, StationConfig
from .time_windows import get_next_midnight


def is_full_day_chunk(chunk_start: UTCDateTime, chunk_end: UTCDateTime) -> bool:
    """Return True when the chunk spans exactly one UTC day."""
    return (
        chunk_start.hour == 0
        and chunk_start.minute == 0
        and chunk_start.second == 0
        and chunk_start.microsecond == 0
        and chunk_end == get_next_midnight(chunk_start)
    )


def format_compact_timestamp(timestamp: UTCDateTime) -> str:
    """Format UTCDateTime as YYYYMMDDTHHMMSS for filenames."""
    return (
        f"{timestamp.year:04d}{timestamp.month:02d}{timestamp.day:02d}T"
        f"{timestamp.hour:02d}{timestamp.minute:02d}{timestamp.second:02d}"
    )


def build_output_path(job: DownloadJob, station_config: StationConfig) -> Path:
    """Build the SDS-compatible output path for a given job."""
    data_type = "D"
    year = job.chunk_start.year
    doy = job.chunk_start.julday
    channel_dir = (
        station_config.base_output_path
        / f"{year:04d}"
        / station_config.network
        / station_config.station
        / f"{job.channel}.{data_type}"
    )
    stream_prefix = (
        f"{station_config.network}.{station_config.station}."
        f"{station_config.location}.{job.channel}.{data_type}"
    )

    if is_full_day_chunk(job.chunk_start, job.chunk_end):
        filename = f"{stream_prefix}.{year:04d}.{doy:03d}"
    else:
        start_str = format_compact_timestamp(job.chunk_start)
        end_str = format_compact_timestamp(job.chunk_end)
        filename = (
            f"{stream_prefix}.{year:04d}.{doy:03d}."
            f"START_{start_str}UTC_END_{end_str}UTC"
        )

    return channel_dir / filename
