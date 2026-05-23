# YouTube Downloader

Self-hosted YouTube video/audio downloader with real-time WebSocket progress, task persistence, automatic disk cleanup, and Docker support.

---

## Features

- **Real-time WebSocket push** — task progress and status updates pushed to the browser instantly via Flask-SocketIO
- **YouTube title + quality preview** — fetches available quality options before downloading
- **Playlist support** — strips `list=`/`index=` params, processes playlist URLs correctly
- **Task persistence** — tasks survive server restarts; interrupted tasks recovered as `error` with one-click redownload
- **yt-dlp auto-update** — background thread checks and updates yt-dlp on every server startup
- **MP3 metadata embedding** — embeds thumbnail (album art), title, and metadata into downloaded MP3s
- **Download history** — paginated log with per-item menu: Delete record / Delete file
- **Dynamic quality selector** — quality dropdown populated based on actual available formats
- **Categories** — create/manage download categories (video/music) via Settings UI
- **Theme** — dark (GitHub black) and light (warm cream) modes; auto-detects by time (6:00–18:00 light), manual toggle in status bar
- **Disk management** — automatic cleanup when video/music directories exceed configured size limits
- **Docker-ready** — `Dockerfile` + `docker-compose.yml` for containerized deployment

---

## Architecture

```
start.py          Flask + Flask-SocketIO server (entry point)
downloader.py     yt-dlp wrapper, disk check + cleanup logic
tasks.py          Task state manager with JSON persistence (tasks_state.json)
config.yaml       All settings (paths, limits, categories, defaults)
config.py         YAML loader with env var overrides
templates/
  index.html      Web UI (Socket.IO client, real-time task cards, theme system)
static/
  app.js          Frontend logic (WebSocket events, theme, menus)
app_logging/
  downloads.py    Logging utility
```

**WebSocket events** (server → client):
- `task_list` — full task list on connect
- `task_update` — individual task status change
- `tasks_cleared` — all tasks cleared

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/ntcjoel/YoutubeDownloader.git
cd YoutubeDownloader

# Prepare local directories (logs must be owned by uid 1000 for container write access)
mkdir -p logs cookies data
sudo chown -R 1000:1000 logs cookies data

# Edit config.yaml — paths are CONTAINER-INTERNAL (not host paths)
# video_dir: "/app/video"    → host /mnt/nfs/pt/ytb_video
# music_dir: "/app/music"    → host /mnt/nfs/pt/ytb_music
vim config.yaml

# Build and start
docker compose up -d --build

# View logs
docker compose logs -f
```

> **Why `user: "1000:1000"`?** The container runs as host user 1000 to avoid NFS root_squash permission errors. Ensure host NFS dirs (`/mnt/nfs/pt/ytb_video`, `/mnt/nfs/pt/ytb_music`) are owned by uid 1000.

Access at `http://<your-server>:1917`

### Bare Metal

```bash
git clone https://github.com/ntcjoel/YoutubeDownloader.git
cd YoutubeDownloader

# Install system deps
sudo apt install ffmpeg python3-venv

# Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Edit config.yaml
vim config.yaml

# Start
python start.py
```

---

## Configuration

All settings live in `config.yaml`:

```yaml
# Server binding
host: "0.0.0.0"
port: 1917

# Disk usage limits in GB (0 = no limit)
max_video_size_gb: 0
max_music_size_gb: 0

# Cleanup policy when limit is exceeded
#   oldest_first  - delete oldest completed files until under limit
#   skip          - reject new downloads when at limit
cleanup_policy: "oldest_first"

# Download defaults
default_quality: "1080p"
default_format: "video"

# Categories (manageable via Settings UI)
categories:
  - name: "video"
    quality: "1080p"
    format: "video"
  - name: "music"
    quality: "bestaudio"
    format: "audio"

# History retention in days (0 = forever)
retention_days: 30
```

### Path configuration by deployment method

**Docker:** `config.yaml` uses **container-internal paths**. The docker-compose volume mounts map these to host directories.

| config key | container path | typical host mount |
|---|---|---|
| `video_dir` | `/app/video` | `/mnt/nfs/pt/ytb_video` |
| `music_dir` | `/app/music` | `/mnt/nfs/pt/ytb_music` |

Example `config.yaml` for Docker:
```yaml
video_dir: "/app/video"
music_dir: "/app/music"
```

**Bare metal:** `config.yaml` uses **host paths directly**.

```yaml
video_dir: "/mnt/nfs/pt/ytb_video"
music_dir: "/mnt/nfs/pt/ytb_music"
```

### Environment Variable Overrides

| Config Key | Env Variable |
|---|---|
| `host` | `HOST` |
| `port` | `PORT` |
| `video_dir` | `VIDEO_DIR` |
| `music_dir` | `MUSIC_DIR` |
| `max_video_size_gb` | `MAX_VIDEO_SIZE_GB` |
| `max_music_size_gb` | `MAX_MUSIC_SIZE_GB` |
| `cleanup_policy` | `CLEANUP_POLICY` |

---

## Project Files

| File | Purpose |
|---|---|
| `start.py` | Server entry point (Flask + Flask-SocketIO), all API routes |
| `downloader.py` | yt-dlp downloader + disk cleanup + task_manager integration |
| `tasks.py` | Task state manager with JSON file persistence (`tasks_state.json`) |
| `config.yaml` | User-editable configuration |
| `config.py` | YAML config loader + env overrides |
| `requirements.txt` | Pinned Python dependencies |
| `Dockerfile` | Container build definition |
| `docker-compose.yml` | Container orchestration (volumes, ports, restart policy) |
| `templates/index.html` | Web UI (Socket.IO v4 client, theme CSS, download form) |
| `static/app.js` | Frontend WebSocket logic, theme, menus |

---

## Tech Stack

- **Flask-SocketIO** — WebSocket server with eventlet
- **yt-dlp** — YouTube downloader backend
- **ffmpeg** — media processing and metadata embedding
- **Socket.IO v4** — real-time browser client (bundled locally, no CDN dependency)
- **Python 3.11+**

---

## License

MIT
