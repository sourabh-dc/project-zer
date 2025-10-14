#!/bin/bash
# Start all services required for Phase 1 & 2 features testing

echo "Starting ZeroQue Phase 1 & 2 Services..."

# Kill any existing services on these ports
echo "Stopping any existing services..."
lsof -ti:8003 | xargs kill -9 2>/dev/null || true
lsof -ti:8216 | xargs kill -9 2>/dev/null || true
lsof -ti:8215 | xargs kill -9 2>/dev/null || true
lsof -ti:8503 | xargs kill -9 2>/dev/null || true

sleep 2

# Change to project directory
cd "/Users/sourabhagrawal/Desktop/Consumables/completed codes/zeroque-sprint15-working copy"

# Set PROMETHEUS_MULTIPROC_DIR to avoid duplicate metrics
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
rm -rf $PROMETHEUS_MULTIPROC_DIR
mkdir -p $PROMETHEUS_MULTIPROC_DIR

echo "Starting Identity service on port 8003..."
SERVICE_PORT=8003 ./venv/bin/python services/identity/main.py > /tmp/identity.log 2>&1 &
IDENTITY_PID=$!

echo "Starting CV Connector service on port 8216..."
SERVICE_PORT=8216 ./venv/bin/python services/cv_connector/main.py > /tmp/cv_connector.log 2>&1 &
CV_CONNECTOR_PID=$!

echo "Starting CV Gateway service on port 8215..."
SERVICE_PORT=8215 ./venv/bin/python services/cv_gateway/main.py > /tmp/cv_gateway.log 2>&1 &
CV_GATEWAY_PID=$!

# Wait for services to start
echo "Waiting for services to start..."
sleep 8

# Check service health
echo ""
echo "=== Service Health Check ==="

check_service() {
    local name=$1
    local port=$2
    local response=$(curl -s http://localhost:$port/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "[OK] $name (port $port): $response"
    else
        echo "[FAIL] $name (port $port): Not responding"
    fi
}

check_service "Provisioning" 8000
check_service "Identity" 8003
check_service "CV Connector" 8216
check_service "CV Gateway" 8215

echo ""
echo "=== Starting Streamlit Dashboard ==="
./venv/bin/streamlit run demo/streamlit_phase1_phase2_features.py \
    --server.port 8503 \
    --server.address 0.0.0.0 \
    --server.headless true \
    > /tmp/streamlit_phase12.log 2>&1 &
STREAMLIT_PID=$!

sleep 5

echo ""
echo "=== Services Started ==="
echo "Identity PID: $IDENTITY_PID"
echo "CV Connector PID: $CV_CONNECTOR_PID"
echo "CV Gateway PID: $CV_GATEWAY_PID"
echo "Streamlit PID: $STREAMLIT_PID"
echo ""
echo "Dashboard URL: http://localhost:8503"
echo ""
echo "To stop services, run: kill $IDENTITY_PID $CV_CONNECTOR_PID $CV_GATEWAY_PID $STREAMLIT_PID"

