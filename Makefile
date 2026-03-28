PYTHON ?= python3
URL_FILE ?= urls.txt
QUERY ?=
QUESTION ?=
DOTENV_LOAD = set -a; [ -f .env ] && . ./.env; set +a;

.PHONY: install install-browser up down logs extract ingest index-keywords index-embeddings bootstrap search answer full-pipeline

install:
	$(PYTHON) -m pip install -e '.[browser,dev]'

install-browser:
	$(PYTHON) -m playwright install chromium

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f meilisearch

extract:
	@if [ -z "$(URL)" ]; then echo "Usage: make extract URL='https://www.youtube.com/watch?v=...'"; exit 1; fi
	$(PYTHON) extract_transcript.py "$(URL)" --cache-write

ingest:
	$(PYTHON) -m app.cli ingest "$(URL_FILE)"

index-keywords:
	$(PYTHON) -m app.cli index-keywords --json

index-embeddings:
	$(PYTHON) -m app.cli index-embeddings --json

bootstrap: install install-browser up

full-pipeline: ingest index-keywords
	@$(DOTENV_LOAD) \
	if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "OPENAI_API_KEY is not set, so embeddings were not built."; \
		echo "Edit .env and set: OPENAI_API_KEY=your_key_here"; \
		echo "See .env.example for the expected format, then rerun: make index-embeddings"; \
		exit 1; \
	fi
	$(PYTHON) -m app.cli index-embeddings --json

search:
	@if [ -z "$(QUERY)" ]; then echo "Usage: make search QUERY='your search terms'"; exit 1; fi
	$(PYTHON) -m app.cli search "$(QUERY)"

answer:
	@if [ -z "$(QUESTION)" ]; then echo "Usage: make answer QUESTION='your question'"; exit 1; fi
	$(PYTHON) -m app.cli answer "$(QUESTION)"
