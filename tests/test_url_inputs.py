from pathlib import Path

import pytest

from app.url_inputs import (
    URLInputError,
    parse_input_file,
    parse_target,
)


def test_parse_input_file_ignores_comments_blanks_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "urls.txt"
    path.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "https://youtu.be/abc123",
                "https://www.youtube.com/watch?v=abc123",
                "https://www.youtube.com/playlist?list=PL123",
            ]
        ),
        encoding="utf-8",
    )
    targets = parse_input_file(path)
    assert [target.normalized_url for target in targets] == [
        "https://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/playlist?list=PL123",
    ]


def test_parse_target_rejects_non_youtube_urls() -> None:
    with pytest.raises(URLInputError):
        parse_target("https://example.com/video")
