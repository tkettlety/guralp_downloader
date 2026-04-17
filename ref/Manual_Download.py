#!/usr/bin/env python3

import argparse
import datetime
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import urllib.parse
import socket
import traceback
import time
import http.client


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


def download_file(url, output_path, timeout=30):
    print(f"\nDownloading: {url}", flush=True)

    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query

    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)

    try:
        t0 = time.time()
        print("Phase 1: connect()", flush=True)
        conn.connect()
        print(f"Connected in {time.time() - t0:.2f}s", flush=True)

        t1 = time.time()
        print("Phase 2: send request", flush=True)
        conn.putrequest("GET", path)
        conn.putheader("User-Agent", "Mozilla/5.0")
        conn.putheader("Accept", "*/*")
        conn.putheader("Connection", "close")
        conn.endheaders()
        print(f"Request sent in {time.time() - t1:.2f}s", flush=True)

        t2 = time.time()
        print("Phase 3: waiting for response headers", flush=True)
        resp = conn.getresponse()
        print(f"Response headers received in {time.time() - t2:.2f}s", flush=True)
        print(f"HTTP status: {resp.status} {resp.reason}", flush=True)
        print(f"Content-Type: {resp.getheader('Content-Type')}", flush=True)
        print(f"Content-Length: {resp.getheader('Content-Length')}", flush=True)

        total = 0
        first_byte_time = None

        with open(output_path, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                if first_byte_time is None:
                    first_byte_time = time.time() - t2
                    print(f"First byte after {first_byte_time:.2f}s", flush=True)
                f.write(chunk)
                total += len(chunk)

        print(f"Saved to: {output_path}", flush=True)
        print(f"Bytes written: {total}", flush=True)
        return True

    except Exception:
        print("Download failed:", flush=True)
        print(traceback.format_exc(), flush=True)
        return False

    finally:
        conn.close()


def preflight(ip, timeout=5):
    print(f"Testing TCP connectivity to {ip}:80 ...", flush=True)
    try:
        with socket.create_connection((ip, 80), timeout=timeout):
            print("TCP connection OK", flush=True)
    except Exception:
        print("TCP connection failed", flush=True)
        print(traceback.format_exc(), flush=True)


def probe_static_page(ip, timeout=15):
    url = f"http://{ip}/tab2.html"
    print(f"\nProbing static page: {url}", flush=True)

    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)

    try:
        print("Static probe: connect()", flush=True)
        conn.connect()
        print("Static probe: request()", flush=True)
        conn.request("GET", parsed.path, headers={
            "User-Agent": "Mozilla/5.0",
            "Connection": "close",
        })
        print("Static probe: getresponse()", flush=True)
        resp = conn.getresponse()
        print(f"Static probe status: {resp.status} {resp.reason}", flush=True)
        body = resp.read(5000).decode("utf-8", errors="replace")
        print("Static probe body preview:", flush=True)
        print(body, flush=True)
        return True
    except Exception:
        print("Static probe failed:", flush=True)
        print(traceback.format_exc(), flush=True)
        return False
    finally:
        conn.close()


def probe_ready(ip, timeout=10):
    print(f"\nRaw probing ready endpoint: http://{ip}/ready", flush=True)
    req = (
        f"GET /ready HTTP/1.1\r\n"
        f"Host: {ip}\r\n"
        f"User-Agent: Mozilla/5.0\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )

    try:
        with socket.create_connection((ip, 80), timeout=timeout) as s:
            s.sendall(req.encode("ascii"))
            data = s.recv(4096)
            print("First bytes from /ready:", flush=True)
            print(repr(data[:200]), flush=True)
            print(data.decode("utf-8", errors="replace"), flush=True)
            return True
    except Exception:
        print("Raw ready probe failed:", flush=True)
        print(traceback.format_exc(), flush=True)
        return False


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
    parser.add_argument("hours", type=float, help="Number of hours")

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

    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")

    args = parser.parse_args()
    channels = [ch.strip() for ch in args.channels.split(",") if ch.strip()]

    
    
    ######################
    # Run Preflight Check
    ######################
    preflight(args.ip)
    probe_static_page(args.ip, timeout=args.timeout)

    # if not probe_ready(args.ip, timeout=args.timeout):
    #     print("Device is not ready for download; aborting.", flush=True)
    #     return

    ######################
    # Time Conversion
    ######################
    start_unix = to_unix_timestamp(args.date, args.start_hour)
    end_unix = start_unix + int(args.hours * 3600)

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

        ok = download_file(url, filepath, timeout=args.timeout)
        if ok and os.path.exists(filepath):
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
