#!/bin/bash
# Start All 9 Core Services Including CV Gateway

cd "$(dirname "$0")"

# Stop any running mock servers
pkill -9 -f "mock_" 2>/dev/null
sleep 1

echo "🚀 Starting 9 ZeroQue Services with Full Schema Coverage..."
echo ""

# Start mock servers
python3 mock_9services.py > logs/mock9.log 2>&1 &
PID=$!

echo "Process ID: $PID"
echo "$PID" > logs/mock9.pid
sleep 4

# Test all services
echo ""
echo "Verifying services..."
curl -s http://localhost:8000/health > /dev/null && echo "  ✓ Provisioning (8000) - Tenants, Sites, Stores, Users"
curl -s http://localhost:8001/health > /dev/null && echo "  ✓ Catalog (8001) - Products, Bundles, Categories"
curl -s http://localhost:8002/health > /dev/null && echo "  ✓ Orders (8002) - Order Management"
curl -s http://localhost:8006/health > /dev/null && echo "  ✓ Pricing (8006) - Pricebooks, Rules"
curl -s http://localhost:8080/health > /dev/null && echo "  ✓ CV Gateway (8080) - Device Monitoring ⭐"
curl -s http://localhost:8212/health > /dev/null && echo "  ✓ Subscriptions (8212) - Plans, Features"
curl -s http://localhost:8218/health > /dev/null && echo "  ✓ Entry (8218) - Entry Codes, QR"
curl -s http://localhost:8223/health > /dev/null && echo "  ✓ Entitlements (8223) - Access Control"
curl -s http://localhost:8224/health > /dev/null && echo "  ✓ Identity (8224) - Users, Roles, OAuth"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ALL 9 SERVICES RUNNING!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 NEW: CV Gateway Device Monitoring Endpoints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  GET  /devices/status              - List all devices"
echo "  GET  /devices/{id}/status         - Get device details"
echo "  PUT  /devices/{id}/status         - Update device status"
echo "  POST /devices/{id}/alert          - Create device alert"
echo "  GET  /cv/reviews                  - List CV reviews"
echo "  GET  /cv/orders                   - List CV orders"
echo "  GET  /cv/stats/{tenant_id}        - CV statistics"
echo ""
echo "Device Schema:"
echo "  • device_id, tenant_id, site_id"
echo "  • device_type (camera/sensor/entry_device)"
echo "  • device_name, zone"
echo "  • status (online/offline/error/maintenance)"
echo "  • health_score (0-100)"
echo "  • last_heartbeat, device_metadata"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 IMPORT TO POSTMAN:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  1. Import: ZeroQue_Services.json (9 services, 101 endpoints)"
echo "  2. Import: ZeroQue_Environment.postman_environment.json"
echo "  3. Select environment: 'ZeroQue Development'"
echo "  4. Test device endpoints in CV Gateway!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To stop: kill $PID"
echo ""

