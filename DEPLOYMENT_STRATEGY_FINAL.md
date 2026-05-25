# Final Deployment Strategy (With Standalone Workers + OPA)

## 📊 Executive Summary

After analysis of your microservices architecture, here's the recommended deployment strategy:

### ✅ **You Need 8 Container Apps** (9 with migration job)

| # | Container App | Type | Purpose | Replicas | Monthly Cost* |
|---|---------------|------|---------|----------|---------------|
| 1 | **opa-server** | Policy Engine | OPA policy evaluation for all services | 2-4 | $50-100 |
| 2 | **provisioning-api** | API | Provisioning REST API | 2-10 | $75-300 |
| 3 | **provisioning-worker** | Worker | Tenant/user/product event processing | 1-3 | $25-75 |
| 4 | **orders-api** | API | Orders REST API (worker extracted) | 2-10 | $75-300 |
| 5 | **orders-worker** | Worker | Notification event processing | 1-3 | $25-75 |
| 6 | **procurement-api** | API | Procurement REST API | 2-10 | $75-300 |
| 7 | **data-intelligence-api** | API | Graph/Vector/AI queries (worker extracted) | 2-10 | $150-600 |
| 8 | **data-intelligence-worker** | Worker | Graph/vector event processing | 1-3 | $50-150 |
| 9 | *migration-job (optional)* | Job | Database migrations | on-demand | $5-10 |

**Total Monthly Cost: $530-1,910** (vs $400-1,575 with embedded workers)
**Why more expensive?** Better isolation, scalability, and reliability worth the 15-20% premium.

*Estimates based on standard tier with typical workload

---

## 🎯 Key Decisions Made

### 1. ✅ Standalone Workers for ALL Services
**Decision: Extract embedded workers to standalone deployments**

#### Before (Your Current State)
```
provisioning: Standalone worker ✅ (correct)
orders:       Embedded worker   ❌ (inefficient)
data_intel:   Embedded worker   ❌ (inefficient)
```

#### After (Recommended)
```
provisioning: Standalone worker ✅
orders:       Standalone worker ✅ NEW
data_intel:   Standalone worker ✅ NEW
```

**Why?**
- ✅ Independent scaling (1 worker vs 10 APIs)
- ✅ Better resource utilization
- ✅ Isolated failure domains
- ✅ Separate monitoring & logging
- ✅ Cost optimization at scale

See [WORKER_ARCHITECTURE_DECISION.md](WORKER_ARCHITECTURE_DECISION.md) for detailed analysis.

### 2. ✅ OPA Server as Container App
**Decision: Deploy OPA as internal Container App**

**Why?**
- ✅ All services need policy evaluation
- ✅ Centralized policy management
- ✅ Internal ingress (secure, fast)
- ✅ High availability (2-4 replicas)
- ✅ Policies loaded from shared/opa_policies/

**Services using OPA:**
- provisioning_service (via policy_client)
- orders_service (via policy_client)
- procurement_service (via policy_client)
- *(any service with `require_policy()` dependency)*

---

## 🏗️ Architecture Overview

### Complete System Architecture
```
                          Internet
                             │
                             ▼
                   ┌─────────────────┐
                   │  Azure Load     │
                   │   Balancer      │
                   └─────────────────┘
                             │
        ┏━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┓
        ▼                    ▼                      ▼
┌──────────────┐    ┌──────────────┐     ┌──────────────┐
│provisioning- │    │  orders-api  │     │procurement-  │
│     api      │    │   (2-10)     │     │    api       │
│   (2-10)     │    └──────────────┘     │  (2-10)      │
└──────────────┘            │             └──────────────┘
        │                   │                     │
        │                   │                     │
        │         ┌─────────┴────────┐           │
        │         ▼                  ▼           │
        │  ┌──────────────┐  ┌──────────────┐   │
        │  │data-intel-   │  │    OPA       │◄──┘
        │  │    api       │  │   Server     │◄───────┐
        │  │  (2-10)      │  │  (Internal)  │        │
        │  └──────────────┘  └──────────────┘        │
        │         │                  ▲                │
        │         │                  │                │
        │         │          All APIs call for        │
        │         │          policy decisions         │
        │         │                                   │
        ▼         ▼                                   │
┌──────────────────────────────────────────────────┐ │
│           Background Workers (No HTTP)            │ │
├──────────────────────────────────────────────────┤ │
│  ┌───────────────┐  ┌───────────────┐           │ │
│  │provisioning-  │  │   orders-     │           │ │
│  │   worker      │  │   worker      │           │ │
│  │   (1-3)       │  │   (1-3)       │           │ │
│  └───────────────┘  └───────────────┘           │ │
│                                                   │ │
│  ┌───────────────────────────────────────┐      │ │
│  │    data-intelligence-worker           │      │ │
│  │           (1-3)                        │      │ │
│  └───────────────────────────────────────┘      │ │
└──────────────────────────────────────────────────┘ │
        │              │              │               │
        ▼              ▼              ▼               │
   PostgreSQL    Service Bus       Neo4j             │
                                                      │
                                           Azure OpenAI
```

### Service Communication Flow
```
User Request
    ↓
[provisioning-api]
    ↓
1. Check OPA policy → [opa-server] (internal)
    ↓
2. Process request
    ↓
3. Write to outbox_events
    ↓
4. Publish to Service Bus
    ↓
[provisioning-worker] ← Service Bus message
    ↓
5. Process event (async)
    ↓
6. Update database
```

---

## 📁 Files Created for You

### New Dockerfiles
1. ✅ `shared/opa_policies/Dockerfile` - OPA server
2. ✅ `orders_service/Dockerfile.worker` - Orders worker
3. ✅ `data_intelligence_service/Dockerfile.worker` - Data intel worker

### New Worker Entry Points
1. ✅ `orders_service/workers/notification_worker_standalone.py`
2. ✅ `data_intelligence_service/workers/consumer_standalone.py`

### Updated Deployment Guides
1. ✅ `DEPLOYMENT_GUIDE.md` - Complete deployment instructions (updated)
2. ✅ `DEPLOYMENT_SUMMARY.md` - Quick reference (original)
3. ✅ `DEPLOYMENT_STRATEGY_FINAL.md` - This file (final strategy)
4. ✅ `WORKER_ARCHITECTURE_DECISION.md` - Worker architecture analysis
5. ✅ `deploy.ps1` - Automated deployment script (updated)

---

## 🚀 Quick Deployment Steps

### Option 1: Automated Deployment (Recommended)
```powershell
# Set your variables
$REGISTRY_NAME = "yourregistry"
$RESOURCE_GROUP = "zeroque-rg"
$ENVIRONMENT = "zeroque-env"

# Run deployment script (builds, pushes, deploys everything)
./deploy.ps1 `
  -RegistryName $REGISTRY_NAME `
  -ResourceGroup $RESOURCE_GROUP `
  -Environment $ENVIRONMENT
```

### Option 2: Manual Step-by-Step
See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed commands.

**Deployment Order:**
1. OPA Server (deploy first - all services depend on it)
2. APIs (provisioning, orders, procurement, data-intelligence)
3. Workers (provisioning, orders, data-intelligence)

---

## ⚙️ Configuration Changes Required

### Environment Variables to Add

#### All APIs
```env
OPA_URL=http://<opa-server-fqdn>:8181  # NEW - OPA policy endpoint
```

#### Orders Service (API + Worker)
No changes needed - already using Service Bus like provisioning.

#### Data Intelligence Service (API Only)
Remove worker-related environment variables:
```env
# REMOVE these (moved to worker):
# POLL_INTERVAL_SECONDS=3
# POLL_BATCH_SIZE=25
```

#### Data Intelligence Worker (Standalone)
Add these environment variables:
```env
POSTGRES_URL=postgresql://...
NEO4J_URI=bolt://...
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
POLL_INTERVAL_SECONDS=3
POLL_BATCH_SIZE=25
```

---

## 🔄 Code Changes Required

### 1. Orders Service - Remove Embedded Worker

**File:** `orders_service/main.py`

**Remove this from lifespan:**
```python
# REMOVE:
from orders_service.core.workers.notification_worker import process_notifications
notification_task = asyncio.create_task(process_notifications())

yield

notification_task.cancel()
try:
    await notification_task
except asyncio.CancelledError:
    pass
```

**After removal, lifespan should only:**
- Initialize database
- Start/stop messaging service

### 2. Data Intelligence Service - Remove Embedded Worker

**File:** `data_intelligence_service/main.py`

**Remove this from lifespan:**
```python
# REMOVE:
poll_task = asyncio.create_task(start_polling())
logger.info("Outbox polling task started")

yield

poll_task.cancel()
```

**After removal, lifespan should only:**
- Initialize Neo4j constraints
- Initialize PgVector
- Register handlers (keep this)
- Check OpenAI key

---

## 📈 Resource Allocation

### Recommended Scaling Rules

| Container App | Min | Max | Trigger | Threshold | Rationale |
|---------------|-----|-----|---------|-----------|-----------|
| opa-server | 2 | 4 | HTTP | 100/req | High availability, fast responses |
| provisioning-api | 2 | 10 | HTTP | 100/req | Standard API scaling |
| provisioning-worker | 1 | 3 | CPU | 70% | Low message volume |
| orders-api | 2 | 10 | HTTP | 100/req | High traffic expected |
| orders-worker | 1 | 3 | Queue | 10/msg | Notification processing |
| procurement-api | 2 | 10 | HTTP | 100/req | Standard API scaling |
| data-intel-api | 2 | 10 | HTTP | 100/req | Complex queries, more resources |
| data-intel-worker | 1 | 3 | CPU | 70% | Graph/vector processing |

### Total Resources

#### Minimum (Low Traffic)
```
vCPUs:  11.5 cores
Memory: 22 GB
Cost:   ~$530/month
```

#### Maximum (High Traffic)
```
vCPUs:  77 cores
Memory: 152 GB
Cost:   ~$1,910/month
```

---

## 🔒 Security Considerations

### OPA Server
- ✅ **Internal ingress only** - Not exposed to internet
- ✅ **All services call internally** via Container Apps environment networking
- ✅ **Policies bundled in image** - No runtime policy updates (intentional)
- ⚠️ **Consider:** External policy bundles for dynamic updates

### Secrets Management
All secrets should be in Azure Key Vault:
- Database connection strings
- Service Bus connection info
- Neo4j credentials
- Azure OpenAI keys
- OPA URL (not secret, but centrally managed)

---

## 🏥 Monitoring & Health Checks

### Health Endpoints by Service

| Service | Endpoint | Expected Response |
|---------|----------|-------------------|
| opa-server | `GET /health` | 200 OK (OPA built-in) |
| provisioning-api | `GET /health` | `{"status": "ok"}` |
| orders-api | `GET /health` | `{"status": "ok"}` |
| procurement-api | `GET /health` | `{"status": "ok"}` |
| data-intelligence-api | `GET /health` | `{"status": "ok"}` |

### Worker Health Monitoring
Workers don't have HTTP endpoints. Monitor via:
- ✅ Container App logs
- ✅ Application Insights (if configured)
- ✅ Service Bus queue metrics
- ✅ Database outbox_event_delivery table status

---

## 🚨 Migration Plan

### Phase 1: Add Standalone Workers (Week 1)
- [x] Create Dockerfiles for workers
- [x] Create standalone entry points
- [ ] Build and push images
- [ ] Deploy worker container apps
- [ ] Verify workers process events
- [ ] APIs and embedded workers still running (redundancy)

### Phase 2: Deploy OPA Server (Week 1)
- [ ] Build and push OPA image
- [ ] Deploy OPA container app
- [ ] Get internal FQDN
- [ ] Update API environment variables with OPA_URL
- [ ] Redeploy APIs
- [ ] Verify policy evaluation works

### Phase 3: Remove Embedded Workers (Week 2)
- [ ] Remove worker code from orders_service/main.py
- [ ] Remove worker code from data_intelligence_service/main.py
- [ ] Build and push updated API images
- [ ] Deploy updated APIs
- [ ] Monitor for issues
- [ ] Verify standalone workers handling all load

### Phase 4: Optimize & Monitor (Ongoing)
- [ ] Fine-tune scaling rules
- [ ] Monitor costs
- [ ] Adjust resource allocations
- [ ] Implement alerts

---

## 💡 Cost Optimization Tips

### 1. Scale to Zero (Dev/Test Environments)
```powershell
# Enable scale to zero for non-prod
az containerapp update --name <service> --min-replicas 0
```

### 2. Use Consumption Plan
For low-traffic services, consumption plan can reduce costs by 30-50%.

### 3. Right-Size Workers
Start with minimum resources, scale up only if needed:
- provisioning-worker: 0.5 CPU / 1GB (sufficient for most workloads)
- orders-worker: 0.5 CPU / 1GB
- data-intel-worker: 1.0 CPU / 2GB (graph processing needs more)

### 4. OPA Server
2 replicas is sufficient for most workloads. Only scale to 4 if latency increases.

---

## ✅ Pre-Deployment Checklist

### Infrastructure
- [ ] Azure Container Registry created
- [ ] Container Apps Environment created
- [ ] PostgreSQL database accessible
- [ ] Azure Service Bus namespace created
- [ ] Service Bus queue created: `outbox-task-queue`
- [ ] Neo4j database accessible
- [ ] Azure OpenAI service provisioned
- [ ] Azure Key Vault created with secrets

### Secrets Configured
- [ ] DATABASE_URL in Key Vault
- [ ] SB_NAMESPACE in Key Vault
- [ ] NEO4J_URI, NEO4J_PASSWORD in Key Vault
- [ ] AZURE_OPENAI_API_KEY in Key Vault

### Code Changes
- [ ] OPA Dockerfile created
- [ ] Worker Dockerfiles created
- [ ] Standalone worker entry points created
- [ ] (Later) Remove embedded workers from API code

### Deployment Artifacts
- [ ] All Dockerfiles validated
- [ ] deploy.ps1 script configured
- [ ] Environment variables documented
- [ ] Deployment order understood

---

## 📞 Useful Commands

### Get OPA Server URL
```powershell
$OPA_FQDN = az containerapp show `
  --name opa-server `
  --resource-group $RESOURCE_GROUP `
  --query "properties.configuration.ingress.fqdn" `
  --output tsv

Write-Host "OPA URL: http://$OPA_FQDN:8181"
```

### Test OPA Server
```powershell
# From within Container Apps environment
curl http://$OPA_FQDN:8181/v1/data

# Should return OPA data API response
```

### View All Container Apps
```powershell
az containerapp list `
  --resource-group $RESOURCE_GROUP `
  --query "[].{Name:name, FQDN:properties.configuration.ingress.fqdn, Replicas:properties.template.scale.minReplicas}" `
  --output table
```

### Stream Worker Logs
```powershell
# Provisioning worker
az containerapp logs show --name provisioning-worker --resource-group $RG --follow

# Orders worker
az containerapp logs show --name orders-worker --resource-group $RG --follow

# Data intelligence worker
az containerapp logs show --name data-intelligence-worker --resource-group $RG --follow
```

---

## 🎯 Success Criteria

### Deployment Success
- ✅ All 8 container apps deployed and healthy
- ✅ All health endpoints returning 200
- ✅ OPA server accessible from all APIs
- ✅ Workers processing events from queues/database
- ✅ No errors in container logs

### Functional Success
- ✅ API requests succeed with policy evaluation
- ✅ Outbox events being processed by workers
- ✅ Service Bus messages being consumed
- ✅ Graph data being updated in Neo4j
- ✅ Vector embeddings being created
- ✅ Notifications being sent

### Performance Success
- ✅ API response times < 500ms (p95)
- ✅ OPA policy evaluation < 50ms (p95)
- ✅ Worker processing latency < 5s (p95)
- ✅ No container restarts or OOMKills
- ✅ Resource utilization < 80% at peak

---

## 📚 Additional Resources

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Detailed deployment instructions
- [WORKER_ARCHITECTURE_DECISION.md](WORKER_ARCHITECTURE_DECISION.md) - Worker design rationale
- [Azure Container Apps Docs](https://learn.microsoft.com/azure/container-apps/)
- [OPA Documentation](https://www.openpolicyagent.org/docs/latest/)

---

**Final Deployment Count:** 8 Container Apps + 1 Optional Migration Job = 9 Total

**Status:** ✅ Ready for Deployment

**Estimated Deployment Time:** 2-3 hours (automated) or 1 day (manual)

**Recommended Approach:** Use `deploy.ps1` for consistency
