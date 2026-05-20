"""
Download core module using yt-dlp with progress callbacks
"""

import os
import re
import yt_dlp
from tasks import task_manager, TaskStatus

# Project base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "video")
MUSIC_DIR = os.path.join(BASE_DIR, "music")

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(MUSIC_DIR, exist_ok=True)

# broadcaster injected by app.py
_broadcast_fn = None

def set_broadcast_fn(fn):
    global _broadcast_fn
    _broadcast_fn = fn


def _emit_update(task_id):
    """Notify task state change"""
    if _broadcast_fn is None:
        return
    task = task_manager.get_task(task_id)
    if task:
        _broadcast_fn("task_update", task.to_dict())


def make_progress_hook(task_id):
    """Generate yt-dlp progress_hook with task state updates"""
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = int(downloaded / total * 100)
                task_manager.get_task(task_id).update(
                    status=TaskStatus.DOWNLOADING,
                    progress=pct,
                    message=f"Downloading... {pct}%"
                )
            else:
                task_manager.get_task(task_id).update(
                    status=TaskStatus.DOWNLOADING,
                    message="Downloading..."
                )
        elif d["status"] == "finished":
            task_manager.get_task(task_id).update(
                status=TaskStatus.PROCESSING,
                progress=100,
                message="Processing..."
            )
        _emit_update(task_id)
    return hook


def get_video_title(url: str) -> str:
    """Extract video title from URL for filename"""
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
    """Remove playlist params to avoid downloading entire playlist"""
    url = re.sub(r'[?&]list=[^&]*', '', url)
    url = re.sub(r'[?&]start_radio=[^&]*', '', url)
    url = re.sub(r'\?$', '', url)
    return url


def download_video(task_id: str, url: str, format: str, quality: str, plex_compatible: bool = True):
    """
    Execute download task
    format: "video" -> merged mp4 saved to video/
           "audio" -> mp3 saved to music/
    plex_compatible: True prefers H.264/AAC MP4 output (avoids AV1/WebM)
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    task.update(status=TaskStatus.DOWNLOADING, progress=0, message="Initializing...")

    # Clean URL
    clean_url = clean_youtube_url(url)

    # Fetch and store title
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
            # Plex compatible: prefer H.264 + AAC, merge to MP4
            # YouTube 1080p usually has no standalone H.264 stream,
            # falls back to bestvideo+bestaudio then remux to MP4
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
            message="Download complete",
            filename=out_path
        )
        task_manager.record_completed(task_id)
    except Exception as e:
        task.update(
            status=TaskStatus.ERROR,
            progress=0,
            message="Download failed",
            error=str(e)
        )
    _emit_update(task_id)
