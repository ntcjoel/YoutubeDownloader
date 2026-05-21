"""
Download core module using yt-dlp with progress callbacks
"""
import os
import re
import glob
from urllib.parse import urlparse, parse_qs, urlencode
import yt_dlp
from tasks import task_manager, TaskStatus
from threading import Semaphore

_download_semaphore = Semaphore(3)  # max 3 concurrent downloads
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
    # Ensure all enabled category directories exist
    for cat_name, cat_conf in config.get_categories().items():
        if cat_conf.get("enabled", True):
            cat_dir = cat_conf.get("dir", "")
            if cat_dir:
                from pathlib import Path
                config_path = Path(config._get_config_path()).parent.resolve()
                if not os.path.isabs(cat_dir):
                    cat_dir = str(config_path / cat_dir)
                os.makedirs(cat_dir, exist_ok=True)


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


def get_video_info(url: str) -> dict:
    """Extract video info from URL for filename and metadata.
    Strips playlist params so we always get single-video info."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 10,
    }

    # Strip playlist params so we always query single video info
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.pop("list", None)
    params.pop("index", None)
    new_query = urlencode(params, doseq=True)
    video_url = parsed._replace(query=new_query).geturl()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return {"title": "video", "uploader": "", "thumbnail": "", "qualities": []}

            # Extract available video heights for quality dropdown
            formats = info.get("formats", [])
            heights = set()
            for f in formats:
                if f.get("vcodec") != "none" and f.get("vcodec") is not None:
                    h = f.get("height")
                    if h:
                        heights.add(h)
            quality_list = sorted([f"{h}p" for h in heights], reverse=True)

            return {
                "title": info.get("title", "video"),
                "uploader": info.get("uploader", ""),
                "thumbnail": info.get("thumbnail", ""),
                "qualities": quality_list,
            }
    except Exception:
        return {"title": "video", "uploader": "", "thumbnail": "", "qualities": []}


def get_video_title(url: str) -> str:
    return get_video_info(url)["title"]


def embed_mp3_metadata(filepath: str, title: str, artist: str = "", thumbnail_url: str = ""):
    """
    Embed title/artist metadata and optional thumbnail into an MP3 file using FFmpeg.
    Uses ID3v2 APIC frame for album art embedding.
    """
    import subprocess, tempfile

    safe_title = title
    safe_artist = artist or "Unknown Artist"

    # Build the FFmpeg command
    # We use two passes:
    # Pass 1: re-encode audio with new metadata (ID3v2 tags)
    # Pass 2: embed thumbnail as APIC (album art) frame
    tmp_out = filepath + ".meta.tmp"

    # Step 1: Write title/artist metadata using stream copy
    # (avoids re-encoding the audio)
    meta_cmd = [
        "ffmpeg", "-y",
        "-i", filepath,
        "-codec", "copy",
        "-id3v2_version", "4",
        "-metadata", f"title={safe_title}",
        "-metadata", f"artist={safe_artist}",
        "-metadata", f"album={safe_artist}",
        tmp_out,
    ]
    try:
        result = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.warning("Metadata tag write failed for %s: %s", filepath, result.stderr[-200:])
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            return
    except Exception as e:
        log.warning("Metadata embed error for %s: %s", filepath, e)
        return

    # Step 2: Embed thumbnail as APIC (album art) if provided
    # Try YouTube thumbnail first, then fall back to alternative thumbnail URL formats
    if thumbnail_url:
        thumb_path = os.path.join(tempfile.gettempdir(), "ytb_thumb.jpg")
        thumb_urls = [thumbnail_url]
        # Add high-res thumbnail as fallback (maxresdefault > hqdefault)
        if "hqdefault" in thumbnail_url:
            thumb_urls.append(thumbnail_url.replace("hqdefault", "maxresdefault"))
        elif "maxresdefault" not in thumbnail_url:
            alt_url = thumbnail_url.rsplit("/", 1)[0] + "/maxresdefault.jpg"
            thumb_urls.append(alt_url)

        thumb_downloaded = False
        for turl in thumb_urls:
            try:
                curl_result = subprocess.run(
                    ["curl", "-s", "-o", thumb_path, "--max-time", "15", turl],
                    timeout=20
                )
                # Verify the file is a valid image (non-empty)
                if curl_result.returncode == 0 and os.path.getsize(thumb_path) > 1000:
                    # Embed as APIC using FFmpeg's image2 demuxer with id3v2
                    embed_cmd = [
                        "ffmpeg", "-y",
                        "-i", tmp_out,
                        "-attach", thumb_path,
                        "-metadata:s:i", "1", "Cover (front)",
                        tmp_out + ".cover",
                    ]
                    result2 = subprocess.run(embed_cmd, capture_output=True, text=True, timeout=60)
                    if result2.returncode == 0:
                        os.replace(tmp_out + ".cover", tmp_out)
                        log.info("Embedded metadata + thumbnail: %s - %s", safe_artist, safe_title)
                        thumb_downloaded = True
                        break
                    else:
                        log.warning("Thumbnail embed failed for %s: %s", filepath, result2.stderr[-200:])
                else:
                    log.warning("Thumbnail download returned empty for %s", turl)
            except Exception as e:
                log.warning("Thumbnail download/embed failed for %s: %s", turl, e)

        # Clean up thumbnail
        if os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass

        if not thumb_downloaded:
            # No thumbnail available - keep file with metadata only
            log.info("Embedded metadata (no thumbnail): %s - %s", safe_artist, safe_title)

    # Move final file into place
    if os.path.exists(tmp_out):
        os.replace(tmp_out, filepath)
        log.info("Embedded metadata: %s - %s", safe_artist, safe_title)

def clean_youtube_url(url: str, strip_playlist: bool = False) -> str:
    """Remove playlist/radio params from YouTube URL."""
    if not strip_playlist:
        return url
    url = re.sub(r'[?&]list=[^&]*', '', url)
    url = re.sub(r'[?&]start_radio=[^&]*', '', url)
    url = re.sub(r'\?$', '', url)
    return url


def _get_target_dir(format: str, category: str = None) -> tuple[str, float]:
    """
    Determine target directory and max size for a download.
    If category is specified and enabled in config, use that category's directory.
    Otherwise fall back to format-based defaults.
    Returns (dir_path, max_size_gb).
    """
    if category:
        cats = config.get_categories()
        cat_conf = cats.get(category)
        if cat_conf and cat_conf.get("enabled", True):
            cat_dir = cat_conf.get("dir", "")
            if cat_dir:
                # Resolve relative paths relative to config file location
                from pathlib import Path
                config_path = Path(config._get_config_path()).parent.resolve()
                if not os.path.isabs(cat_dir):
                    cat_dir = str(config_path / cat_dir)
                # Use category-specific size limit if set, else unlimited (0)
                max_size = cat_conf.get("max_size_gb", 0)
                return cat_dir, max_size

    # Default: route by format
    if format == "audio":
        return config.get_music_dir(), config.get_max_music_size_gb()
    else:
        return config.get_video_dir(), config.get_max_video_size_gb()


def download_video(task_id: str, url: str, format: str, quality: str, custom_name: str = "", strip_playlist: bool = False, category: str = None):
    """
    Execute download task
    format: "video" -> merged mp4 saved to video/
           "audio" -> mp3 saved to music/
    category: optional category name to route to a custom directory
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    with _download_semaphore:
        _ensure_dirs()

        task.update(status=TaskStatus.DOWNLOADING, progress=0, message="Initializing...")

        # Clean URL
        clean_url = clean_youtube_url(url, strip_playlist=strip_playlist)

        # Fetch and store title + metadata fields
        info = get_video_info(clean_url)
        title = info["title"]
        uploader = info["uploader"]
        thumbnail = info["thumbnail"]
        task.update(title=title)
        _emit_update(task_id)
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
        # Determine filename: custom_name takes priority, otherwise use YouTube title
        if custom_name:
            # Strip extension if user included it
            base = custom_name
            if base.lower().endswith((".mp4", ".mp3", ".webm", ".mkv")):
                base = base.rsplit(".", 1)[0]
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in base)
        else:
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)

        # Resolve target directory from category or format defaults
        target_dir, max_size_gb = _get_target_dir(format, category)

        # Build per-format output templates using target_dir
        outtmpl_video = os.path.join(target_dir, f"{safe_name}.%(ext)s")
        outtmpl_audio = os.path.join(target_dir, f"{safe_name}.%(ext)s")

        if format == "audio":
            out_path = os.path.join(target_dir, f"{safe_name}.mp3")
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
                }, {
                    "key": "EmbedThumbnail",
                }, {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }],
                "writethumbnail": True,
                "merge_output_format": "mp3",
                # Capture metadata during extraction
                "getcomments": True,
            }
            download_url = clean_url
        else:
            out_path = os.path.join(target_dir, f"{safe_name}.mp4")
            max_height = quality.replace("p", "")
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
            download_url = clean_url

        # Check / free disk space before downloading (only when disk limit is enabled)
        if config.get_disk_limit_enabled() and max_size_gb > 0:
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
                    status="failed", error=msg,
                    category=category,
                )
                _emit_update(task_id)
                return

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([download_url])

            # Get file size and duration
            size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
            duration_s = 0

            # Auto-embed MP3 metadata:
            # - title: use safe_name (custom_name if provided, else YouTube title)
            # - artist: uploader name from YouTube
            # - thumbnail: YouTube video thumbnail (embedded as album art)
            if format == "audio" and os.path.exists(out_path):
                safe_display_title = safe_name.replace("_", " ").replace("-", " ").strip()
                embed_mp3_metadata(out_path, title=safe_display_title, artist=uploader, thumbnail_url=thumbnail)

            task.update(
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Download complete",
                filename=out_path
            )
            task_manager.record_completed(task_id)
            task_manager.save_tasks()
            log.info("Task %s completed: %s -> %s (%.1f MB)", task_id, title, out_path, size_mb)
            log_download(
                url=url, title=title, filename=out_path,
                fmt=format, quality=quality,
                size_mb=size_mb, duration_s=duration_s,
                status="success",
                category=category,
            )
        except Exception as e:
            log.error("Task %s failed: %s", task_id, e)
            log_download(
                url=url, title=title, filename="",
                fmt=format, quality=quality,
                size_mb=0, duration_s=0,
                status="failed", error=str(e),
                category=category,
            )
            task.update(
                status=TaskStatus.ERROR,
                progress=0,
                message="Download failed",
                error=str(e)
            )
            task_manager.save_tasks()
        _emit_update(task_id)
