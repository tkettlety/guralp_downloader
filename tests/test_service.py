import logging
import time
from pathlib import Path

from obspy import UTCDateTime

from guralp_downloader.models import DownloadWindow, StationConfig
from guralp_downloader.service import DownloaderService


class FakeDownloadClient:
    def __init__(
        self,
        fail: bool = False,
        leave_tmp_on_failure: bool = False,
        write_empty_file: bool = False,
    ) -> None:
        self.fail = fail
        self.leave_tmp_on_failure = leave_tmp_on_failure
        self.write_empty_file = write_empty_file
        self.calls: list[tuple[str, Path]] = []

    def download(self, url: str, output_path: Path, logger) -> None:
        self.calls.append((url, output_path))
        if self.fail:
            if self.leave_tmp_on_failure:
                tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
                tmp_path.write_bytes(b"partial")
            raise RuntimeError("boom")
        if self.write_empty_file:
            output_path.write_bytes(b"")
            return
        output_path.write_bytes(b"mseed")


class SlowDownloadClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def download(self, url: str, output_path: Path, logger) -> None:
        self.calls.append(output_path.name)
        if ".CHZ." in output_path.name:
            time.sleep(0.05)
        else:
            time.sleep(0.01)
        output_path.write_bytes(output_path.name.encode("utf-8"))


def write_config(config_path: Path, base_output_path: Path, channels: str = '["CHZ"]') -> None:
    config_path.write_text(
        f"""
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: {channels}
  base_output_path: "{base_output_path}"
  log_file: "{base_output_path / 'logs' / 'download.log'}"
""".strip(),
        encoding="utf-8",
    )


def test_service_skips_existing_file(tmp_path: Path) -> None:
    client = FakeDownloadClient()
    service = DownloaderService(http_client=client, max_workers=1)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )
    assert summary.results[0].success is True

    second_summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert second_summary.skipped_count == 1
    assert len(client.calls) == 1


def test_service_removes_stale_tmp_before_retry(tmp_path: Path) -> None:
    client = FakeDownloadClient()
    service = DownloaderService(http_client=client, max_workers=1)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    expected_output = (
        tmp_path / "2026" / "OX" / "BOU5" / "CHZ.D" / "OX.BOU5.1L.CHZ.D.2026.003"
    )
    expected_output.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(f"{expected_output}.tmp")
    tmp_file.write_bytes(b"stale")

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert summary.success_count == 1
    assert not tmp_file.exists()
    assert expected_output.read_bytes() == b"mseed"


def test_service_cleans_tmp_file_after_failure(tmp_path: Path) -> None:
    client = FakeDownloadClient(fail=True, leave_tmp_on_failure=True)
    service = DownloaderService(http_client=client, max_workers=1)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    assert result.success is False
    assert result.skipped is False
    assert result.error == "boom"
    assert not Path(f"{result.outfile}.tmp").exists()


def test_service_deletes_zero_byte_download_and_reports_failure(tmp_path: Path) -> None:
    client = FakeDownloadClient(write_empty_file=True)
    service = DownloaderService(http_client=client, max_workers=1)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    assert summary.failure_count == 1
    assert result.success is False
    assert result.skipped is False
    assert result.error == "Downloaded file was empty (0 bytes)"
    assert not result.outfile.exists()


def test_service_builds_expected_url_with_buffer(tmp_path: Path) -> None:
    client = FakeDownloadClient()
    service = DownloaderService(http_client=client, max_workers=1, buffer_seconds=60)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T01:00:00Z"),
        end=UTCDateTime("2026-01-03T03:30:00Z"),
    )

    assert summary.success_count == 1
    url, _ = client.calls[0]
    assert url == (
        "http://172.24.74.246:8080/data"
        "?channel=OX.BOU5.1L.CHZ"
        "&from=1767401940.0"
        "&to=1767411060.0"
    )


def test_service_multi_channel_multi_chunk_summary(tmp_path: Path) -> None:
    client = FakeDownloadClient()
    service = DownloaderService(http_client=client, max_workers=1)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path, channels='["CHZ", "CHN"]')

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T23:00:00Z"),
        end=UTCDateTime("2026-01-05T01:00:00Z"),
    )

    assert isinstance(summary.window, DownloadWindow)
    assert summary.attempted_count == 6
    assert summary.success_count == 6
    assert summary.failure_count == 0


def test_service_returns_results_in_job_order_when_concurrent(tmp_path: Path) -> None:
    client = SlowDownloadClient()
    service = DownloaderService(http_client=client, max_workers=2)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path, channels='["CHZ", "CHN"]')

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert sorted(client.calls) == [
        "OX.BOU5.1L.CHN.D.2026.003",
        "OX.BOU5.1L.CHZ.D.2026.003",
    ]
    assert [result.channel for result in summary.results] == ["CHZ", "CHN"]
    assert summary.success_count == 2


def test_execute_jobs_returns_empty_list_for_no_jobs(tmp_path: Path) -> None:
    service = DownloaderService(http_client=FakeDownloadClient(), max_workers=2)
    station_config = StationConfig(
        sensor="172.24.74.246:8080",
        network="OX",
        station="BOU5",
        location="1L",
        channels=("CHZ",),
        base_output_path=tmp_path,
        log_file=tmp_path / "logs" / "download.log",
    )
    logger = logging.getLogger("test.service.empty")

    results = service._execute_jobs([], station_config, logger)

    assert results == []
