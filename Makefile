# Comenzi scurte pentru vedit. `make help` le listează.
# Presupune un venv activ (python -m venv .venv && source .venv/bin/activate) pentru țintele Python.

PY      ?= python
EXTRAS  ?= whisper,reframe,tts,server,dev
IMAGE   ?= vedit:latest

.DEFAULT_GOAL := help
.PHONY: help install dev server web-dev test build-web docker-build docker-up docker-down docker-logs lint

help: ## arată comenzile
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## pachetul Python (editabil, cu EXTRAS) + dependențele frontend-ului
	$(PY) -m pip install -e '.[$(EXTRAS)]'
	cd web && npm ci

dev: ## server API (:8000) + Vite cu hot reload (:5173); Ctrl+C le oprește pe amândouă
	@trap 'kill 0' INT TERM EXIT; \
	vedit-server & \
	(cd web && npm run dev) & \
	wait

server: ## doar vedit-server (servește și web/dist dacă e construit)
	vedit-server

web-dev: ## doar Vite (proxy /api spre :8000)
	cd web && npm run dev

test: ## toate testele (au nevoie de ffmpeg în PATH)
	$(PY) -m pytest -q

build-web: ## construiește frontend-ul în web/dist
	cd web && npm ci && npm run build

docker-build: ## construiește imaginea Docker (INSTALL_WHISPER=1 / INSTALL_DIARIZE=1 opțional)
	docker build -t $(IMAGE) \
		--build-arg INSTALL_WHISPER=$${INSTALL_WHISPER:-0} \
		--build-arg INSTALL_DIARIZE=$${INSTALL_DIARIZE:-0} .

docker-up: ## pornește aplicația + Caddy (citește .env)
	docker compose up -d --build

docker-down: ## oprește tot (datele din ./data rămân)
	docker compose down

docker-logs: ## urmărește logurile
	docker compose logs -f --tail=100

demo: ## descarcă material de test real în demo/ (vlog cu vorbire reală + poze pentru faceless)
	$(PY) scripts/demo_media.py

lint: ## ruff, dacă e instalat (informativ, nu blochează CI)
	@if command -v ruff >/dev/null 2>&1; then ruff check vedit tests; \
	else echo "ruff nu e instalat: pip install ruff (sau pacman -S ruff)"; fi
