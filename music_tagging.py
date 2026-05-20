"""
Music metadata tagging module.
Handles writing ID3 tags to MP3 files via FFmpeg and auto-filling metadata via MusicBrainz.
"""
import subprocess
import urllib.request
import urllib.parse
import re
import os
import json
from typing import Optional

from app_logging import get_logger
log = get_logger("tagging")

# MusicBrainz API base (rate-limited: 1 request/sec)
MB_API = "https://musicbrainz.org/ws/2"
MB_UA = "YouTubeDownloader/1.0 (music-tagging@example.com)"  # identify yourself!


def _mb_req(url: str) -> Optional[dict]:
    """Make a MusicBrainz API request. Returns None on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": MB_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("MusicBrainz request failed: %s", e)
        return None


def search_musicbrainz(artist: str, title: str) -> Optional[dict]:
    """
    Query MusicBrainz for a recording matching artist + title.
    Returns a dict with artist, title, album, year, genre, cover_url, or None.
    """
    # Escape special Lucene characters
    def lucene_escape(s):
        return re.sub(r'([+\-=&|><!(){}\[\]^"~*?:\\/])', r'\\\1', s)

    q = urllib.parse.quote(f'artist:{lucene_escape(artist)} AND recording:{lucene_escape(title)}')
    url = f"{MB_API}/recording/?query={q}&fmt=json&limit=5"

    data = _mb_req(url)
    if not data or not data.get("recordings"):
        return None

    # Try each recording until one has useful info
    for rec in data["recordings"]:
        # Get artist credit from recording
        artist_name = None
        if rec.get("artist-credit"):
            artist_name = rec["artist-credit"][0].get("name") or rec["artist-credit"][0].get("id", "")

        # Get release info
        releases = rec.get("releases", [])
        album = None
        year = None
        cover_url = None
        genre = None

        if releases:
            # Prefer the first release with a date
            for rel in releases:
                album = rel.get("title")
                date = rel.get("date", "")
                if date:
                    year_match = re.match(r"(\d{4})", date)
                    if year_match:
                        year = year_match.group(1)
                        break
                # Try to get cover art
                if not cover_url and rel.get("id"):
                    cover_url = f"https://coverartarchive.org/release/{rel['id']}/front"

        # Get genre/tags from recording
        tags = rec.get("tags", [])
        if tags:
            genre = tags[0].get("name")

        if artist_name and rec.get("title"):
            return {
                "artist": artist_name,
                "title": rec.get("title"),
                "album": album,
                "year": year,
                "genre": genre,
                "cover_url": cover_url,
            }

    return None


def parse_artist_title_from_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """
    Try to split 'Artist - Title' or 'Title - Artist' from a filename.
    Returns (artist, title). Either may be None if parsing fails.
    """
    # Remove extension
    name = os.path.splitext(os.path.basename(filename))[0]
    # Try common separators
    for sep in [" - ", " – ", " — ", " - "]:
        if sep in name:
            parts = name.split(sep, 1)
            if len(parts) == 2:
                artist, title = parts[0].strip(), parts[1].strip()
                if artist and title:
                    return artist, title
    return None, None


def write_metadata(
    filepath: str,
    artist: str = None,
    title: str = None,
    album: str = None,
    year: str = None,
    genre: str = None,
    cover_url: str = None,
) -> bool:
    """
    Write ID3 metadata to an MP3 file using FFmpeg.
    Downloads cover art if cover_url is provided.
    Returns True on success, False on failure.
    """
    if not os.path.exists(filepath):
        log.error("File not found: %s", filepath)
        return False

    # Build FFmpeg metadata args
    meta_args = []
    if artist:
        meta_args += ["-metadata", f"artist={artist}"]
    if title:
        meta_args += ["-metadata", f"title={title}"]
    if album:
        meta_args += ["-metadata", f"album={album}"]
    if year:
        meta_args += ["-metadata", f"year={year}"]
    if genre:
        meta_args += ["-metadata", f"genre={genre}"]

    # Handle cover art
    cover_path = None
    if cover_url:
        cover_path = filepath + ".cover.jpg"
        try:
            req = urllib.request.Request(cover_url, headers={"User-Agent": MB_UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(cover_path, "wb") as f:
                    f.write(resp.read())
            log.info("Downloaded cover to %s", cover_path)
        except Exception as e:
            log.warning("Failed to download cover art: %s", e)
            cover_path = None

    if cover_path and os.path.exists(cover_path):
        # Attach cover as album art (MP3)
        # FFmpeg: -i cover.jpg -codec copy -metadata:s:v title="Album cover" -disposition: attached_pic
        meta_args += [
            "-i", cover_path,
            "-codec", "copy",
            "-metadata:s:v", "title=Album cover",
            "-disposition:attached_pic", "0",
        ]

    if not meta_args:
        log.warning("No metadata to write for %s", filepath)
        return False

    # Output to a temp file then replace
    tmp_path = filepath + ".tmp"
    cmd = [
        "ffmpeg", "-y",
        "-i", filepath,
    ] + meta_args + [
        "-codec", "copy",
        tmp_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            log.error("FFmpeg failed for %s: %s", filepath, stderr[:500])
            return False

        os.replace(tmp_path, filepath)
        log.info("Wrote metadata to %s: artist=%s, title=%s", filepath, artist, title)
        return True
    except Exception as e:
        log.error("write_metadata exception for %s: %s", filepath, e)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False
    finally:
        # Clean up temp cover
        if cover_path and os.path.exists(cover_path):
            os.remove(cover_path)


def tag_file(filepath: str, metadata: dict) -> bool:
    """
    Convenience function: write a metadata dict to a music file.
    metadata keys: artist, title, album, year, genre, cover_url
    """
    return write_metadata(
        filepath,
        artist=metadata.get("artist"),
        title=metadata.get("title"),
        album=metadata.get("album"),
        year=metadata.get("year"),
        genre=metadata.get("genre"),
        cover_url=metadata.get("cover_url"),
    )


def auto_fill_metadata(filepath: str) -> Optional[dict]:
    """
    Attempt to auto-fill metadata for a music file by:
    1. Parsing artist/title from the filename
    2. Querying MusicBrainz
    Returns the found metadata dict or None.
    """
    artist, title = parse_artist_title_from_filename(filepath)
    if not artist or not title:
        log.info("Could not parse artist/title from filename: %s", filepath)
        return None

    log.info("Auto-fill: querying MusicBrainz for '%s' by '%s'", title, artist)
    result = search_musicbrainz(artist, title)
    if result:
        log.info("Auto-fill found: %s - %s (album=%s)", result.get("artist"), result.get("title"), result.get("album"))
    else:
        log.info("Auto-fill: no MusicBrainz match for '%s' by '%s'", title, artist)
    return result
