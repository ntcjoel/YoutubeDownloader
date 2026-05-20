# YouTube Downloader

Self-hosted YouTube video/audio downloader with real-time WebSocket progress, automatic disk cleanup, and Docker support.

---

## Features

- **Real-time WebSocket push** — task progress and status updates pushed to the browser instantly (no polling)
- **YouTube title preview** — fetches video title before downloading
- **Download history** — paginated log of completed downloads
- **Disk management** — automatic cleanup when video/music directories exceed configured size limits
- **Configurable via YAML** — all settings in `config.yaml`, overridable with environment variables
- **Docker-ready** — `Dockerfile` included for containerized deployment
- **yt-dlp auto-update** — `update.sh` script for scheduled yt-dlp updates via cron

---

## Architecture

```
start.py          Flask + Flask-SocketIO server (entry point)
downloader.py     yt-dlp wrapper, disk check + cleanup logic
tasks.py          In-memory task state manager
app.py            Legacy polling-mode server (reference)
config.yaml       All settings (paths, limits, defaults)
config.py         YAML loader with env var overrides
templates/
  index.html      Web UI (Socket.IO client, real-time task cards)
```

**WebSocket events** (server → client):
- `task_list` — full task list on connect
- `task_update` — individual task status change
- `tasks_cleared` — all tasks cleared

---

## Quick Start

### Bare Metal

```bash
git clone https://github.com/ntcjoel/YoutubeDownloader.git
cd YoutubeDownloader
./setup.sh          # creates venv, installs deps, creates dirs
python start.py     # runs at http://0.0.0.0:1917
```

### Docker

```bash
docker build -t ytdl .
docker run -d -p 1917:1917 \
  -v $(pwd)/video:/downloads/video \
  -v $(pwd)/music:/downloads/music \
  -e MAX_VIDEO_SIZE_GB=100 \
  ytdl
```

---

## Configuration

All settings live in `config.yaml`:

```yaml
# Server binding
host: "0.0.0.0"
port: 1917

# Directory paths (relative to project root or absolute)
video_dir: "video"
music_dir: "music"

# Disk usage limits in GB (0 = no limit)
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

# History retention in days (0 = forever)
retention_days: 30
```

### Environment Variable Overrides

Any config key can be overridden at runtime:

| Config Key | Env Variable |
|---|---|
| `host` | `HOST` |
| `port` | `PORT` |
| `video_dir` | `VIDEO_DIR` |
| `music_dir` | `MUSIC_DIR` |
| `max_video_size_gb` | `MAX_VIDEO_SIZE_GB` |
| `max_music_size_gb` | `MAX_MUSIC_SIZE_GB` |
| `cleanup_policy` | `CLEANUP_POLICY` |

Example:
```bash
MAX_VIDEO_SIZE_GB=200 PORT=8080 python start.py
```

---

## Keeping yt-dlp Updated

YouTube frequently changes its API. Run `update.sh` periodically to stay current:

```bash
./update.sh
```

**Automated (cron)** — every Sunday at 3 AM:
```bash
crontab -e
# add line:
0 3 * * 0 /path/to/update.sh
```

---

## Project Files

| File | Purpose |
|---|---|
| `start.py` | Server entry point (Flask + Flask-SocketIO) |
| `downloader.py` | yt-dlp downloader + disk cleanup |
| `tasks.py` | In-memory task state manager |
| `app.py` | Legacy polling-mode server (not used) |
| `config.yaml` | User-editable configuration |
| `config.py` | YAML config loader + env overrides |
| `requirements.txt` | Pinned Python dependencies |
| `setup.sh` | One-click setup for new machines |
| `update.sh` | yt-dlp update script |
| `Dockerfile` | Containerized deployment |
| `.env.example` | Environment variable template |
| `templates/index.html` | Web UI |

---

## Tech Stack

- **Flask-SocketIO** — WebSocket server with eventlet
- **yt-dlp** — YouTube downloader backend
- **ffmpeg** — media processing
- **Socket.IO** — real-time browser client (bundled locally, no CDN)
- **Python 3.12+**

---

## License

MIT
