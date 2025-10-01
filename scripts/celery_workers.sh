#!/bin/bash
# ZeroQue Celery Workers Deployment Script
# This script starts multiple specialized Celery workers for different queues

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting ZeroQue Celery Workers${NC}"

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}⚠️  Virtual environment not detected. Activating .venv...${NC}"
    source .venv/bin/activate
fi

# Check if Redis is running
echo -e "${BLUE}📡 Checking Redis connection...${NC}"
python -c "import redis; redis.from_url('redis://localhost:4000/0').ping(); print('✅ Redis is running')" || {
    echo -e "${RED}❌ Redis is not running. Please start Redis first.${NC}"
    exit 1
}

# Function to start a worker
start_worker() {
    local worker_name=$1
    local queues=$2
    local concurrency=$3
    local log_level=$4
    
    echo -e "${GREEN}🔄 Starting $worker_name worker...${NC}"
    celery -A zeroque_common.events.celery_app worker \
        --loglevel=$log_level \
        --concurrency=$concurrency \
        --queues=$queues \
        --hostname=$worker_name@%h \
        --pidfile=/tmp/celery_${worker_name}.pid \
        --logfile=/tmp/celery_${worker_name}.log &
    
    echo -e "${GREEN}✅ $worker_name worker started (PID: $!)${NC}"
}

# Start specialized workers
echo -e "${BLUE}📋 Starting specialized workers...${NC}"

# 1. High-priority order processing worker
start_worker "orders-worker" "orders" 8 "info"

# 2. Inventory management worker
start_worker "inventory-worker" "inventory" 4 "info"

# 3. Pricing calculation worker
start_worker "pricing-worker" "pricing" 6 "info"

# 4. General purpose worker for V2 services
start_worker "general-worker" "default,provisioning,orders,pricing" 4 "info"

echo -e "${GREEN}🎉 All Celery workers started successfully!${NC}"
echo -e "${BLUE}📊 Monitor workers with: celery -A zeroque_common.events.celery_app inspect active${NC}"
echo -e "${BLUE}📊 Check queue status: curl http://localhost:8200/events/queues/status${NC}"
echo -e "${BLUE}📊 View worker logs: tail -f /tmp/celery_*.log${NC}"

# Keep script running
echo -e "${YELLOW}⏳ Workers are running in background. Press Ctrl+C to stop all workers.${NC}"
wait
