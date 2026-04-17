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
    - This script downloads one week of seismic data in daily chunks, ending two days before today.
    - Each day is broken into a full-day chunk with a configurable buffer on both ends.
    - Uses the `requests` library to stream data to a temporary `.tmp` file.
    - On successful completion, the `.tmp` file is renamed to `.mseed`.
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
        base_output_path: "/data/boulby_data"
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
    T. Kettlety, University of Oxford (2024 to 2025)
"""

import os
from pathlib import Path
import yaml
from obspy import UTCDateTime
import timeit
import datetime
import logging
import sys
import math
import requests  # to replace wget

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

def main(config_path,station_id):
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
    base_path = Path(config["base_output_path"]) / station  # Base output directory
    log_file = config["log_file"]          # Log file path

    # Setup logging to file with DEBUG level
    logging.basicConfig(filename=log_file,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',  # <-- drops milliseconds
                        filemode='w')
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    logger.info(f"Starting data download for station '{station_id}'")
    logger.info(f"Output directory set to: {base_path}")

    # Record script start time for total runtime measurement
    script_start = timeit.default_timer()

    # Define date range for download:
    # - end is two days ago at midnight (UTC)
    # - start is one week before 'end'
    tmp = math.floor(UTCDateTime.now())
    tmp = math.floor(tmp / 86400) * 86400  # Midnight UTC today
    tmp = UTCDateTime(tmp)
    end = tmp - (1 * 86400)   # one days ago midnight
    start = end - (86 * 86400) # four weeks before 'end'

    # Define chunk size as 1 day timedelta
    shift = datetime.timedelta(days=1)
    buffer_seconds = 60  # Add 60 seconds buffer on both ends of time chunk

    chunk_start = start

    # Loop over day-long chunks from start to end
    while chunk_start < end:
        chunk_end = chunk_start + shift

        # Add buffer to avoid gaps
        query_start = chunk_start - buffer_seconds
        query_end = chunk_end + buffer_seconds

        # Convert query times to UNIX timestamps for URL parameters
        startUNIX = query_start.timestamp
        endUNIX = query_end.timestamp

        # Extract date parts for directory and filename formatting
        year, month, day = chunk_start.year, chunk_start.month, chunk_start.day
        hour, minute, second = chunk_start.hour, chunk_start.minute, chunk_start.second

        # Create directory for the current day, e.g., /base_path/2024/07/10/
        day_dir = base_path / f"{year:04d}" / f"{month:02d}" / f"{day:02d}"
        day_dir.mkdir(parents=True, exist_ok=True)

        # Loop over all channels for this station
        for channel in channels:
            # Build request string, e.g., UB.BOU1.1L.CHZ
            request_str = f"{network}.{station}.{location}.{channel}"

            # Construct output filename, e.g., UB.BOU1.1L.CHZ.20240710T000000.mseed
            outfile = day_dir / f"{request_str}.{year:04d}{month:02d}{day:02d}T{hour:02d}{minute:02d}{second:02d}.mseed"

            # Skip if file already exists
            if outfile.exists():
                logger.info(f"File exists, skipping: {outfile}")
                continue

            # If .tmp exists, it's likely an interrupted download
            tmp_file = outfile.with_suffix(outfile.suffix + ".tmp")
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

        # Move to next chunk (next day)
        chunk_start += shift

    # Log total runtime
    total_runtime = timeit.default_timer() - script_start
    logger.info(f"Finished all downloads for {network}.{station}")
    logger.info(f"Total runtime: {total_runtime:.0f} seconds ({total_runtime/60:.1f} minutes)")

if __name__ == "__main__":
    HELP_TEXT = """\
Miniseed Data Downloader
Usage:
    python guralp_downloader.py <config.yaml> <station_id>

Downloads passive seismic data in daily chunks from a Guralp Certimus/Minimus.
Logs progress and skips already downloaded files.

Example:
    python guralp_downloader.py my_config.yaml BOU1
"""
    if len(sys.argv) != 3:
        print(HELP_TEXT)
        sys.exit(1)

    config_path = sys.argv[1]
    station_id = sys.argv[2]
    main(config_path, station_id)
