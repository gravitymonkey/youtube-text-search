from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from urllib import error, request

from app.cache import CacheRepository
from app.chunking import build_rolling_chunks
from app.models import SearchHit


class OpenAIClient:
    def __init__(self, api_key: str, embedding_model: str, chat_model: str):
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        req = request.Request(
            f"https://api.openai.com{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise RuntimeError(f"OpenAI request failed: {exc.code} {detail}") from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.embedding_model, "input": texts}
        response = self._request("/v1/embeddings", payload)
        return [item["embedding"] for item in response["data"]]

    def answer(self, prompt: str) -> str:
        payload = {
            "model": self.chat_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided transcript evidence. "
                        "Cite timestamps inline. If the evidence is insufficient, say so."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        response = self._request("/v1/chat/completions", payload)
        return response["choices"][0]["message"]["content"]


class SQLiteEmbeddingStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            columns = conn.execute("PRAGMA table_info(embeddings)").fetchall()
            if columns and "chunk_id" not in {column[1] for column in columns}:
                conn.execute("DROP TABLE embeddings")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    anchor_segment_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    anchor_start_seconds INTEGER NOT NULL,
                    anchor_start_timestamp TEXT NOT NULL,
                    window_start_seconds INTEGER NOT NULL,
                    window_end_seconds INTEGER NOT NULL,
                    window_start_timestamp TEXT NOT NULL,
                    window_end_timestamp TEXT NOT NULL,
                    text TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    segment_ids_json TEXT NOT NULL,
                    playlist_ids_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def upsert_chunk(self, chunk, vector: list[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO embeddings (
                    chunk_id, anchor_segment_id, video_id, video_url, title, channel,
                    anchor_start_seconds, anchor_start_timestamp, window_start_seconds,
                    window_end_seconds, window_start_timestamp, window_end_timestamp,
                    text, snippet, segment_ids_json, playlist_ids_json, vector_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    anchor_segment_id=excluded.anchor_segment_id,
                    video_id=excluded.video_id,
                    video_url=excluded.video_url,
                    title=excluded.title,
                    channel=excluded.channel,
                    anchor_start_seconds=excluded.anchor_start_seconds,
                    anchor_start_timestamp=excluded.anchor_start_timestamp,
                    window_start_seconds=excluded.window_start_seconds,
                    window_end_seconds=excluded.window_end_seconds,
                    window_start_timestamp=excluded.window_start_timestamp,
                    window_end_timestamp=excluded.window_end_timestamp,
                    text=excluded.text,
                    snippet=excluded.snippet,
                    segment_ids_json=excluded.segment_ids_json,
                    playlist_ids_json=excluded.playlist_ids_json,
                    vector_json=excluded.vector_json
                """,
                (
                    chunk.chunk_id,
                    chunk.anchor_segment_id,
                    chunk.video_id,
                    chunk.video_url,
                    chunk.title,
                    chunk.channel,
                    chunk.anchor_start_seconds,
                    chunk.anchor_start_timestamp,
                    chunk.window_start_seconds,
                    chunk.window_end_seconds,
                    chunk.window_start_timestamp,
                    chunk.window_end_timestamp,
                    chunk.text,
                    chunk.snippet,
                    json.dumps(chunk.segment_ids),
                    json.dumps(chunk.playlist_ids),
                    json.dumps(vector),
                ),
            )
            conn.commit()

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 10,
        video_id: str | None = None,
        video_url: str | None = None,
    ) -> list[SearchHit]:
        sql = (
            "SELECT chunk_id, anchor_segment_id, video_id, video_url, title, channel, "
            "anchor_start_seconds, anchor_start_timestamp, window_start_seconds, "
            "window_end_seconds, window_start_timestamp, window_end_timestamp, text, "
            "snippet, segment_ids_json, playlist_ids_json, vector_json FROM embeddings"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if video_id:
            clauses.append("video_id = ?")
            params.append(video_id)
        if video_url:
            clauses.append("video_url = ?")
            params.append(video_url)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        ranked: list[SearchHit] = []
        for row in rows:
            vector = json.loads(row[16])
            score = cosine_similarity(query_vector, vector)
            ranked.append(
                SearchHit(
                    chunk_id=row[0],
                    anchor_segment_id=row[1],
                    video_id=row[2],
                    video_url=row[3],
                    title=row[4],
                    channel=row[5],
                    anchor_start_seconds=row[6],
                    anchor_start_timestamp=row[7],
                    window_start_seconds=row[8],
                    window_end_seconds=row[9],
                    window_start_timestamp=row[10],
                    window_end_timestamp=row[11],
                    text=row[12],
                    snippet=row[13],
                    segment_ids=json.loads(row[14]),
                    playlist_ids=json.loads(row[15]),
                    score=score,
                    source="semantic",
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(l * r for l, r in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class VectorIndexer:
    def __init__(
        self,
        cache: CacheRepository,
        openai_client: OpenAIClient,
        embedding_store: SQLiteEmbeddingStore,
        *,
        window_before: int,
        window_after: int,
    ):
        self.cache = cache
        self.openai_client = openai_client
        self.embedding_store = embedding_store
        self.window_before = window_before
        self.window_after = window_after

    def index(self, batch_size: int = 64) -> int:
        chunks = []
        for video_id in self.cache.iter_video_ids():
            segments = self.cache.read_video_segments(video_id)
            chunks.extend(
                build_rolling_chunks(
                    segments,
                    before=self.window_before,
                    after=self.window_after,
                )
            )
        total = 0
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            vectors = self.openai_client.embed_texts([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                self.embedding_store.upsert_chunk(chunk, vector)
                total += 1
        return total
