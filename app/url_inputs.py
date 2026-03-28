from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.models import InputTarget

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


class URLInputError(ValueError):
    pass


def parse_input_file(path: str | Path) -> list[InputTarget]:
    targets: list[InputTarget] = []
    seen: set[str] = set()
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        target = parse_target(line)
        if target.normalized_url in seen:
            continue
        targets.append(target)
        seen.add(target.normalized_url)
    return targets


def parse_target(url: str) -> InputTarget:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise URLInputError(f"Unsupported URL scheme: {url}")
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        raise URLInputError(f"Unsupported host: {url}")
    normalized_url, kind = normalize_youtube_url(url)
    return InputTarget(raw_url=url, normalized_url=normalized_url, kind=kind)


def normalize_youtube_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    query = parse_qs(parsed.query)
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
        if not video_id:
            raise URLInputError(f"Missing video id: {url}")
        return canonical_video_url(video_id), "video"
    if parsed.path.startswith("/watch") and query.get("v"):
        return canonical_video_url(query["v"][0]), "video"
    if parsed.path.startswith("/shorts/"):
        video_id = parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
        return canonical_video_url(video_id), "video"
    if parsed.path.startswith("/playlist") and query.get("list"):
        return canonical_playlist_url(query["list"][0]), "playlist"
    if query.get("list") and not query.get("v"):
        return canonical_playlist_url(query["list"][0]), "playlist"
    raise URLInputError(f"Could not classify URL: {url}")


def canonical_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def canonical_playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def video_id_from_url(url: str) -> str:
    match = re.search(r"[?&]v=([^&]+)", url)
    if not match:
        raise URLInputError(f"Missing video id in {url}")
    return match.group(1)


def playlist_id_from_url(url: str) -> str:
    match = re.search(r"[?&]list=([^&]+)", url)
    if not match:
        raise URLInputError(f"Missing playlist id in {url}")
    return match.group(1)
