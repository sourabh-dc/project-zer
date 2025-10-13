# Multi-stage Dockerfile for ZeroQue V4.1 Microservices
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    netcat-openbsd \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with psycopg2-binary compatibility
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir psycopg2-binary
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY services/ services/
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/ config/
COPY scripts/ scripts/

# Reinstall zeroque_common after copying packages

# Create non-root user
RUN groupadd -r zeroque && useradd -r -g zeroque zeroque
RUN chown -R zeroque:zeroque /app
USER zeroque

# Expose port (will be overridden by the service)
EXPOSE 8000

# Health check with timeout
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Default command (will be overridden by docker-compose)
CMD ["python", "-m", "services.provisioning.main"]