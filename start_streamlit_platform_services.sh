#!/bin/bash
# Start all required services for streamlit_zeroque_platform

set -e

echo "🚀 Starting ZeroQue Platform Services for Streamlit Demo"

# Kill existing services
pkill -9 -f "python.*services/provisioning/main.py" 2>/dev/null || true
pkill -9 -f "python.*services/subscriptions/main.py" 2>/dev/null || true
pkill -9 -f "python.*services/entitlements/main.py" 2>/dev/null || true
pkill -9 -f "python.*services/catalog/main.py" 2>/dev/null || true
pkill -9 -f "python.*services/pricing/main.py" 2>/dev/null || true

sleep 3

# Activate venv
source venv/bin/activate

# Set environment
export ALLOW_DEMO=true
export DATABASE_URL="postgresql://zeroque:zeroque@localhost:5432/zeroque_dev"
export RABBITMQ_URL="amqp://guest:guest@localhost:5672//"
export REDIS_URL="redis://localhost:6379/0"

# Start Provisioning (port 8000)
echo "Starting Provisioning Service on port 8000..."
cd services/provisioning
export SERVICE_PORT=8000
nohup python main.py > /tmp/prov_platform.log 2>&1 &
cd ../..

# Start Subscriptions (port 8212)
echo "Starting Subscriptions Service on port 8212..."
cd services/subscriptions
nohup python main.py > /tmp/subs_platform.log 2>&1 &
cd ../..

# Start Entitlements (port 8003)
echo "Starting Entitlements Service on port 8003..."
cd services/entitlements
export SERVICE_PORT=8003
nohup python main.py > /tmp/ent_platform.log 2>&1 &
cd ../..

# Start Catalog (port 8005)
echo "Starting Catalog Service on port 8005..."
cd services/catalog
export SERVICE_PORT=8005
nohup python main.py > /tmp/cat_platform.log 2>&1 &
cd ../..

# Start Pricing (port 8007)
echo "Starting Pricing Service on port 8007..."
cd services/pricing
export SERVICE_PORT=8007
nohup python main.py > /tmp/price_platform.log 2>&1 &
cd ../..

echo "⏳ Waiting for services to start..."
sleep 10

echo "✅ Services started! Checking health..."
echo ""

for port in 8000 8212 8003 8005 8007; do
    echo "Port $port:"
    curl -s -m 2 http://localhost:$port/health 2>&1 | head -1 || echo "  Not responding"
done

echo ""
echo "🎯 Streamlit ZeroQue Platform is ready at: http://localhost:8510"
echo "📊 Service logs are in /tmp/*_platform.log"

