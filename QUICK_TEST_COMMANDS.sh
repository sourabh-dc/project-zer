#!/bin/bash
# Quick Test Commands for ZeroQue Platform
# Run these commands to test all endpoints

echo "════════════════════════════════════════════════════════════"
echo "  ZeroQue Platform - Quick Endpoint Testing"
echo "════════════════════════════════════════════════════════════"
echo ""

# 1. Health Checks
echo "1️⃣  Testing Health Endpoints..."
echo "─────────────────────────────────────────────────────────────"
for port in 8000 8212 8003 8005 8007 8510; do
    echo "  Port $port:"
    if [ "$port" == "8510" ]; then
        curl -s http://localhost:$port/_stcore/health
    else
        curl -s http://localhost:$port/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  ✓ {d.get('service','app')} v{d.get('version','?')}\")" 2>/dev/null || echo "  ✗ Not responding"
    fi
    echo ""
done
echo ""

# 2. Test Provisioning Service
echo "2️⃣  Testing Provisioning Service (Port 8000)..."
echo "─────────────────────────────────────────────────────────────"
echo "  Creating test tenant..."
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"name":"Quick Test Tenant","tenant_type":"customer"}' \
  http://localhost:8000/provisioning/tenants | python3 -m json.tool
echo ""

# 3. Test Subscriptions Service
echo "3️⃣  Testing Subscriptions Service (Port 8212)..."
echo "─────────────────────────────────────────────────────────────"
echo "  Getting available plans..."
curl -s -H "X-API-Key: zq_demo_key_for_testing" \
  http://localhost:8212/subscriptions/v2/plans | python3 -m json.tool
echo ""

# 4. Test Catalog Service
echo "4️⃣  Testing Catalog Service (Port 8005)..."
echo "─────────────────────────────────────────────────────────────"
echo "  Getting products..."
curl -s -H "X-API-Key: zq_demo_key_for_testing" \
  "http://localhost:8005/products?tenant_id=00000000-0000-0000-0000-000000000001" | python3 -m json.tool
echo ""

# 5. Test Entitlements Service  
echo "5️⃣  Testing Entitlements Service (Port 8003)..."
echo "─────────────────────────────────────────────────────────────"
echo "  Checking entitlement..."
curl -s -H "X-API-Key: zq_demo_key_for_testing" \
  "http://localhost:8003/entitlements/v2/check/00000000-0000-0000-0000-000000000001/api_calls" | python3 -m json.tool
echo ""

# 6. Test Pricing Service
echo "6️⃣  Testing Pricing Service (Port 8007)..."
echo "─────────────────────────────────────────────────────────────"
echo "  Calculating price..."
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-API-Key: zq_demo_key_for_testing" \
  -d '{"product_id":"00000000-0000-0000-0000-000000000001","tenant_id":"00000000-0000-0000-0000-000000000001","quantity":1}' \
  http://localhost:8007/pricing/v2/calculate | python3 -m json.tool
echo ""

# Summary
echo "════════════════════════════════════════════════════════════"
echo "  Testing Complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📊 View detailed report: ENDPOINT_TEST_REPORT.md"
echo "🎯 Open Streamlit App: http://localhost:8510"
echo ""

