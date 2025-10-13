# ZeroQue V4.1 CI/CD Makefile
.PHONY: help up down init seed test lint format type-check security-scan build push deploy migrate health-check clean

# Default target
help:
	@echo "ZeroQue V4.1 CI/CD Commands:"
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
	python -m venv venv && \
	source venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt && \
	pip install -e ./packages/zeroque_common && \
	pip install ruff black mypy pytest pytest-cov pytest-asyncio httpx locust

up:
	docker-compose up -d rabbitmq postgres redis prometheus grafana

down:
	docker-compose down

up-full:
	docker-compose up -d

down-full:
	docker-compose down

seed:
	source venv/bin/activate && python ops/seed/seed_sprint1.py

# Event service management
events:
	source venv/bin/activate && python services/events/main.py &

workers:
	source venv/bin/activate && python scripts/celery_worker.py &

event-consumer:
	source venv/bin/activate && python scripts/event_consumer.py &

# Observability service management
observability:
	source venv/bin/activate && python services/observability/main.py &

stop-events:
	pkill -f "services/events/main.py" || true
	pkill -f "celery_worker.py" || true

stop-observability:
	pkill -f "services/observability/main.py" || true

# ===== Code Quality =====
test:
	source venv/bin/activate && pytest -v --cov=packages/zeroque_common --cov=services --cov-report=html --cov-report=term

test-unit:
	source venv/bin/activate && pytest tests/unit/ -v

test-integration:
	source venv/bin/activate && pytest tests/integration/ -v

test-e2e:
	source venv/bin/activate && pytest tests/e2e/ -v

lint:
	source venv/bin/activate && ruff check . --output-format=github

format:
	source venv/bin/activate && black .

format-check:
	source venv/bin/activate && black --check --diff .

type-check:
	source venv/bin/activate && mypy packages/zeroque_common services/ --ignore-missing-imports

security-scan:
	python scripts/security-audit.py --base-url http://localhost

# ===== Build & Deploy =====
build:
	docker buildx build --platform linux/amd64 -t zeroque-orders:latest --build-arg SERVICE_NAME=orders .
	docker buildx build --platform linux/amd64 -t zeroque-identity:latest --build-arg SERVICE_NAME=identity .
	docker buildx build --platform linux/amd64 -t zeroque-ledger:latest --build-arg SERVICE_NAME=ledger .
	docker buildx build --platform linux/amd64 -t zeroque-payments:latest --build-arg SERVICE_NAME=payments .
	docker buildx build --platform linux/amd64 -t zeroque-events:latest --build-arg SERVICE_NAME=events .
	docker buildx build --platform linux/amd64 -t zeroque-cv-gateway:latest --build-arg SERVICE_NAME=cv-gateway .
	docker buildx build --platform linux/amd64 -t zeroque-cv-connector:latest --build-arg SERVICE_NAME=cv-connector .
	docker buildx build --platform linux/amd64 -t zeroque-approvals:latest --build-arg SERVICE_NAME=approvals .
	docker buildx build --platform linux/amd64 -t zeroque-entitlements:latest --build-arg SERVICE_NAME=entitlements .
	docker buildx build --platform linux/amd64 -t zeroque-subscriptions:latest --build-arg SERVICE_NAME=subscriptions .
	docker buildx build --platform linux/amd64 -t zeroque-notifications:latest --build-arg SERVICE_NAME=notifications .
	docker buildx build --platform linux/amd64 -t zeroque-reports:latest --build-arg SERVICE_NAME=reports .
	docker buildx build --platform linux/amd64 -t zeroque-usage:latest --build-arg SERVICE_NAME=usage .
	docker buildx build --platform linux/amd64 -t zeroque-observability:latest --build-arg SERVICE_NAME=observability .
	docker buildx build --platform linux/amd64 -t zeroque-service-registry:latest --build-arg SERVICE_NAME=service-registry .
	docker buildx build --platform linux/amd64 -t zeroque-monitoring:latest --build-arg SERVICE_NAME=monitoring .

build-service:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make build-service SERVICE=<service_name>"; exit 1; fi
	docker buildx build --platform linux/amd64 -t zeroque-$(SERVICE):latest --build-arg SERVICE_NAME=$(SERVICE) .

push:
	@echo "Pushing images to registry..."
	@for service in orders identity ledger payments events cv-gateway cv-connector approvals entitlements subscriptions notifications reports usage observability service-registry monitoring; do \
		docker push zeroque-$$service:latest; \
	done

deploy-staging:
	@echo "Deploying to staging environment..."
	./scripts/deploy-production.sh staging latest

deploy-prod:
	@echo "Deploying to production environment..."
	./scripts/deploy-production.sh production latest

# ===== Database =====
migrate:
	source venv/bin/activate && alembic upgrade head

migrate-check:
	source venv/bin/activate && alembic check

migrate-create:
	@if [ -z "$(MESSAGE)" ]; then echo "Usage: make migrate-create MESSAGE='<migration message>'"; exit 1; fi
	source venv/bin/activate && alembic revision --autogenerate -m "$(MESSAGE)"

migrate-downgrade:
	source venv/bin/activate && alembic downgrade -1

# ===== Monitoring =====
health-check:
	@echo "Checking service health..."
	@for port in 8080 8085 8086 8087 8088 8000 8100 8211 8212 8213 8300 8400 8200 8600 8500 8700; do \
		echo -n "Port $$port: "; \
		curl -s -f http://localhost:$$port/health > /dev/null && echo "✅ Healthy" || echo "❌ Unhealthy"; \
	done

health-check-detailed:
	@echo "Detailed health check..."
	@for port in 8080 8085 8086 8087 8088 8000 8100 8211 8212 8213 8300 8400 8200 8600 8500 8700; do \
		echo "=== Port $$port ==="; \
		curl -s http://localhost:$$port/health | jq . 2>/dev/null || echo "Service not responding"; \
		echo ""; \
	done

load-test:
	@echo "Running load tests..."
	source venv/bin/activate && locust -f tests/load/locustfile.py --headless -u 50 -r 5 -t 60s --html load-test-report.html

# ===== Service Management =====
start-services:
	@echo "Starting all services..."
	@for service in orders identity ledger payments events cv-gateway cv-connector approvals entitlements subscriptions notifications reports usage observability service-registry monitoring; do \
		echo "Starting $$service..."; \
		source venv/bin/activate && python services/$$service/main.py & \
	done

stop-services:
	@echo "Stopping all services..."
	@pkill -f "python services"

restart-services: stop-services start-services

# ===== Utilities =====
clean:
	@echo "Cleaning up..."
	docker system prune -f
	docker volume prune -f
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf coverage.xml
	rm -rf load-test-report.html
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

logs:
	docker-compose logs -f

logs-service:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make logs-service SERVICE=<service_name>"; exit 1; fi
	docker-compose logs -f $(SERVICE)

# ===== CI/CD Helpers =====
ci-test: lint format-check type-check test

ci-build: build

ci-deploy-staging: build deploy-staging

ci-deploy-prod: build deploy-prod

# ===== Development Helpers =====
dev-setup: init up seed
	@echo "Development environment ready!"
	@echo "Services running on:"
	@echo "  Orders: http://localhost:8080"
	@echo "  Identity: http://localhost:8085"
	@echo "  Ledger: http://localhost:8086"
	@echo "  Payments: http://localhost:8087"
	@echo "  Events: http://localhost:8088"
	@echo "  CV Gateway: http://localhost:8000"
	@echo "  CV Connector: http://localhost:8100"
	@echo "  Entitlements: http://localhost:8211"
	@echo "  Subscriptions: http://localhost:8212"
	@echo "  Approvals: http://localhost:8213"
	@echo "  Notifications: http://localhost:8300"
	@echo "  Reports: http://localhost:8400"
	@echo "  Usage: http://localhost:8200"
	@echo "  Observability: http://localhost:8600"
	@echo "  Service Registry: http://localhost:8500"
	@echo "  Monitoring: http://localhost:8700"
	@echo "  Grafana: http://localhost:3000"
	@echo "  Prometheus: http://localhost:9090"
	@echo "  RabbitMQ Management: http://localhost:15672"

status:
	@echo "Service Status:"
	@docker-compose ps
	@echo ""
	@echo "Health Check:"
	@make health-check