#!/bin/bash

# ZeroQue Application Endpoint Test Script
# This script tests all major API endpoints

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "🧪 ZeroQue Application Endpoint Testing"
echo "======================================="

# Function to test an endpoint
test_endpoint() {
    local method=$1
    local url=$2
    local data=$3
    local expected_status=$4
    local description=$5
    
    print_status "Testing: $description"
    
    if [ -n "$data" ]; then
        response=$(curl -s -w "%{http_code}" -X "$method" "$url" \
            -H "Content-Type: application/json" \
            -d "$data")
    else
        response=$(curl -s -w "%{http_code}" -X "$method" "$url")
    fi
    
    http_code="${response: -3}"
    body="${response%???}"
    
    if [ "$http_code" = "$expected_status" ]; then
        print_success "$description: ✅ $http_code"
        return 0
    else
        print_error "$description: ❌ Expected $expected_status, got $http_code"
        echo "Response: $body"
        return 1
    fi
}

# Test counters
passed=0
failed=0

# Provisioning Service Tests
echo ""
print_status "🏢 Testing Provisioning Service..."

test_endpoint "GET" "http://localhost:8200/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8200/tenants" '{"name": "Test Tenant", "domain": "test.com"}' "200" "Create tenant"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8200/sites" '{"tenant_id": "test-tenant", "name": "Test Site", "domain": "test.com"}' "200" "Create site"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8200/stores" '{"tenant_id": "test-tenant", "site_id": "test-site", "name": "Test Store", "address": "123 Main St"}' "200" "Create store"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Catalog Service Tests
echo ""
print_status "📦 Testing Catalog Service..."

test_endpoint "GET" "http://localhost:8201/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8201/products" '{"sku": "TEST-001", "name": "Test Product", "description": "A test product"}' "200" "Create product"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8201/prices" '{"sku": "TEST-001", "currency": "GBP", "unit_minor": 9.99, "active": true}' "200" "Set price"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Pricing Service Tests
echo ""
print_status "💰 Testing Pricing Service..."

test_endpoint "GET" "http://localhost:8209/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8209/pricing/calculate" '{"store_id": "test-store", "sku": "TEST-001", "user_id": "test-user", "currency": "GBP", "quantity": 1}' "200" "Calculate price"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Orders Service Tests
echo ""
print_status "🛒 Testing Orders Service..."

test_endpoint "GET" "http://localhost:8208/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8208/orders" '{"tenant_id": "test-tenant", "site_id": "test-site", "store_id": "test-store", "shopper_id": "test-user", "items": [{"sku": "TEST-001", "qty": 2}], "currency": "GBP"}' "200" "Create order"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "GET" "http://localhost:8208/orders?tenant_id=test-tenant" "" "200" "List orders"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Identity Service Tests
echo ""
print_status "👤 Testing Identity Service..."

test_endpoint "GET" "http://localhost:8203/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "POST" "http://localhost:8203/users" '{"user_id": "test-user", "display_name": "Test User", "email": "test@example.com"}' "200" "Create user"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Entry Service Tests
echo ""
print_status "🚪 Testing Entry Service..."

test_endpoint "GET" "http://localhost:8202/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Billing Service Tests
echo ""
print_status "💳 Testing Billing Service..."

test_endpoint "GET" "http://localhost:8210/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Subscriptions Service Tests
echo ""
print_status "📋 Testing Subscriptions Service..."

test_endpoint "GET" "http://localhost:8220/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "GET" "http://localhost:8220/plans" "" "200" "List subscription plans"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Usage Service Tests
echo ""
print_status "📊 Testing Usage Service..."

test_endpoint "GET" "http://localhost:8221/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

test_endpoint "GET" "http://localhost:8221/usage/daily?tenant_id=test-tenant&meter=orders" "" "200" "Get usage data"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# CV Connector Tests
echo ""
print_status "🤖 Testing CV Connector Service..."

test_endpoint "GET" "http://localhost:8213/admin/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# CV Gateway Tests
echo ""
print_status "🌐 Testing CV Gateway Service..."

test_endpoint "GET" "http://localhost:8214/health" "" "200" "Health check"
if [ $? -eq 0 ]; then ((passed++)); else ((failed++)); fi

# Test Summary
echo ""
echo "📊 Test Summary:"
echo "================"
echo "Passed: $passed"
echo "Failed: $failed"
echo "Total: $((passed + failed))"

if [ $failed -eq 0 ]; then
    print_success "🎉 All endpoint tests passed!"
    exit 0
else
    print_warning "⚠️  Some tests failed. Check the output above for details."
    exit 1
fi
