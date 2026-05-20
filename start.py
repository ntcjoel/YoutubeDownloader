"""
Flask + Flask-SocketIO Web服务器
运行在 10.1.1.4:1917
使用 eventlet 运行，支持真正的 WebSocket 推送
"""

import os
import eventlet
eventlet.monkey_patch()

import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from tasks import task_manager
import downloader

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
# HTTP 路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tasks")
def get_tasks():
    """返回所有任务"""
    return jsonify(task_manager.get_all_tasks())


@app.route("/title")
def get_title():
    """根据 URL 提取 YouTube 视频标题（用于输入时预览）"""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL 为空"}), 400
    try:
        title = downloader.get_video_title(url)
        return jsonify({"title": title})
    except Exception as e:
        return jsonify({"title": None, "error": str(e)}), 500


@app.route("/clear", methods=["POST"])
def clear_completed():
    task_manager.clear_completed()
    # 广播清除事件，让所有客户端刷新任务列表
    socketio.emit("tasks_cleared", {})
    return jsonify({"ok": True})


@app.route("/logs")
def get_logs():
    """返回分页的下载历史"""
    page = int(request.args.get("page", 1))
    return jsonify(task_manager.get_history(page))


@app.route("/download", methods=["POST"])
def start_download():
    """接收下载请求"""
    data = request.get_json()
    url = data.get("url", "").strip()
    fmt = data.get("format", "video")
    quality = data.get("quality", "1080p")
    plex = data.get("plex_compatible", True)

    if not url:
        return jsonify({"error": "URL 不能为空"}), 400

    task = task_manager.create_task(url, fmt, quality)

    # 后台线程执行下载
    t = threading.Thread(
        target=downloader.download_video,
        args=(task.id, url, fmt, quality, plex),
        daemon=True
    )
    t.start()

    return jsonify({"task_id": task.id, "task": task.to_dict()})


# ============================================================
# WebSocket 事件
# ============================================================

@socketio.on("connect")
def on_connect():
    print(f"[WS] Client connected: {request.sid}")
    # 客户端连接后立即推送当前所有任务
    emit("task_list", task_manager.get_all_tasks())


@socketio.on("disconnect")
def on_disconnect():
    print(f"[WS] Client disconnected: {request.sid}")


@socketio.on("request_tasks")
def on_request_tasks():
    """客户端主动请求任务列表"""
    emit("task_list", task_manager.get_all_tasks())


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("YouTube Downloader")
    print(f"URL: http://10.1.1.4:1917")
    print(f"Video : ~/youtube-downloader/video/")
    print(f"Audio : ~/youtube-downloader/music/")
    print("=" * 50)

    socketio.run(app, host="10.1.1.4", port=1917, debug=False)
