#!/usr/bin/env python3
"""Compatibility wrapper for the packaged guralp downloader CLI."""

from guralp_downloader.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
