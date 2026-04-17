import runpy
from pathlib import Path

import pytest
from obspy import UTCDateTime

from guralp_downloader.cli import main
from guralp_downloader.models import RunSummary, StationConfig
from guralp_downloader.service import DownloaderService
from guralp_downloader.time_windows import resolve_download_window


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        station_config = StationConfig(
            sensor="sensor",
            network="OX",
            station="BOU5",
            location="1L",
            channels=("CHZ",),
            base_output_path=Path("/tmp/archive"),
            log_file=Path("/tmp/archive/download.log"),
        )
        return RunSummary(
            station_id="BOU5",
            station_config=station_config,
            window=resolve_download_window(
                start=UTCDateTime("2026-01-03T00:00:00Z"),
                end=UTCDateTime("2026-01-04T00:00:00Z"),
            ),
        )


class NoopClient:
    def download(self, url: str, output_path: Path, logger) -> None:
        output_path.write_bytes(b"ok")


def test_cli_happy_path_with_injected_service() -> None:
    service = FakeService()

    exit_code = main(
        [
            "config.yaml",
            "BOU5",
            "--start",
            "2026-01-03T00:00:00Z",
            "--end",
            "2026-01-04T00:00:00Z",
        ],
        service=service,
    )

    assert exit_code == 0
    assert service.calls[0]["station_id"] == "BOU5"


def test_cli_invalid_window_returns_error(tmp_path: Path, capsys) -> None:
    service = DownloaderService(http_client=NoopClient(), max_workers=1)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: ["CHZ"]
  base_output_path: "{tmp_path}"
  log_file: "{tmp_path / 'logs' / 'download.log'}"
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(
        [
            str(config_path),
            "BOU5",
            "--start",
            "2026-01-03T00:00:00Z",
        ],
        service=service,
    )

    assert exit_code == 1
    assert "Both --start and --end" in capsys.readouterr().err


def test_cli_missing_station_returns_error(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    service = DownloaderService(http_client=NoopClient(), max_workers=1)

    exit_code = main([str(config_path), "BOU5"], service=service)

    assert exit_code == 1
    assert "No config found for station 'BOU5'" in capsys.readouterr().err


def test_cli_workflow_with_real_service_and_temp_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: ["CHZ"]
  base_output_path: "{tmp_path}"
  log_file: "{tmp_path / 'logs' / 'download.log'}"
""".strip(),
        encoding="utf-8",
    )
    service = DownloaderService(http_client=NoopClient(), max_workers=1)

    exit_code = main(
        [
            str(config_path),
            "BOU5",
            "--start",
            "2026-01-03T00:00:00Z",
            "--end",
            "2026-01-04T00:00:00Z",
        ],
        service=service,
    )

    assert exit_code == 0
    assert (
        tmp_path / "2026" / "OX" / "BOU5" / "CHZ.D" / "OX.BOU5.1L.CHZ.D.2026.003"
    ).exists()


def test_package_main_invokes_cli_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_main() -> int:
        return 7

    monkeypatch.setattr("guralp_downloader.cli.main", fake_main)

    with pytest.raises(SystemExit, match="7"):
        runpy.run_module("guralp_downloader", run_name="__main__")
