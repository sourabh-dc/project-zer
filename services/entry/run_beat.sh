#!/bin/bash
# Start Celery Beat scheduler for entry Service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting entry Service Celery Beat Scheduler...${NC}"

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

# Start Celery Beat
echo -e "${GREEN}Starting Celery Beat scheduler for entry service...${NC}"
celery -A main.celery_app beat \
    --loglevel=info \
    --pidfile=entry-beat.pid \
    --schedule=entry-beat-schedule
