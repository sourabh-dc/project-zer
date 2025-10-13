#!/bin/bash
# ZeroQue Production Deployment Script
# Comprehensive production deployment with health checks and rollback capabilities

set -euo pipefail

# Configuration
ENVIRONMENT=${1:-production}
NAMESPACE="zeroque-${ENVIRONMENT}"
REGISTRY="ghcr.io"
IMAGE_TAG=${2:-latest}
BACKUP_DIR="/backups/zeroque-$(date +%Y%m%d-%H%M%S)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Service definitions
SERVICES=(
    "orders:8080"
    "identity:8085"
    "ledger:8086"
    "payments:8087"
    "events:8088"
    "cv-gateway:8000"
    "cv-connector:8100"
    "approvals:8213"
    "entitlements:8211"
    "subscriptions:8212"
    "notifications:8300"
    "reports:8400"
    "usage:8200"
    "observability:8600"
    "service-registry:8500"
    "monitoring:8700"
)

# Infrastructure services
INFRASTRUCTURE_SERVICES=(
    "rabbitmq:5672"
    "postgres:5432"
    "redis:6379"
    "prometheus:9090"
    "grafana:3000"
    "nginx:80"
)

# Pre-deployment checks
pre_deployment_checks() {
    log_info "Running pre-deployment checks..."
    
    # Check if Docker is running
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running"
        exit 1
    fi
    
    # Check if required tools are installed
    local required_tools=("docker" "docker-compose" "kubectl" "helm")
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "$tool is not installed"
            exit 1
        fi
    done
    
    # Check Kubernetes cluster connectivity
    if ! kubectl cluster-info >/dev/null 2>&1; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Check if namespace exists
    if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        log_info "Creating namespace: $NAMESPACE"
        kubectl create namespace "$NAMESPACE"
    fi
    
    log_success "Pre-deployment checks passed"
}

# Backup current deployment
backup_deployment() {
    log_info "Creating backup of current deployment..."
    
    mkdir -p "$BACKUP_DIR"
    
    # Backup Kubernetes resources
    kubectl get all -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/k8s-resources.yaml"
    kubectl get configmaps -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/configmaps.yaml"
    kubectl get secrets -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/secrets.yaml"
    
    # Backup database
    if kubectl get pod -n "$NAMESPACE" -l app=postgres -o name | head -1; then
        log_info "Backing up database..."
        kubectl exec -n "$NAMESPACE" "$(kubectl get pod -n "$NAMESPACE" -l app=postgres -o name | head -1 | cut -d'/' -f2)" -- pg_dump -U zeroque zeroque_prod > "$BACKUP_DIR/database.sql"
    fi
    
    # Backup RabbitMQ
    if kubectl get pod -n "$NAMESPACE" -l app=rabbitmq -o name | head -1; then
        log_info "Backing up RabbitMQ configuration..."
        kubectl exec -n "$NAMESPACE" "$(kubectl get pod -n "$NAMESPACE" -l app=rabbitmq -o name | head -1 | cut -d'/' -f2)" -- rabbitmqctl export_definitions /tmp/definitions.json
        kubectl cp "$NAMESPACE/$(kubectl get pod -n "$NAMESPACE" -l app=rabbitmq -o name | head -1 | cut -d'/' -f2):/tmp/definitions.json" "$BACKUP_DIR/rabbitmq-definitions.json"
    fi
    
    log_success "Backup completed: $BACKUP_DIR"
}

# Deploy infrastructure services
deploy_infrastructure() {
    log_info "Deploying infrastructure services..."
    
    # Deploy using Docker Compose for local development
    if [ "$ENVIRONMENT" = "local" ]; then
        log_info "Deploying infrastructure with Docker Compose..."
        docker-compose -f docker-compose.production.yml up -d rabbitmq postgres redis prometheus grafana nginx
        
        # Wait for infrastructure to be ready
        wait_for_infrastructure
    else
        # Deploy using Kubernetes for production
        log_info "Deploying infrastructure with Kubernetes..."
        helm upgrade --install zeroque-infrastructure ./helm/infrastructure \
            --namespace "$NAMESPACE" \
            --set environment="$ENVIRONMENT" \
            --set image.tag="$IMAGE_TAG"
    fi
    
    log_success "Infrastructure deployment completed"
}

# Wait for infrastructure services
wait_for_infrastructure() {
    log_info "Waiting for infrastructure services to be ready..."
    
    for service in "${INFRASTRUCTURE_SERVICES[@]}"; do
        local name=$(echo "$service" | cut -d':' -f1)
        local port=$(echo "$service" | cut -d':' -f2)
        
        log_info "Waiting for $name to be ready..."
        local max_attempts=30
        local attempt=1
        
        while [ $attempt -le $max_attempts ]; do
            if nc -z localhost "$port" 2>/dev/null; then
                log_success "$name is ready"
                break
            fi
            
            if [ $attempt -eq $max_attempts ]; then
                log_error "$name failed to start after $max_attempts attempts"
                exit 1
            fi
            
            sleep 5
            ((attempt++))
        done
    done
}

# Deploy microservices
deploy_microservices() {
    log_info "Deploying microservices..."
    
    for service in "${SERVICES[@]}"; do
        local name=$(echo "$service" | cut -d':' -f1)
        local port=$(echo "$service" | cut -d':' -f2)
        
        log_info "Deploying $name service..."
        
        if [ "$ENVIRONMENT" = "local" ]; then
            # Deploy with Docker Compose
            docker-compose -f docker-compose.production.yml up -d "$name"
        else
            # Deploy with Kubernetes
            helm upgrade --install "zeroque-$name" "./helm/services/$name" \
                --namespace "$NAMESPACE" \
                --set image.repository="$REGISTRY/zeroque/$name" \
                --set image.tag="$IMAGE_TAG" \
                --set environment="$ENVIRONMENT"
        fi
        
        # Wait for service to be ready
        wait_for_service "$name" "$port"
        
        log_success "$name service deployed successfully"
    done
}

# Wait for service to be ready
wait_for_service() {
    local service_name=$1
    local port=$2
    local max_attempts=30
    local attempt=1
    
    log_info "Waiting for $service_name to be ready..."
    
    while [ $attempt -le $max_attempts ]; do
        if [ "$ENVIRONMENT" = "local" ]; then
            if curl -f "http://localhost:$port/health" >/dev/null 2>&1; then
                log_success "$service_name is ready"
                return 0
            fi
        else
            if kubectl get pod -n "$NAMESPACE" -l app="$service_name" -o jsonpath='{.items[0].status.phase}' | grep -q "Running"; then
                log_success "$service_name is ready"
                return 0
            fi
        fi
        
        if [ $attempt -eq $max_attempts ]; then
            log_error "$service_name failed to start after $max_attempts attempts"
            return 1
        fi
        
        sleep 10
        ((attempt++))
    done
}

# Run health checks
run_health_checks() {
    log_info "Running comprehensive health checks..."
    
    local failed_services=()
    
    for service in "${SERVICES[@]}"; do
        local name=$(echo "$service" | cut -d':' -f1)
        local port=$(echo "$service" | cut -d':' -f2)
        
        log_info "Checking health of $name..."
        
        if [ "$ENVIRONMENT" = "local" ]; then
            if ! curl -f "http://localhost:$port/health" >/dev/null 2>&1; then
                failed_services+=("$name")
                log_error "$name health check failed"
            else
                log_success "$name health check passed"
            fi
        else
            if ! kubectl get pod -n "$NAMESPACE" -l app="$name" -o jsonpath='{.items[0].status.phase}' | grep -q "Running"; then
                failed_services+=("$name")
                log_error "$name health check failed"
            else
                log_success "$name health check passed"
            fi
        fi
    done
    
    if [ ${#failed_services[@]} -gt 0 ]; then
        log_error "Health check failed for services: ${failed_services[*]}"
        return 1
    fi
    
    log_success "All health checks passed"
}

# Run load tests
run_load_tests() {
    log_info "Running load tests..."
    
    if command -v locust >/dev/null 2>&1; then
        locust -f tests/load/locustfile.py --headless -u 50 -r 5 -t 60s --html load-test-report.html
        log_success "Load tests completed"
    else
        log_warning "Locust not installed, skipping load tests"
    fi
}

# Run security audit
run_security_audit() {
    log_info "Running security audit..."
    
    if [ -f "scripts/security-audit.py" ]; then
        python3 scripts/security-audit.py --base-url "http://localhost" --output security-audit-report.json
        
        if [ $? -eq 0 ]; then
            log_success "Security audit passed"
        else
            log_warning "Security audit found issues"
        fi
    else
        log_warning "Security audit script not found"
    fi
}

# Rollback deployment
rollback_deployment() {
    log_warning "Rolling back deployment..."
    
    if [ -d "$BACKUP_DIR" ]; then
        log_info "Restoring from backup: $BACKUP_DIR"
        
        # Restore Kubernetes resources
        kubectl apply -f "$BACKUP_DIR/k8s-resources.yaml"
        kubectl apply -f "$BACKUP_DIR/configmaps.yaml"
        kubectl apply -f "$BACKUP_DIR/secrets.yaml"
        
        # Restore database
        if [ -f "$BACKUP_DIR/database.sql" ]; then
            log_info "Restoring database..."
            kubectl exec -n "$NAMESPACE" "$(kubectl get pod -n "$NAMESPACE" -l app=postgres -o name | head -1 | cut -d'/' -f2)" -- psql -U zeroque -d zeroque_prod < "$BACKUP_DIR/database.sql"
        fi
        
        log_success "Rollback completed"
    else
        log_error "No backup found for rollback"
        exit 1
    fi
}

# Cleanup function
cleanup() {
    log_info "Cleaning up..."
    
    # Remove temporary files
    rm -f load-test-report.html
    rm -f security-audit-report.json
    
    log_success "Cleanup completed"
}

# Main deployment function
main() {
    log_info "Starting ZeroQue production deployment..."
    log_info "Environment: $ENVIRONMENT"
    log_info "Namespace: $NAMESPACE"
    log_info "Image Tag: $IMAGE_TAG"
    
    # Set trap for cleanup on exit
    trap cleanup EXIT
    
    # Pre-deployment checks
    pre_deployment_checks
    
    # Create backup
    backup_deployment
    
    # Deploy infrastructure
    deploy_infrastructure
    
    # Deploy microservices
    deploy_microservices
    
    # Run health checks
    if ! run_health_checks; then
        log_error "Health checks failed, rolling back..."
        rollback_deployment
        exit 1
    fi
    
    # Run load tests
    run_load_tests
    
    # Run security audit
    run_security_audit
    
    log_success "ZeroQue production deployment completed successfully!"
    log_info "Services are available at:"
    
    for service in "${SERVICES[@]}"; do
        local name=$(echo "$service" | cut -d':' -f1)
        local port=$(echo "$service" | cut -d':' -f2)
        echo "  - $name: http://localhost:$port"
    done
}

# Handle script arguments
case "${1:-}" in
    "rollback")
        rollback_deployment
        ;;
    "health-check")
        run_health_checks
        ;;
    "load-test")
        run_load_tests
        ;;
    "security-audit")
        run_security_audit
        ;;
    *)
        main
        ;;
esac
