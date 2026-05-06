# guralp-downloader

`guralp-downloader` downloads miniSEED waveform data from a Guralp Certimus or Minimus sensor and writes it into an SDS-style archive on disk.

The package is built around a small set of focused components:

- a CLI for scheduled or ad hoc downloads
- YAML-based station configuration
- UTC window resolution and midnight chunking
- atomic HTTP downloads with cleanup of partial files
- immediate retry support for failed downloads
- SDS-compatible output path generation

## What It Does

For a configured station, the downloader:

- resolves a download time window
- splits that window into UTC day-bounded chunks
- creates one download job per channel per chunk
- requests data from the sensor's `/data` endpoint
- stores full-day chunks using standard SDS-style names
- stores partial-day chunks using filenames that include explicit start and end times
- skips files that already exist so repeated runs are safe

This makes it useful for cron jobs, rolling backfills, and one-off recovery of missing waveform segments.

## Installation

The package requires Python 3.10+.

```bash
pip install .
```

Core dependencies:

- `obspy`
- `PyYAML`
- `requests`

Development extras:

```bash
pip install .[dev]
```

## Entry Points

Two equivalent entry points are provided:

- Compatibility script: `python guralp_downloader.py <config.yaml> <station_id>`
- Package CLI: `python -m guralp_downloader <config.yaml> <station_id>`

The package form is the main interface; the top-level script is a thin wrapper around it.

## CLI Usage

```bash
python -m guralp_downloader <config.yaml> <station_id> [--start <UTC>] [--end <UTC>]
```

Arguments:

- `config_path`: path to a YAML file containing one or more station definitions
- `station_id`: top-level YAML key selecting the station to run

Optional arguments:

- `--start`: explicit UTC start time in `YYYY-MM-DDTHH:MM:SSZ`
- `--end`: explicit UTC end time in `YYYY-MM-DDTHH:MM:SSZ`

If `--start` and `--end` are omitted, the package uses its default rolling backfill window:

- end: yesterday at `00:00:00` UTC
- start: 14 days before that

Both `--start` and `--end` must be supplied together, and `start` must be earlier than `end`.

Example:

```bash
python -m guralp_downloader examples/guralp_downloader_test.yaml BOU5 \
  --start 2026-01-03T01:00:00Z \
  --end 2026-01-03T03:30:00Z
```

## Configuration File

The YAML file is keyed by station ID. Each station entry must define:

- `sensor`: sensor host and port, for example `172.24.74.246:8080`
- `network`: SEED network code
- `station`: SEED station code
- `location`: SEED location code
- `channels`: list of channels to download
- `base_output_path`: root directory of the SDS archive
- `log_file`: path to the run log file

Example:

```yaml
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: ["CHZ", "CHN", "CHE"]
  base_output_path: "/data/guralp_archive"
  log_file: "/data/guralp_archive/logs/BOU5_download.log"
```

If the selected station is missing, required keys are absent, or the channel list is empty, the CLI exits with an error.

## Download Behavior

### Window resolution

The package resolves a `DownloadWindow` before any network activity begins.

- In default mode it backfills a fixed 14-day period ending at yesterday's midnight UTC.
- In explicit mode it uses the exact `--start` and `--end` values you provide.

### Midnight chunking

The downloader never requests an arbitrary long interval in one step. It breaks the requested window at UTC midnight boundaries.

For example, this request:

```text
2026-01-03T23:00:00Z -> 2026-01-05T01:00:00Z
```

becomes three time chunks:

- `2026-01-03T23:00:00Z -> 2026-01-04T00:00:00Z`
- `2026-01-04T00:00:00Z -> 2026-01-05T00:00:00Z`
- `2026-01-05T00:00:00Z -> 2026-01-05T01:00:00Z`

If two channels are configured, that produces six download jobs.

### Request URLs

Each job is turned into a request of the form:

```text
http://<sensor>/data?channel=<network>.<station>.<location>.<channel>&from=<timestamp>&to=<timestamp>
```

The service adds a 60-second buffer on both sides of the chunk when building the request URL:

- query start = chunk start - 60 seconds
- query end = chunk end + 60 seconds

This buffer is applied to the sensor request only. Output filenames still reflect the original chunk boundaries.

### Concurrency

Downloads are executed with a thread pool. By default:

- up to 3 jobs can run in parallel
- result ordering is preserved in the returned summary

### Safe file handling

The downloader is designed to be rerun safely:

- existing output files are skipped
- downloads are written via a `.tmp` file first
- stale `.tmp` files are removed before retrying
- failed downloads are retried immediately up to 3 total attempts by default
- failed downloads clean up their temporary file
- each failed attempt is logged before any retry is started
- zero-byte output files are deleted and recorded as failed downloads with the message `Downloaded file was empty (0 bytes)`
- small plain-ASCII output files up to 1024 bytes are deleted and recorded as failed downloads with a message like `Downloaded file was small ASCII text instead of miniSEED (104 bytes)`

## Output Layout

Files are written beneath `base_output_path` using an SDS-style directory structure:

```text
<base_output_path>/<year>/<network>/<station>/<channel>.D/<filename>
```

### Full-day chunks

If a chunk spans exactly one UTC day, the filename is SDS-style:

```text
OX.BOU5.1L.CHZ.D.2026.003
```

### Partial-day chunks

If a chunk is shorter than a full UTC day, the filename records the exact UTC bounds:

```text
OX.BOU5.1L.CHZ.D.2026.003.START_20260103T010000UTC_END_20260103T033000UTC
```

Example output tree:

```text
examples/data/
└── 2026/
    └── OX/
        └── BOU5/
            ├── CHE.D/
            ├── CHN.D/
            └── CHZ.D/
```

## Package API

The package exposes a small public API for reuse in scripts and tests.

### `DownloaderService`

Coordinates the full workflow:

- loads station config
- resolves the time window
- creates jobs for each channel/chunk pair
- downloads data
- returns a `RunSummary`

Important methods:

- `run(config_path, station_id, start=None, end=None, now=None)`: main orchestration method
- `build_request_url(job, station_config)`: constructs the sensor request URL for a single job

Constructor options:

- `http_client`: inject a custom downloader implementation
- `max_workers`: control concurrency
- `buffer_seconds`: control request padding around each chunk
- `retry_attempts`: total attempts per file before giving up, default `3`

Retry behavior is controlled in `DownloaderService`, not in the YAML station config.

### `load_station_config`

Reads one station definition from YAML and returns a validated `StationConfig`.

### `resolve_download_window`

Returns the effective `DownloadWindow` from either:

- explicit `start` and `end`
- the package's default rolling backfill logic

### `build_download_jobs`

Splits a `DownloadWindow` at UTC midnight boundaries and creates one `DownloadJob` per channel for each resulting chunk.

### `build_output_path`

Creates the SDS-style output path for a `DownloadJob`, including the special naming used for partial-day chunks.

## Data Models

The main dataclasses are:

- `StationConfig`: validated station configuration
- `DownloadWindow`: overall requested time span
- `DownloadJob`: one channel over one chunk
- `DownloadResult`: outcome of a single download
- `RunSummary`: aggregate result for the whole run

`RunSummary` includes convenience properties:

- `attempted_count`
- `success_count`
- `skipped_count`
- `failure_count`

## Logging

Each run creates or appends to the configured log file and records:

- station start/end information
- archive root
- resolved UTC window
- per-file download URLs
- skipped files
- failures
- retry messages after failed attempts when another attempt remains
- zero-byte file rejections with their failure message
- small ASCII file rejections with their failure message
- total runtime

## Examples

Files in `examples/` include:

- `guralp_downloader_test.yaml`: sample station config
- `guralp_downloader_test.sh`: example invocation wrapper
- `boulby_download_config.yaml`: another station config example
- `boulby_data_cron_job.sh`: cron-oriented wrapper script
- `plot_mseed.ipynb`: notebook for inspecting downloaded data

## Tests

Run the test suite with:

```bash
PYTHONPATH=. pytest
```

The tests cover:

- config validation
- UTC timestamp parsing
- default and explicit window selection
- chunk splitting across midnight boundaries
- output path generation
- skip-on-existing behavior
- temporary file cleanup
- retry-on-failure behavior and retry logging
- zero-byte download rejection and cleanup
- small ASCII download rejection and cleanup
- URL construction and buffering
- ordered results under concurrent execution
