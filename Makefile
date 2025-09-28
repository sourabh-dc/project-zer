# ZeroQue CI/CD Makefile
.PHONY: help up down init seed test lint format type-check security-scan build push deploy migrate health-check clean

# Default target
help:
	@echo "ZeroQue CI/CD Commands:"
	@echo "  Development:"
	@echo "    make init          - Initialize development environment"
	@echo "    make up            - Start infrastructure services"
	@echo "    make down          - Stop infrastructure services"
	@echo "    make seed          - Seed development database"
	@echo "    make events        - Start event service and workers"
	@echo "    make workers       - Start Celery workers"
	@echo ""
	@echo "  Code Quality:"
	@echo "    make test          - Run all tests"
	@echo "    make lint          - Run linting checks"
	@echo "    make format        - Format code with Black"
	@echo "    make type-check    - Run type checking with MyPy"
	@echo "    make security-scan - Run security vulnerability scan"
	@echo ""
	@echo "  Build & Deploy:"
	@echo "    make build         - Build all Docker images"
	@echo "    make push          - Push images to registry"
	@echo "    make deploy-staging - Deploy to staging environment"
	@echo "    make deploy-prod   - Deploy to production environment"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate       - Run database migrations"
	@echo "    make migrate-check - Check migration status"
	@echo ""
	@echo "  Monitoring:"
	@echo "    make health-check  - Check service health"
	@echo "    make load-test     - Run load tests"
	@echo ""
	@echo "  Utilities:"
	@echo "    make clean         - Clean up build artifacts"

# ===== Development =====
init:
	python -m venv .venv && \
	source .venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt && \
	pip install -e ./packages/zeroque_common && \
	pip install ruff black mypy pytest pytest-cov pytest-asyncio httpx && \
	cp .env.example .env

up:
	docker compose -f infra/docker-compose.dev.yml up -d

down:
	docker compose -f infra/docker-compose.dev.yml down

up-full:
	docker compose up -d

down-full:
	docker compose down

seed:
	source .venv/bin/activate && python ops/seed/seed_sprint1.py

# Event service management
events:
	source .venv/bin/activate && python -m services.events.main --port 8213 &

workers:
	source .venv/bin/activate && python scripts/celery_worker.py &

event-consumer:
	source .venv/bin/activate && python scripts/event_consumer.py &

# Observability service management
observability:
	source .venv/bin/activate && python -m services.observability.main --port 8214 &

stop-events:
	pkill -f "services.events.main" || true
	pkill -f "celery_worker.py" || true

stop-observability:
	pkill -f "services.observability.main" || true

# ===== Code Quality =====
test:
	source .venv/bin/activate && pytest -v --cov=packages/zeroque_common --cov=services --cov-report=html --cov-report=term

test-unit:
	source .venv/bin/activate && pytest tests/ -v

test-integration:
	source .venv/bin/activate && pytest tests/test_smoke_services.py -v

lint:
	source .venv/bin/activate && ruff check . --output-format=github

format:
	source .venv/bin/activate && black .

format-check:
	source .venv/bin/activate && black --check --diff .

type-check:
	source .venv/bin/activate && mypy packages/zeroque_common services/ --ignore-missing-imports

security-scan:
	docker run --rm -v $(PWD):/app aquasec/trivy fs /app

# ===== Build & Deploy =====
build:
	docker buildx build --platform linux/amd64 -t zeroque-provisioning:latest --build-arg SERVICE_NAME=provisioning .
	docker buildx build --platform linux/amd64 -t zeroque-catalog:latest --build-arg SERVICE_NAME=catalog .
	docker buildx build --platform linux/amd64 -t zeroque-entry:latest --build-arg SERVICE_NAME=entry .
	docker buildx build --platform linux/amd64 -t zeroque-identity:latest --build-arg SERVICE_NAME=identity .
	docker buildx build --platform linux/amd64 -t zeroque-orders:latest --build-arg SERVICE_NAME=orders .
	docker buildx build --platform linux/amd64 -t zeroque-billing:latest --build-arg SERVICE_NAME=billing .
	docker buildx build --platform linux/amd64 -t zeroque-pricing:latest --build-arg SERVICE_NAME=pricing .

build-service:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make build-service SERVICE=<service_name>"; exit 1; fi
	docker buildx build --platform linux/amd64 -t zeroque-$(SERVICE):latest --build-arg SERVICE_NAME=$(SERVICE) .

push:
	@echo "Pushing images to registry..."
	@for service in provisioning catalog entry identity orders billing pricing; do \
		docker push zeroque-$$service:latest; \
	done

deploy-staging:
	@echo "Deploying to staging environment..."
	# Add staging deployment commands here
	@echo "Staging deployment completed"

deploy-prod:
	@echo "Deploying to production environment..."
	# Add production deployment commands here
	@echo "Production deployment completed"

# ===== Database =====
migrate:
	source .venv/bin/activate && alembic upgrade head

migrate-check:
	source .venv/bin/activate && alembic check

migrate-create:
	@if [ -z "$(MESSAGE)" ]; then echo "Usage: make migrate-create MESSAGE='<migration message>'"; exit 1; fi
	source .venv/bin/activate && alembic revision --autogenerate -m "$(MESSAGE)"

migrate-downgrade:
	source .venv/bin/activate && alembic downgrade -1

# ===== Monitoring =====
health-check:
	@echo "Checking service health..."
	@for port in 8201 8202 8204 8206 8208 8209 8210; do \
		echo -n "Port $$port: "; \
		curl -s -f http://localhost:$$port/health > /dev/null && echo "✅ Healthy" || echo "❌ Unhealthy"; \
	done

health-check-detailed:
	@echo "Detailed health check..."
	@for port in 8201 8202 8204 8206 8208 8209 8210; do \
		echo "=== Port $$port ==="; \
		curl -s http://localhost:$$port/health | jq . 2>/dev/null || echo "Service not responding"; \
		echo ""; \
	done

load-test:
	@echo "Running load tests..."
	@if ! command -v ab >/dev/null 2>&1; then echo "Install apache2-utils first: sudo apt-get install apache2-utils"; exit 1; fi
	@for port in 8201 8202 8208; do \
		echo "Load testing port $$port..."; \
		ab -n 100 -c 10 http://localhost:$$port/health; \
		echo ""; \
	done

# ===== Service Management =====
start-services:
	@echo "Starting all services..."
	@for service in provisioning catalog entry identity orders billing pricing; do \
		echo "Starting $$service..."; \
		source .venv/bin/activate && uvicorn services.$$service.main:app --host 0.0.0.0 --port 8$$(echo $$service | wc -c | tr -d ' ')01 --reload & \
	done

stop-services:
	@echo "Stopping all services..."
	@pkill -f "uvicorn services"

restart-services: stop-services start-services

# ===== Utilities =====
clean:
	@echo "Cleaning up..."
	docker system prune -f
	docker volume prune -f
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

logs:
	docker compose logs -f

logs-service:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make logs-service SERVICE=<service_name>"; exit 1; fi
	docker compose logs -f $(SERVICE)

# ===== CI/CD Helpers =====
ci-test: lint format-check type-check test

ci-build: build

ci-deploy-staging: build deploy-staging

ci-deploy-prod: build deploy-prod

# ===== Development Helpers =====
dev-setup: init up seed
	@echo "Development environment ready!"
	@echo "Services running on:"
	@echo "  Provisioning: http://localhost:8201"
	@echo "  Catalog: http://localhost:8202"
	@echo "  Entry: http://localhost:8204"
	@echo "  Identity: http://localhost:8210"
	@echo "  Orders: http://localhost:8208"
	@echo "  Billing: http://localhost:8206"
	@echo "  Pricing: http://localhost:8209"
	@echo "  Events: http://localhost:8213"
	@echo "  Observability: http://localhost:8214"
	@echo "  Streamlit Demo: http://localhost:8501"

status:
	@echo "Service Status:"
	@docker compose ps
	@echo ""
	@echo "Health Check:"
	@make health-check
