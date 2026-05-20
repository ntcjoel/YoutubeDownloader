"""
Download core module using yt-dlp with progress callbacks
"""
import os
import re
import glob
import yt_dlp
from tasks import task_manager, TaskStatus
import config
from app_logging import get_logger
from app_logging.downloads import log_download

log = get_logger("downloader")


def _dir_size(path: str) -> float:
    """Return total size of directory in GB"""
    if not os.path.exists(path):
        return 0.0
    total = sum(
        os.path.getsize(f) for f in glob.glob(os.path.join(path, "*"))
        if os.path.isfile(f)
    )
    return total / (1024 ** 3)


def _list_completed_files(dir_path: str) -> list[tuple[str, float]]:
    """Return list of (filepath, mtime) for all mp4/mp3 files in dir, oldest first"""
    files = []
    for ext in ("*.mp4", "*.mp3", "*.webm"):
        for f in glob.glob(os.path.join(dir_path, ext)):
            if os.path.isfile(f):
                files.append((f, os.path.getmtime(f)))
    files.sort(key=lambda x: x[1])
    return files


def _cleanup_if_needed(dir_path: str, max_size_gb: float, needed_gb: float = 1.0) -> bool:
    """
    Remove oldest completed files until dir is under max_size_gb.
    Returns True if space was freed (or already ok), False if cannot free enough.
    """
    policy = config.get_cleanup_policy()
    max_bytes = max_size_gb * (1024 ** 3)

    while True:
        current_size = _dir_size(dir_path)
        if current_size + needed_gb * (1024 ** 3) <= max_bytes:
            return True  # enough space

        if policy == "skip":
            return False  # reject download

        # oldest_first: delete oldest files
        files = _list_completed_files(dir_path)
        if not files:
            return False  # no files to delete

        oldest_file, _ = files[0]
        try:
            size = os.path.getsize(oldest_file)
            os.remove(oldest_file)
            log.warning("Cleanup removed %s (%.1f MB)", oldest_file, size / 1024**2)
        except OSError as e:
            log.error("Cleanup failed to remove %s: %s", oldest_file, e)
            return False


def _ensure_dirs():
    os.makedirs(config.get_video_dir(), exist_ok=True)
    os.makedirs(config.get_music_dir(), exist_ok=True)


# broadcaster injected by start.py
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

    _ensure_dirs()

    task.update(status=TaskStatus.DOWNLOADING, progress=0, message="Initializing...")

    # Clean URL
    clean_url = clean_youtube_url(url)

    # Fetch and store title
    title = get_video_title(clean_url)
    task.update(title=title)
    _emit_update(task_id)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)

    outtmpl_video = os.path.join(config.get_video_dir(), f"{safe_title}.%(ext)s")
    outtmpl_audio = os.path.join(config.get_music_dir(), f"{safe_title}.%(ext)s")

    if format == "audio":
        target_dir = config.get_music_dir()
        max_size_gb = config.get_max_music_size_gb()
        out_path = os.path.join(target_dir, f"{safe_title}.mp3")
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
        download_url = clean_url
    else:
        target_dir = config.get_video_dir()
        max_size_gb = config.get_max_video_size_gb()
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
        out_path = os.path.join(target_dir, f"{safe_title}.mp4")
        download_url = clean_url

    # Check / free disk space before downloading
    if max_size_gb > 0:
        if not _cleanup_if_needed(target_dir, max_size_gb):
            msg = "Disk limit reached, no files to free"
            task.update(
                status=TaskStatus.ERROR,
                progress=0,
                message=msg,
                error="Disk limit exceeded"
            )
            log.error("Task %s failed: %s", task_id, msg)
            log_download(
                url=url, title=title, filename="",
                fmt=format, quality=quality,
                size_mb=0, duration_s=0,
                status="failed", error=msg
            )
            _emit_update(task_id)
            return

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([download_url])

        # Get file size and duration
        size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
        duration_s = 0

        task.update(
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Download complete",
            filename=out_path
        )
        task_manager.record_completed(task_id)
        log.info("Task %s completed: %s -> %s (%.1f MB)", task_id, title, out_path, size_mb)
        log_download(
            url=url, title=title, filename=out_path,
            fmt=format, quality=quality,
            size_mb=size_mb, duration_s=duration_s,
            status="success"
        )
    except Exception as e:
        log.error("Task %s failed: %s", task_id, e)
        log_download(
            url=url, title=title, filename="",
            fmt=format, quality=quality,
            size_mb=0, duration_s=0,
            status="failed", error=str(e)
        )
        task.update(
            status=TaskStatus.ERROR,
            progress=0,
            message="Download failed",
            error=str(e)
        )
    _emit_update(task_id)
