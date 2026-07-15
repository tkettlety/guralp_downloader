from __future__ import annotations

from pathlib import Path

import yaml

from .models import StationConfig


REQUIRED_KEYS = (
    "sensor",
    "network",
    "station",
    "location",
    "channels",
    "base_output_path",
    "log_file",
)


def load_station_config(config_path: str | Path, station_id: str) -> StationConfig:
    """Load and validate one station configuration from YAML."""
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        config_data = yaml.safe_load(handle) or {}

    if station_id not in config_data:
        raise ValueError(f"No config found for station '{station_id}'")

    station_config = config_data[station_id] or {}
    missing = [key for key in REQUIRED_KEYS if key not in station_config]
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(
            f"Station '{station_id}' is missing required config keys: {missing_list}"
        )

    channels = tuple(station_config["channels"])
    if not channels:
        raise ValueError(f"Station '{station_id}' must define at least one channel")

    return StationConfig(
        sensor=str(station_config["sensor"]),
        network=str(station_config["network"]),
        station=str(station_config["station"]),
        location=str(station_config["location"]),
        channels=channels,
        base_output_path=Path(station_config["base_output_path"]),
        log_file=Path(station_config["log_file"]),
    )
