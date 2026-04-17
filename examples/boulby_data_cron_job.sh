#!/bin/bash

# Directory of conda setup file
source /Users/tom/opt/anaconda3/etc/profile.d/conda.sh 

# activate required conda environment
conda activate p311 || { echo "Failed to activate conda environment"; exit 1; }

# Define paths
PYTHON_SCRIPT="/Users/tom/work/boulby_data/guralp_downloader.py"
CONFIG_FILE="/Users/tom/work/boulby_data/boulby_download_config.yaml"
CLEANUP_SCRIPT="/Users/tom/work/boulby_data/cleanup_tmp.sh"
RSYNC_LOG="/Users/tom/work/boulby_data/boulby_rsync.log"
LOCAL_DATA_DIR="/Users/tom/work/boulby_data"
REMOTE_DATA_DIR="/rfs/eart0514/boulby_seismic_study/"
REMOTE_USER="eart0514@barra"

# Define station IDs and cleanup directories
STATIONS=("BOU5")
# STATIONS=("MRY2" "BOU1" "BOU5" "BOU6")
# STATIONS=("MRSY" ) 

# Corresponding data directories (must match STATIONS order)
STATION_DIRS=(
  "/Users/tom/work/boulby_data/remote_seis/BOU5"
)
# STATION_DIRS=(
#   "/Users/tom/work/boulby_data/remote_seis/MRY2"
#   "/Users/tom/work/boulby_data/remote_seis/BOU1"
#   "/Users/tom/work/boulby_data/remote_seis/BOU5"
#   "/Users/tom/work/boulby_data/remote_seis/BOU6"
# )
# STATION_DIRS=(
  # "/Users/tom/work/boulby_data/mars_yard/MRSY"
  
# )

# Start downloads in parallel
# Loop over each station and start the download in the background
for station in "${STATIONS[@]}"; do
    # echo "Starting download for $station"
    python "$PYTHON_SCRIPT" "$CONFIG_FILE" "$station" &
done

# Example manual one-off window:
# python "$PYTHON_SCRIPT" "$CONFIG_FILE" "BOU5" \
#   --start 2026-01-03T01:00:00Z \
#   --end 2026-01-03T03:30:00Z

# Wait for all background jobs to finish
wait
# echo "All downloads complete."

# Clean up incomplete .tmp files
for i in "${!STATIONS[@]}"; do
    station="${STATIONS[$i]}"
    dir="${STATION_DIRS[$i]}"
    # echo "Cleaning up $dir"
    "$CLEANUP_SCRIPT" "$dir"
done

# Backup to RFS
# echo "Syncing data to remote server..."
rsync -havzP --stats "$LOCAL_DATA_DIR" "$REMOTE_USER:$REMOTE_DATA_DIR" \
    --log-file="$RSYNC_LOG" > /dev/null 2>&1


