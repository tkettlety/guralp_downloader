# guralp_downloader

Download day-chunked miniseed data from Guralp Certimus/Minimus sensors into an SDS-style archive.

## Entry points

- Compatibility script: `python guralp_downloader.py <config.yaml> <station_id>`
- Package CLI: `python -m guralp_downloader <config.yaml> <station_id>`

## Layout

- `guralp_downloader/`: package code
- `tests/`: pytest suite
- `examples/`: sample configs and wrapper scripts

## Example

```bash
python -m guralp_downloader examples/guralp_downloader_test.yaml BOU5 \
  --start 2026-01-03T01:00:00Z \
  --end 2026-01-03T03:30:00Z
```
