# Response Reference

This file shows the JSON shape you can expect from the main CLI commands.

## `search --json`

Example:

```json
[
  {
    "chunk_id": "YZ1GoP8Yy8o_0_0_w5_5",
    "anchor_segment_id": "YZ1GoP8Yy8o:0:0",
    "video_id": "YZ1GoP8Yy8o",
    "video_url": "https://www.youtube.com/watch?v=YZ1GoP8Yy8o",
    "title": "Yemen's Iran-backed Houthis launch missile at Israel for first time since war began | BBC News",
    "channel": "BBC News",
    "anchor_start_seconds": 0,
    "anchor_start_timestamp": "0:00",
    "window_start_seconds": 0,
    "window_end_seconds": 43,
    "window_start_timestamp": "0:00",
    "window_end_timestamp": "0:43",
    "text": "The Houthi movement in Yemen has attacked Israel for the first time since the start of the war on Iran...",
    "snippet": "The Houthi movement in Yemen has attacked Israel for the first time since the start of the war on Iran...",
    "segment_ids": [
      "YZ1GoP8Yy8o:0:0",
      "YZ1GoP8Yy8o:8:1",
      "YZ1GoP8Yy8o:16:2",
      "YZ1GoP8Yy8o:24:3",
      "YZ1GoP8Yy8o:35:4",
      "YZ1GoP8Yy8o:43:5"
    ],
    "playlist_ids": [
      "PLS3XGZxi7cBXc5taq0DkNtqMT8xhzl0zb"
    ],
    "score": 1.0,
    "source": "keyword",
    "window_segments": [
      {
        "video_id": "YZ1GoP8Yy8o",
        "video_url": "https://www.youtube.com/watch?v=YZ1GoP8Yy8o",
        "title": "Yemen's Iran-backed Houthis launch missile at Israel for first time since war began | BBC News",
        "channel": "BBC News",
        "segment_id": "YZ1GoP8Yy8o:0:0",
        "start_seconds": 0,
        "start_timestamp": "0:00",
        "text": "The Houthi movement in Yemen has attacked Israel for the first time since the start of the war on Iran. The Israeli military said the missile had",
        "source_run_at": "2026-03-28T16:20:45.824793+00:00",
        "playlist_ids": [
          "PLS3XGZxi7cBXc5taq0DkNtqMT8xhzl0zb"
        ]
      }
    ]
  }
]
```

### Key fields

- `chunk_id`: the indexed rolling-window chunk identifier
- `anchor_segment_id`: the original transcript row that anchors the chunk
- `video_url`: the source video URL
- `anchor_start_timestamp`: the main timestamp for linking to the hit
- `window_start_timestamp` / `window_end_timestamp`: the full transcript window covered by the hit
- `snippet`: short preview text for quick inspection
- `score`: result score used for ranking
- `source`: `keyword`, `semantic`, or a merged hybrid value such as `keyword+semantic`
- `window_segments`: the original transcript rows included in the hit window

## `answer --json`

Example:

```json
{
  "answer": "The speaker says the Houthis entered the conflict after signaling they would do so if attacks on Iran continued, and describes them as an Iran-backed proxy force [0:00] [0:24].",
  "citations": [
    {
      "title": "Yemen's Iran-backed Houthis launch missile at Israel for first time since war began | BBC News",
      "video_url": "https://www.youtube.com/watch?v=YZ1GoP8Yy8o&t=0s",
      "timestamp": "0:00",
      "chunk_id": "YZ1GoP8Yy8o_0_0_w5_5"
    },
    {
      "title": "Yemen's Iran-backed Houthis launch missile at Israel for first time since war began | BBC News",
      "video_url": "https://www.youtube.com/watch?v=YZ1GoP8Yy8o&t=24s",
      "timestamp": "0:24",
      "chunk_id": "YZ1GoP8Yy8o_24_3_w5_5"
    }
  ],
  "warning": null
}
```

### Key fields

- `answer`: the LLM-generated answer grounded in retrieved transcript evidence
- `citations`: timestamped source links used to support the answer
- `warning`: present when retrieval returned weak or insufficient evidence

## Notes

- `search --mode keyword --json` shows only Meilisearch matches.
- `search --mode semantic --json` shows only embedding matches.
- `search --mode hybrid --json` merges both result sets.
- `answer --json` first runs retrieval, then asks the LLM to synthesize an answer from the top transcript hits.
