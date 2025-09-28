# Multi-stage Dockerfile for ZeroQue microservices
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
COPY packages/zeroque_common/pyproject.toml packages/zeroque_common/

# Install Python dependencies with psycopg2-binary compatibility
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir psycopg2-binary
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e ./packages/zeroque_common

# Copy application code
COPY packages/ packages/
COPY services/ services/
COPY alembic/ alembic/
COPY alembic.ini .

# Reinstall zeroque_common after copying packages
RUN pip install --no-cache-dir -e ./packages/zeroque_common

# Create non-root user
RUN groupadd -r zeroque && useradd -r -g zeroque zeroque
RUN chown -R zeroque:zeroque /app
USER zeroque

# Expose port (will be overridden by the service)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Default command (will be overridden)
CMD ["python", "-m", "services.provisioning.main"]
