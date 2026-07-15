# Agent Context

## Package Purpose

`guralp-downloader` is a small Python 3.10+ package for downloading miniSEED waveform data from Guralp Certimus/Minimus sensors into an SDS-style archive on disk. It supports scheduled rolling backfills and explicit one-off UTC windows.

The two user-facing entry points are equivalent:

- `python -m guralp_downloader <config.yaml> <station_id> [--start ... --end ...]`
- `python guralp_downloader.py <config.yaml> <station_id> [--start ... --end ...]`

The top-level `guralp_downloader.py` is only a compatibility wrapper around `guralp_downloader.cli.main`.

## Project Shape

- `guralp_downloader/cli.py`: argparse CLI and exit-code handling.
- `guralp_downloader/service.py`: main orchestration via `DownloaderService`.
- `guralp_downloader/client.py`: HTTP download abstraction plus `requests` implementation.
- `guralp_downloader/config.py`: YAML station loading and validation.
- `guralp_downloader/time_windows.py`: UTC timestamp parsing, default window logic, midnight chunking, job creation.
- `guralp_downloader/paths.py`: SDS-compatible output path construction.
- `guralp_downloader/models.py`: frozen dataclasses for config, windows, jobs, results, and run summaries.
- `guralp_downloader/logging_utils.py`: dedicated file logger creation.
- `examples/`: sample YAML, shell wrappers, and notebook.
- `tests/`: focused pytest coverage for config, CLI, time windows, paths, client, and service behavior.
- `ref/`: reference/vendor material from Guralp, including docs and example miniSEED files. Treat this as supporting material, not package source.

## Core Flow

1. `cli.main()` parses `config_path`, `station_id`, optional `--start`, and optional `--end`.
2. `DownloaderService.run()` loads the selected station config from YAML.
3. The service resolves a `DownloadWindow`.
   - With no explicit bounds: 14-day rolling backfill ending at yesterday midnight UTC.
   - With explicit bounds: both `--start` and `--end` are required, and `start < end`.
4. The window is split at UTC midnight boundaries.
5. One `DownloadJob` is created for each channel for each chunk.
6. Each job builds a request URL for `http://<sensor>/data`.
7. Request URLs are buffered by `buffer_seconds` on each side, default 60 seconds.
8. Output filenames still reflect the original, unbuffered chunk boundaries.
9. Downloads run through a thread pool when `max_workers > 1`; returned results preserve original job order.
10. The service returns a `RunSummary`.

## Output Rules

Archive layout:

```text
<base_output_path>/<year>/<network>/<station>/<channel>.D/<filename>
```

Full UTC-day chunks use SDS-style filenames:

```text
OX.BOU5.1L.CHZ.D.2026.003
```

Partial-day chunks include exact UTC start/end bounds:

```text
OX.BOU5.1L.CHZ.D.2026.003.START_20260103T010000UTC_END_20260103T033000UTC
```

## Safety And Retry Behavior

- Existing output files are skipped.
- Parent directories are created as needed.
- Downloads write through `.tmp` files and then rename to the final path.
- Stale `.tmp` files are removed before starting a job.
- Failed attempts clean up leftover `.tmp` files.
- `DownloaderService` retries the whole download/validation flow up to `retry_attempts` total attempts, default 3.
- Zero-byte final files are deleted and treated as failed downloads with error text `Downloaded file was empty (0 bytes)`.
- Small plain-ASCII final files up to 1024 bytes are deleted and treated as failed downloads with error text `Downloaded file was small ASCII text instead of miniSEED (<N> bytes)`.
- Logging is per station run and written to the configured `log_file`; `create_file_logger()` clears prior handlers for that named logger and opens the file in write mode.

## Configuration

YAML files are keyed by station ID. Required station keys are:

- `sensor`
- `network`
- `station`
- `location`
- `channels`
- `base_output_path`
- `log_file`

`channels` must be non-empty. Values are converted into a `StationConfig`, with paths stored as `pathlib.Path` objects and channels as a tuple.

## Public API

`guralp_downloader.__init__` exports:

- `DownloaderService`
- `StationConfig`
- `DownloadWindow`
- `DownloadJob`
- `DownloadResult`
- `RunSummary`
- `load_station_config`
- `parse_utc_timestamp`
- `resolve_download_window`
- `build_download_jobs`
- `build_output_path`

When extending behavior, prefer preserving this small API and dependency-injection style. Tests commonly inject fake download clients into `DownloaderService`.

## Development Commands

Install in editable/dev mode when dependencies are needed:

```bash
pip install -e .[dev]
```

Run tests:

```bash
PYTHONPATH=. pytest
```

The declared runtime dependencies are `obspy`, `PyYAML`, and `requests`; `pytest` is the only declared dev extra.

## Notes For Future Agents

- Keep edits scoped; this package is intentionally small and explicit.
- Use `obspy.UTCDateTime` consistently for timestamps.
- Preserve UTC-only behavior and the strict CLI timestamp format `YYYY-MM-DDTHH:MM:SSZ`.
- Be careful with filename compatibility: tests assert exact SDS and partial-chunk path strings.
- Be careful with retry and cleanup behavior: tests assert call counts, log messages, zero-byte cleanup, small ASCII cleanup, and `.tmp` removal.
- Existing `.DS_Store` changes under `ref/` may appear in git status; they are unrelated to package source.
