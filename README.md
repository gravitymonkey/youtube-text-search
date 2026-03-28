# YouTube Text Search

Turn a YouTube playlist or set of YouTube URLs into a searchable transcript index.


<img src="./header.png" width=500 alt="influencers">

## Getting started

### 1. Clone the repo

```bash
git clone <repo-url>
cd yt-text-search
```

### 2. Create a Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Copy the default config and example URL list

```bash
cp .env.example .env
cp urls.example.txt urls.txt
```

The included `urls.example.txt` already contains a public starter playlist.

By default, the app will only process the first 10 videos from that playlist, so you can try the system without changing anything.

### 4. Install everything and start Docker

```bash
make bootstrap
```

This will:

- install Python dependencies
- install Playwright Chromium
- start Meilisearch in Docker

### 5. Run the pipeline

```bash
make full-pipeline URL_FILE=urls.txt
```

This will:

- fetch transcripts
- store them locally
- index them for keyword search
- build embeddings if `OPENAI_API_KEY` is set in `.env`
If `OPENAI_API_KEY` is missing, `make full-pipeline` will stop with a clear message after keyword indexing and tell you how to enable embeddings.

make search QUERY="your search terms"
```

If you want to see the exact JSON response shape for `search` and `answer`, see [RESPONSE.md](/Users/jason/dev/yt-text-search/RESPONSE.md).

### 7. Ask a question

If you want answer synthesis, add your OpenAI API key to `.env` first:

```bash
OPENAI_API_KEY=your_key_here
```

Then run:

```bash
make index-embeddings
make answer QUESTION="your question"
```

Example:

```bash
make answer QUESTION="What are the main ideas in this playlist?"
```

## Using your own URLs

Edit `urls.txt` and add:

- a YouTube playlist URL
- a YouTube video URL
- or a mix of both

Use one URL per line.

Then rerun:

```bash
make full-pipeline URL_FILE=urls.txt
```

## Useful commands

Start services:

```bash
make up
```

Stop services:

```bash
make down
```

Watch Meilisearch logs:

```bash
make logs
```

Extract one transcript directly:

```bash
python3 extract_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Default first-run behavior

Out of the box:

- the example playlist is already provided
- only the first 10 videos are processed
- keyword search works after `make full-pipeline`
- semantic search and `answer` work after you add `OPENAI_API_KEY`

## Use the force, read the source; but if you just want to get going:

```bash
git clone https://github.com/gravitymonkey/youtube-text-search.git
cd yt-text-search
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env (edit .env to add your OPENAI_API_KEY for embeddings and RAG response)
cp urls.example.txt urls.txt (edit urls.txt or use default latest BBC news)
make bootstrap
make full-pipeline URL_FILE=urls.txt
make search QUERY="revolution" (or your search term)
```


<img src="./screenshot.png" width=500 alt="example output">
