from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

from app.models import ExtractionResult, ManifestEntry, TranscriptSegment, VideoMetadata


class CacheRepository:
    """Flat-file cache for extracted transcripts and derived indexes.

    This is the single persistence layer for extracted video artifacts.
    Both the batch ingest flow and any one-off extraction workflow should
    write transcript artifacts through this class so the on-disk layout stays
    stable and easy to maintain.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.videos_dir = self.root / "videos"
        self.playlists_dir = self.root / "playlists"
        self.manifest_path = self.root / "manifest.json"
        self.url_index_path = self.root / "url_index.json"
        self.embeddings_db_path = self.root / "embeddings.sqlite3"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(content)
            temp_path = Path(tmp.name)
        temp_path.replace(path)

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        self._atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))

    def compute_content_hash(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def video_dir(self, video_id: str) -> Path:
        return self.videos_dir / video_id

    def persist_transcript_artifact(self, result: ExtractionResult) -> Path:
        """Persist one extracted video artifact using the canonical cache layout."""
        video_dir = self.video_dir(result.metadata.video_id)
        self._atomic_write_json(video_dir / "meta.json", result.metadata.to_dict())
        lines = "\n".join(json.dumps(segment.to_dict()) for segment in result.segments)
        if lines:
            lines += "\n"
        self._atomic_write_text(video_dir / "transcript.jsonl", lines)
        return video_dir

    def write_video(self, metadata: VideoMetadata, segments: list[TranscriptSegment]) -> None:
        # Backward-compatible wrapper retained while callers migrate to the
        # artifact-centric API.
        self.persist_transcript_artifact(
            ExtractionResult(metadata=metadata, segments=segments)
        )

    def read_video_meta(self, video_id: str) -> dict[str, Any]:
        return json.loads((self.video_dir(video_id) / "meta.json").read_text("utf-8"))

    def read_video_segments(self, video_id: str) -> list[TranscriptSegment]:
        transcript_path = self.video_dir(video_id) / "transcript.jsonl"
        segments: list[TranscriptSegment] = []
        if not transcript_path.exists():
            return segments
        for line in transcript_path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            segments.append(TranscriptSegment(**json.loads(line)))
        return segments

    def read_transcript_artifact(self, video_id: str) -> ExtractionResult:
        """Read one extracted video artifact back into application models."""
        metadata = VideoMetadata(**self.read_video_meta(video_id))
        segments = self.read_video_segments(video_id)
        return ExtractionResult(metadata=metadata, segments=segments)

    def write_playlist(self, playlist_id: str, video_urls: list[str]) -> None:
        self._atomic_write_json(
            self.playlists_dir / f"{playlist_id}.json",
            {"playlist_id": playlist_id, "video_urls": video_urls},
        )

    def load_manifest(self) -> dict[str, dict[str, Any]]:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text("utf-8"))

    def save_manifest(self, manifest: dict[str, dict[str, Any]]) -> None:
        self._atomic_write_json(self.manifest_path, manifest)

    def upsert_manifest_entry(self, entry: ManifestEntry) -> None:
        manifest = self.load_manifest()
        manifest[entry.video_id] = entry.to_dict()
        self.save_manifest(manifest)

    def get_manifest_entry(self, video_id: str) -> dict[str, Any] | None:
        return self.load_manifest().get(video_id)

    def load_url_index(self) -> dict[str, Any]:
        if not self.url_index_path.exists():
            return {}
        return json.loads(self.url_index_path.read_text("utf-8"))

    def save_url_index(self, index: dict[str, Any]) -> None:
        self._atomic_write_json(self.url_index_path, index)

    def update_url_index(self, url: str, payload: dict[str, Any]) -> None:
        index = self.load_url_index()
        index[url] = payload
        self.save_url_index(index)

    def iter_segments(self) -> Iterable[TranscriptSegment]:
        for video_dir in sorted(self.videos_dir.iterdir()):
            transcript_path = video_dir / "transcript.jsonl"
            if not transcript_path.exists():
                continue
            for line in transcript_path.read_text("utf-8").splitlines():
                if line.strip():
                    yield TranscriptSegment(**json.loads(line))

    def iter_video_ids(self) -> Iterable[str]:
        for video_dir in sorted(self.videos_dir.iterdir()):
            if video_dir.is_dir():
                yield video_dir.name
