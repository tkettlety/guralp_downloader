#!/bin/bash

# Directory of conda setup file
source /Users/tom/opt/anaconda3/etc/profile.d/conda.sh 

# activate required conda environment
conda activate p311 || { echo "Failed to activate conda environment"; exit 1; }

# Define paths
PYTHON_SCRIPT="/Users/tom/work/scripts_packages/python/guralp_downloader/guralp_downloader.py"
CONFIG_FILE="/Users/tom/work/scripts_packages/python/guralp_downloader/examples/guralp_downloader_test.yaml"

# Define station IDs and cleanup directories
STATIONS=("BOU5")

# Example manual one-off window:
# python "$PYTHON_SCRIPT" "$CONFIG_FILE" "BOU5" \
#   --start 2026-01-03T01:00:00Z \
#   --end 2026-01-03T03:30:00Z
#
# SDS output examples:
#   /archive/2026/OX/BOU5/CHZ.D/OX.BOU5.1L.CHZ.D.2026.003
#   /archive/2026/OX/BOU5/CHZ.D/OX.BOU5.1L.CHZ.D.START_20260103T010000_END_20260103T033000

# Start downloads for each station in parallel
# Loop over each station and start the download in the background
for station in "${STATIONS[@]}"; do
    # echo "Starting download for $station"
    python "$PYTHON_SCRIPT" "$CONFIG_FILE" "$station" --start 2026-04-01T12:00:00Z --end 2026-04-01T13:00:00Z & 
done




