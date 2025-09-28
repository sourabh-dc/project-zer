# 🚀 ZeroQue Quick Start Guide

## For Your Other System - Complete Setup in 5 Minutes

### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/sourabh-dc/project-zer.git
cd project-zer
git checkout sourabh/develop-new

# Setup environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e packages/zeroque_common
```

### Step 2: Database Setup

```bash
# Start PostgreSQL and Redis (adjust for your system)
sudo systemctl start postgresql redis  # Linux
# or
brew services start postgresql redis    # macOS

# Create database
psql -U postgres -c "CREATE DATABASE zeroque_dev; CREATE USER zeroque WITH PASSWORD 'zeroque'; GRANT ALL PRIVILEGES ON DATABASE zeroque_dev TO zeroque;"

# Run migrations
export DATABASE_URL="postgresql+psycopg2://zeroque:zeroque@localhost:5432/zeroque_dev"
alembic upgrade head

# If you get "orders relation does not exist" error, run migrations again
# The missing tables have been fixed in the latest migrations
```

### Step 3: Start Everything (One Command!)

```bash
# Start all 19 services + Celery + Streamlit
./scripts/start_all_services.sh
```

### Step 4: Verify Everything Works

```bash
# Check all services are healthy
./scripts/health_check.sh

# Test all API endpoints
./scripts/test_all_endpoints.sh
```

### Step 5: Access Applications

- **🎯 Streamlit E2E App**: http://localhost:8501
- **📚 API Docs**: http://localhost:8200/docs (and similar for other services)

## Quick Commands

```bash
# Start all services
./scripts/start_all_services.sh

# Stop all services
./scripts/stop_all_services.sh

# Health check
./scripts/health_check.sh

# Test endpoints
./scripts/test_all_endpoints.sh

# View logs
tail -f logs/orders.log
tail -f logs/celery.log
```

## Manual Service Start (if needed)

```bash
# Start services individually
source .venv/bin/activate

# Core services
uvicorn services.provisioning.main:app --reload --port 8200 &
uvicorn services.catalog.main:app --reload --port 8201 &
uvicorn services.orders.main:app --reload --port 8208 &
uvicorn services.pricing.main:app --reload --port 8209 &

# Celery workers
celery -A zeroque_common.events.celery_app worker --loglevel=info --concurrency=4 &

# Streamlit E2E
streamlit run demo/streamlit_e2e.py --server.port 8501 &
```

## Test with Curl Commands

```bash
# Create tenant
curl -X POST "http://localhost:8200/tenants" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Tenant", "domain": "test.com"}'

# Create product
curl -X POST "http://localhost:8201/products" \
  -H "Content-Type: application/json" \
  -d '{"sku": "TEST-001", "name": "Test Product", "description": "A test product"}'

# Set price
curl -X POST "http://localhost:8201/prices" \
  -H "Content-Type: application/json" \
  -d '{"sku": "TEST-001", "currency": "GBP", "unit_minor": 9.99, "active": true}'

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

### Port Already in Use

```bash
# Find and kill processes
lsof -i :8200
kill -9 <PID>
```

### Database Issues

```bash
# Check PostgreSQL
sudo systemctl status postgresql
psql -U zeroque -d zeroque_dev -c "\dt"

# Check Redis
redis-cli ping
```

### Service Not Starting

```bash
# Check logs
tail -f logs/<service>.log

# Check Python path
echo $PYTHONPATH
```

## What You Get

✅ **19 Microservices** running on different ports  
✅ **Celery Workers** for async processing  
✅ **Streamlit E2E App** for testing  
✅ **Complete API Documentation** for each service  
✅ **Health Monitoring** and logging  
✅ **Event-driven Architecture** with Redis Streams  
✅ **Enhanced Communication** patterns (Circuit Breaker, Saga, etc.)

## Next Steps

1. **Open Streamlit**: http://localhost:8501
2. **Test all functionalities** in the E2E app
3. **Run curl commands** to test APIs
4. **Check logs** for any issues
5. **Explore API docs** at each service's `/docs` endpoint

🎉 **You're ready to go!** The complete ZeroQue application is now running on your system.
