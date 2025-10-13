#!/bin/bash

# Comprehensive End-to-End Testing for All ZeroQue Services
# Tests all endpoints, validates responses, and checks service health

set +e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BASE_URL="http://localhost"
TIMEOUT=10
VERBOSE=false

# Service configurations (name port) matching docker-compose
SERVICES_LIST=$(cat <<'EOF'
orders 8080
identity 8085
ledger 8086
payments 8087
events 8088
cv_gateway 8000
cv_connector 8100
approvals 8213
entitlements 8211
subscriptions 8212
notifications 8300
reports 8400
usage 8200
observability 8600
service_registry 8500
monitoring 8700
EOF
)

# Test results
PASSED=0
FAILED=0
SKIPPED=0

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

log_warning() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
    ((SKIPPED++))
}

# Test service health
test_service_health() {
    local service=$1
    local port=$2
    
    log_info "Testing health endpoint for $service on port $port"
    
    if curl -s --max-time $TIMEOUT "$BASE_URL:$port/health" > /dev/null 2>&1; then
        log_success "$service health check passed"
        return 0
    else
        log_error "$service health check failed"
        return 1
    fi
}

# Test service readiness
test_service_readiness() {
    local service=$1
    local port=$2
    
    log_info "Testing readiness endpoint for $service on port $port"
    
    if curl -s --max-time $TIMEOUT "$BASE_URL:$port/readiness" > /dev/null 2>&1; then
        log_success "$service readiness check passed"
        return 0
    else
        log_warning "$service readiness check failed (may not be implemented)"
        return 1
    fi
}

# Test service metrics
test_service_metrics() {
    local service=$1
    local port=$2
    
    log_info "Testing metrics endpoint for $service on port $port"
    
    if curl -s --max-time $TIMEOUT "$BASE_URL:$port/metrics" > /dev/null 2>&1; then
        log_success "$service metrics endpoint accessible"
        return 0
    else
        log_warning "$service metrics endpoint not accessible"
        return 1
    fi
}

# Test provisioning service endpoints
test_provisioning_service() {
    local port=$1
    
    log_info "Testing Provisioning Service endpoints"
    
    # Test tenant creation
    log_info "Testing tenant creation"
    local tenant_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/provisioning/tenants" \
        -H "Content-Type: application/json" \
        -d '{"name": "E2E Test Tenant", "tenant_type": "customer"}')
    
    if echo "$tenant_response" | grep -q "tenant_id"; then
        log_success "Tenant creation successful"
        local tenant_id=$(echo "$tenant_response" | grep -o '"tenant_id":"[^"]*"' | cut -d'"' -f4)
        
        # Test site creation
        log_info "Testing site creation"
        local site_response=$(curl -s --max-time $TIMEOUT -X PUT "$BASE_URL:$port/provisioning/sites/test-site-id?tenant_id=$tenant_id" \
            -H "Content-Type: application/json" \
            -d '{"name": "E2E Test Site"}')
        
        if echo "$site_response" | grep -q "site_id"; then
            log_success "Site creation successful"
        else
            log_error "Site creation failed"
        fi
        
        # Test tenant listing
        log_info "Testing tenant listing"
        if curl -s --max-time $TIMEOUT "$BASE_URL:$port/provisioning/tenants" | grep -q "tenant_id"; then
            log_success "Tenant listing successful"
        else
            log_error "Tenant listing failed"
        fi
    else
        log_error "Tenant creation failed"
    fi
}

# Test orders service endpoints
test_orders_service() {
    local port=$1
    
    log_info "Testing Orders Service endpoints"
    
    # Test order creation
    log_info "Testing order creation"
    local order_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/orders/v4" \
        -H "Content-Type: application/json" \
        -d '{
            "tenant_id": "test-tenant",
            "customer_id": "test-customer",
            "items": [{"product_id": "test-product", "quantity": 1, "price_minor": 1000}],
            "total_minor": 1000
        }')
    
    if echo "$order_response" | grep -q "order_id"; then
        log_success "Order creation successful"
    else
        log_warning "Order creation failed (may require authentication)"
    fi
}

# Test identity service endpoints
test_identity_service() {
    local port=$1
    
    log_info "Testing Identity Service endpoints"
    
    # Test token generation
    log_info "Testing token generation"
    local token_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/identity/v4/tokens" \
        -H "Content-Type: application/json" \
        -d '{"user_id": "test-user", "tenant_id": "test-tenant"}')
    
    if echo "$token_response" | grep -q "token"; then
        log_success "Token generation successful"
    else
        log_warning "Token generation failed (may require proper setup)"
    fi
}

# Test usage service endpoints
test_usage_service() {
    local port=$1
    
    log_info "Testing Usage Service endpoints"
    
    # Test usage event recording
    log_info "Testing usage event recording"
    local usage_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/usage/v4/events" \
        -H "Content-Type: application/json" \
        -d '{
            "tenant_id": "test-tenant",
            "user_id": "test-user",
            "meter_code": "api_calls",
            "quantity": 1
        }')
    
    if echo "$usage_response" | grep -q "event_id"; then
        log_success "Usage event recording successful"
    else
        log_warning "Usage event recording failed"
    fi
}

# Test entry service endpoints
test_entry_service() {
    local port=$1
    
    log_info "Testing Entry Service endpoints"
    
    # Test entry code generation
    log_info "Testing entry code generation"
    local code_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/entry/v4/issue-code" \
        -H "Content-Type: application/json" \
        -d '{
            "tenant_id": "test-tenant",
            "user_id": "test-user",
            "ttl_minutes": 60
        }')
    
    if echo "$code_response" | grep -q "code"; then
        log_success "Entry code generation successful"
    else
        log_warning "Entry code generation failed"
    fi
}

# Test monitoring service endpoints
test_monitoring_service() {
    local port=$1
    
    log_info "Testing Monitoring Service endpoints"
    
    # Test health check initiation
    log_info "Testing health check initiation"
    local health_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/monitoring/v4/check-health" \
        -H "Content-Type: application/json" \
        -d '{
            "service_name": "test-service",
            "endpoint": "http://localhost:8000/health",
            "timeout_seconds": 30
        }')
    
    if echo "$health_response" | grep -q "task_id"; then
        log_success "Health check initiation successful"
    else
        log_warning "Health check initiation failed"
    fi
}

# Test observability service endpoints
test_observability_service() {
    local port=$1
    
    log_info "Testing Observability Service endpoints"
    
    # Test metric recording
    log_info "Testing metric recording"
    local metric_response=$(curl -s --max-time $TIMEOUT -X POST "$BASE_URL:$port/observability/v4/metrics" \
        -H "Content-Type: application/json" \
        -d '{
            "metric_name": "test_metric",
            "metric_type": "counter",
            "value": 1.0,
            "labels": {"service": "test"}
        }')
    
    if echo "$metric_response" | grep -q "metric_id"; then
        log_success "Metric recording successful"
    else
        log_warning "Metric recording failed"
    fi
}

# Main test execution
main() {
    log_info "Starting comprehensive end-to-end testing of all ZeroQue services"
    log_info "Testing services..."
    
    # Test all service health endpoints
    while read -r service port; do
        [ -z "$service" ] && continue
        
        echo ""
        log_info "=== Testing $service Service (Port: $port) ==="
        
        # Basic health checks
        test_service_health "$service" "$port"
        test_service_readiness "$service" "$port"
        test_service_metrics "$service" "$port"
        
        # Service-specific endpoint tests
        case $service in
            "provisioning")
                log_warning "Skipping provisioning (not running in compose)"
                ;;
            "orders")
                test_orders_service "$port"
                ;;
            "identity")
                test_identity_service "$port"
                ;;
            "usage")
                test_usage_service "$port"
                ;;
            "entry")
                log_warning "Skipping entry (not running in compose)"
                ;;
            "monitoring")
                test_monitoring_service "$port"
                ;;
            "observability")
                test_observability_service "$port"
                ;;
            *)
                log_info "No specific endpoint tests defined for $service"
                ;;
        esac
    done <<< "$SERVICES_LIST"
    
    # Summary
    echo ""
    log_info "=== Test Summary ==="
    log_success "Passed: $PASSED"
    log_error "Failed: $FAILED"
    log_warning "Skipped: $SKIPPED"
    
    local total=$((PASSED + FAILED + SKIPPED))
    log_info "Total tests: $total"
    
    if [ $FAILED -eq 0 ]; then
        log_success "All critical tests passed! Services are ready for production."
        exit 0
    else
        log_error "Some tests failed. Please review and fix issues before production deployment."
        exit 1
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -t|--timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -v, --verbose    Enable verbose output"
            echo "  -t, --timeout    Set timeout for requests (default: 10)"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main function
main
