#!/bin/bash

# Comprehensive Test Script for Unified Provisioning Service
# Tests all 50+ endpoints with JWT authentication

BASE_URL="http://localhost:8000"
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Global variables to store IDs
TENANT_ID=""
TENANT_ID_2=""
SITE_ID=""
SITE_ID_2=""
STORE_ID=""
USER_ID=""
USER_ID_2=""
ROLE_ID=""
ROLE_ID_2=""
VENDOR_ID=""
COST_CENTRE_ID=""
CATEGORY_ID=""
PRODUCT_ID=""
VARIANT_ID=""
PLAN_CODE="test-basic"
FEATURE_CODE="api-calls"
SUBSCRIPTION_ID=""
CHAIN_ID=""
APPROVAL_REQUEST_ID=""

# JWT Tokens (will be generated)
JWT_TOKEN_ADMIN=""
JWT_TOKEN_TENANT_ADMIN=""
JWT_TOKEN_USER=""

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  ZeroQue Unified Service - Comprehensive Endpoint Testing     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Generate mock JWT tokens
generate_jwt_token() {
    local user_id="$1"
    local tenant_id="$2"
    local roles="$3"
    
    python3 <<EOF
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_mock_jwt import generate_mock_token
token = generate_mock_token("$user_id", "$tenant_id", $roles.split() if "$roles" else [])
print(token)
EOF
}

# Helper function to test endpoint with JWT
test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected_status="${5:-200}"
    local jwt_token="${6:-${JWT_TOKEN_ADMIN}}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    if [ "$method" == "GET" ] || [ "$method" == "DELETE" ]; then
        response=$(curl -s -w "\n%{http_code}" -X "$method" "${BASE_URL}${endpoint}" \
            -H "Authorization: Bearer ${jwt_token}")
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "${BASE_URL}${endpoint}" \
            -H "Authorization: Bearer ${jwt_token}" \
            -H "Content-Type: application/json" \
            -d "$data")
    fi
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" -eq "$expected_status" ] || [ "$http_code" -eq 201 ]; then
        echo -e "${GREEN}✅ PASS${NC} - $name (HTTP $http_code)"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo "$body"
        echo "$body" >> /tmp/test_response.json
        return 0
    else
        echo -e "${RED}❌ FAIL${NC} - $name (HTTP $http_code, expected $expected_status)"
        echo "Response: $body"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

# Health check (no auth required)
echo -e "\n${YELLOW}━━━ HEALTH CHECK ━━━${NC}"
response=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/health")
http_code=$(echo "$response" | tail -n1)
if [ "$http_code" -eq 200 ]; then
    echo -e "${GREEN}✅ PASS${NC} - Health Check (HTTP $http_code)"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ FAIL${NC} - Health Check (HTTP $http_code)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))
echo ""

# ==================================================================================
# PROVISIONING - TENANTS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  1. PROVISIONING SERVICE - TENANTS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Generate admin JWT token first (for tenant creation - requires app_admin)
ADMIN_USER_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
ADMIN_TENANT_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
JWT_TOKEN_ADMIN=$(python3 <<EOF
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_mock_jwt import generate_mock_token
token = generate_mock_token("$ADMIN_USER_ID", "$ADMIN_TENANT_ID", ["app_admin"])
print(token)
EOF
)
echo -e "${BLUE}🔑 Generated Admin JWT Token${NC}"

echo -e "\n📝 Creating Tenant 1..."
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/v1/tenants" \
    -H "Authorization: Bearer ${JWT_TOKEN_ADMIN}" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Acme Corporation",
        "type": "customer"
    }')
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')
if [ "$http_code" -eq 201 ]; then
    echo -e "${GREEN}✅ PASS${NC} - Create Tenant 1 (HTTP $http_code)"
    echo "$body"
    TENANT_ID=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin)['tenant_id'])" 2>/dev/null)
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ FAIL${NC} - Create Tenant 1 (HTTP $http_code)"
    echo "$body"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📝 Creating Tenant 2..."
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/v1/tenants" \
    -H "Authorization: Bearer ${JWT_TOKEN_ADMIN}" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "TechCorp Ltd",
        "type": "retailer"
    }')
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')
if [ "$http_code" -eq 201 ]; then
    echo -e "${GREEN}✅ PASS${NC} - Create Tenant 2 (HTTP $http_code)"
    echo "$body"
    TENANT_ID_2=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin)['tenant_id'])" 2>/dev/null)
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ FAIL${NC} - Create Tenant 2 (HTTP $http_code)"
    echo "$body"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

sleep 1

# Generate tenant admin token for Tenant 1 (for tenant-scoped operations)
TENANT_ADMIN_USER_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
JWT_TOKEN_TENANT_ADMIN=$(python3 <<EOF
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_mock_jwt import generate_mock_token
token = generate_mock_token("$TENANT_ADMIN_USER_ID", "$TENANT_ID", ["tenant_admin"])
print(token)
EOF
)
echo -e "${BLUE}🔑 Generated Tenant Admin JWT Token for Tenant 1${NC}"

echo -e "\n📋 Listing all tenants..."
test_endpoint "List Tenants" "GET" "/v1/tenants?limit=10" "" 200 "${JWT_TOKEN_ADMIN}"

echo -e "\n🔍 Getting specific tenant..."
test_endpoint "Get Tenant by ID" "GET" "/v1/tenants/${TENANT_ID}" "" 200 "${JWT_TOKEN_ADMIN}"

echo -e "\n✏️  Updating tenant..."
test_endpoint "Update Tenant" "PUT" "/v1/tenants/${TENANT_ID}?name=Acme%20Corp%20Updated" "" 200 "${JWT_TOKEN_ADMIN}"

# ==================================================================================
# PROVISIONING - SITES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  2. PROVISIONING SERVICE - SITES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Site 1 for Tenant 1..."
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/v1/sites?tenant_id=${TENANT_ID}" \
    -H "Authorization: Bearer ${JWT_TOKEN_TENANT_ADMIN}" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "London HQ",
        "type": "headquarters",
        "geo": {"city": "London", "country": "UK"}
    }')
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')
if [ "$http_code" -eq 201 ]; then
    echo -e "${GREEN}✅ PASS${NC} - Create Site 1 (HTTP $http_code)"
    echo "$body"
    SITE_ID=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin)['site_id'])" 2>/dev/null)
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ FAIL${NC} - Create Site 1 (HTTP $http_code)"
    echo "$body"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📝 Creating Site 2 for Tenant 1..."
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/v1/sites?tenant_id=${TENANT_ID}" \
    -H "Authorization: Bearer ${JWT_TOKEN_TENANT_ADMIN}" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Manchester Branch",
        "type": "branch",
        "geo": {"city": "Manchester", "country": "UK"}
    }')
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')
if [ "$http_code" -eq 201 ]; then
    echo -e "${GREEN}✅ PASS${NC} - Create Site 2 (HTTP $http_code)"
    echo "$body"
    SITE_ID_2=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin)['site_id'])" 2>/dev/null)
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ FAIL${NC} - Create Site 2 (HTTP $http_code)"
    echo "$body"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing all sites..."
test_endpoint "List Sites" "GET" "/v1/sites?limit=10" "" 200 "${JWT_TOKEN_TENANT_ADMIN}"

echo -e "\n📋 Listing sites for Tenant 1..."
test_endpoint "List Sites by Tenant" "GET" "/v1/sites?tenant_id=${TENANT_ID}" "" 200 "${JWT_TOKEN_TENANT_ADMIN}"

# ==================================================================================
# PROVISIONING - STORES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  3. PROVISIONING SERVICE - STORES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Store under Site 1..."
response=$(curl -s -X POST "${BASE_URL}/v1/stores?site_id=${SITE_ID}" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "London Store 1",
        "type": "retail",
        "geo": {"floor": "Ground"}
    }')
echo "$response"
STORE_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['store_id'])" 2>/dev/null)
if [ -n "$STORE_ID" ]; then
    echo -e "${GREEN}✅ Store created: $STORE_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create store${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing all stores..."
test_endpoint "List Stores" "GET" "/v1/stores?limit=10"

# ==================================================================================
# PROVISIONING - USERS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  4. PROVISIONING SERVICE - USERS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating User 1..."
response=$(curl -s -X POST "${BASE_URL}/v1/users" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"email\": \"john.doe@acme.com\",
        \"display_name\": \"John Doe\",
        \"password\": \"SecurePass123\"
    }")
echo "$response"
USER_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['user_id'])" 2>/dev/null)
if [ -n "$USER_ID" ]; then
    echo -e "${GREEN}✅ User 1 created: $USER_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create user 1${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing users..."
test_endpoint "List Users" "GET" "/v1/users?limit=10"

echo -e "\n📝 Bulk importing users..."
response=$(curl -s -X POST "${BASE_URL}/v1/users/bulk-import" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"users\": [
            {\"email\": \"jane.smith@acme.com\", \"display_name\": \"Jane Smith\"},
            {\"email\": \"bob.jones@acme.com\", \"display_name\": \"Bob Jones\"}
        ]
    }")
echo "$response"
USER_ID_2=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['results']['success'][0]['user_id']) if d.get('results',{}).get('success') else ''" 2>/dev/null)
if [ -n "$USER_ID_2" ]; then
    echo -e "${GREEN}✅ Bulk import successful${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Bulk import failed${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

# ==================================================================================
# PROVISIONING - ROLES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  5. PROVISIONING SERVICE - ROLES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Role 1 - Manager..."
response=$(curl -s -X POST "${BASE_URL}/v1/roles" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Manager",
        "code": "manager",
        "description": "Site manager role"
    }')
echo "$response"
ROLE_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['role_id'])" 2>/dev/null)
if [ -n "$ROLE_ID" ]; then
    echo -e "${GREEN}✅ Role 1 created: $ROLE_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create role 1${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📝 Creating Role 2 - Finance Controller..."
response=$(curl -s -X POST "${BASE_URL}/v1/roles" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Finance Controller",
        "code": "finance_controller",
        "description": "Finance controller role"
    }')
echo "$response"
ROLE_ID_2=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['role_id'])" 2>/dev/null)
if [ -n "$ROLE_ID_2" ]; then
    echo -e "${GREEN}✅ Role 2 created: $ROLE_ID_2${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create role 2${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing roles..."
test_endpoint "List Roles" "GET" "/v1/roles?limit=10"

echo -e "\n🔗 Assigning Role to User..."
test_endpoint "Assign Role to User" "POST" "/v1/users/${USER_ID}/roles" "{\"role_id\": \"${ROLE_ID}\"}" 201

echo -e "\n📋 Getting user's roles..."
test_endpoint "Get User Roles" "GET" "/v1/users/${USER_ID}/roles"

echo -e "\n🗑️  Removing role from user..."
test_endpoint "Remove Role from User" "DELETE" "/v1/users/${USER_ID}/roles/${ROLE_ID}"

# ==================================================================================
# PROVISIONING - VENDORS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  6. PROVISIONING SERVICE - VENDORS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Vendor..."
response=$(curl -s -X POST "${BASE_URL}/v1/vendors" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"name\": \"Office Supplies Co\",
        \"contact_email\": \"contact@officesupplies.com\",
        \"description\": \"Premium office supplies vendor\"
    }")
echo "$response"
VENDOR_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['vendor_id'])" 2>/dev/null)
if [ -n "$VENDOR_ID" ]; then
    echo -e "${GREEN}✅ Vendor created: $VENDOR_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create vendor${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing vendors..."
test_endpoint "List Vendors" "GET" "/v1/vendors?limit=10"

# ==================================================================================
# PROVISIONING - COST CENTRES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  7. PROVISIONING SERVICE - COST CENTRES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Cost Centre..."
response=$(curl -s -X POST "${BASE_URL}/v1/cost-centres" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"name\": \"IT Department\",
        \"budget_minor\": 100000,
        \"manager_user_id\": \"${USER_ID}\"
    }")
echo "$response"
COST_CENTRE_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['cost_centre_id'])" 2>/dev/null)
if [ -n "$COST_CENTRE_ID" ]; then
    echo -e "${GREEN}✅ Cost Centre created: $COST_CENTRE_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create cost centre${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing cost centres..."
test_endpoint "List Cost Centres" "GET" "/v1/cost-centres?limit=10"

# ==================================================================================
# CATALOG - CATEGORIES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  8. CATALOG SERVICE - CATEGORIES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Category..."
response=$(curl -s -X POST "${BASE_URL}/v1/catalog/categories" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"name\": \"Office Supplies\",
        \"code\": \"office-supplies\",
        \"description\": \"General office supplies\"
    }")
echo "$response"
CATEGORY_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['category_id'])" 2>/dev/null)
if [ -n "$CATEGORY_ID" ]; then
    echo -e "${GREEN}✅ Category created: $CATEGORY_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create category${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing categories..."
test_endpoint "List Categories" "GET" "/v1/catalog/categories?limit=10"

echo -e "\n🔍 Getting specific category..."
test_endpoint "Get Category by ID" "GET" "/v1/catalog/categories/${CATEGORY_ID}"

# ==================================================================================
# CATALOG - PRODUCTS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  9. CATALOG SERVICE - PRODUCTS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Product..."
response=$(curl -s -X POST "${BASE_URL}/v1/catalog/products" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"category_id\": \"${CATEGORY_ID}\",
        \"sku\": \"DESK-001\",
        \"name\": \"Executive Desk\",
        \"description\": \"Premium executive desk\",
        \"brand\": \"OfficePro\",
        \"manufacturer\": \"Furniture Inc\",
        \"base_price_minor\": 50000,
        \"currency\": \"GBP\",
        \"tax_rate\": 2000,
        \"product_type\": \"physical\"
    }")
echo "$response"
PRODUCT_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['product_id'])" 2>/dev/null)
if [ -n "$PRODUCT_ID" ]; then
    echo -e "${GREEN}✅ Product created: $PRODUCT_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create product${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing products..."
test_endpoint "List Products" "GET" "/v1/catalog/products?limit=10"

echo -e "\n🔍 Getting specific product..."
test_endpoint "Get Product by ID" "GET" "/v1/catalog/products/${PRODUCT_ID}"

echo -e "\n🔍 Getting product category..."
test_endpoint "Get Product Category" "GET" "/v1/catalog/products/${PRODUCT_ID}/category"

# ==================================================================================
# CATALOG - VARIANTS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  10. CATALOG SERVICE - VARIANTS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Variant 1..."
response=$(curl -s -X POST "${BASE_URL}/v1/catalog/variants" \
    -H "Content-Type: application/json" \
    -d "{
        \"product_id\": \"${PRODUCT_ID}\",
        \"sku\": \"DESK-001-OAK\",
        \"name\": \"Executive Desk - Oak\",
        \"attributes\": {\"color\": \"oak\", \"size\": \"large\"},
        \"price_minor\": 55000,
        \"currency\": \"GBP\",
        \"stock_quantity\": 10,
        \"low_stock_threshold\": 3
    }")
echo "$response"
VARIANT_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['variant_id'])" 2>/dev/null)
if [ -n "$VARIANT_ID" ]; then
    echo -e "${GREEN}✅ Variant created: $VARIANT_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create variant${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing variants..."
test_endpoint "List Variants" "GET" "/v1/catalog/variants?limit=10"

echo -e "\n🔍 Getting specific variant..."
test_endpoint "Get Variant by ID" "GET" "/v1/catalog/variants/${VARIANT_ID}"

echo -e "\n🔍 Getting product variants..."
test_endpoint "Get Product Variants" "GET" "/v1/catalog/products/${PRODUCT_ID}/variants"

# ==================================================================================
# SUBSCRIPTIONS - PLANS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  11. SUBSCRIPTIONS SERVICE - PLANS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Subscription Plan..."
test_endpoint "Create Plan" "POST" "/v1/subscriptions/plans" \
    "{
        \"code\": \"${PLAN_CODE}\",
        \"name\": \"Basic Plan\",
        \"description\": \"Basic subscription plan\",
        \"price_yearly_minor\": 99900,
        \"currency\": \"GBP\"
    }" 201

echo -e "\n📋 Listing subscription plans..."
test_endpoint "List Plans" "GET" "/v1/subscriptions/plans?limit=10"

# ==================================================================================
# SUBSCRIPTIONS - FEATURES
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  12. SUBSCRIPTIONS SERVICE - FEATURES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Feature..."
test_endpoint "Create Feature" "POST" "/v1/subscriptions/features" \
    "{
        \"code\": \"${FEATURE_CODE}\",
        \"name\": \"API Calls\",
        \"description\": \"API call limit\",
        \"category\": \"usage\"
    }" 201

echo -e "\n📋 Listing features..."
test_endpoint "List Features" "GET" "/v1/subscriptions/features?limit=10"

echo -e "\n🔗 Adding feature to plan..."
test_endpoint "Add Feature to Plan" "PUT" "/v1/subscriptions/plans/${PLAN_CODE}/features/${FEATURE_CODE}" \
    "{\"limits\": {\"rate_limit\": 1000}}" 201

echo -e "\n📋 Getting plan features..."
test_endpoint "Get Plan Features" "GET" "/v1/subscriptions/plans/${PLAN_CODE}/features"

echo -e "\n🗑️  Removing feature from plan..."
test_endpoint "Remove Feature from Plan" "DELETE" "/v1/subscriptions/plans/${PLAN_CODE}/features/${FEATURE_CODE}"

echo -e "\n🔗 Re-adding feature to plan (for entitlement test)..."
curl -s -X PUT "${BASE_URL}/v1/subscriptions/plans/${PLAN_CODE}/features/${FEATURE_CODE}" \
    -H "Content-Type: application/json" \
    -d '{"limits": {"rate_limit": 1000}}' > /dev/null

# ==================================================================================
# SUBSCRIPTIONS - TENANT SUBSCRIPTIONS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  13. SUBSCRIPTIONS SERVICE - TENANT SUBSCRIPTIONS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating tenant subscription..."
response=$(curl -s -X POST "${BASE_URL}/v1/subscriptions/subscriptions" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"plan_code\": \"${PLAN_CODE}\",
        \"payment_method\": \"stripe\",
        \"billing_cycle\": \"yearly\"
    }")
echo "$response"
SUBSCRIPTION_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['subscription_id'])" 2>/dev/null)
if [ -n "$SUBSCRIPTION_ID" ]; then
    echo -e "${GREEN}✅ Subscription created: $SUBSCRIPTION_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create subscription${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Getting tenant subscription..."
test_endpoint "Get Tenant Subscription" "GET" "/v1/subscriptions/subscriptions/${TENANT_ID}"

echo -e "\n🔄 Renewing subscription..."
test_endpoint "Renew Subscription" "POST" "/v1/subscriptions/subscriptions/${TENANT_ID}/renew"

echo -e "\n❌ Canceling subscription..."
test_endpoint "Cancel Subscription" "POST" "/v1/subscriptions/subscriptions/${TENANT_ID}/cancel?cancel_at_period_end=true"

# ==================================================================================
# ENTITLEMENTS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  14. ENTITLEMENTS SERVICE${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n🔍 Checking entitlement..."
test_endpoint "Check Entitlement" "POST" "/v1/entitlements/check" \
    "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"feature_code\": \"${FEATURE_CODE}\"
    }"

echo -e "\n📝 Recording usage..."
test_endpoint "Record Usage" "POST" "/v1/entitlements/usage/record" \
    "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"feature_code\": \"${FEATURE_CODE}\",
        \"usage_type\": \"api_call\",
        \"count\": 5
    }" 201

echo -e "\n📊 Getting usage summary..."
test_endpoint "Get Usage Summary" "GET" "/v1/entitlements/usage/${TENANT_ID}"

# ==================================================================================
# APPROVALS
# ==================================================================================
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  15. APPROVALS SERVICE${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n📝 Creating Approval Chain..."
response=$(curl -s -X POST "${BASE_URL}/v1/approvals/chains" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"name\": \"Budget Approval Workflow\",
        \"description\": \"Multi-step budget approval\",
        \"chain_type\": \"budget\",
        \"is_active\": true
    }")
echo "$response"
CHAIN_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['chain_id'])" 2>/dev/null)
if [ -n "$CHAIN_ID" ]; then
    echo -e "${GREEN}✅ Approval Chain created: $CHAIN_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create approval chain${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing approval chains..."
test_endpoint "List Approval Chains" "GET" "/v1/approvals/chains?limit=10"

echo -e "\n📝 Creating Approval Chain Step 1..."
test_endpoint "Create Chain Step 1" "POST" "/v1/approvals/chains/steps" \
    "{
        \"approval_chain_id\": \"${CHAIN_ID}\",
        \"step_number\": 1,
        \"approver_role\": \"manager\",
        \"approver_scope\": \"site\",
        \"is_required\": true
    }" 201

echo -e "\n📝 Creating Approval Chain Step 2..."
test_endpoint "Create Chain Step 2" "POST" "/v1/approvals/chains/steps" \
    "{
        \"approval_chain_id\": \"${CHAIN_ID}\",
        \"step_number\": 2,
        \"approver_role\": \"finance_controller\",
        \"approver_scope\": \"tenant\",
        \"is_required\": true
    }" 201

echo -e "\n📋 Listing chain steps..."
test_endpoint "List Chain Steps" "GET" "/v1/approvals/chains/${CHAIN_ID}/steps"

echo -e "\n📝 Creating Approval Request..."
response=$(curl -s -X POST "${BASE_URL}/v1/approvals/requests" \
    -H "Content-Type: application/json" \
    -d "{
        \"tenant_id\": \"${TENANT_ID}\",
        \"chain_id\": \"${CHAIN_ID}\",
        \"request_type\": \"budget\",
        \"requested_by\": \"${USER_ID}\",
        \"total_amount_minor\": 50000,
        \"currency\": \"GBP\",
        \"request_data\": {
            \"purpose\": \"Office supplies budget\",
            \"period\": \"monthly\"
        }
    }")
echo "$response"
APPROVAL_REQUEST_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['request_id'])" 2>/dev/null)
if [ -n "$APPROVAL_REQUEST_ID" ]; then
    echo -e "${GREEN}✅ Approval Request created: $APPROVAL_REQUEST_ID${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo -e "${RED}❌ Failed to create approval request${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
TOTAL_TESTS=$((TOTAL_TESTS + 1))

echo -e "\n📋 Listing approval requests..."
test_endpoint "List Approval Requests" "GET" "/v1/approvals/requests?limit=10"

echo -e "\n🔍 Getting specific approval request..."
test_endpoint "Get Approval Request" "GET" "/v1/approvals/requests/${APPROVAL_REQUEST_ID}"

echo -e "\n👥 Getting request approvers..."
test_endpoint "Get Request Approvers" "GET" "/v1/approvals/requests/${APPROVAL_REQUEST_ID}/approvers"

echo -e "\n✅ Responding to approval request..."
test_endpoint "Respond to Approval" "POST" "/v1/approvals/requests/${APPROVAL_REQUEST_ID}/respond" \
    "{
        \"approver_user_id\": \"${USER_ID}\",
        \"approved\": true,
        \"notes\": \"Budget approved for office supplies\"
    }"

# ==================================================================================
# SUMMARY
# ==================================================================================
echo -e "\n${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                      TEST SUMMARY                              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Total Tests:  ${TOTAL_TESTS}"
echo -e "${GREEN}Passed:       ${PASSED_TESTS}${NC}"
echo -e "${RED}Failed:       ${FAILED_TESTS}${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL TESTS PASSED! Service is working perfectly!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed. Please review the errors above.${NC}"
    exit 1
fi

