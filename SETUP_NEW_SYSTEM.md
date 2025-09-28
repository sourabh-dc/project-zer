# ZeroQue Application Setup Guide for New System

This guide will help you set up and run the complete ZeroQue application on a new system.

## Prerequisites

- Python 3.11+ installed
- PostgreSQL 13+ installed and running
- Redis 6+ installed and running
- Git installed
- curl installed (for testing)

## Step 1: Clone the Repository

```bash
git clone https://github.com/sourabh-dc/project-zer.git
cd project-zer
git checkout sourabh/develop-new
```

## Step 2: Set Up Environment

### Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
pip install -e packages/zeroque_common
```

### Set Up Environment Variables

```bash
cp .env.example .env
# Edit .env with your database and Redis credentials
```

## Step 3: Database Setup

### Start PostgreSQL and Redis

```bash
# Start PostgreSQL (adjust for your system)
sudo systemctl start postgresql  # Linux
# or
brew services start postgresql   # macOS

# Start Redis
sudo systemctl start redis       # Linux
# or
brew services start redis        # macOS
```

### Create Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE zeroque_dev;
CREATE USER zeroque WITH PASSWORD 'zeroque';
GRANT ALL PRIVILEGES ON DATABASE zeroque_dev TO zeroque;
\q
```

### Run Migrations

```bash
# Set database URL
export DATABASE_URL="postgresql+psycopg2://zeroque:zeroque@localhost:5432/zeroque_dev"

# Run migrations
alembic upgrade head

# If you get "orders relation does not exist" error, the migrations have been fixed
# Just run the migrations again - the missing tables will be created

# If you get "multiple head revisions" error, run:
./scripts/fix_migration_heads.sh

# If migrations are completely broken, reset them:
./scripts/reset_migrations.sh
```

## Step 4: Start All Services

### Option A: Manual Start (Recommended for Development)

```bash
# Terminal 1: Start Infrastructure
docker-compose up -d  # If using Docker for PostgreSQL/Redis

# Terminal 2: Start Core Services
source .venv/bin/activate
uvicorn services.provisioning.main:app --reload --port 8200 &
uvicorn services.catalog.main:app --reload --port 8201 &
uvicorn services.entry.main:app --reload --port 8202 &
uvicorn services.identity.main:app --reload --port 8203 &
uvicorn services.orders.main:app --reload --port 8208 &
uvicorn services.billing.main:app --reload --port 8210 &
uvicorn services.pricing.main:app --reload --port 8209 &
uvicorn services.approvals.main:app --reload --port 8211 &
uvicorn services.cv_connector.main:app --reload --port 8213 &
uvicorn services.cv_gateway.main:app --reload --port 8214 &
uvicorn services.entitlements.main:app --reload --port 8215 &
uvicorn services.events.main:app --reload --port 8200 &
uvicorn services.ledger.main:app --reload --port 8216 &
uvicorn services.notifications.main:app --reload --port 8217 &
uvicorn services.payments.main:app --reload --port 8218 &
uvicorn services.reports.main:app --reload --port 8219 &
uvicorn services.subscriptions.main:app --reload --port 8220 &
uvicorn services.usage.main:app --reload --port 8221 &
uvicorn services.observability.main:app --reload --port 8222 &

# Terminal 3: Start Celery Workers
source .venv/bin/activate
celery -A zeroque_common.events.celery_app worker --loglevel=info --concurrency=4 --queues=default,orders,inventory,budget,notifications,webhooks,pricing,analytics --hostname=zeroque-worker@%h &

# Terminal 4: Start Streamlit E2E App
source .venv/bin/activate
streamlit run demo/streamlit_e2e.py --server.port 8501 &
```

### Option B: Automated Start Script

```bash
# Make the startup script executable
chmod +x scripts/start_all_services.sh

# Run the startup script
./scripts/start_all_services.sh
```

## Step 5: Verify Services are Running

```bash
# Check all services health
curl http://localhost:8200/health  # Provisioning
curl http://localhost:8201/health  # Catalog
curl http://localhost:8202/health  # Entry
curl http://localhost:8203/health  # Identity
curl http://localhost:8208/health  # Orders
curl http://localhost:8209/health  # Pricing
curl http://localhost:8210/health  # Billing
curl http://localhost:8211/health  # Approvals
curl http://localhost:8213/health  # CV Connector
curl http://localhost:8214/health  # CV Gateway
curl http://localhost:8215/health  # Entitlements
curl http://localhost:8200/health  # Events
curl http://localhost:8216/health  # Ledger
curl http://localhost:8217/health  # Notifications
curl http://localhost:8218/health  # Payments
curl http://localhost:8219/health  # Reports
curl http://localhost:8220/health  # Subscriptions
curl http://localhost:8221/health  # Usage
curl http://localhost:8222/health  # Observability
```

## Step 6: Run Complete Test Suite

### Test All Services

```bash
# Run the comprehensive test script
python tests/test_smoke_services.py
```

### Test Enhanced Communication

```bash
python tests/test_enhanced_communication.py
```

## Step 7: Access Applications

- **Streamlit E2E App**: http://localhost:8501
- **API Documentation**:
  - Provisioning: http://localhost:8200/docs
  - Catalog: http://localhost:8201/docs
  - Orders: http://localhost:8208/docs
  - Pricing: http://localhost:8209/docs
  - And so on for each service...

## Step 8: Run Sample Curl Commands

### Basic Setup Commands

```bash
# Create tenant
curl -X POST "http://localhost:8200/tenants" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Tenant", "domain": "test.com"}'

# Create site
curl -X POST "http://localhost:8200/sites" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "test-tenant", "name": "Test Site", "domain": "test.com"}'

# Create store
curl -X POST "http://localhost:8200/stores" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "test-tenant", "site_id": "test-site", "name": "Test Store", "address": "123 Main St"}'
```

### Product Management

```bash
# Create product
curl -X POST "http://localhost:8201/products" \
  -H "Content-Type: application/json" \
  -d '{"sku": "TEST-001", "name": "Test Product", "description": "A test product"}'

# Set price
curl -X POST "http://localhost:8201/prices" \
  -H "Content-Type: application/json" \
  -d '{"sku": "TEST-001", "currency": "GBP", "unit_minor": 9.99, "active": true}'
```

### Order Processing

```bash
# Create order
curl -X POST "http://localhost:8208/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test-tenant",
    "site_id": "test-site",
    "store_id": "test-store",
    "shopper_id": "test-user",
    "items": [{"sku": "TEST-001", "qty": 2}],
    "currency": "GBP"
  }'
```

## Troubleshooting

### Common Issues

1. **Port Already in Use**

   ```bash
   # Find and kill processes using ports
   lsof -i :8200
   kill -9 <PID>
   ```

2. **Database Connection Issues**

   ```bash
   # Check PostgreSQL is running
   sudo systemctl status postgresql

   # Check database exists
   psql -U zeroque -d zeroque_dev -c "\dt"
   ```

3. **Redis Connection Issues**

   ```bash
   # Check Redis is running
   redis-cli ping
   ```

4. **Service Not Starting**

   ```bash
   # Check logs
   tail -f logs/service.log

   # Check Python path
   echo $PYTHONPATH
   ```

### Health Check Script

```bash
#!/bin/bash
# health_check.sh

services=(
  "8200:provisioning"
  "8201:catalog"
  "8202:entry"
  "8203:identity"
  "8208:orders"
  "8209:pricing"
  "8210:billing"
  "8211:approvals"
  "8213:cv_connector"
  "8214:cv_gateway"
  "8215:entitlements"
  "8216:ledger"
  "8217:notifications"
  "8218:payments"
  "8219:reports"
  "8220:subscriptions"
  "8221:usage"
  "8222:observability"
)

for service in "${services[@]}"; do
  port=$(echo $service | cut -d: -f1)
  name=$(echo $service | cut -d: -f2)

  if curl -s http://localhost:$port/health > /dev/null; then
    echo "✅ $name (port $port): OK"
  else
    echo "❌ $name (port $port): FAILED"
  fi
done
```

## Next Steps

1. **Run the Streamlit E2E App** to test all functionalities
2. **Execute the curl commands** to test API endpoints
3. **Monitor logs** for any issues
4. **Test the enhanced communication system** with Celery workers
5. **Verify AIFI integration** if needed

## Support

If you encounter any issues:

1. Check the logs in each service terminal
2. Verify all prerequisites are installed
3. Ensure all services are running on correct ports
4. Check database and Redis connections
5. Review the README.md for detailed documentation
