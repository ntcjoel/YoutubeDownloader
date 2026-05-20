"""
Flask + 轮询模式 Web服务器
运行在 10.1.1.4:1917
"""

import threading
from flask import Flask, render_template, jsonify, request
from tasks import task_manager
import downloader

# Flask app
app = Flask(__name__,
            template_folder="templates",
            static_folder="static")
app.config["SECRET"] = "youtube-downloader-secret"

# broadcaster（轮询模式下不需要）
def noop_broadcast(*args, **kwargs):
    pass
downloader.set_broadcast_fn(noop_broadcast)

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
# 启动
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("YouTube Downloader")
    print(f"URL: http://10.1.1.4:1917")
    print(f"Video : ~/youtube-downloader/video/")
    print(f"Audio : ~/youtube-downloader/music/")
    print("=" * 50)

    app.run(host="10.1.1.4", port=1917, threaded=True, debug=False)
