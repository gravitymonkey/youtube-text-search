from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.cache import CacheRepository
from app.config import load_settings
from app.extractors.playwright_extractor import PlaywrightYouTubeExtractor
from app.indexing.embeddings import OpenAIClient, SQLiteEmbeddingStore, VectorIndexer
from app.indexing.keyword import KeywordIndexer, MeilisearchClient
from app.ingest import IngestService
from app.llm import AnswerSynthesizer
from app.search.hybrid import SearchEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt-search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest videos and playlists from a URL file")
    ingest.add_argument("url_file")
    ingest.add_argument("--force", action="store_true")

    keyword = subparsers.add_parser("index-keywords", help="Index transcript rows into Meilisearch")
    keyword.add_argument("--json", action="store_true", help="Print JSON summary")

    embeddings = subparsers.add_parser("index-embeddings", help="Generate embeddings into SQLite store")
    embeddings.add_argument("--json", action="store_true", help="Print JSON summary")

    extract = subparsers.add_parser("extract", help="Debug extraction for a single video or playlist URL")
    extract.add_argument("url")
    extract.add_argument("--json", action="store_true")

    search = subparsers.add_parser("search", help="Search transcript rows")
    search.add_argument("query")
    search.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--video-id")
    search.add_argument("--video-url")
    search.add_argument("--json", action="store_true")

    answer = subparsers.add_parser("answer", help="Answer a question using transcript evidence")
    answer.add_argument("question")
    answer.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    answer.add_argument("--top-k", type=int, default=6)
    answer.add_argument("--video-id")
    answer.add_argument("--video-url")
    answer.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings, cache, keyword_client, openai_client, embedding_store = _build_runtime()

    if args.command == "ingest":
        extractor = _build_extractor(settings)
        service = IngestService(
            cache,
            extractor,
            playlist_max_videos=settings.playlist_max_videos,
        )
        summary = service.ingest_file(args.url_file, force=args.force)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.command == "extract":
        extractor = _build_extractor(settings)
        payload = extractor.extract_url_summary(args.url)
        _print_payload(payload, as_json=True)
        return

    if args.command == "index-keywords":
        indexer = KeywordIndexer(
            cache,
            keyword_client,
            window_before=settings.meili_window_before,
            window_after=settings.meili_window_after,
        )
        count = indexer.index()
        _print_payload({"indexed_segments": count}, as_json=args.json)
        return

    if args.command == "index-embeddings":
        indexer = VectorIndexer(
            cache,
            openai_client,
            embedding_store,
            window_before=settings.embed_window_before,
            window_after=settings.embed_window_after,
        )
        count = indexer.index()
        _print_payload({"indexed_segments": count}, as_json=args.json)
        return

    search_engine = SearchEngine(
        cache,
        keyword_client,
        embedding_store,
        openai_client,
        retrieval_window=settings.retrieval_window,
    )

    if args.command == "search":
        hits = search_engine.search(
            args.query,
            mode=args.mode,
            limit=args.top_k,
            video_id=args.video_id,
            video_url=args.video_url,
        )
        if args.json:
            _print_payload([_hit_to_dict(hit) for hit in hits], as_json=True)
        else:
            _print_hits(hits)
        return

    if args.command == "answer":
        hits = search_engine.search(
            args.question,
            mode=args.mode,
            limit=args.top_k,
            video_id=args.video_id,
            video_url=args.video_url,
        )
        synthesizer = AnswerSynthesizer(openai_client)
        result = synthesizer.answer(args.question, hits)
        if args.json:
            _print_payload(asdict(result), as_json=True)
        else:
            print(result.answer)
            for citation in result.citations:
                print(
                    f"- {citation['title']} [{citation['timestamp']}] {citation['video_url']}"
                )
            if result.warning:
                print(f"warning: {result.warning}")
        return


def _print_payload(payload, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload)


def _hit_to_dict(hit) -> dict:
    data = {
        "chunk_id": hit.chunk_id,
        "anchor_segment_id": hit.anchor_segment_id,
        "video_id": hit.video_id,
        "video_url": hit.video_url,
        "title": hit.title,
        "channel": hit.channel,
        "anchor_start_seconds": hit.anchor_start_seconds,
        "anchor_start_timestamp": hit.anchor_start_timestamp,
        "window_start_seconds": hit.window_start_seconds,
        "window_end_seconds": hit.window_end_seconds,
        "window_start_timestamp": hit.window_start_timestamp,
        "window_end_timestamp": hit.window_end_timestamp,
        "text": hit.text,
        "snippet": hit.snippet,
        "segment_ids": hit.segment_ids,
        "playlist_ids": hit.playlist_ids,
        "score": hit.score,
        "source": hit.source,
    }
    if hit.window_segments is not None:
        data["window_segments"] = [segment.to_dict() for segment in hit.window_segments]
    return data


def _print_hits(hits) -> None:
    for hit in hits:
        print(
            f"[{hit.score:.3f}] {hit.title} "
            f"{hit.window_start_timestamp}-{hit.window_end_timestamp} "
            f"{hit.video_url}&t={hit.anchor_start_seconds}s"
        )
        print(hit.snippet)
        if hit.window_segments:
            joined_window = " | ".join(segment.text for segment in hit.window_segments)
            print(f"context: {joined_window}")
        print("")

def _build_runtime():
    settings = load_settings()
    cache = CacheRepository(settings.cache_dir)
    keyword_client = MeilisearchClient(
        settings.meili_host, settings.meili_api_key, settings.meili_index
    )
    openai_client = OpenAIClient(
        settings.openai_api_key,
        settings.openai_embedding_model,
        settings.openai_chat_model,
    )
    embedding_store = SQLiteEmbeddingStore(cache.embeddings_db_path)
    return settings, cache, keyword_client, openai_client, embedding_store


def _build_extractor(settings) -> PlaywrightYouTubeExtractor:
    return PlaywrightYouTubeExtractor(
        headless=settings.playwright_headless,
        timeout_ms=settings.playwright_timeout_ms,
        debug_dir=settings.cache_dir / "debug",
    )


if __name__ == "__main__":
    main()
