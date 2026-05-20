#!/bin/bash
# ============================================================
# YouTube Downloader - yt-dlp Auto-Update Script
# Run manually or schedule via cron:
#   crontab -e
#   # Every Sunday at 3am:
#   0 3 * * 0 /path/to/update.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "YouTube Downloader - Updating yt-dlp"
echo "=========================================="

# Activate venv if it exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    PYTHON="venv/bin/python"
else
    PYTHON="python3"
fi

echo "Current yt-dlp version:"
$PYTHON -m yt_dlp --version

echo ""
echo "Updating yt-dlp..."
pip install --upgrade yt-dlp

echo ""
echo "Updated yt-dlp version:"
$PYTHON -m yt_dlp --version

echo ""
echo "=========================================="
echo "yt-dlp update complete!"
echo "=========================================="
