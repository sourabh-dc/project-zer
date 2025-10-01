#!/bin/bash

# ZeroQue Application Stop Script
# This script stops all running ZeroQue services

set -e

echo "🛑 Stopping ZeroQue Application..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to stop a service by PID file
stop_service_by_pid() {
    local service_name=$1
    local pid_file="logs/${service_name}.pid"
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            print_status "Stopping $service_name (PID: $pid)..."
            kill "$pid"
            sleep 2
            if kill -0 "$pid" 2>/dev/null; then
                print_warning "Force killing $service_name..."
                kill -9 "$pid"
            fi
            print_success "$service_name stopped"
        else
            print_warning "$service_name was not running"
        fi
        rm -f "$pid_file"
    else
        print_warning "No PID file found for $service_name"
    fi
}

# Stop services by PID files
services=(
    "provisioning"
    "orders"
    "pricing"
)

for service in "${services[@]}"; do
    stop_service_by_pid "$service"
done

# Stop Celery workers
stop_service_by_pid "celery"

# Stop Streamlit
stop_service_by_pid "streamlit"

# Kill any remaining processes on our ports
print_status "Cleaning up any remaining processes on ZeroQue ports..."

ports=(8200 8201 8202 8203 8208 8209 8210 8211 8213 8214 8215 8216 8217 8218 8219 8220 8221 8222 8501)

for port in "${ports[@]}"; do
    if lsof -i :$port > /dev/null 2>&1; then
        print_warning "Killing remaining process on port $port"
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
    fi
done

# Clean up log files
print_status "Cleaning up log files..."
rm -rf logs/*.pid

print_success "🎉 All ZeroQue services stopped successfully!"
