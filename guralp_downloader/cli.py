from __future__ import annotations

import argparse
import sys

from .service import DownloaderService
from .time_windows import parse_utc_timestamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download passive seismic data in daily chunks from a "
            "Guralp Certimus/Minimus."
        )
    )
    parser.add_argument("config_path", help="Path to the station YAML config file.")
    parser.add_argument(
        "station_id",
        help="Station ID to download, matching a top-level key in the config file.",
    )
    parser.add_argument(
        "--start",
        type=parse_utc_timestamp,
        help=(
            "Optional UTC start timestamp for an explicit download window, "
            "formatted as YYYY-MM-DDTHH:MM:SSZ."
        ),
    )
    parser.add_argument(
        "--end",
        type=parse_utc_timestamp,
        help=(
            "Optional UTC end timestamp for an explicit download window, "
            "formatted as YYYY-MM-DDTHH:MM:SSZ."
        ),
    )
    parser.epilog = (
        "Default mode downloads the rolling backfill window from yesterday "
        "midnight UTC back to 14 days earlier. Full-day chunks use SDS "
        "filenames, while partial chunks use explicit UTC start/end names. "
        "Provide both --start and --end to download a specific UTC time period "
        "instead.\n\n"
        "Examples:\n"
        "  python guralp_downloader.py my_config.yaml BOU1\n"
        "  python -m guralp_downloader my_config.yaml BOU1 "
        "--start 2026-01-03T01:00:00Z --end 2026-01-03T03:30:00Z"
    )
    return parser


def main(argv: list[str] | None = None, service: DownloaderService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    downloader = service or DownloaderService()

    try:
        downloader.run(
            config_path=args.config_path,
            station_id=args.station_id,
            start=args.start,
            end=args.end,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0
