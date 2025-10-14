#!/bin/bash
# ZeroQue - Phase 1 & Phase 2 Feature Testing Script
# Tests all implemented features from Identity & Access and Sites & Hardware

set -e  # Exit on error

# Configuration
API_KEY="zq_demo_key_for_testing"
BASE_URL="http://localhost"
PROVISIONING_PORT="8000"
IDENTITY_PORT="8003"
CV_CONNECTOR_PORT="8216"
CV_GATEWAY_PORT="8215"

PROVISIONING_URL="${BASE_URL}:${PROVISIONING_PORT}"
IDENTITY_URL="${BASE_URL}:${IDENTITY_PORT}"
CV_CONNECTOR_URL="${BASE_URL}:${CV_CONNECTOR_PORT}"
CV_GATEWAY_URL="${BASE_URL}:${CV_GATEWAY_PORT}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
print_test() {
    echo -e "\n${YELLOW}=== TEST: $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
    ((TESTS_PASSED++))
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
    ((TESTS_FAILED++))
}

check_response() {
    local response="$1"
    local expected_field="$2"
    
    if echo "$response" | grep -q "$expected_field"; then
        return 0
    else
        return 1
    fi
}

# ===============================================
# PHASE 1: IDENTITY & ACCESS TESTS
# ===============================================

echo -e "\n${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   PHASE 1: IDENTITY & ACCESS FEATURE TESTS   ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"

# Test 1.1: Create Tenant
print_test "1.1 - Create Tenant"
TENANT_RESPONSE=$(curl -s -X POST "$PROVISIONING_URL/provisioning/tenants" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Corp Phase1",
    "tenant_type": "enterprise"
  }')

if check_response "$TENANT_RESPONSE" "tenant_id"; then
    TENANT_ID=$(echo "$TENANT_RESPONSE" | grep -o '"tenant_id":"[^"]*"' | cut -d'"' -f4)
    print_success "Tenant created: $TENANT_ID"
else
    print_error "Failed to create tenant"
    echo "Response: $TENANT_RESPONSE"
fi

# Test 1.2: Bulk User Import (Self-Service Provisioning)
print_test "1.2 - Bulk User Import (Pro/Ent Feature)"
BULK_USER_RESPONSE=$(curl -s -X POST "$PROVISIONING_URL/provisioning/users/bulk-import" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "users": [
      {"email": "user1@testcorp.com", "display_name": "Alice Johnson", "permissions": ["catalog.view"]},
      {"email": "user2@testcorp.com", "display_name": "Bob Smith", "permissions": ["orders.create"]},
      {"email": "user3@testcorp.com", "display_name": "Charlie Brown"}
    ],
    "auto_generate_api_keys": true,
    "notify_users": false
  }')

if check_response "$BULK_USER_RESPONSE" "success_count"; then
    SUCCESS_COUNT=$(echo "$BULK_USER_RESPONSE" | grep -o '"success_count":[0-9]*' | cut -d':' -f2)
    print_success "Bulk import completed: $SUCCESS_COUNT users created"
    
    # Extract first user ID and API key for later tests
    USER1_ID=$(echo "$BULK_USER_RESPONSE" | grep -o '"user_id":"[^"]*"' | head -1 | cut -d'"' -f4)
    USER1_API_KEY=$(echo "$BULK_USER_RESPONSE" | grep -o '"api_key":"[^"]*"' | head -1 | cut -d'"' -f4)
else
    print_error "Bulk user import failed"
    echo "Response: $BULK_USER_RESPONSE"
fi

# Test 1.3: OAuth Provider Configuration (SSO)
print_test "1.3 - Create OAuth Provider (SSO - Pro/Ent Feature)"
OAUTH_PROVIDER_RESPONSE=$(curl -s -X POST "$IDENTITY_URL/identity/v4/oauth/providers" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "provider_type": "azure_ad",
    "provider_name": "TestCorp Azure AD",
    "client_id": "test-azure-client-id",
    "client_secret": "test-azure-client-secret",
    "tenant_domain": "testcorp.onmicrosoft.com",
    "scopes": ["openid", "profile", "email"]
  }')

if check_response "$OAUTH_PROVIDER_RESPONSE" "provider_id"; then
    OAUTH_PROVIDER_ID=$(echo "$OAUTH_PROVIDER_RESPONSE" | grep -o '"provider_id":"[^"]*"' | cut -d'"' -f4)
    print_success "OAuth provider created: $OAUTH_PROVIDER_ID"
else
    print_error "OAuth provider creation failed"
    echo "Response: $OAUTH_PROVIDER_RESPONSE"
fi

# Test 1.4: List OAuth Providers
print_test "1.4 - List OAuth Providers"
OAUTH_LIST_RESPONSE=$(curl -s -X GET "$IDENTITY_URL/identity/v4/oauth/providers?tenant_id=$TENANT_ID" \
  -H "x-api-key: $API_KEY")

if check_response "$OAUTH_LIST_RESPONSE" "providers"; then
    print_success "OAuth providers listed successfully"
else
    print_error "OAuth providers list failed"
fi

# Test 1.5: Initiate OAuth Flow
print_test "1.5 - Initiate OAuth Flow"
OAUTH_INITIATE_RESPONSE=$(curl -s -X POST "$IDENTITY_URL/identity/v4/oauth/initiate" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "provider_id": "'$OAUTH_PROVIDER_ID'",
    "redirect_uri": "https://testcorp.zeroque.com/auth/callback"
  }')

if check_response "$OAUTH_INITIATE_RESPONSE" "authorization_url"; then
    OAuth_STATE=$(echo "$OAUTH_INITIATE_RESPONSE" | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
    print_success "OAuth flow initiated, state: $OAUTH_STATE"
else
    print_error "OAuth initiate failed"
    echo "Response: $OAUTH_INITIATE_RESPONSE"
fi

# Test 1.6: QR Entry (existing feature, verify it works)
print_test "1.6 - QR Code Entry"
# First create a site and store for the entry test
SITE_RESPONSE=$(curl -s -X PUT "$PROVISIONING_URL/provisioning/sites/$(uuidgen)" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Flagship Store",
    "site_type": "retail",
    "geo": {"lat": 51.5074, "lon": -0.1278}
  }' \
  --get --data-urlencode "tenant_id=$TENANT_ID")

SITE_ID=$(echo "$SITE_RESPONSE" | grep -o '"site_id":"[^"]*"' | cut -d'"' -f4)

STORE_RESPONSE=$(curl -s -X PUT "$PROVISIONING_URL/provisioning/stores/$(uuidgen)" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Main Floor",
    "store_type": "retail"
  }' \
  --get --data-urlencode "tenant_id=$TENANT_ID&site_id=$SITE_ID")

STORE_ID=$(echo "$STORE_RESPONSE" | grep -o '"store_id":"[^"]*"' | cut -d'"' -f4)

QR_ENTRY_RESPONSE=$(curl -s -X POST "$CV_CONNECTOR_URL/cv/entry/qr" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "user_id": "'$USER1_ID'",
    "group_size": 1,
    "displayable": true
  }')

if check_response "$QR_ENTRY_RESPONSE" "qr_image"; then
    print_success "QR entry code generated successfully"
else
    print_error "QR entry failed"
    echo "Response: $QR_ENTRY_RESPONSE"
fi

# Test 1.7: Card Entry (NEW - Phase 1.3)
print_test "1.7 - Card-Based Entry (RFID)"
CARD_ENTRY_RESPONSE=$(curl -s -X POST "$CV_CONNECTOR_URL/cv/entry/card" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "user_id": "'$USER1_ID'",
    "store_id": "'$STORE_ID'",
    "card_number": "1234567890",
    "card_type": "rfid",
    "device_id": "entry-device-01"
  }')

if check_response "$CARD_ENTRY_RESPONSE" "entry_method"; then
    print_success "Card entry created successfully"
else
    print_error "Card entry failed"
    echo "Response: $CARD_ENTRY_RESPONSE"
fi

# Test 1.8: Biometric Entry (NEW - Phase 1.3)
print_test "1.8 - Biometric Entry (Face Recognition)"
BIOMETRIC_ENTRY_RESPONSE=$(curl -s -X POST "$CV_CONNECTOR_URL/cv/entry/biometric" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "user_id": "'$USER1_ID'",
    "store_id": "'$STORE_ID'",
    "biometric_type": "face",
    "biometric_data": "base64_encoded_face_template_hash",
    "confidence_score": 0.95,
    "device_id": "biometric-scanner-01"
  }')

if check_response "$BIOMETRIC_ENTRY_RESPONSE" "biometric_type"; then
    print_success "Biometric entry created successfully"
else
    print_error "Biometric entry failed"
    echo "Response: $BIOMETRIC_ENTRY_RESPONSE"
fi

# ===============================================
# PHASE 2: SITES & HARDWARE TESTS
# ===============================================

echo -e "\n${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   PHASE 2: SITES & HARDWARE FEATURE TESTS    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"

# Test 2.1: Site Registry with Device Metadata
print_test "2.1 - Create Site with Device Metadata"
SITE_WITH_DEVICES_ID=$(uuidgen)
SITE_WITH_DEVICES_RESPONSE=$(curl -s -X PUT "$PROVISIONING_URL/provisioning/sites/$SITE_WITH_DEVICES_ID" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tech Hub Store",
    "site_type": "retail",
    "geo": {"lat": 40.7128, "lon": -74.0060},
    "device_metadata": {
      "cameras": [
        {"id": "cam-01", "type": "overhead", "zone": "checkout", "resolution": "4K"},
        {"id": "cam-02", "type": "entrance", "zone": "entry", "resolution": "1080p"}
      ],
      "sensors": [
        {"id": "sensor-01", "type": "motion", "zone": "entry"},
        {"id": "sensor-02", "type": "temperature", "zone": "storage"}
      ],
      "entry_devices": [
        {"id": "entry-01", "type": "rfid_reader"},
        {"id": "entry-02", "type": "biometric_scanner"}
      ]
    }
  }' \
  --get --data-urlencode "tenant_id=$TENANT_ID")

if check_response "$SITE_WITH_DEVICES_RESPONSE" "site_id"; then
    print_success "Site with device metadata created"
else
    print_error "Site with devices creation failed"
    echo "Response: $SITE_WITH_DEVICES_RESPONSE"
fi

# Wait for SITE_CREATED event to be processed by CV Gateway
echo "Waiting 3 seconds for SITE_CREATED event processing..."
sleep 3

# Test 2.2: List Devices (Device Monitoring)
print_test "2.2 - List All Devices for Tenant"
DEVICES_LIST_RESPONSE=$(curl -s -X GET "$CV_GATEWAY_URL/devices/status?tenant_id=$TENANT_ID" \
  -H "x-api-key: $API_KEY")

if check_response "$DEVICES_LIST_RESPONSE" "total_devices"; then
    DEVICE_COUNT=$(echo "$DEVICES_LIST_RESPONSE" | grep -o '"total_devices":[0-9]*' | cut -d':' -f2)
    print_success "Devices listed: $DEVICE_COUNT devices found"
    
    # Extract first device ID for status tests
    DEVICE_ID=$(echo "$DEVICES_LIST_RESPONSE" | grep -o '"device_id":"[^"]*"' | head -1 | cut -d'"' -f4)
else
    print_error "Device list failed"
    echo "Response: $DEVICES_LIST_RESPONSE"
fi

# Test 2.3: Get Single Device Status
if [ ! -z "$DEVICE_ID" ]; then
    print_test "2.3 - Get Device Status"
    DEVICE_STATUS_RESPONSE=$(curl -s -X GET "$CV_GATEWAY_URL/devices/$DEVICE_ID/status?tenant_id=$TENANT_ID" \
      -H "x-api-key: $API_KEY")
    
    if check_response "$DEVICE_STATUS_RESPONSE" "device_id"; then
        print_success "Device status retrieved: $DEVICE_ID"
    else
        print_error "Device status retrieval failed"
        echo "Response: $DEVICE_STATUS_RESPONSE"
    fi
else
    print_error "No device ID available for status test"
fi

# Test 2.4: Update Device Status
if [ ! -z "$DEVICE_ID" ]; then
    print_test "2.4 - Update Device Status"
    DEVICE_UPDATE_RESPONSE=$(curl -s -X PUT "$CV_GATEWAY_URL/devices/$DEVICE_ID/status?tenant_id=$TENANT_ID" \
      -H "x-api-key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "status": "online",
        "health_score": 95,
        "details": {"temperature": 22.5, "uptime_hours": 168}
      }')
    
    if check_response "$DEVICE_UPDATE_RESPONSE" "success"; then
        print_success "Device status updated successfully"
    else
        print_error "Device status update failed"
        echo "Response: $DEVICE_UPDATE_RESPONSE"
    fi
else
    print_error "No device ID available for update test"
fi

# Test 2.5: Create Device Alert
if [ ! -z "$DEVICE_ID" ]; then
    print_test "2.5 - Create Device Alert"
    DEVICE_ALERT_RESPONSE=$(curl -s -X POST "$CV_GATEWAY_URL/devices/$DEVICE_ID/alert?tenant_id=$TENANT_ID" \
      -H "x-api-key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "alert_type": "low_health",
        "severity": "warning",
        "message": "Device health score below threshold (95 < 98)"
      }')
    
    if check_response "$DEVICE_ALERT_RESPONSE" "success"; then
        print_success "Device alert created successfully"
    else
        print_error "Device alert creation failed"
        echo "Response: $DEVICE_ALERT_RESPONSE"
    fi
else
    print_error "No device ID available for alert test"
fi

# Test 2.6: Filter Devices by Site
print_test "2.6 - Filter Devices by Site"
DEVICES_FILTERED_RESPONSE=$(curl -s -X GET "$CV_GATEWAY_URL/devices/status?tenant_id=$TENANT_ID&site_id=$SITE_WITH_DEVICES_ID" \
  -H "x-api-key: $API_KEY")

if check_response "$DEVICES_FILTERED_RESPONSE" "site_id"; then
    SITE_DEVICE_COUNT=$(echo "$DEVICES_FILTERED_RESPONSE" | grep -o '"total_devices":[0-9]*' | cut -d':' -f2)
    print_success "Devices filtered by site: $SITE_DEVICE_COUNT devices"
else
    print_error "Device filtering by site failed"
fi

# Test 2.7: Filter Devices by Status
print_test "2.7 - Filter Devices by Status"
DEVICES_ONLINE_RESPONSE=$(curl -s -X GET "$CV_GATEWAY_URL/devices/status?tenant_id=$TENANT_ID&status=online" \
  -H "x-api-key: $API_KEY")

if check_response "$DEVICES_ONLINE_RESPONSE" "status_filter"; then
    ONLINE_DEVICE_COUNT=$(echo "$DEVICES_ONLINE_RESPONSE" | grep -o '"total_devices":[0-9]*' | cut -d':' -f2)
    print_success "Devices filtered by status: $ONLINE_DEVICE_COUNT online devices"
else
    print_error "Device filtering by status failed"
fi

# ===============================================
# TEST SUMMARY
# ===============================================

echo -e "\n${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              TEST SUMMARY                     ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED))
echo -e "\nTotal Tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✓ ALL TESTS PASSED!${NC}"
    exit 0
else
    echo -e "\n${RED}✗ SOME TESTS FAILED${NC}"
    exit 1
fi

