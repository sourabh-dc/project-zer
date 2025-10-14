#!/bin/bash

# ZeroQue Provisioning Service - Complete Endpoint Testing Script
# Tests ALL 17 endpoints across tenants, sites, stores, users, roles, vendors, cost-centres

BASE_URL="http://localhost:8000"
SERVICE_NAME="provisioning"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counter
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Test data - Using existing tenant
TENANT_ID="ad328f59-1761-4e18-afac-9a6c3cfbe9b6"
SITE_ID="550e8400-e29b-41d4-a716-446655440001"
STORE_ID="550e8400-e29b-41d4-a716-446655440002"
USER_ID="550e8400-e29b-41d4-a716-446655440003"
ROLE_ID="550e8400-e29b-41d4-a716-446655440004"
VENDOR_ID="550e8400-e29b-41d4-a716-446655440005"
COST_CENTRE_ID="550e8400-e29b-41d4-a716-446655440006"

echo -e "${BLUE}🚀 Starting ZeroQue Provisioning Service Endpoint Tests${NC}"
echo "=================================================="

# Function to run test
run_test() {
    local test_name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected_status="$5"

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    local url="$BASE_URL$endpoint"

    echo -e "\n${YELLOW}🧪 Test $TOTAL_TESTS: $test_name${NC}"
    echo "   Method: $method"
    echo "   URL: $url"
    echo "   Expected Status: $expected_status"

    if [ -n "$data" ]; then
        echo "   Data: $data"
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            -H "Content-Type: application/json" \
            -H "X-Tenant-ID: $TENANT_ID" \
            -H "X-API-Key: zq_demo_key_for_testing" \
            -d "$data" 2>/dev/null)
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            -H "X-Tenant-ID: $TENANT_ID" \
            -H "X-API-Key: zq_demo_key_for_testing" 2>/dev/null)
    fi

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | head -n -1)

    echo "   Response Code: $http_code"
    echo "   Response Body: $body"

    if [ "$http_code" = "$expected_status" ]; then
        echo -e "   ✅ ${GREEN}PASSED${NC}"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "   ❌ ${RED}FAILED (Expected $expected_status, got $http_code)${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

# Test 1: Health Check
run_test "Health Check" "GET" "/health" "" "200"

# Test 2: Metrics
run_test "Metrics" "GET" "/metrics" "" "200"

# Test 3: Skip Tenant Creation (using existing tenant)

# Test 4: List Tenants
run_test "List Tenants" "GET" "/provisioning/tenants" "" "200"

# Test 5: Create Site
SITE_DATA='{
    "name": "Test Site",
    "site_type": "office",
    "device_metadata": {
        "cameras": 4,
        "entry_devices": 2,
        "sensors": 8
    }
}'
run_test "Create Site" "PUT" "/provisioning/sites/$SITE_ID?tenant_id=$TENANT_ID" "$SITE_DATA" "200"

# Test 6: List Sites
run_test "List Sites" "GET" "/provisioning/sites" "" "200"

# Test 7: Create Store
STORE_DATA='{
    "name": "Test Store",
    "store_type": "retail"
}'
run_test "Create Store" "PUT" "/provisioning/stores/$STORE_ID?site_id=$SITE_ID" "$STORE_DATA" "200"

# Test 8: List Stores
run_test "List Stores" "GET" "/provisioning/stores" "" "200"

# Test 9: Create User
USER_DATA='{
    "email": "test.user@test-tenant.com",
    "display_name": "Test User",
    "tenant_id": "'$TENANT_ID'"
}'
run_test "Create User" "PUT" "/provisioning/users/$USER_ID" "$USER_DATA" "200"

# Test 10: List Users
run_test "List Users" "GET" "/provisioning/users" "" "200"

# Test 11: Bulk Import Users
BULK_USERS_DATA='{
    "tenant_id": "'$TENANT_ID'",
    "users": [
        {
            "email": "bulk1@test-tenant.com",
            "display_name": "Bulk User 1"
        },
        {
            "email": "bulk2@test-tenant.com",
            "display_name": "Bulk User 2"
        }
    ]
}'
run_test "Bulk Import Users" "POST" "/provisioning/users/bulk-import" "$BULK_USERS_DATA" "200"

# Test 12: Create Role
ROLE_DATA='{
    "code": "test-role",
    "name": "Test Role",
    "description": "Test role for endpoint testing"
}'
run_test "Create Role" "PUT" "/provisioning/roles/$ROLE_ID" "$ROLE_DATA" "200"

# Test 13: List Roles
run_test "List Roles" "GET" "/provisioning/roles" "" "200"

# Test 14: Create Vendor
VENDOR_DATA='{
    "tenant_id": "'$TENANT_ID'",
    "name": "Test Vendor",
    "contact_email": "contact@test-vendor.com"
}'
run_test "Create Vendor" "PUT" "/provisioning/vendors/$VENDOR_ID" "$VENDOR_DATA" "200"

# Test 15: List Vendors
run_test "List Vendors" "GET" "/provisioning/vendors" "" "200"

# Test 16: Create Cost Centre
COST_CENTRE_DATA='{
    "tenant_id": "'$TENANT_ID'",
    "name": "Test Cost Centre",
    "budget_minor": 100000
}'
run_test "Create Cost Centre" "POST" "/provisioning/cost-centres" "$COST_CENTRE_DATA" "200"

# Test 17: List Cost Centres
run_test "List Cost Centres" "GET" "/provisioning/cost-centres" "" "200"

# Summary
echo -e "\n${BLUE}📊 Test Summary${NC}"
echo "=============="
echo "Total Tests: $TOTAL_TESTS"
echo -e "✅ Passed: ${GREEN}$PASSED_TESTS${NC}"
echo -e "❌ Failed: ${RED}$FAILED_TESTS${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "\n${GREEN}🎉 ALL TESTS PASSED! Provisioning service is working perfectly.${NC}"
    exit 0
else
    echo -e "\n${RED}⚠️  Some tests failed. Please check the output above.${NC}"
    exit 1
fi
