#!/bin/bash

#===============================================================================
# ZeroQue Platform - Service Health Check
#===============================================================================

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║          ZeroQue Platform - Health Check                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

services=(
  "8000:Provisioning Service     "
  "8001:Catalog Service          "
  "8002:Orders Service           "
  "8006:Pricing Service          "
  "8080:CV Gateway Service       "
  "8084:Approvals Service        "
  "8085:Events Service           "
  "8086:Ledger Service           "
  "8212:Subscriptions Service    "
  "8213:Payments Service         "
  "8214:Billing Service          "
  "8215:Notifications Service    "
  "8216:CV Connector Service     "
  "8217:Reports Service          "
  "8218:Entry Service            "
  "8219:Usage Service            "
  "8220:Observability Service    "
  "8221:Monitoring Service       "
  "8222:Service Registry         "
  "8223:Entitlements Service     "
  "8224:Identity Service         "
)

healthy=0
unhealthy=0

for service in "${services[@]}"; do
  port="${service%%:*}"
  name="${service##*:}"
  
  if curl -s -f "http://localhost:${port}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} ${name} (port ${port})"
    ((healthy++))
  else
    echo -e "${RED}✗${NC} ${name} (port ${port})"
    ((unhealthy++))
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "Results: ${GREEN}${healthy} healthy${NC} | ${RED}${unhealthy} unhealthy${NC} | Total: 21 services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $unhealthy -eq 0 ]; then
  echo -e "${GREEN}🎉 All services are healthy!${NC}"
  exit 0
else
  echo -e "${YELLOW}⚠️  Some services are not responding. Check logs with:${NC}"
  echo "   docker-compose logs -f"
  exit 1
fi

echo ""


