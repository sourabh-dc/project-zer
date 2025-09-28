#!/bin/bash

# ZeroQue Application Startup Script
# This script starts all 19 microservices and supporting infrastructure

set -e  # Exit on any error

echo "🚀 Starting ZeroQue Application..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
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

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    print_error "Virtual environment not found. Please run setup first."
    echo "Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
print_status "Activating virtual environment..."
source .venv/bin/activate

# Check if required services are running
check_service() {
    local service_name=$1
    local port=$2
    local url=$3
    
    if curl -s "$url" > /dev/null 2>&1; then
        print_success "$service_name is running on port $port"
        return 0
    else
        print_warning "$service_name is not running on port $port"
        return 1
    fi
}

# Check prerequisites
print_status "Checking prerequisites..."

# Check PostgreSQL
if command -v psql > /dev/null 2>&1; then
    if psql -U zeroque -d zeroque_dev -c "\q" > /dev/null 2>&1; then
        print_success "PostgreSQL is accessible"
    else
        print_error "PostgreSQL connection failed. Please check your database setup."
        exit 1
    fi
else
    print_error "PostgreSQL client not found. Please install PostgreSQL."
    exit 1
fi

# Check Redis
if command -v redis-cli > /dev/null 2>&1; then
    if redis-cli ping > /dev/null 2>&1; then
        print_success "Redis is accessible"
    else
        print_error "Redis connection failed. Please check your Redis setup."
        exit 1
    fi
else
    print_error "Redis client not found. Please install Redis."
    exit 1
fi

# Create logs directory
mkdir -p logs

# Function to start a service
start_service() {
    local service_name=$1
    local service_path=$2
    local port=$3
    local log_file="logs/${service_name}.log"
    
    print_status "Starting $service_name on port $port..."
    
    # Kill any existing process on the port
    if lsof -i :$port > /dev/null 2>&1; then
        print_warning "Port $port is already in use. Killing existing process..."
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    
    # Start the service
    nohup uvicorn "$service_path" --reload --port "$port" > "$log_file" 2>&1 &
    local pid=$!
    
    # Wait a moment for the service to start
    sleep 3
    
    # Check if service started successfully
    if curl -s "http://localhost:$port/health" > /dev/null 2>&1; then
        print_success "$service_name started successfully (PID: $pid)"
        echo "$pid" > "logs/${service_name}.pid"
    else
        print_error "$service_name failed to start. Check $log_file for details."
        return 1
    fi
}

# Start all services
print_status "Starting all microservices..."

services=(
    "provisioning:services.provisioning.main:app:8200"
    "catalog:services.catalog.main:app:8201"
    "entry:services.entry.main:app:8202"
    "identity:services.identity.main:app:8203"
    "orders:services.orders.main:app:8208"
    "pricing:services.pricing.main:app:8209"
    "billing:services.billing.main:app:8210"
    "approvals:services.approvals.main:app:8211"
    "cv_connector:services.cv_connector.main:app:8213"
    "cv_gateway:services.cv_gateway.main:app:8214"
    "entitlements:services.entitlements.main:app:8215"
    "events:services.events.main:app:8200"
    "ledger:services.ledger.main:app:8216"
    "notifications:services.notifications.main:app:8217"
    "payments:services.payments.main:app:8218"
    "reports:services.reports.main:app:8219"
    "subscriptions:services.subscriptions.main:app:8220"
    "usage:services.usage.main:app:8221"
    "observability:services.observability.main:app:8222"
)

# Start services
for service_info in "${services[@]}"; do
    IFS=':' read -r name path module port <<< "$service_info"
    start_service "$name" "$path" "$port"
done

# Start Celery workers
print_status "Starting Celery workers..."
nohup celery -A zeroque_common.events.celery_app worker --loglevel=info --concurrency=4 --queues=default,orders,inventory,budget,notifications,webhooks,pricing,analytics --hostname=zeroque-worker@%h > logs/celery.log 2>&1 &
celery_pid=$!
echo "$celery_pid" > logs/celery.pid
print_success "Celery workers started (PID: $celery_pid)"

# Start Streamlit E2E app
print_status "Starting Streamlit E2E application..."
nohup streamlit run demo/streamlit_e2e.py --server.port 8501 > logs/streamlit.log 2>&1 &
streamlit_pid=$!
echo "$streamlit_pid" > logs/streamlit.pid
print_success "Streamlit E2E app started (PID: $streamlit_pid)"

# Wait for all services to be ready
print_status "Waiting for all services to be ready..."
sleep 10

# Health check all services
print_status "Performing health checks..."

health_check_services=(
    "8200:provisioning"
    "8201:catalog"
    "8202:entry"
    "8203:identity"
    "8208:orders"
    "8209:pricing"
    "8210:billing"
    "8211:approvals"
    "8213:cv_connector"
    "8214:cv_gateway"
    "8215:entitlements"
    "8216:ledger"
    "8217:notifications"
    "8218:payments"
    "8219:reports"
    "8220:subscriptions"
    "8221:usage"
    "8222:observability"
)

healthy_services=0
total_services=${#health_check_services[@]}

for service_info in "${health_check_services[@]}"; do
    IFS=':' read -r port name <<< "$service_info"
    if check_service "$name" "$port" "http://localhost:$port/health"; then
        ((healthy_services++))
    fi
done

# Check Streamlit
if check_service "streamlit" "8501" "http://localhost:8501"; then
    ((healthy_services++))
fi

print_status "Health check complete: $healthy_services/$((total_services + 1)) services healthy"

# Display access information
echo ""
print_success "🎉 ZeroQue Application Started Successfully!"
echo ""
echo -e "${BLUE}📱 Access Points:${NC}"
echo "  • Streamlit E2E App: http://localhost:8501"
echo "  • API Documentation:"
for service_info in "${health_check_services[@]}"; do
    IFS=':' read -r port name <<< "$service_info"
    echo "    - $name: http://localhost:$port/docs"
done
echo ""
echo -e "${BLUE}📊 Monitoring:${NC}"
echo "  • Service logs: logs/"
echo "  • Process IDs: logs/*.pid"
echo "  • Celery workers: logs/celery.log"
echo "  • Streamlit app: logs/streamlit.log"
echo ""
echo -e "${BLUE}🛠️  Management Commands:${NC}"
echo "  • Stop all services: ./scripts/stop_all_services.sh"
echo "  • Health check: ./scripts/health_check.sh"
echo "  • View logs: tail -f logs/<service>.log"
echo ""
echo -e "${GREEN}✅ Ready to test! Run the curl commands from SETUP_NEW_SYSTEM.md${NC}"
