# ZeroQue V2 Setup Guide

This guide will help you set up and run the ZeroQue V2 multi-tenant marketplace platform on a new system.

## Prerequisites

- **Python 3.13+** installed
- **PostgreSQL 15+** installed and running
- **Redis 7+** installed and running
- **Git** installed
- **curl** installed (for testing)
- **Docker & Docker Compose** (optional but recommended)

## Step 1: Clone the Repository

```bash
git clone <repository-url>
cd zeroque-sprint15-working-copy
```

## Step 2: Set Up Environment

### Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 3: Database Setup

### Option A: Using Docker (Recommended)

```bash
# Start PostgreSQL and Redis
docker-compose up postgres redis -d

# Wait for services to be ready
sleep 10

# Verify services are running
docker-compose ps
```

### Option B: Local Installation

#### PostgreSQL Setup
```bash
# Create database
createdb zeroque_dev

# Create user (if needed)
psql -c "CREATE USER zeroque WITH PASSWORD 'zeroque';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE zeroque_dev TO zeroque;"
```

#### Redis Setup
```bash
# Start Redis server
redis-server

# Verify Redis is running
redis-cli ping  # Should return PONG
```

## Step 4: Run Database Migrations

```bash
# Check current migration status
alembic current

# Apply all migrations
alembic upgrade head

# Verify tables were created
psql -h localhost -p 5000 -U zeroque -d zeroque_dev -c "\dt"
```

## Step 5: Start Services

### Option A: Using Docker Compose (Recommended)

```bash
# Start all V2 services
docker-compose up provisioning orders pricing -d

# Check service status
docker-compose ps

# View logs
docker-compose logs provisioning
docker-compose logs orders
docker-compose logs pricing
```

### Option B: Manual Start

```bash
# Terminal 1 - Provisioning Service
uvicorn services.provisioning.main:app --port 8201 --reload

# Terminal 2 - Orders Service
uvicorn services.orders.main:app --port 8203 --reload

# Terminal 3 - Pricing Service
uvicorn services.pricing.main:app --port 8209 --reload
```

## Step 6: Verify Installation

### Health Checks

```bash
# Check service health
curl http://localhost:8201/health  # Provisioning
curl http://localhost:8203/health  # Orders
curl http://localhost:8209/health  # Pricing
```

Expected response:
```json
{
  "status": "ok",
  "service": "provisioning",
  "version": "2.0.0",
  "enhanced": true
}
```

### API Documentation

Open the following URLs in your browser:
- **Provisioning API**: http://localhost:8201/docs
- **Orders API**: http://localhost:8203/docs
- **Pricing API**: http://localhost:8209/docs

## Step 7: Test the System

### Create a Tenant

```bash
curl -X POST "http://localhost:8201/provisioning/v2/tenants" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Marketplace",
    "type": "marketplace",
    "active": true
  }'
```

### Create a Site

```bash
curl -X POST "http://localhost:8201/provisioning/v2/sites" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Main Warehouse",
    "site_type": "warehouse",
    "address": "123 Main St, London, UK",
    "geo_lat": 51.5074,
    "geo_lng": -0.1278,
    "timezone": "Europe/London",
    "active": true
  }'
```

### Create a Store

```bash
curl -X POST "http://localhost:8201/provisioning/v2/stores" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "London Store",
    "store_type": "cashierless",
    "address": "456 High St, London, UK",
    "geo_lat": 51.5074,
    "geo_lng": -0.1278,
    "timezone": "Europe/London",
    "active": true
  }'
```

### Test Order Creation

```bash
curl -X POST "http://localhost:8203/orders/v2" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "store_id": "550e8400-e29b-41d4-a716-446655440002",
    "customer_id": "550e8400-e29b-41d4-a716-446655440001",
    "currency": "GBP",
    "items": [
      {
        "offer_id": "579ad27d-48f0-430a-84f5-bfec84524756",
        "quantity": 2,
        "unit_price_minor": 1000,
        "total_minor": 2000
      }
    ],
    "payment_method": "trade"
  }'
```

## Step 8: Development Setup

### Using Scripts

```bash
# Start all services
./scripts/start_all_services.sh

# Health check all services
./scripts/health_check.sh

# Test all endpoints
./scripts/test_all_endpoints.sh

# Stop all services
./scripts/stop_all_services.sh
```

### Celery Workers (Optional)

```bash
# Start Celery workers for background tasks
./scripts/celery_workers.sh
```

## Troubleshooting

### Common Issues

#### Database Connection Issues
```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check connection
psql -h localhost -p 5000 -U zeroque -d zeroque_dev -c "SELECT 1;"
```

#### Redis Connection Issues
```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connection
redis-cli -h localhost -p 4000 ping
```

#### Service Startup Issues
```bash
# Check service logs
docker-compose logs provisioning
docker-compose logs orders
docker-compose logs pricing

# Check port availability
netstat -tulpn | grep :8201
netstat -tulpn | grep :8203
netstat -tulpn | grep :8209
```

#### Migration Issues
```bash
# Check migration status
alembic current

# Reset migrations (if needed)
./scripts/reset_migrations.sh

# Fix migration heads (if needed)
./scripts/fix_migration_heads.sh
```

### Environment Variables

Create a `.env` file in the project root:

```bash
# Database
DATABASE_URL=postgresql+psycopg2://zeroque:zeroque@localhost:5000/zeroque_dev

# Redis
REDIS_URL=redis://localhost:4000/0

# Service Configuration
V2=true
USE_V2_SCHEMA=true
MULTI_TENANT_ENABLED=true
VENDOR_MARKETPLACE_ENABLED=true

# Service URLs
PAYMENTS_BASE=http://localhost:8216
PRICING_BASE=http://localhost:8209
INVENTORY_BASE=http://localhost:8202
```

## Next Steps

### Development
1. **Read the Architecture**: Check `architecture_v4.1.md` for detailed architecture
2. **Explore APIs**: Use the `/docs` endpoints to explore available APIs
3. **Run Tests**: Execute the test suite to verify functionality
4. **Monitor Logs**: Watch service logs for debugging

### Production Deployment
1. **Environment Setup**: Configure production environment variables
2. **Security**: Set up proper authentication and authorization
3. **Monitoring**: Configure comprehensive monitoring and alerting
4. **Backup**: Set up regular database backups
5. **Scaling**: Plan for horizontal scaling of services

## Support

- **Documentation**: Check `README_v2.md` for comprehensive documentation
- **API Docs**: Use the `/docs` endpoints for interactive API documentation
- **Issues**: Create GitHub issues for bugs or feature requests
- **Discussions**: Use GitHub discussions for questions

---

**ZeroQue V2** - Ready for development! 🚀