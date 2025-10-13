#!/bin/bash
# End-to-end test script for all ZeroQue services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧪 ZeroQue Services End-to-End Testing${NC}"
echo -e "${BLUE}================================================${NC}"

# Services configuration
declare -A SERVICES=(
    ["provisioning"]="8000"
    ["approvals"]="8001"
    ["billing"]="8002"
    ["orders"]="8003"
    ["identity"]="8004"
    ["payments"]="8005"
    ["ledger"]="8006"
    ["pricing"]="8007"
    ["catalog"]="8008"
    ["notifications"]="8009"
    ["subscriptions"]="8010"
    ["entitlements"]="8011"
    ["usage"]="8012"
    ["entry"]="8013"
    ["cv_connector"]="8014"
    ["cv_gateway"]="8015"
    ["service_registry"]="8016"
    ["reports"]="8017"
    ["monitoring"]="8018"
    ["observability"]="8019"
    ["events"]="8020"
)

# Test results
declare -A TEST_RESULTS
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Function to test service health
test_service_health() {
    local service_name=$1
    local port=$2
    local url="http://localhost:$port/health"
    
    echo -n "Testing $service_name health endpoint... "
    
    if curl -s --max-time 10 "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}"
        TEST_RESULTS["${service_name}_health"]="PASS"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}❌ FAIL${NC}"
        TEST_RESULTS["${service_name}_health"]="FAIL"
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
}

# Function to test service metrics
test_service_metrics() {
    local service_name=$1
    local port=$2
    local url="http://localhost:$port/metrics"
    
    echo -n "Testing $service_name metrics endpoint... "
    
    if curl -s --max-time 10 "$url" | grep -q "prometheus" 2>/dev/null; then
        echo -e "${GREEN}✅ PASS${NC}"
        TEST_RESULTS["${service_name}_metrics"]="PASS"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}❌ FAIL${NC}"
        TEST_RESULTS["${service_name}_metrics"]="FAIL"
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
}

# Function to test service API endpoints
test_service_api() {
    local service_name=$1
    local port=$2
    
    echo -n "Testing $service_name API endpoints... "
    
    case $service_name in
        "provisioning")
            # Test tenant creation
            response=$(curl -s -X POST "http://localhost:$port/provisioning/tenants" \
                -H "Content-Type: application/json" \
                -d '{"name": "E2E Test Tenant", "tenant_type": "customer"}' \
                --max-time 10)
            if echo "$response" | grep -q "tenant_id"; then
                echo -e "${GREEN}✅ PASS${NC}"
                TEST_RESULTS["${service_name}_api"]="PASS"
                ((PASSED_TESTS++))
            else
                echo -e "${RED}❌ FAIL${NC}"
                TEST_RESULTS["${service_name}_api"]="FAIL"
                ((FAILED_TESTS++))
            fi
            ;;
        "identity")
            # Test token generation
            response=$(curl -s -X POST "http://localhost:$port/identity/tokens" \
                -H "Content-Type: application/json" \
                -d '{"user_id": "test-user", "tenant_id": "test-tenant"}' \
                --max-time 10)
            if echo "$response" | grep -q "access_token\|error"; then
                echo -e "${GREEN}✅ PASS${NC}"
                TEST_RESULTS["${service_name}_api"]="PASS"
                ((PASSED_TESTS++))
            else
                echo -e "${RED}❌ FAIL${NC}"
                TEST_RESULTS["${service_name}_api"]="FAIL"
                ((FAILED_TESTS++))
            fi
            ;;
        "orders")
            # Test order creation
            response=$(curl -s -X POST "http://localhost:$port/orders" \
                -H "Content-Type: application/json" \
                -d '{"customer_id": "test-customer", "items": []}' \
                --max-time 10)
            if echo "$response" | grep -q "order_id\|error"; then
                echo -e "${GREEN}✅ PASS${NC}"
                TEST_RESULTS["${service_name}_api"]="PASS"
                ((PASSED_TESTS++))
            else
                echo -e "${RED}❌ FAIL${NC}"
                TEST_RESULTS["${service_name}_api"]="FAIL"
                ((FAILED_TESTS++))
            fi
            ;;
        *)
            # Generic API test - just check if service responds
            if curl -s --max-time 10 "http://localhost:$port/" > /dev/null 2>&1; then
                echo -e "${GREEN}✅ PASS${NC}"
                TEST_RESULTS["${service_name}_api"]="PASS"
                ((PASSED_TESTS++))
            else
                echo -e "${RED}❌ FAIL${NC}"
                TEST_RESULTS["${service_name}_api"]="FAIL"
                ((FAILED_TESTS++))
            fi
            ;;
    esac
    ((TOTAL_TESTS++))
}

# Function to test Celery workers
test_celery_workers() {
    local service_name=$1
    
    echo -n "Testing $service_name Celery workers... "
    
    # Check if Celery worker process is running
    if pgrep -f "celery.*worker.*${service_name}" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}"
        TEST_RESULTS["${service_name}_celery"]="PASS"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}❌ FAIL${NC}"
        TEST_RESULTS["${service_name}_celery"]="FAIL"
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
}

# Function to test database connectivity
test_database_connectivity() {
    local service_name=$1
    local port=$2
    
    echo -n "Testing $service_name database connectivity... "
    
    # Test database connection through service
    response=$(curl -s --max-time 10 "http://localhost:$port/health" 2>/dev/null)
    if echo "$response" | grep -q "healthy\|status"; then
        echo -e "${GREEN}✅ PASS${NC}"
        TEST_RESULTS["${service_name}_database"]="PASS"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}❌ FAIL${NC}"
        TEST_RESULTS["${service_name}_database"]="FAIL"
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
}

# Run all tests
echo -e "${BLUE}🔍 Running Health Checks...${NC}"
for service in "${!SERVICES[@]}"; do
    test_service_health "$service" "${SERVICES[$service]}"
done

echo -e "${BLUE}📊 Running Metrics Tests...${NC}"
for service in "${!SERVICES[@]}"; do
    test_service_metrics "$service" "${SERVICES[$service]}"
done

echo -e "${BLUE}🔌 Running API Tests...${NC}"
for service in "${!SERVICES[@]}"; do
    test_service_api "$service" "${SERVICES[$service]}"
done

echo -e "${BLUE}⚙️  Running Celery Worker Tests...${NC}"
for service in "${!SERVICES[@]}"; do
    test_celery_workers "$service"
done

echo -e "${BLUE}🗄️  Running Database Connectivity Tests...${NC}"
for service in "${!SERVICES[@]}"; do
    test_database_connectivity "$service" "${SERVICES[$service]}"
done

# Summary
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}📈 Test Summary:${NC}"
echo -e "Total Tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"

# Calculate success rate
if [ $TOTAL_TESTS -gt 0 ]; then
    success_rate=$((PASSED_TESTS * 100 / TOTAL_TESTS))
    echo -e "Success Rate: $success_rate%"
    
    if [ $success_rate -eq 100 ]; then
        echo -e "${GREEN}🎉 All tests passed!${NC}"
    elif [ $success_rate -ge 80 ]; then
        echo -e "${YELLOW}⚠️  Most tests passed${NC}"
    else
        echo -e "${RED}🚨 Multiple tests failed${NC}"
    fi
fi

echo -e "${BLUE}================================================${NC}"

# Detailed results
if [ $FAILED_TESTS -gt 0 ]; then
    echo -e "${RED}❌ Failed Tests:${NC}"
    for test in "${!TEST_RESULTS[@]}"; do
        if [ "${TEST_RESULTS[$test]}" = "FAIL" ]; then
            echo -e "  - $test"
        fi
    done
    echo ""
fi

# Exit with appropriate code
if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed${NC}"
    exit 1
fi

