# 🎯 ZeroQue Platform - START HERE

## ⚠️ IMPORTANT: What You Need to Know

### You Just Discovered the Mock vs Real Services Issue!

**What happened:**

- You ran `python mock_servers.py`
- Postman returned generic mock responses
- No real data was stored or retrieved

**Why:**
Mock servers are lightweight placeholders that return fake data. They don't connect to databases!

---

## 🚀 Quick Start Guide

### Step 1: Stop Mock Servers (Already Done ✅)

The mock servers have been stopped. You're ready for real services!

### Step 2: Start Docker Desktop

1. Open the **Docker Desktop** application
2. Wait until it shows "Docker Desktop is running" (green status)

### Step 3: Run Real Services

```bash
./run_postman_services.sh
```

This will:

- ✅ Activate virtual environment
- ✅ Install dependencies
- ✅ Start PostgreSQL database
- ✅ Start Redis cache
- ✅ Start RabbitMQ message broker
- ✅ Build and start all 21 microservices
- ✅ Run health checks

**Wait time:**

- First run: 5-10 minutes (building images)
- After that: 1-2 minutes

### Step 4: Verify Services

```bash
./check_services.sh
```

You should see all 21 services showing ✓ (healthy)

### Step 5: Test in Postman

Now when you:

- **Create a tenant** → Gets saved to PostgreSQL
- **List tenants** → Returns all tenants from database
- **Get tenant by ID** → Returns specific tenant data

---

## 📋 All Your Services

```
Core Services:
  ✓ Provisioning        → localhost:8000
  ✓ Catalog             → localhost:8001
  ✓ Orders              → localhost:8002
  ✓ Pricing             → localhost:8006

Gateway & Business:
  ✓ CV Gateway          → localhost:8080
  ✓ Approvals           → localhost:8084
  ✓ Entry               → localhost:8218

Financial:
  ✓ Ledger              → localhost:8086
  ✓ Payments            → localhost:8213
  ✓ Billing             → localhost:8214

Communication:
  ✓ Events              → localhost:8085
  ✓ Notifications       → localhost:8215
  ✓ Reports             → localhost:8217

Monitoring:
  ✓ Usage               → localhost:8219
  ✓ Observability       → localhost:8220
  ✓ Monitoring          → localhost:8221
  ✓ Service Registry    → localhost:8222

Platform:
  ✓ Subscriptions       → localhost:8212
  ✓ Entitlements        → localhost:8223
  ✓ Identity            → localhost:8224

CV Integration:
  ✓ CV Connector        → localhost:8216
```

---

## 📚 Documentation Files

| File                      | What It's For                     |
| ------------------------- | --------------------------------- |
| **THIS FILE**             | Start here for overview           |
| `QUICK_START.md`          | 3-step quick start guide          |
| `START_REAL_SERVICES.md`  | Mock vs Real services explanation |
| `POSTMAN_DOCKER_SETUP.md` | Complete Docker setup guide       |
| `SERVICES_PORT_MAP.md`    | Port reference for all services   |

---

## 🎯 What You Get with Real Services

### Creating a Tenant (Real Response):

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Manufacturing Co",
  "company_name": "Manufacturing Solutions Ltd",
  "industry": "manufacturing",
  "admin_email": "admin@company.com",
  "admin_name": "Admin User",
  "status": "active",
  "subscription_tier": "trial",
  "created_at": "2025-10-21T15:42:56.123456Z",
  "updated_at": "2025-10-21T15:42:56.123456Z",
  "metadata": {
    "settings": {},
    "preferences": {}
  }
}
```

### Listing Tenants (Real Response):

```json
{
  "tenants": [
    {
      "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Manufacturing Co",
      "company_name": "Manufacturing Solutions Ltd",
      "status": "active",
      "subscription_tier": "trial",
      "created_at": "2025-10-21T15:42:56.123456Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

---

## 🛠️ Common Commands

```bash
# Start all services
./run_postman_services.sh

# Check service health
./check_services.sh

# View logs for all services
docker-compose logs -f

# View logs for specific service
docker-compose logs -f provisioning

# Stop all services
./stop_postman_services.sh

# Restart a specific service
docker-compose restart provisioning

# Check Docker container status
docker-compose ps
```

---

## 🔧 Management UIs

Once services are running, access:

- **RabbitMQ Management**: http://localhost:15672
  - User: `zeroque` | Pass: `zeroque_prod_2024`
- **Grafana Dashboards**: http://localhost:3000
  - User: `admin` | Pass: `zeroque_admin_2024`
- **Prometheus Metrics**: http://localhost:9090

---

## ❓ Troubleshooting

### Docker Not Running

```bash
# Check Docker status
docker info

# If not running, start Docker Desktop app
```

### Port Conflicts

```bash
# Check what's using a port
lsof -i :8000

# Kill process on port
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

### Services Not Responding

```bash
# Wait 60 seconds after startup
# Then check logs
docker-compose logs provisioning

# Restart if needed
docker-compose restart provisioning
```

### Clean Restart

```bash
# Stop everything
docker-compose down -v

# Start fresh
./run_postman_services.sh
```

---

## 📊 Architecture

```
┌─────────────────────────────┐
│     Postman Client          │
│  (Your API Testing Tool)    │
└──────────────┬──────────────┘
               │
               │ HTTP Requests
               ↓
┌─────────────────────────────┐
│  21 Microservices           │
│  (Docker Containers)        │
│  • Real Business Logic      │
│  • Database Operations      │
│  • Message Queue            │
└──────────────┬──────────────┘
               │
               ↓
┌─────────────────────────────┐
│  Infrastructure Services    │
│  (Docker Containers)        │
│  • PostgreSQL (Database)    │
│  • Redis (Cache)            │
│  • RabbitMQ (Messages)      │
│  • Prometheus (Metrics)     │
│  • Grafana (Dashboards)     │
└─────────────────────────────┘
```

---

## ✅ Checklist

Before testing in Postman:

- [ ] Docker Desktop is running
- [ ] Ran `./run_postman_services.sh`
- [ ] Waited for "ALL SERVICES RUNNING!" message
- [ ] Ran `./check_services.sh` - all green ✓
- [ ] Imported Postman collections
- [ ] Set environment to "ZeroQue Environment"
- [ ] Set `BASE_URL` to `localhost`

---

## 🎯 Your Next Steps

1. **Ensure Docker Desktop is running** (Check the menu bar icon)

2. **Run the startup script:**

   ```bash
   ./run_postman_services.sh
   ```

3. **Wait for completion** (~5-10 min first time, ~1-2 min after)

4. **Verify everything is healthy:**

   ```bash
   ./check_services.sh
   ```

5. **Open Postman and test:**
   - Import `ZeroQue_Final.postman_collection.json`
   - Import `ZeroQue_Environment.postman_environment.json`
   - Select "ZeroQue Environment"
   - Test the APIs!

---

## 📞 Support

If you encounter issues:

1. Check Docker is running: `docker info`
2. Check logs: `docker-compose logs -f`
3. Check service health: `./check_services.sh`
4. Read troubleshooting: `START_REAL_SERVICES.md`
5. Read detailed setup: `POSTMAN_DOCKER_SETUP.md`

---

**You're ready! Start Docker Desktop, run the script, and enjoy testing with real data! 🚀**

