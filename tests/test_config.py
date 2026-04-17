from pathlib import Path

import pytest

from guralp_downloader.config import load_station_config


def test_load_station_config_success(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: ["CHZ", "CHN"]
  base_output_path: "/tmp/archive"
  log_file: "/tmp/archive/download.log"
""".strip(),
        encoding="utf-8",
    )

    station_config = load_station_config(config_path, "BOU5")

    assert station_config.sensor == "172.24.74.246:8080"
    assert station_config.channels == ("CHZ", "CHN")
    assert station_config.base_output_path == Path("/tmp/archive")


def test_load_station_config_missing_station(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="No config found for station 'BOU5'"):
        load_station_config(config_path, "BOU5")


def test_load_station_config_missing_required_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
BOU5:
  sensor: "172.24.74.246:8080"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required config keys"):
        load_station_config(config_path, "BOU5")


def test_load_station_config_rejects_empty_channels(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
BOU5:
  sensor: "172.24.74.246:8080"
  network: "OX"
  station: "BOU5"
  location: "1L"
  channels: []
  base_output_path: "/tmp/archive"
  log_file: "/tmp/archive/download.log"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define at least one channel"):
        load_station_config(config_path, "BOU5")
