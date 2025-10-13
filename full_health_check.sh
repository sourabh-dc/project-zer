#!/bin/bash

echo "=== COMPREHENSIVE HEALTH CHECK - ALL 21 SERVICES ==="
echo ""

healthy=0
unhealthy=0

# All services with their ports
services=(
    "provisioning:8000"
    "catalog:8001"
    "pricing:8002"
    "billing:8003"
    "ledger:8086"
    "payments:8005"
    "cv_gateway:8006"
    "cv_connector:8007"
    "approvals:8008"
    "entitlements:8009"
    "subscriptions:8010"
    "notifications:8011"
    "events:8012"
    "orders:8080"
    "entry:8100"
    "usage:8200"
    "identity:8300"
    "reports:8400"
    "service_registry:8500"
    "observability:8600"
    "monitoring:8700"
)

for svc_port in "${services[@]}"; do
    IFS=':' read -r service port <<< "$svc_port"
    printf "%-25s (:%s) " "$service" "$port"
    
    response=$(curl -s http://localhost:$port/health -m 3 2>/dev/null)
    
    if [ ! -z "$response" ] && echo "$response" | grep -q -E "ok|healthy|status"; then
        echo "✅ HEALTHY"
        ((healthy++))
    else
        echo "❌ UNHEALTHY"
        ((unhealthy++))
    fi
done

echo ""
echo "=== SUMMARY ==="
echo "✅ Healthy: $healthy/21"
echo "❌ Unhealthy: $unhealthy/21"
echo "📊 Success Rate: $((healthy * 100 / 21))%"
