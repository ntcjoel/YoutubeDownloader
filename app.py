"""
Flask + polling-mode web server (legacy)
Running at 10.1.1.4:1917
"""

import os
import threading
from flask import Flask, render_template, jsonify, request
from tasks import task_manager
import downloader
import config
from app_logging.downloads import read_downloads, count_downloads

# Flask app
app = Flask(__name__,
            template_folder="templates",
            static_folder="static")
app.config["SECRET"] = "youtube-downloader-secret"

# broadcaster (noop in polling mode)
def noop_broadcast(*args, **kwargs):
    pass
downloader.set_broadcast_fn(noop_broadcast)

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
    """Extract YouTube video title from URL for preview"""
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
    """Return last N lines of app.log for the browser console tab"""
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

    # Run download in background thread
    t = threading.Thread(
        target=downloader.download_video,
        args=(task.id, url, fmt, quality, plex),
        daemon=True
    )
    t.start()

    return jsonify({"task_id": task.id, "task": task.to_dict()})


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("YouTube Downloader")
    print(f"URL: http://10.1.1.4:1917")
    print(f"Video : ~/youtube-downloader/video/")
    print(f"Audio : ~/youtube-downloader/music/")
    print("=" * 50)

    app.run(host="10.1.1.4", port=1917, threaded=True, debug=False)
