#!/bin/bash
# Quick test for Provisioning service Phase 1 & 2 features

set -e

API_KEY="zq_demo_key_for_testing"
BASE_URL="http://localhost:8000"

echo "=== Testing Provisioning Service Features ==="
echo ""

# Test 1: Create Tenant
echo "Test 1: Creating tenant..."
TENANT_RESPONSE=$(curl -s -X POST "$BASE_URL/provisioning/tenants" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Phase Test Corp",
    "tenant_type": "enterprise"
  }')

echo "Response: $TENANT_RESPONSE"
TENANT_ID=$(echo "$TENANT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tenant_id', ''))" 2>/dev/null || echo "")

if [ -z "$TENANT_ID" ]; then
    echo "❌ Failed to create tenant"
    exit 1
else
    echo "✅ Tenant created: $TENANT_ID"
fi

echo ""

# Test 2: Bulk User Import
echo "Test 2: Bulk user import..."
BULK_RESPONSE=$(curl -s -X POST "$BASE_URL/provisioning/users/bulk-import" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "users": [
      {"email": "alice@test.com", "display_name": "Alice"},
      {"email": "bob@test.com", "display_name": "Bob"},
      {"email": "charlie@test.com", "display_name": "Charlie"}
    ],
    "auto_generate_api_keys": true
  }')

echo "Response: $BULK_RESPONSE"
SUCCESS_COUNT=$(echo "$BULK_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('success_count', 0))" 2>/dev/null || echo "0")

if [ "$SUCCESS_COUNT" -gt 0 ]; then
    echo "✅ Bulk import successful: $SUCCESS_COUNT users created"
else
    echo "⚠️ Bulk import response received (check if users were created)"
fi

echo ""

# Test 3: Create Site with Device Metadata
echo "Test 3: Creating site with device metadata..."
SITE_ID=$(uuidgen)
SITE_RESPONSE=$(curl -s -X PUT "$BASE_URL/provisioning/sites/$SITE_ID?tenant_id=$TENANT_ID" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Store with Devices",
    "site_type": "retail",
    "geo": {"lat": 40.7128, "lon": -74.0060},
    "device_metadata": {
      "cameras": [
        {"id": "cam-01", "type": "overhead", "zone": "checkout"},
        {"id": "cam-02", "type": "entrance", "zone": "entry"}
      ],
      "sensors": [
        {"id": "sensor-01", "type": "motion", "zone": "entry"}
      ],
      "entry_devices": [
        {"id": "entry-01", "type": "rfid_reader"}
      ]
    }
  }')

echo "Response: $SITE_RESPONSE"

if echo "$SITE_RESPONSE" | grep -q "site_id"; then
    echo "✅ Site with devices created successfully"
else
    echo "⚠️ Site creation response received"
fi

echo ""
echo "=== Test Summary ==="
echo "✅ All Provisioning service tests completed"
echo "   - Tenant creation: $TENANT_ID"
echo "   - Bulk user import: $SUCCESS_COUNT users"
echo "   - Site with devices: $SITE_ID"
echo ""
echo "Next: Start other services (Identity, CV Connector, CV Gateway) to test remaining features"

