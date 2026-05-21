"""
Download record logging: append-only JSON Lines file.
Each completed/failed download gets one line appended.
"""
import os
import json
import config
from app_logging import get_logger

log = get_logger("downloads")


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
    category: str = None,
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
    if category:
        record["category"] = category

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


def update_download_record(ts: str, updates: dict) -> bool:
    """
    Update a single download record by its timestamp key.
    Rewrites the log file. Returns True if the record was found and updated.
    """
    path = get_log_path()
    if not os.path.exists(path):
        return False

    records = []
    found = False
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ts") == ts:
                rec.update(updates)
                found = True
            records.append(rec)

    if not found:
        return False

    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def delete_download_records(ts_list: list[str], delete_file: bool = False) -> int:
    """
    Delete records by their timestamp keys.
    If delete_file=True and the record has a filename pointing to an existing file, delete it too.
    Returns the number of records deleted.
    """
    if not ts_list:
        return 0
    ts_set = set(ts_list)
    path = get_log_path()
    if not os.path.exists(path):
        return 0

    records = []
    deleted = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ts") in ts_set:
                deleted += 1
                if delete_file and rec.get("filename"):
                    fpath = rec["filename"]
                    if os.path.isfile(fpath):
                        try:
                            os.remove(fpath)
                            log.info("Deleted file: %s", fpath)
                        except OSError as e:
                            log.warning("Failed to delete file %s: %s", fpath, e)
                continue
            records.append(rec)

    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return deleted
