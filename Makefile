# Helper targets
.PHONY: up down init seed

up:
	docker compose -f infra/docker-compose.dev.yml up -d

down:
	docker compose -f infra/docker-compose.dev.yml down

init:
	python -m venv .venv && \
	source .venv/bin/activate && \
	pip install -r requirements.txt && \
	pip install -e ./packages/zeroque_common && \
	cp .env.example .env

seed:
	python ops/seed/seed_sprint1.py
