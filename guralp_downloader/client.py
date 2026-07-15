from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import requests


class DownloadClient(Protocol):
    def download(self, url: str, output_path: Path, logger: logging.Logger) -> None:
        """Download url to output_path or raise an exception on failure."""


class RequestsDownloadClient:
    """requests-backed downloader that writes atomically via a .tmp file."""

    def __init__(self, timeout: int = 30, chunk_size: int = 8192) -> None:
        self.timeout = timeout
        self.chunk_size = chunk_size

    def download(self, url: str, output_path: Path, logger: logging.Logger) -> None:
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        try:
            with requests.get(url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                with tmp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            handle.write(chunk)
            tmp_path.rename(output_path)
            logger.info("Download complete: %s", output_path)
        except requests.exceptions.RequestException:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
