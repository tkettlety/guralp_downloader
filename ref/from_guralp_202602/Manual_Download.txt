#!/usr/bin/env python3

import argparse
import datetime
import os
import sys
import urllib.request

######################
# Helper Functions
######################
def to_unix_timestamp(date_str, hour):
    try:
        dt = datetime.datetime.strptime(f"{date_str} {hour}", "%Y-%m-%d %H")
        return int(dt.timestamp())
    except ValueError:
        print("Error: Invalid date or hour format. Use YYYY-MM-DD and 0-23.")
        sys.exit(1)


def download_file(url, output_path):
    try:
        print(f"Downloading: {url}")
        urllib.request.urlretrieve(url, output_path)
        print(f"Saved to: {output_path}")
    except Exception as e:
        print(f"Error downloading {url}")
        print(e)


######################
# Main
######################
def main():
    parser = argparse.ArgumentParser(
        description="Time-based data download from device (miniSEED)"
    )

    # Required Arguments
    parser.add_argument("ip", help="Device IP address")
    parser.add_argument("date", help="Date (YYYY-MM-DD)")
    parser.add_argument("start_hour", type=int, help="Start hour (0-23)")
    parser.add_argument("hours", type=int, help="Number of hours")

    # Add default values or add with flag
    parser.add_argument("--net", default="XX", help="Network code")
    parser.add_argument("--station", default="XXXX", help="Station code")
    parser.add_argument("--loc", default="00", help="Location code")

    parser.add_argument(
        "--channels",
        default="HNZ,HNN,HNE",
        help="Comma-separated channel list"
    )

    # Optional, combines all downloads to a single file
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Combine channels into one file",
    )

    # Specify output directory for where to save downloads
    parser.add_argument(
        "--output",
        default=".",
        help="Base output directory (default: current directory)",
    )

    args = parser.parse_args()
    channels = [ch.strip() for ch in args.channels.split(",") if ch.strip()]


    ######################
    # Time Conversion
    ######################
    start_unix = to_unix_timestamp(args.date, args.start_hour)
    end_unix = start_unix + (args.hours * 3600)

    print(f"Start UNIX: {start_unix}")
    print(f"End UNIX:   {end_unix}")

    ######################
    # Output Directory
    ######################
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(
        args.output,
        f"data_{args.ip}_{timestamp}"
    )

    os.makedirs(output_dir, exist_ok=True)
    print(f"Saving to: {output_dir}")

    ######################
    # Download Channels
    ######################
    downloaded_files = []

    for ch in channels:
        filename = f"{ch}.mseed"
        filepath = os.path.join(output_dir, filename)

        url = (
            f"http://{args.ip}/data?"
            f"channel={args.net}.{args.station}.{args.loc}.{ch}"
            f"&from={start_unix}&to={end_unix}"
        )

        download_file(url, filepath)

        if os.path.exists(filepath):
            downloaded_files.append(filepath)

    ######################
    # Combine Files (optional)
    ######################
    if args.combine and downloaded_files:
        dt_string = datetime.datetime.fromtimestamp(start_unix).strftime(
            "%Y.%m.%d-%H.%M.%S"
        )

        combined_name = f"{args.net}.{args.station}-{dt_string}.mseed"
        combined_path = os.path.join(output_dir, combined_name)

        print(f"Combining into: {combined_path}")

        with open(combined_path, "wb") as outfile:
            for f in downloaded_files:
                with open(f, "rb") as infile:
                    outfile.write(infile.read())

        print("Combined file created.")
    else:
        print("Combine disabled.")


if __name__ == "__main__":
    main()
