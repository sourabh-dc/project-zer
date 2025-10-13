#!/bin/bash
# Master script to stop all ZeroQue services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🛑 Stopping ZeroQue Microservices${NC}"
echo -e "${BLUE}================================================${NC}"

# Function to stop a service
stop_service() {
    local service_name=$1
    local pid_file="logs/${service_name}.pid"
    local worker_pid_file="logs/${service_name}_worker.pid"
    local beat_pid_file="logs/${service_name}_beat.pid"
    
    # Stop main service
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping $service_name service (PID: $pid)...${NC}"
            kill "$pid"
            rm -f "$pid_file"
            echo -e "${GREEN}✅ $service_name service stopped${NC}"
        else
            echo -e "${YELLOW}⚠️  $service_name service not running${NC}"
            rm -f "$pid_file"
        fi
    fi
    
    # Stop Celery worker
    if [ -f "$worker_pid_file" ]; then
        local worker_pid=$(cat "$worker_pid_file")
        if ps -p "$worker_pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping $service_name Celery worker (PID: $worker_pid)...${NC}"
            kill "$worker_pid"
            rm -f "$worker_pid_file"
            echo -e "${GREEN}✅ $service_name Celery worker stopped${NC}"
        else
            echo -e "${YELLOW}⚠️  $service_name Celery worker not running${NC}"
            rm -f "$worker_pid_file"
        fi
    fi
    
    # Stop Celery Beat
    if [ -f "$beat_pid_file" ]; then
        local beat_pid=$(cat "$beat_pid_file")
        if ps -p "$beat_pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping $service_name Celery Beat (PID: $beat_pid)...${NC}"
            kill "$beat_pid"
            rm -f "$beat_pid_file"
            echo -e "${GREEN}✅ $service_name Celery Beat stopped${NC}"
        else
            echo -e "${YELLOW}⚠️  $service_name Celery Beat not running${NC}"
            rm -f "$beat_pid_file"
        fi
    fi
}

# Services list
SERVICES=(
    "provisioning"
    "approvals"
    "billing"
    "orders"
    "identity"
    "payments"
    "ledger"
    "pricing"
    "catalog"
    "notifications"
    "subscriptions"
    "entitlements"
    "usage"
    "entry"
    "cv_connector"
    "cv_gateway"
    "service_registry"
    "reports"
    "monitoring"
    "observability"
    "events"
)

# Stop all services
for service in "${SERVICES[@]}"; do
    stop_service "$service"
done

# Clean up any remaining processes
echo -e "${YELLOW}Cleaning up any remaining processes...${NC}"

# Kill any remaining Python processes related to our services
pkill -f "python3 main.py" 2>/dev/null || true
pkill -f "celery.*worker" 2>/dev/null || true
pkill -f "celery.*beat" 2>/dev/null || true

# Clean up PID files
rm -f logs/*.pid

echo -e "${GREEN}🎉 All services stopped successfully!${NC}"
echo -e "${BLUE}================================================${NC}"

