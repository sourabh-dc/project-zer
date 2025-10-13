#!/bin/bash
# Master script to start all ZeroQue services with Celery workers

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting ZeroQue Microservices with Celery Integration${NC}"
echo -e "${BLUE}================================================${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export ALLOW_DEMO=true
export RABBITMQ_URL=${RABBITMQ_URL:-"amqp://guest:guest@localhost:5672//"}
export REDIS_URL=${REDIS_URL:-"redis://localhost:6379/0"}
export DATABASE_URL=${DATABASE_URL:-"postgresql://zeroque:zeroque@localhost:5432/zeroque_dev"}

# Function to start a service
start_service() {
    local service_name=$1
    local service_port=$2
    local service_dir="services/$service_name"
    
    if [ -d "$service_dir" ]; then
        echo -e "${GREEN}Starting $service_name service on port $service_port...${NC}"
        cd "$service_dir"
        
        # Install dependencies if requirements.txt exists
        if [ -f "requirements.txt" ]; then
            pip install -r requirements.txt > /dev/null 2>&1
        fi
        
        # Start the service
        nohup python3 main.py > "../logs/${service_name}.log" 2>&1 &
        echo $! > "../logs/${service_name}.pid"
        
        cd - > /dev/null
        echo -e "${GREEN}✅ $service_name service started (PID: $(cat logs/${service_name}.pid))${NC}"
    else
        echo -e "${RED}❌ Service directory $service_dir not found${NC}"
    fi
}

# Function to start Celery worker for a service
start_celery_worker() {
    local service_name=$1
    local service_dir="services/$service_name"
    
    if [ -d "$service_dir" ] && [ -f "$service_dir/celeryconfig.py" ]; then
        echo -e "${GREEN}Starting Celery worker for $service_name...${NC}"
        cd "$service_dir"
        
        # Start Celery worker
        nohup celery -A main.celery_app worker --loglevel=info --concurrency=4 --queues=${service_name}_events,${service_name}_maintenance,${service_name}_outbox --hostname=${service_name}-worker@%h --without-gossip --without-mingle --without-heartbeat > "../logs/${service_name}_worker.log" 2>&1 &
        echo $! > "../logs/${service_name}_worker.pid"
        
        cd - > /dev/null
        echo -e "${GREEN}✅ $service_name Celery worker started (PID: $(cat logs/${service_name}_worker.pid))${NC}"
    else
        echo -e "${YELLOW}⚠️  No Celery configuration found for $service_name${NC}"
    fi
}

# Function to start Celery Beat for a service
start_celery_beat() {
    local service_name=$1
    local service_dir="services/$service_name"
    
    if [ -d "$service_dir" ] && [ -f "$service_dir/celeryconfig.py" ]; then
        echo -e "${GREEN}Starting Celery Beat for $service_name...${NC}"
        cd "$service_dir"
        
        # Start Celery Beat
        nohup celery -A main.celery_app beat --loglevel=info --pidfile=${service_name}-beat.pid --schedule=${service_name}-beat-schedule > "../logs/${service_name}_beat.log" 2>&1 &
        echo $! > "../logs/${service_name}_beat.pid"
        
        cd - > /dev/null
        echo -e "${GREEN}✅ $service_name Celery Beat started (PID: $(cat logs/${service_name}_beat.pid))${NC}"
    else
        echo -e "${YELLOW}⚠️  No Celery configuration found for $service_name${NC}"
    fi
}

# Create logs directory
mkdir -p logs

# Services configuration
declare -A SERVICES=(
    ["provisioning"]="8000"
    ["approvals"]="8001"
    ["billing"]="8002"
    ["orders"]="8003"
    ["identity"]="8004"
    ["payments"]="8005"
    ["ledger"]="8006"
    ["pricing"]="8007"
    ["catalog"]="8008"
    ["notifications"]="8009"
    ["subscriptions"]="8010"
    ["entitlements"]="8011"
    ["usage"]="8012"
    ["entry"]="8013"
    ["cv_connector"]="8014"
    ["cv_gateway"]="8015"
    ["service_registry"]="8016"
    ["reports"]="8017"
    ["monitoring"]="8018"
    ["observability"]="8019"
    ["events"]="8020"
)

# Start all services
echo -e "${BLUE}📦 Starting Services...${NC}"
for service in "${!SERVICES[@]}"; do
    start_service "$service" "${SERVICES[$service]}"
    sleep 2
done

# Start Celery workers
echo -e "${BLUE}⚙️  Starting Celery Workers...${NC}"
for service in "${!SERVICES[@]}"; do
    start_celery_worker "$service"
    sleep 1
done

# Start Celery Beat schedulers
echo -e "${BLUE}⏰ Starting Celery Beat Schedulers...${NC}"
for service in "${!SERVICES[@]}"; do
    start_celery_beat "$service"
    sleep 1
done

# Wait a moment for services to start
sleep 5

# Check service health
echo -e "${BLUE}🔍 Checking Service Health...${NC}"
for service in "${!SERVICES[@]}"; do
    port="${SERVICES[$service]}"
    if curl -s "http://localhost:$port/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ $service (port $port) - Healthy${NC}"
    else
        echo -e "${RED}❌ $service (port $port) - Unhealthy${NC}"
    fi
done

echo -e "${GREEN}🎉 All services started successfully!${NC}"
echo -e "${BLUE}================================================${NC}"
echo -e "${YELLOW}Service Ports:${NC}"
for service in "${!SERVICES[@]}"; do
    echo -e "  $service: http://localhost:${SERVICES[$service]}"
done

echo -e "${YELLOW}Logs Directory:${NC} logs/"
echo -e "${YELLOW}PID Files:${NC} logs/*.pid"

echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}🚀 ZeroQue Microservices are ready!${NC}"

