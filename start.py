"""
Flask + Flask-SocketIO web server
Configurable via config.yaml
"""
import os
import subprocess
import sys
import threading

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from tasks import task_manager
import downloader
import config
from app_logging import get_logger
from app_logging.downloads import read_downloads, count_downloads, delete_download_records, get_log_path as _get_downloads_log_path
import app_logging.downloads as downloads
import music_tagging

# Load config
cfg = config.load_config()
log = get_logger("server")


# ---- Auto-update yt-dlp on startup (background) ----
def _update_yt_dlp():
    """Check and update yt-dlp in a background thread so it doesn't block server start."""
    try:
        python = sys.executable
        result = subprocess.run(
            [python, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if "Requirement already satisfied" in out:
                log.info("yt-dlp is up-to-date")
            else:
                # Extract version line from output
                for line in out.splitlines():
                    if "Successfully installed" in line or "yt-dlp" in line.lower():
                        log.info("yt-dlp auto-updated: %s", line.strip())
                        break
                else:
                    log.info("yt-dlp auto-update completed")
        else:
            log.warning("yt-dlp auto-update failed: %s", result.stderr.strip()[-200:])
    except Exception as e:
        log.warning("yt-dlp auto-update error: %s", e)


_updater = threading.Thread(target=_update_yt_dlp, daemon=True)
_updater.start()

# Flask app
app = Flask(__name__,
            template_folder="templates",
            static_folder="static")
app.config["SECRET"] = "youtube-downloader-secret"

# SocketIO with eventlet
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    transports=["polling", "websocket"],
    ping_timeout=20,
    ping_interval=5,
    async_mode="eventlet",
)

# Wire up real broadcast function
downloader.set_broadcast_fn(socketio.emit)

# ============================================================
# HTTP Routes
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tasks")
def get_tasks():
    """Return all tasks"""
    return jsonify(task_manager.get_all_tasks())


@app.route("/title")
def get_title():
    """Extract YouTube video info from URL for input preview and quality options"""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is empty"}), 400
    try:
        info = downloader.get_video_info(url)
        return jsonify({
            "title": info.get("title", "video"),
            "qualities": info.get("qualities", []),
        })
    except Exception as e:
        return jsonify({"title": None, "qualities": [], "error": str(e)}), 500


@app.route("/clear", methods=["POST"])
def clear_completed():
    task_manager.clear_completed()
    socketio.emit("tasks_cleared", {})
    return jsonify({"ok": True})


@app.route("/logs")
def get_logs():
    """Return paginated download history from downloads.log"""
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = (page - 1) * limit
    records = read_downloads(limit=limit, offset=offset)
    total = count_downloads()
    pages = max(1, (total + limit - 1) // limit)
    return jsonify({
        "items": records,
        "page": page,
        "pages": pages,
        "total": total,
    })


@app.route("/api/app-log")
def get_app_log():
    """Return last N lines of app.log"""
    lines = int(request.args.get("lines", 100))
    log_dir = config.get_log_dir()
    log_path = os.path.join(log_dir, "app.log")
    if not os.path.exists(log_path):
        return jsonify({"lines": []})
    with open(log_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    return jsonify({"lines": [l.rstrip("\n") for l in tail]})


@app.route("/api/metadata-form")
def get_metadata_form():
    """
    Return current metadata for a music file, plus auto-filled suggestions from MusicBrainz.
    Query params: filepath (URL-encoded absolute path)
    """
    filepath = request.args.get("filepath", "").strip()
    if not filepath:
        return jsonify({"error": "filepath is required"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    # Read current metadata from file using ffprobe
    current = _read_current_metadata(filepath)

    # Auto-fill from MusicBrainz
    suggestion = music_tagging.auto_fill_metadata(filepath)
    if suggestion:
        # Merge: prefer existing values, fall back to suggestion
        def _nvl(a, b): return a if (a and a.strip()) else b
        suggestion = {
            "artist": _nvl(current.get("artist"), suggestion.get("artist")),
            "title": _nvl(current.get("title"), suggestion.get("title")),
            "album": suggestion.get("album"),
            "year": suggestion.get("year"),
            "genre": suggestion.get("genre"),
            "cover_url": suggestion.get("cover_url"),
        }
    else:
        suggestion = current.copy()

    return jsonify({
        "filepath": filepath,
        "current": current,
        "suggestion": suggestion,
    })


@app.route("/api/save-metadata", methods=["POST"])
def save_metadata():
    """Save metadata to a music file. Expects JSON: {filepath, artist, title, album, year, genre, cover_url}"""
    data = request.get_json()
    filepath = data.get("filepath", "").strip()
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    success = music_tagging.write_metadata(
        filepath,
        artist=data.get("artist", "").strip() or None,
        title=data.get("title", "").strip() or None,
        album=data.get("album", "").strip() or None,
        year=data.get("year", "").strip() or None,
        genre=data.get("genre", "").strip() or None,
        cover_url=data.get("cover_url", "").strip() or None,
    )
    if success:
        log.info("Metadata saved: %s", filepath)
        return jsonify({"ok": True})
    else:
        return jsonify({"error": "FFmpeg failed to write metadata"}), 500


@app.route("/api/config")
def get_config():
    """Return current config (all keys)."""
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def update_config():
    """
    Save partial config update to config.yaml.
    Returns updated config on success.
    """
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    # Filter to known config keys
    allowed = {
        "video_dir", "music_dir", "disk_limit_enabled",
        "max_video_size_gb", "max_music_size_gb",
        "cleanup_policy", "default_quality", "default_format",
        "retention_days", "strip_playlist", "cookie_site", "cookie_custom_path",
    }
    filtered = {k: v for k, v in data.items() if k in allowed}
    if not filtered:
        return jsonify({"error": "No valid config keys provided"}), 400

    try:
        config.save_config(filtered)
    except Exception as e:
        log.error("Failed to save config: %s", e)
        return jsonify({"error": str(e)}), 500

    # Reload config in this process
    global cfg
    cfg = config.load_config()

    # Broadcast config change to all connected clients
    socketio.emit("config_updated", cfg)

    log.info("Config updated: %s", list(filtered.keys()))
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/categories")
def get_categories():
    """Return current category definitions."""
    return jsonify(config.get_categories())


@app.route("/api/categories", methods=["POST"])
def update_categories():
    """
    Save full categories dict to config.yaml.
    Each category has: name, dir, enabled, max_size_gb (optional).
    """
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    try:
        config.save_categories(data)
    except Exception as e:
        log.error("Failed to save categories: %s", e)
        return jsonify({"error": str(e)}), 500

    log.info("Categories updated: %s", list(data.keys()))
    return jsonify({"ok": True, "categories": data})


@app.route("/api/tasks/remove", methods=["POST"])
def remove_tasks():
    """
    Remove specific task IDs from the task manager.
    Body: { ids: ["id1", "id2", ...] }
    """
    data = request.get_json()
    ids = data.get("ids", [])
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400
    for task_id in ids:
        task_manager.remove_task(task_id)
    return jsonify({"ok": True, "removed": len(ids)})


@app.route("/api/tasks/redownload", methods=["POST"])
def redownload_task():
    """
    Remove an error task and restart it with the same URL/format/quality/category.
    Body: { task_id: "..." }
    """
    data = request.get_json()
    task_id = data.get("task_id", "")
    old_task = task_manager.get_task(task_id)
    if not old_task:
        return jsonify({"error": "Task not found"}), 404

    url = old_task.url
    fmt = old_task.format
    quality = old_task.quality
    category = old_task.category

    task_manager.remove_task(task_id)

    cfg = config.load_config()
    strip_playlist = cfg.get("strip_playlist", False)
    new_task = task_manager.create_task(url, fmt, quality, category=category)

    t = threading.Thread(
        target=downloader.download_video,
        args=(new_task.id, url, fmt, quality, "", strip_playlist, category),
        daemon=True
    )
    t.start()

    return jsonify({"task_id": new_task.id, "task": new_task.to_dict()})


@app.route("/api/batch/delete-history", methods=["POST"])
def batch_delete_history():
    """
    Delete selected history records by their timestamp keys.
    Body: { ids: [ts1, ts2, ...] }
    """
    data = request.get_json()
    ids = data.get("ids", [])
    delete_file = bool(data.get("delete_file", False))
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400

    deleted = delete_download_records(ids, delete_file=delete_file)
    log.info("Batch deleted %d history records (delete_file=%s)", deleted, delete_file)
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/batch/move-history", methods=["POST"])
def batch_move_history():
    """
    Move files for selected history records to a new directory, then update the records.
    Body: { ids: [ts1, ...], dest_dir: "/new/path" }
    """
    data = request.get_json()
    ids = data.get("ids", [])
    dest_dir = (data.get("dest_dir") or "").strip()
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400
    if not dest_dir:
        return jsonify({"error": "dest_dir is required"}), 400
    if not os.path.isdir(dest_dir):
        return jsonify({"error": f"Destination directory does not exist: {dest_dir}"}), 400

    # Read all records and update those matching ids
    path = downloads.get_log_path()
    if not os.path.exists(path):
        return jsonify({"error": "downloads.log not found"}), 404

    import json as _json
    records = []
    moved = 0
    errors = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if rec.get("ts") in ids and rec.get("filename"):
                old_path = rec["filename"]
                if os.path.isfile(old_path):
                    basename = os.path.basename(old_path)
                    new_path = os.path.join(dest_dir, basename)
                    try:
                        os.rename(old_path, new_path)
                        rec["filename"] = new_path
                        moved += 1
                    except OSError as e:
                        errors.append(f"{old_path}: {e}")
                else:
                    errors.append(f"File not found: {old_path}")
            records.append(rec)

    if moved > 0:
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    log.info("Batch moved %d files to %s (%d errors)", moved, dest_dir, len(errors))
    return jsonify({"ok": True, "moved": moved, "errors": errors})


@app.route("/api/batch/rename-history", methods=["POST"])
def batch_rename_history():
    """
    Rename files for selected history records (rename in-place with new base name).
    Body: { ids: [ts1, ...], new_basename: "new_name" }
    The extension is preserved from the original file.
    """
    data = request.get_json()
    ids = data.get("ids", [])
    new_basename = (data.get("new_basename") or "").strip()
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400
    if not new_basename:
        return jsonify({"error": "new_basename is required"}), 400

    # Sanitize: keep only safe chars
    import re
    safe_name = re.sub(r"[^\w\- ]", "_", new_basename)
    safe_name = re.sub(r" +", " ", safe_name).strip()
    if not safe_name:
        return jsonify({"error": "new_basename contains no valid characters"}), 400

    path = downloads.get_log_path()
    if not os.path.exists(path):
        return jsonify({"error": "downloads.log not found"}), 404

    import json as _json
    records = []
    renamed = 0
    errors = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if rec.get("ts") in ids and rec.get("filename"):
                old_path = rec["filename"]
                if os.path.isfile(old_path):
                    dir_part = os.path.dirname(old_path)
                    ext = os.path.splitext(old_path)[1]
                    new_path = os.path.join(dir_part, f"{safe_name}{ext}")
                    if new_path == old_path:
                        renamed += 1  # no-op but count as processed
                    else:
                        try:
                            os.rename(old_path, new_path)
                            rec["filename"] = new_path
                            # Also update title to match new basename
                            rec["title"] = safe_name
                            renamed += 1
                        except OSError as e:
                            errors.append(f"{old_path}: {e}")
                else:
                    errors.append(f"File not found: {old_path}")
            records.append(rec)

    if renamed > 0:
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    log.info("Batch renamed %d files (%d errors)", renamed, len(errors))
    return jsonify({"ok": True, "renamed": renamed, "errors": errors})


def _read_current_metadata(filepath: str) -> dict:
    """Read existing metadata from a media file using ffprobe."""
    import json as _json
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode == 0:
            info = _json.loads(result.stdout)
            tags = info.get("format", {}).get("tags", {})
            return {
                "artist": tags.get("artist") or tags.get("TPE1"),
                "title": tags.get("title") or tags.get("TIT2"),
                "album": tags.get("album") or tags.get("TALB"),
                "year": tags.get("date") or tags.get("TYER") or tags.get("TDRC"),
                "genre": tags.get("genre") or tags.get("TCON"),
                "cover_url": None,
            }
    except Exception:
        pass
    return {}


@app.route("/download", methods=["POST"])
def start_download():
    """Receive download request"""
    data = request.get_json()
    url = data.get("url", "").strip()
    fmt = data.get("format", "video")
    quality = data.get("quality", "1080p")
    category = data.get("category")  # may be None

    if not url:
        return jsonify({"error": "URL cannot be empty"}), 400

    task = task_manager.create_task(url, fmt, quality, category=category)

    # Read server config for download behaviour flags
    cfg = config.load_config()
    strip_playlist = cfg.get("strip_playlist", False)

    t = threading.Thread(
        target=downloader.download_video,
        args=(task.id, url, fmt, quality, data.get("custom_name", ""), strip_playlist, category),
        daemon=True
    )
    t.start()

    return jsonify({"task_id": task.id, "task": task.to_dict()})


# ============================================================
# WebSocket Events
# ============================================================

@socketio.on("connect")
def on_connect():
    log.info(f"Client connected: {request.sid}")
    emit("task_list", task_manager.get_all_tasks())


@socketio.on("disconnect")
def on_disconnect():
    log.info(f"Client disconnected: {request.sid}")


@socketio.on("request_tasks")
def on_request_tasks():
    emit("task_list", task_manager.get_all_tasks())


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    host = cfg.get("host", "0.0.0.0")
    port = cfg.get("port", 1917)
    video_dir = config.get_video_dir()
    music_dir = config.get_music_dir()
    max_video = config.get_max_video_size_gb()
    max_music = config.get_max_music_size_gb()

    log.info("YouTube Downloader started on %s:%s", host, port)
    log.info("Video : %s (max %s GB)", video_dir, max_video)
    log.info("Audio : %s (max %s GB)", music_dir, max_music)

    socketio.run(app, host=host, port=port, debug=False)
