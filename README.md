# ZeroQue - Complete Production Platform

A comprehensive **multi-tenant marketplace platform** for retail operations, featuring advanced provisioning, order processing with saga orchestration, sophisticated pricing engine, and enterprise-grade production infrastructure.

## 🚀 V4.1 Architecture Overview

ZeroQue V4.1 is built as a microservices architecture with the following core components:

### **Infrastructure Stack**

- **Message Broker**: RabbitMQ 3.12 with clustering
- **Database**: PostgreSQL 15 with RLS and auditing
- **Cache**: Redis 7 with persistence
- **Monitoring**: Prometheus + Grafana
- **Load Balancer**: Nginx with SSL termination
- **Container Orchestration**: Docker Compose (dev) / Kubernetes (prod)

### **Microservices (16 total)**

1. **Orders Service** (8080) - Order lifecycle management
2. **Identity Service** (8085) - Authentication & authorization
3. **Ledger Service** (8086) - Double-entry accounting
4. **Payments Service** (8087) - Multi-provider payment processing
5. **Events Service** (8088) - Event bus and messaging
6. **CV Gateway** (8000) - Computer vision integration hub
7. **CV Connector** (8100) - External provider connectivity
8. **Approvals Service** (8213) - Workflow-based approvals
9. **Entitlements Service** (8211) - Feature access control
10. **Subscriptions Service** (8212) - Plan and billing management
11. **Notifications Service** (8300) - Multi-channel notifications
12. **Reports Service** (8400) - Advanced analytics
13. **Usage Service** (8200) - Real-time usage tracking
14. **Observability Service** (8600) - System monitoring
15. **Service Registry** (8500) - Service discovery
16. **Monitoring Service** (8700) - Centralized monitoring

## 📋 Production Prerequisites

### System Requirements

- **OS**: Ubuntu 20.04+ or macOS 12+
- **CPU**: 8+ cores
- **RAM**: 32GB+
- **Storage**: 500GB+ SSD
- **Network**: 1Gbps+ bandwidth

### Required Software

```bash
# Docker & Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Kubernetes & Helm (for production)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install apt-transport-https --yes
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable.list
sudo apt-get update
sudo apt-get install helm

# Load Testing Tools
pip install locust k6

# Security Tools
pip install bandit safety trivy
```

## 🚀 Quick Start

### 1. Local Development Setup

```bash
# Clone repository
git clone <repository-url>
cd zeroque-sprint15-working-copy

# Setup environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start infrastructure services
docker-compose -f docker-compose.production.yml up -d rabbitmq postgres redis prometheus grafana

# Wait for infrastructure to be ready
./scripts/deploy-production.sh health-check

# Start microservices (in separate terminals)
cd services/orders && source ../../venv/bin/activate && python main.py &
cd services/identity && source ../../venv/bin/activate && python main.py &
# ... repeat for other services

# Run health checks
curl http://localhost:8080/health  # Orders
curl http://localhost:8085/health  # Identity
# ... check all services
```

### 2. Production Deployment

```bash
# Full production deployment
./scripts/deploy-production.sh production latest

# Or step by step:
./scripts/deploy-production.sh production latest
```

## 🔧 Configuration

### Environment Variables

```bash
# Database
export DATABASE_URL="postgresql://zeroque:password@localhost:5432/zeroque_prod"

# RabbitMQ
export RABBITMQ_URL="amqp://zeroque:password@localhost:5672/zeroque"

# Redis
export REDIS_URL="redis://localhost:6379/0"

# JWT
export JWT_SECRET_KEY="your-super-secret-jwt-key"
export JWT_ALGORITHM="HS256"
export JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Monitoring
export PROMETHEUS_ENDPOINT="http://localhost:9090"
export GRAFANA_ENDPOINT="http://localhost:3000"
```

### Security Configuration

```bash
# SSL/TLS Certificates
mkdir -p config/nginx/ssl
# Place your certificates in config/nginx/ssl/

# Database Security
export POSTGRES_PASSWORD="secure-random-password"
export RABBITMQ_PASSWORD="secure-random-password"

# API Keys
export STRIPE_SECRET_KEY="sk_live_..."
export TWILIO_AUTH_TOKEN="your-twilio-token"
```

## 📊 Monitoring & Observability

### Grafana Dashboards

Access Grafana at `http://localhost:3000`

- **Username**: admin
- **Password**: zeroque_admin_2024

### Available Dashboards

1. **System Overview** - Overall system health
2. **Service Performance** - Individual service metrics
3. **Database Performance** - PostgreSQL metrics
4. **Message Queue** - RabbitMQ metrics
5. **Security Events** - Security monitoring
6. **Business Metrics** - Revenue, orders, users

### Prometheus Metrics

Access Prometheus at `http://localhost:9090`

Key metrics to monitor:

- `http_requests_total` - Request rates
- `http_request_duration_seconds` - Response times
- `database_connections_active` - DB connections
- `rabbitmq_queue_messages` - Queue depths
- `service_health_status` - Service health

## 🧪 Testing

### Load Testing

```bash
# Install Locust
pip install locust

# Run load tests
locust -f tests/load/locustfile.py --host=http://localhost

# Run specific service tests
locust -f tests/load/locustfile.py OrdersUser --host=http://localhost:8080
```

### Security Testing

```bash
# Run security audit
python scripts/security-audit.py --base-url http://localhost

# Run dependency security check
safety check

# Run code security scan
bandit -r services/
```

### Performance Testing

```bash
# Run comprehensive tests
./scripts/deploy-production.sh load-test

# Check service performance
curl http://localhost:8080/metrics | grep duration
```

## 🔒 Security

### Authentication & Authorization

- JWT-based authentication
- Role-based access control (RBAC)
- Row-level security (RLS) in database
- API rate limiting
- CORS protection

### Data Protection

- Encryption at rest (database)
- Encryption in transit (TLS)
- Sensitive data masking
- Audit logging
- GDPR compliance features

### Network Security

- VPC isolation
- Security groups
- Network policies
- SSL/TLS termination
- DDoS protection

## 📈 Scaling

### Horizontal Scaling

```bash
# Scale services with Docker Compose
docker-compose -f docker-compose.production.yml up -d --scale orders=3

# Scale with Kubernetes
kubectl scale deployment zeroque-orders --replicas=5 -n zeroque-production
```

### Database Scaling

- Read replicas for read-heavy workloads
- Connection pooling
- Query optimization
- Index optimization

### Message Queue Scaling

- RabbitMQ clustering
- Queue partitioning
- Consumer scaling
- Dead letter handling

## 🚨 Troubleshooting

### Common Issues

#### Service Won't Start

```bash
# Check logs
docker-compose logs service-name

# Check health
curl http://localhost:port/health

# Check dependencies
curl http://localhost:5432  # PostgreSQL
curl http://localhost:5672  # RabbitMQ
curl http://localhost:6379  # Redis
```

#### Database Connection Issues

```bash
# Check database status
docker-compose logs postgres

# Test connection
psql -h localhost -U zeroque -d zeroque_prod

# Check RLS policies
psql -h localhost -U zeroque -d zeroque_prod -c "SELECT * FROM pg_policies;"
```

#### Message Queue Issues

```bash
# Check RabbitMQ status
docker-compose logs rabbitmq

# Check queues
curl -u zeroque:password http://localhost:15672/api/queues

# Check connections
curl -u zeroque:password http://localhost:15672/api/connections
```

### Performance Issues

```bash
# Check resource usage
docker stats

# Check slow queries
curl http://localhost:9090/api/v1/query?query=pg_stat_statements

# Check service metrics
curl http://localhost:port/metrics
```

## 📞 Support

### Monitoring Alerts

- Service downtime alerts
- High error rate alerts
- Resource usage alerts
- Security breach alerts

### Log Analysis

- Centralized logging with ELK stack
- Structured logging with JSON
- Log aggregation and search
- Error tracking and alerting

### Backup & Recovery

```bash
# Database backup
pg_dump -h localhost -U zeroque zeroque_prod > backup.sql

# Restore database
psql -h localhost -U zeroque zeroque_prod < backup.sql

# RabbitMQ backup
rabbitmqctl export_definitions /tmp/definitions.json
```

## 🔄 CI/CD Pipeline

### Automated Deployment

- GitHub Actions for CI/CD
- Automated testing
- Security scanning
- Performance testing
- Blue-green deployment

### Quality Gates

- Code quality checks
- Security vulnerability scans
- Performance benchmarks
- Integration tests
- Load tests

## 📚 Additional Resources

- [API Documentation](docs/)
- [Architecture Guide](architecture_v4.1.md)
- [Security Guidelines](docs/SECURITY.md)
- [Performance Tuning](docs/PERFORMANCE.md)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md)

## 🎯 Production Checklist

- [ ] Infrastructure services running
- [ ] All microservices healthy
- [ ] Database RLS policies applied
- [ ] SSL certificates configured
- [ ] Monitoring dashboards active
- [ ] Security audit passed
- [ ] Load tests successful
- [ ] Backup procedures tested
- [ ] Disaster recovery plan ready
- [ ] Team training completed

---

**ZeroQue Production Platform** - Enterprise-ready microservices architecture with comprehensive monitoring, security, and scalability.
