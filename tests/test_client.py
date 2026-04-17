import logging
from pathlib import Path

import pytest
import requests

from guralp_downloader.client import RequestsDownloadClient


class FakeResponse:
    def __init__(self, chunks=None, error: Exception | None = None) -> None:
        self.chunks = chunks or []
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_content(self, chunk_size: int):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def test_requests_download_client_success_ignores_empty_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = RequestsDownloadClient(timeout=12, chunk_size=4)
    output_path = tmp_path / "data.mseed"
    response = FakeResponse(chunks=[b"abc", b"", None, b"def"])
    calls: list[tuple[str, bool, int]] = []

    def fake_get(url: str, stream: bool, timeout: int):
        calls.append((url, stream, timeout))
        return response

    monkeypatch.setattr("guralp_downloader.client.requests.get", fake_get)
    logger = logging.getLogger("test.client.success")

    with caplog.at_level(logging.INFO):
        client.download("http://example.test/data", output_path, logger)

    assert output_path.read_bytes() == b"abcdef"
    assert not output_path.with_suffix(".mseed.tmp").exists()
    assert calls == [("http://example.test/data", True, 12)]
    assert "Download complete" in caplog.text


def test_requests_download_client_removes_tmp_on_request_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RequestsDownloadClient()
    output_path = tmp_path / "data.mseed"
    response = FakeResponse(
        chunks=[b"partial", requests.exceptions.RequestException("stream failure")]
    )

    def fake_get(url: str, stream: bool, timeout: int):
        return response

    monkeypatch.setattr("guralp_downloader.client.requests.get", fake_get)
    logger = logging.getLogger("test.client.failure")

    with pytest.raises(requests.exceptions.RequestException, match="stream failure"):
        client.download("http://example.test/data", output_path, logger)

    assert not output_path.exists()
    assert not output_path.with_suffix(".mseed.tmp").exists()
