VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: install web test lint clean help

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install: $(VENV)/bin/activate  ## Set up virtualenv and install all dependencies

web: $(VENV)/bin/activate  ## Start the web server (accessible on local network)
	$(VENV)/bin/uvicorn audio_articles.web.app:app --reload --host 0.0.0.0

test: $(VENV)/bin/activate  ## Run the test suite
	$(VENV)/bin/pytest

lint: $(VENV)/bin/activate  ## Run ruff linter
	$(VENV)/bin/ruff check src tests

clean:  ## Remove the virtualenv
	rm -rf $(VENV)

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
