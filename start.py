"""
Flask + Flask-SocketIO web server
Configurable via config.yaml
"""
import os
import eventlet
eventlet.monkey_patch()

import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from tasks import task_manager
import downloader
import config
from app_logging import get_logger
from app_logging.downloads import read_downloads, count_downloads

# Load config
cfg = config.load_config()
log = get_logger("server")

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
    """Extract YouTube video title from URL for input preview"""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is empty"}), 400
    try:
        title = downloader.get_video_title(url)
        return jsonify({"title": title})
    except Exception as e:
        return jsonify({"title": None, "error": str(e)}), 500


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


@app.route("/download", methods=["POST"])
def start_download():
    """Receive download request"""
    data = request.get_json()
    url = data.get("url", "").strip()
    fmt = data.get("format", "video")
    quality = data.get("quality", "1080p")
    plex = data.get("plex_compatible", True)

    if not url:
        return jsonify({"error": "URL cannot be empty"}), 400

    task = task_manager.create_task(url, fmt, quality)

    t = threading.Thread(
        target=downloader.download_video,
        args=(task.id, url, fmt, quality, plex, data.get("custom_name", "")),
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
