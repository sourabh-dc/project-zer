#!/bin/bash

# Script to restart services and test database schema fixes

echo "🔧 Restarting services to pick up database schema fixes..."

# Kill any existing services
echo "Stopping existing services..."
pkill -f "uvicorn.*provisioning" || true
pkill -f "uvicorn.*catalog" || true
pkill -f "uvicorn.*pricing" || true
pkill -f "uvicorn.*orders" || true

sleep 2

# Start services in background
echo "Starting services..."

# Start provisioning service
echo "Starting provisioning service..."
cd /Users/sourabhagrawal/Desktop/Consumables/completed\ codes/zeroque-sprint15-working\ copy
source .venv/bin/activate
uvicorn services.provisioning.main:app --port 8201 --host 0.0.0.0 &
PROVISIONING_PID=$!

sleep 3

# Start catalog service
echo "Starting catalog service..."
uvicorn services.catalog.main:app --port 8202 --host 0.0.0.0 &
CATALOG_PID=$!

sleep 3

# Start orders service
echo "Starting orders service..."
uvicorn services.orders.main:app --port 8203 --host 0.0.0.0 &
ORDERS_PID=$!

sleep 3

# Start pricing service
echo "Starting pricing service..."
uvicorn services.pricing.main:app --port 8209 --host 0.0.0.0 &
PRICING_PID=$!

sleep 5

echo "✅ All services started. PIDs:"
echo "  Provisioning: $PROVISIONING_PID"
echo "  Catalog: $CATALOG_PID"
echo "  Orders: $ORDERS_PID"
echo "  Pricing: $PRICING_PID"

# Test services
echo ""
echo "🧪 Testing services..."

# Test provisioning
echo "Testing provisioning service..."
curl -s "http://localhost:8201/health" | jq .status || echo "❌ Provisioning service not responding"

# Test catalog
echo "Testing catalog service..."
curl -s "http://localhost:8202/health" | jq .status || echo "❌ Catalog service not responding"

# Test orders
echo "Testing orders service..."
curl -s "http://localhost:8203/health" | jq .status || echo "❌ Orders service not responding"

# Test pricing
echo "Testing pricing service..."
curl -s "http://localhost:8209/health" | jq .status || echo "❌ Pricing service not responding"

# Test pricing price resolution (the main issue we fixed)
echo ""
echo "🎯 Testing pricing price resolution..."
curl -s -X POST "http://localhost:8209/pricing/v2/resolve" \
  -H "Content-Type: application/json" \
  -d '{"store_id":"550e8400-e29b-41d4-a716-446655440001","offer_id":"550e8400-e29b-41d4-a716-446655440002","user_id":"550e8400-e29b-41d4-a716-446655440003","quantity":1,"currency":"GBP"}' | jq . || echo "❌ Price resolution failed"

echo ""
echo "✅ Service restart and testing complete!"
echo "Services are running in the background."
echo "To stop them, run: kill $PROVISIONING_PID $CATALOG_PID $ORDERS_PID $PRICING_PID"
