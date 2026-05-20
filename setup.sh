#!/bin/bash
# ============================================================
# YouTube Downloader - One-time Setup Script
# Run this once on a new machine to set up the environment
# ============================================================
set -e

echo "=========================================="
echo "YouTube Downloader - Setup"
echo "=========================================="

# Detect Python
if command -v python3 &>/dev/null; then
    PYTHON=$(command -v python3)
elif command -v python &>/dev/null; then
    PYTHON=$(command -v python)
else
    echo "ERROR: Python not found. Please install Python 3.9+ first."
    exit 1
fi

echo "Using Python: $PYTHON"
$PYTHON --version

# Get script directory (works with symlinks)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv venv
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create output directories
mkdir -p video music

# Check if config.yaml exists, if not copy from example
if [ ! -f "config.yaml" ]; then
    echo "No config.yaml found. Copying default..."
    # Create default config
    cat > config.yaml << 'EOF'
# YouTube Downloader Configuration

# Server binding
host: "0.0.0.0"
port: 1917

# Directory paths (absolute or relative to project root)
video_dir: "video"
music_dir: "music"

# Disk usage limits (in GB, 0 = no limit)
max_video_size_gb: 50
max_music_size_gb: 10

# Cleanup policy when limit is exceeded
#   oldest_first  - delete oldest completed files until under limit
#   skip          - reject new downloads when at limit
cleanup_policy: "oldest_first"

# Download defaults
default_quality: "1080p"
default_format: "video"
plex_compatible: true

# History retention (days, 0 = forever)
retention_days: 30
EOF
    echo "Created config.yaml with defaults."
else
    echo "config.yaml already exists, skipping."
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  python start.py"
echo ""
echo "Or run in background:"
echo "  nohup python start.py > server.log 2>&1 &"
echo ""
echo "To update yt-dlp in the future:"
echo "  ./update.sh"
echo "=========================================="
