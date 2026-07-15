from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from obspy import UTCDateTime


@dataclass(frozen=True)
class StationConfig:
    sensor: str
    network: str
    station: str
    location: str
    channels: tuple[str, ...]
    base_output_path: Path
    log_file: Path


@dataclass(frozen=True)
class DownloadWindow:
    start: UTCDateTime
    end: UTCDateTime


@dataclass(frozen=True)
class DownloadJob:
    channel: str
    chunk_start: UTCDateTime
    chunk_end: UTCDateTime


@dataclass(frozen=True)
class DownloadResult:
    channel: str
    chunk_start: UTCDateTime
    chunk_end: UTCDateTime
    outfile: Path
    success: bool
    skipped: bool
    elapsed: float
    error: str | None = None


@dataclass(frozen=True)
class RunSummary:
    station_id: str
    station_config: StationConfig
    window: DownloadWindow
    results: list[DownloadResult] = field(default_factory=list)
    total_runtime: float = 0.0

    @property
    def attempted_count(self) -> int:
        return len(self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for result in self.results if result.success)

    @property
    def skipped_count(self) -> int:
        return sum(1 for result in self.results if result.skipped)

    @property
    def failure_count(self) -> int:
        return sum(1 for result in self.results if not result.success and not result.skipped)
