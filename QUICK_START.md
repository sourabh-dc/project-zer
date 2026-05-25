# 🚀 Quick Start Deployment Guide

## TL;DR - What You Need

**8 Container Apps** to deploy your microservices:

```
1. opa-server                    (Policy engine for all services)
2. provisioning-api              (API)
3. provisioning-worker           (Background worker)
4. orders-api                    (API)
5. orders-worker                 (Background worker) ← NEW
6. procurement-api               (API)
7. data-intelligence-api         (API)
8. data-intelligence-worker      (Background worker) ← NEW
```

---

## ⚡ 5-Minute Deployment

### Prerequisites
```powershell
# You need:
✅ Azure Container Registry
✅ Container Apps Environment
✅ PostgreSQL database
✅ Azure Service Bus
✅ Neo4j database
✅ Azure OpenAI
```

### Deploy Everything
```powershell
# 1. Set variables
$REGISTRY_NAME = "yourregistry"
$RESOURCE_GROUP = "zeroque-rg"
$ENVIRONMENT = "zeroque-env"

# 2. Run deployment script
./deploy.ps1 `
  -RegistryName $REGISTRY_NAME `
  -ResourceGroup $RESOURCE_GROUP `
  -Environment $ENVIRONMENT

# Done! ✅
```

---

## 🤔 Why 8 Container Apps?

### What Changed?
**Before:** 5 Container Apps (some with embedded workers)
**After:** 8 Container Apps (all workers standalone + OPA)

### Why Standalone Workers?

#### ❌ Embedded Workers (Old Way)
```
orders-api replica 1: [API + Worker] ← Processing
orders-api replica 2: [API + Worker] ← IDLE (waste!)
orders-api replica 3: [API + Worker] ← IDLE (waste!)
...
orders-api replica 8: [API + Worker] ← IDLE (waste!)
```

**Problem:** 8 workers running, only 1 actually working!

#### ✅ Standalone Workers (New Way)
```
orders-api replica 1-8: [API only] ← Serving requests
orders-worker replica 1: [Worker]  ← Processing (efficient!)
```

**Solution:** 
- 8 APIs handle traffic
- 1 worker handles background tasks
- Independent scaling
- **30-50% cost savings** at scale!

### Why OPA Server?

All your services use OPA for policy evaluation:
```python
# In your routes:
@router.post("/sites")
async def create_site(
    gate = Depends(require_policy("site.create")),  # ← Calls OPA
):
```

OPA Server provides:
- ✅ Centralized policy evaluation
- ✅ High availability (2-4 replicas)
- ✅ Internal ingress (fast, secure)
- ✅ All Rego policies pre-loaded

---

## 📁 Files You Need to Know

### For Understanding
- 📘 **DEPLOYMENT_STRATEGY_FINAL.md** ← Read this for complete strategy
- 📘 **WORKER_ARCHITECTURE_DECISION.md** ← Why standalone workers?
- 📘 **DEPLOYMENT_GUIDE.md** ← Detailed step-by-step

### For Deployment
- 🔧 **deploy.ps1** ← Automated deployment script
- 🐳 **Dockerfiles** ← All services have Dockerfiles
  - provisioning_service/Dockerfile (API)
  - provisioning_service/Dockerfile.worker (Worker)
  - orders_service/Dockerfile (API)
  - orders_service/Dockerfile.worker (Worker) ← NEW
  - data_intelligence_service/Dockerfile (API)
  - data_intelligence_service/Dockerfile.worker (Worker) ← NEW
  - shared/opa_policies/Dockerfile (OPA) ← NEW

---

## 🔧 Configuration Required

### Step 1: Deploy OPA First
```powershell
# OPA must be deployed first
# All other services need OPA_URL
```

### Step 2: Get OPA URL
```powershell
$OPA_FQDN = az containerapp show `
  --name opa-server `
  --resource-group $RESOURCE_GROUP `
  --query "properties.configuration.ingress.fqdn" `
  --output tsv

$OPA_URL = "http://${OPA_FQDN}:8181"
```

### Step 3: Set Environment Variables

All APIs need:
```env
OPA_URL=http://<opa-fqdn>:8181
DATABASE_URL=postgresql://...
```

Workers need:
```env
DATABASE_URL=postgresql://...
# + service-specific vars
```

---

## 📊 What Gets Deployed

### APIs (External Ingress)
```
provisioning-api       → https://<app>.azurecontainerapps.io
orders-api             → https://<app>.azurecontainerapps.io
procurement-api        → https://<app>.azurecontainerapps.io
data-intelligence-api  → https://<app>.azurecontainerapps.io
```

### Workers (No HTTP, Internal Only)
```
provisioning-worker         (Service Bus consumer)
orders-worker               (Service Bus consumer)
data-intelligence-worker    (Database poller)
```

### Internal Services
```
opa-server                  (Internal HTTP, policy evaluation)
```

---

## ⚠️ Important Code Changes Needed

### After Deploying Standalone Workers

You need to remove embedded worker code from your APIs:

#### 1. Orders Service
**File:** `orders_service/main.py`

Remove from lifespan:
```python
# DELETE THIS:
from orders_service.core.workers.notification_worker import process_notifications
notification_task = asyncio.create_task(process_notifications())
yield
notification_task.cancel()
```

#### 2. Data Intelligence Service
**File:** `data_intelligence_service/main.py`

Remove from lifespan:
```python
# DELETE THIS:
poll_task = asyncio.create_task(start_polling())
yield
poll_task.cancel()
```

**Why?** 
- Standalone workers now handle background tasks
- Keeping embedded workers = duplicate processing
- Remove after confirming standalone workers are running

---

## ✅ Verification Steps

### 1. Check All Container Apps
```powershell
az containerapp list --resource-group $RG --output table
```

Should show 8 apps with "Running" status.

### 2. Check Health Endpoints
```powershell
# Test APIs
curl https://provisioning-api.<fqdn>/health
curl https://orders-api.<fqdn>/health
curl https://procurement-api.<fqdn>/health
curl https://data-intelligence-api.<fqdn>/health
```

All should return `{"status": "ok"}`

### 3. Check Worker Logs
```powershell
# Provisioning worker
az containerapp logs show --name provisioning-worker --resource-group $RG --follow

# Should see: "Worker started. Listening for messages..."
```

### 4. Test OPA
```powershell
# From your local machine (via VPN/bastion if internal)
curl http://$OPA_FQDN:8181/v1/data
```

Should return OPA data API response.

---

## 💰 Cost Estimate

### Production (Min-Max)
```
OPA:              $50-100/month
APIs (3):         $225-900/month
Workers (3):      $100-300/month
─────────────────────────────────
Total:            $375-1,300/month
```

### Development (Scale to Zero)
```
Enable scale-to-zero: $50-150/month
```

---

## 🆘 Troubleshooting

### Workers Not Processing Events

**Check:**
1. Service Bus connection configured?
2. Database connection working?
3. Outbox events in database?
4. Worker logs showing errors?

```powershell
# Check worker status
az containerapp replica list --name orders-worker --resource-group $RG
```

### OPA Policy Errors

**Check:**
1. OPA_URL environment variable set?
2. OPA server accessible from APIs?
3. Policies loaded in OPA?

```powershell
# Test OPA from API
az containerapp exec --name provisioning-api --resource-group $RG --command "curl http://$OPA_FQDN:8181/health"
```

### High Costs

**Optimize:**
1. Scale to zero in dev/test
2. Reduce max replicas
3. Use consumption tier
4. Right-size CPU/memory

---

## 📞 Next Steps

1. ✅ Review [DEPLOYMENT_STRATEGY_FINAL.md](DEPLOYMENT_STRATEGY_FINAL.md)
2. ✅ Run `deploy.ps1` to deploy everything
3. ✅ Verify all health checks pass
4. ✅ Test API endpoints
5. ✅ Remove embedded worker code from APIs
6. ✅ Monitor for 24 hours
7. ✅ Optimize scaling and costs

---

## 🎯 Quick Commands Reference

```powershell
# Deploy everything
./deploy.ps1 -RegistryName $REG -ResourceGroup $RG -Environment $ENV

# Build only (no deploy)
./deploy.ps1 -RegistryName $REG -ResourceGroup $RG -Environment $ENV -BuildOnly

# Deploy only (skip build)
./deploy.ps1 -RegistryName $REG -ResourceGroup $RG -Environment $ENV -DeployOnly

# View logs
az containerapp logs show --name <app> --resource-group $RG --follow

# Scale app
az containerapp update --name <app> --resource-group $RG --min-replicas 3

# List all apps
az containerapp list --resource-group $RG --output table

# Get FQDN
az containerapp show --name <app> --resource-group $RG --query "properties.configuration.ingress.fqdn"
```

---

**Status:** ✅ Ready to Deploy

**Estimated Time:** 2-3 hours (automated)

**Difficulty:** Easy (script does everything)

---

**Questions?** Check [DEPLOYMENT_STRATEGY_FINAL.md](DEPLOYMENT_STRATEGY_FINAL.md) for details.
