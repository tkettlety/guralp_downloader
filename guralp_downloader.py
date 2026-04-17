#!/usr/bin/env python
"""
Miniseed Data Downloader Script
--------------------------------

Downloads day-chunked miniseed data from a Certimus seismometer via HTTP,
for a specified station configuration.

USAGE:
    python guralp_downloader.py <config.yaml> <station_id>

ARGUMENTS:
    config.yaml     Path to a YAML configuration file containing station settings.
    station_id      ID of the station to download data for. Must match a key in the config file.

DESCRIPTION:
    - This script downloads passive seismic data in UTC day-bounded chunks.
    - Full single-day chunks are written using the SeisComP SDS archive layout.
    - Partial-day chunks are written in the same SDS directory with explicit
      start/end timestamps in the filename.
    - Uses the `requests` library to stream data to a temporary `.tmp` file.
    - On successful completion, the `.tmp` file is renamed to the final archive name.
    - Skips already downloaded files.
    - Removes and retries interrupted `.tmp` files.
    - Writes detailed logs to a file specified in the config.

CONFIG YAML FORMAT (example):
    BOU1:
        sensor: "172.24.71.134:8080"
        network: "UB"
        station: "BOU1"
        location: "1L"
        channels: ["CHZ", "CHN", "CHE"]
        base_output_path: "/data/archive"
        log_file: "/data/logs/BOU1_download.log"

LOGGING:
    Logs are written to the file specified under `log_file` in the config YAML.
    Timestamps are rounded to the nearest second.

DEPENDENCIES:
    - requests
    - obspy
    - PyYAML

AUTHORS:
    J. Asplet, University of Oxford (2023 to 2025)
    T. Kettlety, University of Oxford (2024 to 2026)
"""

import argparse
import os
from pathlib import Path
import yaml
from obspy import UTCDateTime
import timeit
import datetime
import logging
import math
import requests  # to replace wget

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

def load_config(config_path, station_id):
    """
    Load the configuration from a YAML files at config_path for the given
    station ID.
    """
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
    if station_id not in cfg:
        raise ValueError(f"No config found for station '{station_id}'")
    return cfg[station_id]

def download_file(url, output_path, logger, station_id):
    """
    Downloads a file from `url` to a temporary file (`.tmp` extension)
    using requests, writing the file in chunks to avoid loading entire content
    into memory. If successful, renames it to `output_path`. Returns True if 
    download succeeded, False otherwise. Logs progress and errors.
    """

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()

            # Write content in chunks to the .tmp file
            with open(tmp_path, "wb") as f:
                # total = int(r.headers.get('content-length', 0))
                # downloaded = 0
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        # downloaded += len(chunk)
                        # done = int(50 * downloaded / total) if total else 0
                        # sys.stdout.write(f"\r[{station_id}] [{'=' * done}{' ' * (50 - done)}] {downloaded / 1e6:.2f}MB")
                        # sys.stdout.flush()

        # If download completes, rename .tmp to final .mseed
        tmp_path.rename(output_path)
        logger.info(f"Download complete: {output_path}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed download for {url} -> {tmp_path.name}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()  # Clean up incomplete file
        return False

def parse_utc_timestamp(timestamp_str):
    """
    Parse a UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format.
    """
    try:
        parsed = datetime.datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid UTC timestamp '{timestamp_str}'. Use YYYY-MM-DDTHH:MM:SSZ."
        ) from exc

    return UTCDateTime(parsed.replace(tzinfo=datetime.timezone.utc))

def get_default_date_range():
    """
    Return the default rolling backfill window (14 days).
    """
    tmp = math.floor(UTCDateTime.now())
    tmp = math.floor(tmp / 86400) * 86400  # Midnight UTC today
    tmp = UTCDateTime(tmp)
    end = tmp - (1 * 86400)    # yesterday midnight UTC
    start = end - (14 * 86400) # 14 days before end
    return start, end

def resolve_date_range(start=None, end=None):
    """
    Resolve the requested download window from optional CLI timestamps.
    """
    if start is None and end is None:
        return get_default_date_range()

    if start is None or end is None:
        raise ValueError("Both --start and --end must be provided together.")

    if start >= end:
        raise ValueError("--start must be earlier than --end.")

    return start, end

def get_next_midnight(timestamp):
    """
    Return the next midnight UTC after the supplied timestamp.
    """
    current_day = datetime.datetime(
        timestamp.year,
        timestamp.month,
        timestamp.day,
        tzinfo=datetime.timezone.utc,
    )
    return UTCDateTime(current_day + datetime.timedelta(days=1))

def is_full_day_chunk(chunk_start, chunk_end):
    """
    Return True when the chunk spans exactly one UTC day boundary to boundary.
    """
    return (
        chunk_start.hour == 0
        and chunk_start.minute == 0
        and chunk_start.second == 0
        and chunk_start.microsecond == 0
        and chunk_end == get_next_midnight(chunk_start)
    )

def format_compact_timestamp(timestamp):
    """
    Format UTCDateTime as YYYYMMDDTHHMMSS for partial-file naming.
    """
    return (
        f"{timestamp.year:04d}{timestamp.month:02d}{timestamp.day:02d}T"
        f"{timestamp.hour:02d}{timestamp.minute:02d}{timestamp.second:02d}"
    )

def build_sds_output_path(base_path, network, station, location, channel, chunk_start, chunk_end):
    """
    Build the SDS-compatible output path for a given chunk.
    """
    data_type = "D"
    year = chunk_start.year
    doy = chunk_start.julday
    channel_dir = base_path / f"{year:04d}" / network / station / f"{channel}.{data_type}"
    stream_prefix = f"{network}.{station}.{location}.{channel}.{data_type}"

    if is_full_day_chunk(chunk_start, chunk_end):
        filename = f"{stream_prefix}.{year:04d}.{doy:03d}"
    else:
        start_str = format_compact_timestamp(chunk_start)
        end_str = format_compact_timestamp(chunk_end)
        filename = f"{stream_prefix}.{year:04d}.{doy:03d}.START_{start_str}UTC_END_{end_str}UTC"

    return channel_dir / filename

def main(config_path, station_id, start=None, end=None):
    """
    Main function to:
    - Load config for given station_id
    - Set up logging
    - Loop over daily chunks in the date range
    - Download miniseed data files for each channel and time chunk
    """
    # Load station-specific config
    config = load_config(config_path,station_id)

    # Extract parameters from config
    sensor = config["sensor"]              # e.g., IP:port string
    network = config["network"]            # e.g., "UB"
    station = config["station"]            # e.g., "BOU1"
    location = config["location"]          # e.g., "1L"
    channels = config["channels"]          # list of channels, e.g., ["CHZ", "CHN", "CHE"]
    base_path = Path(config["base_output_path"])  # SDS archive root directory
    log_file = config["log_file"]          # Log file path

    # Setup logging to file with DEBUG level
    logging.basicConfig(filename=log_file,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',  # <-- drops milliseconds
                        filemode='w')
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    logger.info(f"Starting data download for station '{station_id}'")
    logger.info(f"SDS archive root set to: {base_path}")

    # Record script start time for total runtime measurement
    script_start = timeit.default_timer()

    # Define date range for download.
    start, end = resolve_date_range(start=start, end=end)
    logger.info(f"Download window start (UTC): {start}")
    logger.info(f"Download window end (UTC): {end}")

    buffer_seconds = 60  # Add 60 seconds buffer on both ends of time chunk

    chunk_start = start

    # Loop over day-bounded chunks from start to end
    while chunk_start < end:
        chunk_end = min(get_next_midnight(chunk_start), end)

        # Add buffer to avoid gaps
        query_start = chunk_start - buffer_seconds
        query_end = chunk_end + buffer_seconds

        # Convert query times to UNIX timestamps for URL parameters
        startUNIX = query_start.timestamp
        endUNIX = query_end.timestamp

        # Loop over all channels for this station
        for channel in channels:
            # Build request string, e.g., UB.BOU1.1L.CHZ
            request_str = f"{network}.{station}.{location}.{channel}"

            # Construct SDS output filename for full days, or an explicit
            # start/end variant for partial chunks.
            outfile = build_sds_output_path(
                base_path,
                network,
                station,
                location,
                channel,
                chunk_start,
                chunk_end,
            )
            outfile.parent.mkdir(parents=True, exist_ok=True)

            # Skip if file already exists
            if outfile.exists():
                logger.info(f"File exists, skipping: {outfile}")
                continue

            # If .tmp exists, it's likely an interrupted download
            tmp_file = Path(f"{outfile}.tmp")
            if tmp_file.exists():
                logger.warning(f"Incomplete .tmp file detected, removing: {tmp_file}")
                tmp_file.unlink()

            # Build URL for data request
            url = f"http://{sensor}/data?channel={request_str}&from={startUNIX}&to={endUNIX}"
            logger.info(f"Downloading from URL: {url}")
            logger.info(f"Saving to: {outfile}")

            # Download file with requests
            start_time = timeit.default_timer()
            success = download_file(url, outfile, logger, station_id)
            elapsed = timeit.default_timer() - start_time

            if success:
                logger.info(f"Download completed in {elapsed:.0f} seconds")
            else:
                logger.error(f"Download failed for {outfile}")

        # Move to next chunk
        chunk_start = chunk_end

    # Log total runtime
    total_runtime = timeit.default_timer() - script_start
    logger.info(f"Finished all downloads for {network}.{station}")
    logger.info(f"Total runtime: {total_runtime:.0f} seconds ({total_runtime/60:.1f} minutes)")

if __name__ == "__main__":
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
        "  python guralp_downloader.py my_config.yaml BOU1 "
        "--start 2026-01-03T01:00:00Z --end 2026-01-03T03:30:00Z"
    )

    args = parser.parse_args()
    main(args.config_path, args.station_id, start=args.start, end=args.end)
