#!/bin/bash
# Setup demo environment for ZeroQue Provisioning Service testing

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🚀 Setting up ZeroQue Provisioning Service Demo Environment${NC}"
echo "=================================================================="

# Check if we're in the right directory
if [ ! -f "services/provisioning/main.py" ]; then
    echo -e "${RED}❌ Error: Please run this script from the project root directory${NC}"
    exit 1
fi

# Function to check if a service is running
check_service() {
    local service_name="$1"
    local check_command="$2"
    
    echo -e "${BLUE}🔍 Checking $service_name...${NC}"
    
    if eval "$check_command" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ $service_name is running${NC}"
        return 0
    else
        echo -e "${RED}❌ $service_name is not running${NC}"
        return 1
    fi
}

# Check required services
echo -e "${YELLOW}📋 Checking required services...${NC}"

services_ok=true

# Check PostgreSQL
if ! check_service "PostgreSQL" "psql -h localhost -U zeroque -d zeroque_dev -c 'SELECT 1;'"; then
    echo -e "${YELLOW}💡 To start PostgreSQL:${NC}"
    echo "   brew services start postgresql"
    echo "   createdb zeroque_dev"
    echo "   psql -d zeroque_dev -c \"CREATE USER zeroque WITH PASSWORD 'zeroque';\""
    echo "   psql -d zeroque_dev -c \"GRANT ALL PRIVILEGES ON DATABASE zeroque_dev TO zeroque;\""
    services_ok=false
fi

# Check RabbitMQ
if ! check_service "RabbitMQ" "curl -s http://localhost:15672/api/overview"; then
    echo -e "${YELLOW}💡 To start RabbitMQ:${NC}"
    echo "   brew services start rabbitmq"
    echo "   # Or with Docker: docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management"
    services_ok=false
fi

# Check Redis
if ! check_service "Redis" "redis-cli ping"; then
    echo -e "${YELLOW}💡 To start Redis:${NC}"
    echo "   brew services start redis"
    echo "   # Or with Docker: docker run -d --name redis -p 6379:6379 redis:alpine"
    services_ok=false
fi

if [ "$services_ok" = false ]; then
    echo -e "${RED}❌ Some required services are not running. Please start them and try again.${NC}"
    exit 1
fi

# Install Python dependencies
echo -e "${YELLOW}📦 Installing Python dependencies...${NC}"
if [ -f "services/provisioning/requirements.txt" ]; then
    pip install -r services/provisioning/requirements.txt
    echo -e "${GREEN}✅ Dependencies installed${NC}"
else
    echo -e "${YELLOW}⚠️  requirements.txt not found, installing manually...${NC}"
    pip install fastapi uvicorn sqlalchemy psycopg2-binary pika celery prometheus_client httpx tenacity pybreaker pyjwt redis
fi

# Create demo user
echo -e "${YELLOW}👤 Creating demo user...${NC}"
if python3 create_demo_user.py; then
    echo -e "${GREEN}✅ Demo user created${NC}"
else
    echo -e "${RED}❌ Failed to create demo user${NC}"
    exit 1
fi

# Start the provisioning service
echo -e "${YELLOW}🎯 Starting provisioning service...${NC}"
echo -e "${BLUE}💡 The service will start in the background. Check logs with:${NC}"
echo "   tail -f services/provisioning/logs/provisioning.log"
echo ""

# Create logs directory
mkdir -p services/provisioning/logs

# Start service in background
nohup python3 services/provisioning/main.py > services/provisioning/logs/provisioning.log 2>&1 &
SERVICE_PID=$!

echo -e "${GREEN}✅ Provisioning service started (PID: $SERVICE_PID)${NC}"

# Wait for service to be ready
echo -e "${YELLOW}⏳ Waiting for service to be ready...${NC}"
sleep 5

# Test if service is responding
if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Service is responding${NC}"
else
    echo -e "${RED}❌ Service is not responding. Check logs:${NC}"
    echo "   tail -f services/provisioning/logs/provisioning.log"
    exit 1
fi

# Run curl tests
echo -e "${YELLOW}🧪 Running curl tests...${NC}"
if ./test_provisioning_curl.sh; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
else
    echo -e "${RED}❌ Some tests failed${NC}"
fi

echo ""
echo -e "${YELLOW}📋 Demo Environment Setup Complete${NC}"
echo "=========================================="
echo -e "${GREEN}✅ Provisioning service is running on http://localhost:8000${NC}"
echo -e "${GREEN}✅ Demo API key: zq_demo_key_for_testing${NC}"
echo -e "${GREEN}✅ Service PID: $SERVICE_PID${NC}"
echo ""
echo -e "${BLUE}🔧 Useful commands:${NC}"
echo "   # Stop the service:"
echo "   kill $SERVICE_PID"
echo ""
echo "   # View logs:"
echo "   tail -f services/provisioning/logs/provisioning.log"
echo ""
echo "   # Run tests again:"
echo "   ./test_provisioning_curl.sh"
echo ""
echo "   # Test individual endpoints:"
echo "   curl -H 'X-API-Key: zq_demo_key_for_testing' http://localhost:8000/provisioning/tenants"
echo ""
echo -e "${BLUE}📚 API Documentation:${NC}"
echo "   http://localhost:8000/docs"
echo "   http://localhost:8000/redoc"
echo ""
echo -e "${BLUE}📊 Metrics:${NC}"
echo "   http://localhost:8000/metrics"
echo ""
echo -e "${BLUE}❤️  Health Check:${NC}"
echo "   http://localhost:8000/health"

