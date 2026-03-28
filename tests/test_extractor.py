import pytest

from app.extractors.base import TranscriptExtractionError
from app.extractors.playwright_extractor import PlaywrightYouTubeExtractor


def test_timestamp_to_seconds_supports_minute_and_hour_formats() -> None:
    extractor = PlaywrightYouTubeExtractor()
    assert extractor._timestamp_to_seconds("1:05") == 65
    assert extractor._timestamp_to_seconds("1:02:03") == 3723


def test_timestamp_to_seconds_rejects_invalid_format() -> None:
    extractor = PlaywrightYouTubeExtractor()
    with pytest.raises(TranscriptExtractionError):
        extractor._timestamp_to_seconds("abc")


def test_normalize_transcript_rows_drops_invalid_and_blank_rows() -> None:
    extractor = PlaywrightYouTubeExtractor()
    rows = extractor._normalize_transcript_rows(
        [
            {"timestamp": " 0:05 ", "text": " hello   world "},
            {"timestamp": "", "text": "missing"},
            {"timestamp": "bad", "text": "broken"},
            {"timestamp": "0:06", "text": "   "},
        ]
    )
    assert rows == [{"timestamp": "0:05", "text": "hello world"}]


def test_normalize_transcript_rows_accepts_modern_transcript_shape() -> None:
    extractor = PlaywrightYouTubeExtractor()
    rows = extractor._normalize_transcript_rows(
        [
            {
                "timestamp": "0:00",
                "text": "Welcome all. Hello. Good evening.",
            }
        ]
    )
    assert rows == [
        {"timestamp": "0:00", "text": "Welcome all. Hello. Good evening."}
    ]
