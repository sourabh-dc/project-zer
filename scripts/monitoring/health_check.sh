#!/bin/bash

# ZeroQue Application Health Check Script
# This script checks the health of all ZeroQue services

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

echo "🏥 ZeroQue Application Health Check"
echo "=================================="

# Function to check service health
check_service() {
    local service_name=$1
    local port=$2
    local url=$3
    
    if curl -s --max-time 5 "$url" > /dev/null 2>&1; then
        print_success "$service_name (port $port): ✅ HEALTHY"
        return 0
    else
        print_error "$service_name (port $port): ❌ UNHEALTHY"
        return 1
    fi
}

# Services to check
services=(
    "8201:provisioning:http://localhost:8201/health"
    "8203:orders:http://localhost:8203/health"
    "8209:pricing:http://localhost:8209/health"
)

# Check all services
healthy_count=0
total_count=${#services[@]}

for service_info in "${services[@]}"; do
    IFS=':' read -r port name url <<< "$service_info"
    if check_service "$name" "$port" "$url"; then
        ((healthy_count++))
    fi
done

# Check Streamlit
if check_service "streamlit" "8501" "http://localhost:8501"; then
    ((healthy_count++))
    ((total_count++))
fi

# Check Celery workers
print_status "Checking Celery workers..."
if pgrep -f "celery.*worker" > /dev/null; then
    print_success "celery-workers: ✅ RUNNING"
    ((healthy_count++))
else
    print_error "celery-workers: ❌ NOT RUNNING"
fi
((total_count++))

echo ""
echo "📊 Health Summary:"
echo "=================="
echo "Healthy services: $healthy_count/$total_count"

if [ $healthy_count -eq $total_count ]; then
    print_success "🎉 All services are healthy!"
    exit 0
else
    print_warning "⚠️  Some services are unhealthy. Check logs for details."
    exit 1
fi
