from pathlib import Path

from obspy import UTCDateTime

from guralp_downloader.models import DownloadJob, StationConfig
from guralp_downloader.paths import build_output_path


def make_station_config(base_output_path: Path) -> StationConfig:
    return StationConfig(
        sensor="172.24.74.246:8080",
        network="OX",
        station="BOU5",
        location="1L",
        channels=("CHZ",),
        base_output_path=base_output_path,
        log_file=base_output_path / "logs" / "download.log",
    )


def test_build_output_path_for_full_day_chunk(tmp_path: Path) -> None:
    job = DownloadJob(
        channel="CHZ",
        chunk_start=UTCDateTime("2026-01-03T00:00:00Z"),
        chunk_end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    output_path = build_output_path(job, make_station_config(tmp_path))

    assert output_path == (
        tmp_path / "2026" / "OX" / "BOU5" / "CHZ.D" / "OX.BOU5.1L.CHZ.D.2026.003"
    )


def test_build_output_path_for_partial_chunk(tmp_path: Path) -> None:
    job = DownloadJob(
        channel="CHZ",
        chunk_start=UTCDateTime("2026-01-03T01:00:00Z"),
        chunk_end=UTCDateTime("2026-01-03T03:30:00Z"),
    )

    output_path = build_output_path(job, make_station_config(tmp_path))

    assert output_path == (
        tmp_path
        / "2026"
        / "OX"
        / "BOU5"
        / "CHZ.D"
        / "OX.BOU5.1L.CHZ.D.2026.003.START_20260103T010000UTC_END_20260103T033000UTC"
    )
