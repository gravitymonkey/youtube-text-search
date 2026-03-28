from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


@dataclass(slots=True)
class Settings:
    cache_dir: Path
    meili_host: str
    meili_api_key: str
    meili_index: str
    openai_api_key: str
    openai_embedding_model: str
    openai_chat_model: str
    playwright_headless: bool
    playwright_timeout_ms: int
    playlist_max_videos: int
    retrieval_window: int
    meili_window_before: int
    meili_window_after: int
    embed_window_before: int
    embed_window_after: int


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        cache_dir=Path(os.getenv("YT_CACHE_DIR", "./cache")).resolve(),
        meili_host=os.getenv("MEILI_HOST", "http://127.0.0.1:7700").rstrip("/"),
        meili_api_key=os.getenv("MEILI_API_KEY", ""),
        meili_index=os.getenv("MEILI_INDEX", "transcript_segments"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        playwright_headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
        playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000")),
        playlist_max_videos=int(os.getenv("PLAYLIST_MAX_VIDEOS", "10")),
        retrieval_window=int(os.getenv("RETRIEVAL_WINDOW", "1")),
        meili_window_before=int(os.getenv("MEILI_WINDOW_BEFORE", "5")),
        meili_window_after=int(os.getenv("MEILI_WINDOW_AFTER", "5")),
        embed_window_before=int(os.getenv("EMBED_WINDOW_BEFORE", "5")),
        embed_window_after=int(os.getenv("EMBED_WINDOW_AFTER", "5")),
    )
