#!/bin/bash
# Start Celery worker for notifications Service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting notifications Service Celery Worker...${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt

# Set environment variables
export CELERY_BROKER_URL=${RABBITMQ_URL:-"amqp://guest:guest@localhost:5672//"}
export CELERY_RESULT_BACKEND=${REDIS_URL:-"redis://localhost:6379/0"}
export SERVICE_PORT=${SERVICE_PORT:-8000}

# Start Celery worker
echo -e "${GREEN}Starting Celery worker for notifications service...${NC}"
celery -A main.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    --queues=notifications_events,notifications_maintenance,notifications_outbox \
    --hostname=notifications-worker@%h \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
