from __future__ import annotations

import logging
import timeit
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .client import DownloadClient, RequestsDownloadClient
from .config import load_station_config
from .logging_utils import create_file_logger
from .models import DownloadJob, DownloadResult, DownloadWindow, RunSummary, StationConfig
from .paths import build_output_path
from .time_windows import build_download_jobs, resolve_download_window


class DownloaderService:
    """Coordinate config loading, job construction, downloading, and reporting."""

    def __init__(
        self,
        http_client: DownloadClient | None = None,
        max_workers: int = 3,
        buffer_seconds: int = 60,
        timer=timeit.default_timer,
    ) -> None:
        self.http_client = http_client or RequestsDownloadClient()
        self.max_workers = max_workers
        self.buffer_seconds = buffer_seconds
        self.timer = timer

    def run(
        self,
        config_path: str | Path,
        station_id: str,
        start=None,
        end=None,
        now=None,
    ) -> RunSummary:
        station_config = load_station_config(config_path, station_id)
        window = resolve_download_window(start=start, end=end, now=now)
        logger = create_file_logger(
            station_config.log_file,
            logger_name=f"guralp_downloader.{station_id}",
        )

        logger.info("Starting data download for station '%s'", station_id)
        logger.info("SDS archive root set to: %s", station_config.base_output_path)
        logger.info("Download window start (UTC): %s", window.start)
        logger.info("Download window end (UTC): %s", window.end)

        jobs = build_download_jobs(window, station_config.channels)
        start_time = self.timer()
        results = self._execute_jobs(jobs, station_config, logger)
        total_runtime = self.timer() - start_time

        logger.info(
            "Finished all downloads for %s.%s",
            station_config.network,
            station_config.station,
        )
        logger.info(
            "Total runtime: %.0f seconds (%.1f minutes)",
            total_runtime,
            total_runtime / 60,
        )

        return RunSummary(
            station_id=station_id,
            station_config=station_config,
            window=window,
            results=results,
            total_runtime=total_runtime,
        )

    def build_request_url(self, job: DownloadJob, station_config: StationConfig) -> str:
        query_start = job.chunk_start - self.buffer_seconds
        query_end = job.chunk_end + self.buffer_seconds
        request_str = (
            f"{station_config.network}.{station_config.station}."
            f"{station_config.location}.{job.channel}"
        )
        return (
            f"http://{station_config.sensor}/data"
            f"?channel={request_str}"
            f"&from={query_start.timestamp}"
            f"&to={query_end.timestamp}"
        )

    def _execute_jobs(
        self,
        jobs: list[DownloadJob],
        station_config: StationConfig,
        logger: logging.Logger,
    ) -> list[DownloadResult]:
        if not jobs:
            return []

        if self.max_workers <= 1 or len(jobs) == 1:
            return [self._run_job(job, station_config, logger) for job in jobs]

        results: list[DownloadResult] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as executor:
            futures = {
                executor.submit(self._run_job, job, station_config, logger): index
                for index, job in enumerate(jobs)
            }
            ordered_results: dict[int, DownloadResult] = {}
            for future in as_completed(futures):
                ordered_results[futures[future]] = future.result()
            for index in range(len(jobs)):
                results.append(ordered_results[index])
        return results

    def _run_job(
        self,
        job: DownloadJob,
        station_config: StationConfig,
        logger: logging.Logger,
    ) -> DownloadResult:
        outfile = build_output_path(job, station_config)
        outfile.parent.mkdir(parents=True, exist_ok=True)

        if outfile.exists():
            logger.info("File exists, skipping: %s", outfile)
            return DownloadResult(
                channel=job.channel,
                chunk_start=job.chunk_start,
                chunk_end=job.chunk_end,
                outfile=outfile,
                success=False,
                skipped=True,
                elapsed=0.0,
            )

        tmp_file = Path(f"{outfile}.tmp")
        if tmp_file.exists():
            logger.warning("Incomplete .tmp file detected, removing: %s", tmp_file)
            tmp_file.unlink()

        url = self.build_request_url(job, station_config)
        logger.info("Downloading from URL: %s", url)
        logger.info("Saving to: %s", outfile)

        start_time = self.timer()
        try:
            self.http_client.download(url, outfile, logger)
            elapsed = self.timer() - start_time
            logger.info("Download completed in %.0f seconds: %s", elapsed, outfile)
            return DownloadResult(
                channel=job.channel,
                chunk_start=job.chunk_start,
                chunk_end=job.chunk_end,
                outfile=outfile,
                success=True,
                skipped=False,
                elapsed=elapsed,
            )
        except Exception as exc:
            elapsed = self.timer() - start_time
            if tmp_file.exists():
                tmp_file.unlink()
            logger.error("Download failed for %s: %s", outfile, exc)
            return DownloadResult(
                channel=job.channel,
                chunk_start=job.chunk_start,
                chunk_end=job.chunk_end,
                outfile=outfile,
                success=False,
                skipped=False,
                elapsed=elapsed,
                error=str(exc),
            )
