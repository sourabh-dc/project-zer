#!/bin/bash
# Health check script for all ZeroQue services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔍 ZeroQue Services Health Check${NC}"
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

# Counters
healthy_count=0
unhealthy_count=0
total_count=${#SERVICES[@]}

# Function to check service health
check_service_health() {
    local service_name=$1
    local port=$2
    local url="http://localhost:$port/health"
    
    echo -n "Checking $service_name (port $port)... "
    
    # Check if service is responding
    if curl -s --max-time 5 "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Healthy${NC}"
        ((healthy_count++))
        return 0
    else
        echo -e "${RED}❌ Unhealthy${NC}"
        ((unhealthy_count++))
        return 1
    fi
}

# Check all services
echo -e "${BLUE}📊 Service Status:${NC}"
for service in "${!SERVICES[@]}"; do
    check_service_health "$service" "${SERVICES[$service]}"
done

echo -e "${BLUE}================================================${NC}"

# Summary
echo -e "${BLUE}📈 Summary:${NC}"
echo -e "Total Services: $total_count"
echo -e "${GREEN}Healthy: $healthy_count${NC}"
echo -e "${RED}Unhealthy: $unhealthy_count${NC}"

# Calculate health percentage
if [ $total_count -gt 0 ]; then
    health_percentage=$((healthy_count * 100 / total_count))
    echo -e "Health Percentage: $health_percentage%"
    
    if [ $health_percentage -eq 100 ]; then
        echo -e "${GREEN}🎉 All services are healthy!${NC}"
    elif [ $health_percentage -ge 80 ]; then
        echo -e "${YELLOW}⚠️  Most services are healthy${NC}"
    else
        echo -e "${RED}🚨 Multiple services are unhealthy${NC}"
    fi
fi

echo -e "${BLUE}================================================${NC}"

# Detailed health information
if [ $unhealthy_count -gt 0 ]; then
    echo -e "${YELLOW}🔍 Detailed Health Information:${NC}"
    for service in "${!SERVICES[@]}"; do
        port="${SERVICES[$service]}"
        url="http://localhost:$port/health"
        
        if ! curl -s --max-time 5 "$url" > /dev/null 2>&1; then
            echo -e "${RED}❌ $service (port $port):${NC}"
            echo -e "   URL: $url"
            echo -e "   Status: Not responding"
            echo -e "   Log: logs/${service}.log"
            echo ""
        fi
    done
fi

# Exit with appropriate code
if [ $unhealthy_count -eq 0 ]; then
    exit 0
else
    exit 1
fi

