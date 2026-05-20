"""
Download record logging: append-only JSON Lines file.
Each completed/failed download gets one line appended.
"""
import os
import json
import config


def get_log_path() -> str:
    log_dir = config.get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "downloads.log")


def log_download(
    url: str,
    title: str,
    filename: str,
    fmt: str,
    quality: str,
    size_mb: float,
    duration_s: int,
    status: str,
    error: str = None,
) -> None:
    """
    Append one JSON record to downloads.log.
    status: "success" or "failed"
    """
    record = {
        "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "title": title,
        "filename": filename,
        "format": fmt,
        "quality": quality,
        "size_mb": round(size_mb, 2),
        "duration_s": duration_s,
        "status": status,
    }
    if error:
        record["error"] = error

    path = get_log_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_downloads(limit: int = 100, offset: int = 0) -> list:
    """
    Read the last `limit` records from downloads.log.
    Returns list of dicts, newest last.
    """
    path = get_log_path()
    if not os.path.exists(path):
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Return paginated slice from newest, reversed so newest comes first
    records_rev = list(reversed(records))
    start = offset
    end = offset + limit
    return records_rev[start:end]


def count_downloads() -> int:
    """Total number of download records."""
    path = get_log_path()
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())
