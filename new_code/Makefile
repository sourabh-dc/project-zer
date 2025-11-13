.PHONY: help install run dev docker-build docker-run docker-up docker-down clean test

help:
	@echo "ZeroQue Provisioning Service - Available Commands:"
	@echo ""
	@echo "  make install        Install Python dependencies"
	@echo "  make run            Run the service locally"
	@echo "  make dev            Run with auto-reload (development mode)"
	@echo "  make docker-build   Build Docker image"
	@echo "  make docker-run     Run Docker container"
	@echo "  make docker-up      Start all services (docker-compose)"
	@echo "  make docker-down    Stop all services (docker-compose)"
	@echo "  make clean          Clean up Python cache files"
	@echo "  make test           Run tests"
	@echo ""

install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt

run:
	@echo "Starting provisioning service..."
	python main.py

dev:
	@echo "Starting provisioning service in development mode..."
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

docker-build:
	@echo "Building Docker image..."
	docker build -t zeroque-provisioning:latest .

docker-run: docker-build
	@echo "Running Docker container..."
	docker run -d \
		-p 8000:8000 \
		-e DATABASE_URL="postgresql://zeroque:zeroque@host.docker.internal:5432/zeroque_dev" \
		-e REDIS_URL="redis://host.docker.internal:6379/0" \
		--name provisioning \
		zeroque-provisioning:latest
	@echo "Service running at http://localhost:8000"
	@echo "View logs: docker logs -f provisioning"

docker-up:
	@echo "Starting all services with docker-compose..."
	docker-compose up -d
	@echo "Services started!"
	@echo "  - PostgreSQL: localhost:5432"
	@echo "  - Redis: localhost:6379"
	@echo "  - API: http://localhost:8000"
	@echo "  - Health: http://localhost:8000/health"
	@echo "  - Metrics: http://localhost:8000/metrics"

docker-down:
	@echo "Stopping all services..."
	docker-compose down

docker-logs:
	docker-compose logs -f provisioning

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	@echo "Clean complete!"

test:
	@echo "Running tests..."
	pytest tests/ -v

setup-rls:
	@echo "Setting up PostgreSQL RLS policies..."
	@if [ -z "$$DATABASE_URL" ]; then \
		echo "Error: DATABASE_URL environment variable not set"; \
		exit 1; \
	fi
	psql $$DATABASE_URL -f setup_rls.sql
	@echo "RLS policies created!"

health:
	@echo "Checking service health..."
	@curl -s http://localhost:8000/health | python -m json.tool

metrics:
	@echo "Fetching metrics..."
	@curl -s http://localhost:8000/metrics


