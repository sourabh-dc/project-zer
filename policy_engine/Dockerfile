# Policy Engine Service Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY policy_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the policy engine code
COPY policy_engine /app/policy_engine

# Copy the shared packages
COPY packages /app/packages

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Run the service
CMD ["uvicorn", "policy_engine.main:app", "--host", "0.0.0.0", "--port", "8004"]
