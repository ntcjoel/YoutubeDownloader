"""
Configuration loader - reads config.yaml and supports env var overrides.
Environment variables take precedence over config.yaml values.
"""
import os
import yaml
import logging
import sys
from pathlib import Path

# Basic logging setup (avoid circular import with app_logging)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [config] %(message)s'))
_logger = logging.getLogger("config")
_logger.addHandler(_handler)
log = _logger

_CONFIG = None

def _get_config_path() -> str:
    """Find config.yaml relative to this file or project root"""
    base = Path(__file__).parent.resolve()
    p = base / "config.yaml"
    if p.exists():
        return str(p)
    return "config.yaml"


def load_config() -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    path = _get_config_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
    else:
        raw = {}

    _CONFIG = _get_defaults()
    if raw:
        _CONFIG.update(raw)

    # Migrate legacy cookie_file -> cookie_site + cookie_custom_path
    if "cookie_file" in raw and "cookie_site" not in raw:
        old_path = raw["cookie_file"]
        if old_path:
            _CONFIG["cookie_site"] = "custom"
            _CONFIG["cookie_custom_path"] = old_path
        # Remove legacy key so it doesn't persist
        _CONFIG.pop("cookie_file", None)

    # Env var overrides — only apply when explicitly set in environment
    env_overrides = {
        "host":          os.environ.get("HOST"),
        "port":          _env_int("PORT"),
        "video_dir":     os.environ.get("VIDEO_DIR"),
        "music_dir":     os.environ.get("MUSIC_DIR"),
        "log_dir":       os.environ.get("LOG_DIR"),
        "disk_limit_enabled": _env_bool("DISK_LIMIT_ENABLED"),
        "max_video_size_gb": _env_float("MAX_VIDEO_SIZE_GB"),
        "max_music_size_gb": _env_float("MAX_MUSIC_SIZE_GB"),
        "cleanup_policy": os.environ.get("CLEANUP_POLICY"),
        "default_quality": os.environ.get("DEFAULT_QUALITY"),
        "default_format":  os.environ.get("DEFAULT_FORMAT"),
        "retention_days":  _env_int("RETENTION_DAYS"),
    }
    for key, val in env_overrides.items():
        if val is not None and val != "":
            if isinstance(val, bool):
                _CONFIG[key] = val
            elif val.lower() in ("true", "false"):
                _CONFIG[key] = val.lower() == "true"
            else:
                _CONFIG[key] = val

    # Resolve relative paths relative to config file location
    config_dir = Path(path).parent.resolve()
    for key in ("video_dir", "music_dir", "log_dir"):
        val = _CONFIG.get(key, "")
        if val and not os.path.isabs(val):
            _CONFIG[key] = str(config_dir / val)

    return _CONFIG


def _get_defaults() -> dict:
    base = Path(__file__).parent.resolve()
    return {
        "host": "0.0.0.0",
        "port": 1917,
        "video_dir": str(base / "video"),
        "music_dir": str(base / "music"),
        "log_dir":   str(base / "logs"),
        "disk_limit_enabled": False,
        "max_video_size_gb": 50,
        "max_music_size_gb": 10,
        "cleanup_policy": "oldest_first",
        "default_quality": "1080p",
        "default_format": "video",
        "retention_days": 30,
        "strip_playlist": False,
    }


def _env_int(key: str) -> int | None:
    val = os.environ.get(key)
    return int(val) if val is not None and val.isdigit() else None


def _env_float(key: str) -> float | None:
    val = os.environ.get(key)
    try:
        return float(val) if val else None
    except ValueError:
        return None


def _env_bool(key: str) -> bool | None:
    val = os.environ.get(key)
    if val is None:
        return None
    return val.lower() in ("true", "1", "yes")


def get(key: str, default=None):
    return load_config().get(key, default)


def get_video_dir() -> str:
    return get("video_dir")

def get_music_dir() -> str:
    return get("music_dir")

def get_log_dir() -> str:
    return get("log_dir")

def get_max_video_size_gb() -> float:
    return float(get("max_video_size_gb", 50))

def get_max_music_size_gb() -> float:
    return float(get("max_music_size_gb", 10))

def get_cleanup_policy() -> str:
    return get("cleanup_policy", "oldest_first")

def get_disk_limit_enabled() -> bool:
    return bool(get("disk_limit_enabled", False))

def get_cookie_site() -> str:
    """Which site to use cookies for: '', 'youtube', 'bilibili', 'tiktok', 'custom'."""
    return get("cookie_site", "")

def get_cookie_custom_path() -> str:
    """Custom cookie file path when site='custom'."""
    return get("cookie_custom_path", "")

# Map site key -> expected cookie file path inside the container
_SITE_COOKIE_PATHS = {
    "youtube":   "/app/cookies/youtube.txt",
    "bilibili":  "/app/cookies/bilibili.txt",
    "tiktok":    "/app/cookies/tiktok.txt",
}

def get_cookie_file() -> str:
    """
    Resolve the actual cookie file path based on the selected site.
    Returns empty string if no site is selected or file does not exist.
    """
    site = get_cookie_site()
    if not site or site == "none":
        return ""
    if site == "custom":
        path = get_cookie_custom_path()
        return path if path else ""
    return _SITE_COOKIE_PATHS.get(site, "")



def save_config(values: dict) -> None:
    """
    Write values dict to config.yaml (partial update).
    Clears the _CONFIG cache so next load_config() picks up changes.
    """
    global _CONFIG
    path = _get_config_path()

    # Load existing yaml as-is (preserve comments, structure)
    existing = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            existing = yaml.safe_load(f) or {}

    # Merge new values (only keys user is changing)
    existing.update(values)

    # Write back atomically
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp, path)

    # Invalidate cache so next call reloads
    _CONFIG = None


# ---- Category config helpers ----

def get_categories() -> dict:
    """Return category dict from config, e.g. {'music': {'dir': '/path', 'enabled': True}, ...}"""
    return get("categories", {})


def save_categories(categories: dict) -> None:
    """Save full categories dict to config.yaml."""
    save_config({"categories": categories})

def _get_cookie_file_for_site(site: str, custom_path: str = "") -> str:
    """Resolve cookie file path given a site key (used during save)."""
    if not site or site == "none":
        return ""
    if site == "custom":
        return custom_path if custom_path else ""
    return _SITE_COOKIE_PATHS.get(site, "")


def save_cookie_file(site: str, content: str) -> bool:
    """
    Write cookie content to the appropriate cookie file.
    Returns True on success, False on failure.
    """
    if not site or site == "none":
        return False
    path = _get_cookie_file_for_site(site, get_cookie_custom_path())
    if not path:
        return False
    try:
        # Ensure parent dir exists
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info("Saved cookie file: %s", path)
        return True
    except Exception as e:
        log.error("Failed to save cookie file %s: %s", path, e)
        return False
