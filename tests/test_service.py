import logging
import threading
import time
from pathlib import Path

from obspy import UTCDateTime

from guralp_downloader.models import DownloadWindow, StationConfig
from guralp_downloader.service import DownloaderService


TEST_MSEED_BYTES = b"\x89mseed"
SMALL_ASCII_ERROR_BYTES = (
    b"The limit of data download connections has been reached. "
    b"Please wait until current transactions finish.\n"
)
SMALL_ASCII_ERROR = "Downloaded file was small ASCII text instead of miniSEED (104 bytes)"


class FakeDownloadClient:
    def __init__(
        self,
        fail: bool = False,
        leave_tmp_on_failure: bool = False,
        write_empty_file: bool = False,
        write_small_ascii_file: bool = False,
    ) -> None:
        self.fail = fail
        self.leave_tmp_on_failure = leave_tmp_on_failure
        self.write_empty_file = write_empty_file
        self.write_small_ascii_file = write_small_ascii_file
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
        if self.write_small_ascii_file:
            output_path.write_bytes(SMALL_ASCII_ERROR_BYTES)
            return
        output_path.write_bytes(TEST_MSEED_BYTES)


class SequencedDownloadClient:
    def __init__(self, outcomes: list[str], leave_tmp_on_failure: bool = False) -> None:
        self.outcomes = outcomes
        self.leave_tmp_on_failure = leave_tmp_on_failure
        self.calls: list[tuple[str, Path]] = []

    def download(self, url: str, output_path: Path, logger) -> None:
        self.calls.append((url, output_path))
        outcome = self.outcomes[len(self.calls) - 1]
        if outcome == "fail":
            if self.leave_tmp_on_failure:
                tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
                tmp_path.write_bytes(b"partial")
            raise RuntimeError("boom")
        if outcome == "empty":
            output_path.write_bytes(b"")
            return
        if outcome == "small_ascii":
            output_path.write_bytes(SMALL_ASCII_ERROR_BYTES)
            return
        output_path.write_bytes(TEST_MSEED_BYTES)


class SlowDownloadClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def download(self, url: str, output_path: Path, logger) -> None:
        self.calls.append(output_path.name)
        if ".CHZ." in output_path.name:
            time.sleep(0.05)
        else:
            time.sleep(0.01)
        output_path.write_bytes(b"\x89" + output_path.name.encode("utf-8"))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []
        self._lock = threading.Lock()

    def timer(self) -> float:
        with self._lock:
            return self.now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleep_calls.append(seconds)
            self.now += seconds


class TimedSequencedDownloadClient:
    def __init__(self, outcomes: list[str], clock: FakeClock) -> None:
        self.outcomes = outcomes
        self.clock = clock
        self.calls: list[tuple[float, str]] = []

    def download(self, url: str, output_path: Path, logger) -> None:
        self.calls.append((self.clock.timer(), output_path.name))
        outcome = self.outcomes[len(self.calls) - 1]
        if outcome == "fail":
            raise RuntimeError("boom")
        if outcome == "empty":
            output_path.write_bytes(b"")
            return
        if outcome == "small_ascii":
            output_path.write_bytes(SMALL_ASCII_ERROR_BYTES)
            return
        output_path.write_bytes(TEST_MSEED_BYTES)


class ConcurrentCooldownDownloadClient:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.chn_started = threading.Event()
        self.failure_recorded = threading.Event()
        self.calls: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def download(self, url: str, output_path: Path, logger) -> None:
        channel = output_path.name.split(".")[3]
        with self._lock:
            self.calls.append((channel, self.clock.timer()))

        if channel == "CHZ":
            self.chn_started.wait(timeout=1.0)
            self.failure_recorded.set()
            raise RuntimeError("boom")
        if channel == "CHN":
            self.chn_started.set()
            self.failure_recorded.wait(timeout=1.0)

        output_path.write_bytes(b"\x89" + channel.encode("ascii"))


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
    assert expected_output.read_bytes() == TEST_MSEED_BYTES


def test_service_cleans_tmp_file_after_failure(tmp_path: Path) -> None:
    client = FakeDownloadClient(fail=True, leave_tmp_on_failure=True)
    service = DownloaderService(http_client=client, max_workers=1, retry_delay_seconds=0)
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


def test_service_retries_failed_download_until_success(tmp_path: Path) -> None:
    client = SequencedDownloadClient(["fail", "fail", "success"], leave_tmp_on_failure=True)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=3,
        retry_delay_seconds=0,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert result.success is True
    assert len(client.calls) == 3
    assert log_text.count("Download failed for") == 2
    assert "Retrying download for" in log_text
    assert "attempt 2/3" in log_text
    assert "attempt 3/3" in log_text


def test_service_reports_failure_after_exhausting_retries(tmp_path: Path) -> None:
    client = SequencedDownloadClient(["fail", "fail", "fail"], leave_tmp_on_failure=True)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=3,
        retry_delay_seconds=0,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert summary.failure_count == 1
    assert result.success is False
    assert result.error == "boom"
    assert len(client.calls) == 3
    assert log_text.count("Download failed for") == 3
    assert log_text.count("Retrying download for") == 2
    assert not Path(f"{result.outfile}.tmp").exists()


def test_service_deletes_zero_byte_download_and_reports_failure(tmp_path: Path) -> None:
    client = FakeDownloadClient(write_empty_file=True)
    service = DownloaderService(http_client=client, max_workers=1, retry_delay_seconds=0)
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


def test_service_retries_zero_byte_download_until_success(tmp_path: Path) -> None:
    client = SequencedDownloadClient(["empty", "success"])
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=2,
        retry_delay_seconds=0,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert result.success is True
    assert len(client.calls) == 2
    assert "Downloaded file was empty (0 bytes)" in log_text
    assert "Retrying download for" in log_text


def test_service_deletes_small_ascii_download_and_reports_failure(tmp_path: Path) -> None:
    client = FakeDownloadClient(write_small_ascii_file=True)
    service = DownloaderService(http_client=client, max_workers=1, retry_delay_seconds=0)
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")
    assert summary.failure_count == 1
    assert result.success is False
    assert result.skipped is False
    assert result.error == SMALL_ASCII_ERROR
    assert not result.outfile.exists()
    assert "Please wait until current transactions finish." in log_text


def test_service_retries_small_ascii_download_until_success(tmp_path: Path) -> None:
    client = SequencedDownloadClient(["small_ascii", "success"])
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=2,
        retry_delay_seconds=0,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    result = summary.results[0]
    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert result.success is True
    assert result.outfile.read_bytes() == TEST_MSEED_BYTES
    assert len(client.calls) == 2
    assert SMALL_ASCII_ERROR in log_text
    assert "Please wait until current transactions finish." in log_text
    assert "Retrying download for" in log_text


def test_service_waits_30_seconds_before_retry_after_failure(tmp_path: Path) -> None:
    clock = FakeClock()
    client = TimedSequencedDownloadClient(["fail", "success"], clock)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=2,
        retry_delay_seconds=30,
        timer=clock.timer,
        sleep=clock.sleep,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert summary.success_count == 1
    assert clock.sleep_calls == [30.0]
    assert [call_time for call_time, _ in client.calls] == [0.0, 30.0]
    assert "Retrying download for" in log_text
    assert "after 30-second pause" in log_text
    assert "Pausing all new download attempts for 30 seconds after failure." in log_text


def test_service_waits_30_seconds_before_retry_after_zero_byte_file(tmp_path: Path) -> None:
    clock = FakeClock()
    client = TimedSequencedDownloadClient(["empty", "success"], clock)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=2,
        retry_delay_seconds=30,
        timer=clock.timer,
        sleep=clock.sleep,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert summary.success_count == 1
    assert clock.sleep_calls == [30.0]
    assert [call_time for call_time, _ in client.calls] == [0.0, 30.0]


def test_service_waits_30_seconds_before_retry_after_small_ascii_file(tmp_path: Path) -> None:
    clock = FakeClock()
    client = TimedSequencedDownloadClient(["small_ascii", "success"], clock)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=2,
        retry_delay_seconds=30,
        timer=clock.timer,
        sleep=clock.sleep,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert summary.success_count == 1
    assert clock.sleep_calls == [30.0]
    assert [call_time for call_time, _ in client.calls] == [0.0, 30.0]


def test_service_retry_attempts_one_disables_retry_logging(tmp_path: Path) -> None:
    client = SequencedDownloadClient(["fail"], leave_tmp_on_failure=True)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=1,
        retry_delay_seconds=0,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path)

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    log_text = (tmp_path / "logs" / "download.log").read_text(encoding="utf-8")

    assert summary.failure_count == 1
    assert len(client.calls) == 1
    assert "Retrying download for" not in log_text


def test_service_pauses_before_next_serial_job_after_failure(tmp_path: Path) -> None:
    clock = FakeClock()
    client = TimedSequencedDownloadClient(["fail", "success"], clock)
    service = DownloaderService(
        http_client=client,
        max_workers=1,
        retry_attempts=1,
        retry_delay_seconds=30,
        timer=clock.timer,
        sleep=clock.sleep,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path, channels='["CHZ", "CHN"]')

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert summary.failure_count == 1
    assert summary.success_count == 1
    assert clock.sleep_calls == [30.0]
    assert client.calls == [
        (0.0, "OX.BOU5.1L.CHZ.D.2026.003"),
        (30.0, "OX.BOU5.1L.CHN.D.2026.003"),
    ]


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


def test_service_pauses_new_concurrent_attempts_after_failure(tmp_path: Path) -> None:
    clock = FakeClock()
    client = ConcurrentCooldownDownloadClient(clock)
    service = DownloaderService(
        http_client=client,
        max_workers=2,
        retry_attempts=1,
        retry_delay_seconds=30,
        timer=clock.timer,
        sleep=clock.sleep,
    )
    config_path = tmp_path / "config.yaml"
    write_config(config_path, tmp_path, channels='["CHZ", "CHN", "CHE"]')

    summary = service.run(
        config_path=config_path,
        station_id="BOU5",
        start=UTCDateTime("2026-01-03T00:00:00Z"),
        end=UTCDateTime("2026-01-04T00:00:00Z"),
    )

    assert summary.failure_count == 1
    assert summary.success_count == 2
    assert clock.sleep_calls == [30.0]
    assert sorted(client.calls[:2]) == [("CHN", 0.0), ("CHZ", 0.0)]
    assert client.calls[2] == ("CHE", 30.0)


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
