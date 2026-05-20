"""
下载核心模块
使用 yt-dlp 进行下载，支持进度回调
"""

import os
import re
import yt_dlp
from tasks import task_manager, TaskStatus

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "video")
MUSIC_DIR = os.path.join(BASE_DIR, "music")

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(MUSIC_DIR, exist_ok=True)

# broadcaster 由 app.py 注入
_broadcast_fn = None

def set_broadcast_fn(fn):
    global _broadcast_fn
    _broadcast_fn = fn


def _emit_update(task_id):
    """通知任务状态变化"""
    if _broadcast_fn is None:
        return
    task = task_manager.get_task(task_id)
    if task:
        _broadcast_fn("task_update", task.to_dict())


def make_progress_hook(task_id):
    """生成 yt-dlp 的 progress_hook，回调通知任务进度"""
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = int(downloaded / total * 100)
                task_manager.get_task(task_id).update(
                    status=TaskStatus.DOWNLOADING,
                    progress=pct,
                    message=f"下载中... {pct}%"
                )
            else:
                task_manager.get_task(task_id).update(
                    status=TaskStatus.DOWNLOADING,
                    message="下载中..."
                )
        elif d["status"] == "finished":
            task_manager.get_task(task_id).update(
                status=TaskStatus.PROCESSING,
                progress=100,
                message="处理中..."
            )
        _emit_update(task_id)
    return hook


def get_video_title(url: str) -> str:
    """从 URL 获取视频标题用于文件名"""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 10,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "video") if info else "video"
    except Exception:
        return "video"


def clean_youtube_url(url: str) -> str:
    """移除播放列表参数，避免 yt-dlp 解析整个列表"""
    url = re.sub(r'[?&]list=[^&]*', '', url)
    url = re.sub(r'[?&]start_radio=[^&]*', '', url)
    url = re.sub(r'\?$', '', url)
    return url


def download_video(task_id: str, url: str, format: str, quality: str, plex_compatible: bool = True):
    """
    执行下载任务
    format: "video" -> 合并后mp4存video/
           "audio" -> 纯音频mp3存music/
    plex_compatible: True 时优先使用 H.264/AAC MP4（避免 AV1/WebM）
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    task.update(status=TaskStatus.DOWNLOADING, progress=0, message="初始化...")

    # 清理 URL
    clean_url = clean_youtube_url(url)

    # 获取标题并存储
    title = get_video_title(clean_url)
    task.update(title=title)
    _emit_update(task_id)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)

    outtmpl_video = os.path.join(VIDEO_DIR, f"{safe_title}.%(ext)s")
    outtmpl_audio = os.path.join(MUSIC_DIR, f"{safe_title}.%(ext)s")

    if format == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl_audio,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [make_progress_hook(task_id)],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "merge_output_format": "mp3",
        }
        out_path = os.path.join(MUSIC_DIR, f"{safe_title}.mp3")
        download_url = clean_url
    else:
        max_height = quality.replace("p", "")
        if plex_compatible:
            # Plex 兼容：优先 H.264 + AAC，直接合并为 MP4
            # YouTube 1080p 通常没有独立 H.264 流，回退到 bestvideo+bestaudio 再转 MP4
            video_format = (
                f"bestvideo[height<={max_height}][vcodec=h264]+bestaudio[acodec=mp4a]/"
                f"bestvideo[height<={max_height}][vcodec=h264]+bestaudio[acodec=aac]/"
                f"bestvideo[height<={max_height}]+bestaudio"
            )
        else:
            video_format = f"bestvideo[height<={max_height}]+bestaudio/best"

        ydl_opts = {
            "format": video_format,
            "outtmpl": outtmpl_video,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "merge_output_format": "mp4",
            "progress_hooks": [make_progress_hook(task_id)],
        }
        out_path = os.path.join(VIDEO_DIR, f"{safe_title}.mp4")
        download_url = clean_url

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([download_url])

        task.update(
            status=TaskStatus.COMPLETED,
            progress=100,
            message="下载完成",
            filename=out_path
        )
        task_manager.record_completed(task_id)
    except Exception as e:
        task.update(
            status=TaskStatus.ERROR,
            progress=0,
            message="下载失败",
            error=str(e)
        )
    _emit_update(task_id)
