# Azure Container Apps Deployment Guide

## 📋 Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Container Apps Required](#container-apps-required)
3. [Prerequisites](#prerequisites)
4. [Build & Push Images](#build--push-images)
5. [Deploy Infrastructure](#deploy-infrastructure)
6. [Deploy Services](#deploy-services)
7. [Configuration](#configuration)
8. [Scaling Strategy](#scaling-strategy)
9. [Monitoring & Health Checks](#monitoring--health-checks)

---

## 🏗️ Architecture Overview

Your application consists of **4 microservices** requiring **6 Container Apps**:

```
┌──────────────────────────────────────────────────────────────────┐
│                     Azure Container Apps                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ provisioning-api│  │   orders-api    │  │ procurement-api  │ │
│  │   (HTTP API)    │  │   (HTTP API)    │  │   (HTTP API)     │ │
│  │   Port: 80      │  │   Port: 80      │  │   Port: 80       │ │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘ │
│           │                    │                     │            │
│           │                    │                     │            │
│           │                    │                     │            │
│           ▼                    ▼                     ▼            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ provisioning-   │  │   orders-       │  │data-intelligence-│ │
│  │   worker        │  │   worker        │  │      api         │ │
│  │ (Background)    │  │ (Background)    │  │   (HTTP API)     │ │
│  └─────────────────┘  └─────────────────┘  │   Port: 80       │ │
│                                             └──────────────────┘ │
│  ┌─────────────────┐                                │            │
│  │data-intelligence│                                │            │
│  │    -worker      │                                │            │
│  │ (Background)    │                                │            │
│  └─────────────────┘                                │            │
│                                                      │            │
│  ┌────────────────────────────────────────────────┐ │            │
│  │          opa-server (Policy Engine)            │ │            │
│  │          Internal Port: 8181                   │ │            │
│  │     ← All services call for policy decisions   │ │            │
│  └────────────────────────────────────────────────┘ │            │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
         │                    │                │                │
         ▼                    ▼                ▼                ▼
    PostgreSQL          Service Bus         Neo4j        Azure OpenAI
```

---

## 📦 Container Apps Required

| # | Container App Name | Type | Ingress | Replicas | Port | Purpose |
|---|-------------------|------|---------|----------|------|---------|
| 1 | `provisioning-api` | HTTP API | External | 2-10 | 80 | Provisioning REST API |
| 2 | `provisioning-worker` | Worker | None | 1-3 | - | Processes tenant/user/product events |
| 3 | `orders-api` | HTTP API | External | 2-10 | 80 | Orders REST API |
| 4 | `orders-worker` | Worker | None | 1-3 | - | Processes notification events |
| 5 | `procurement-api` | HTTP API | External | 2-10 | 80 | Procurement REST API |
| 6 | `data-intelligence-api` | HTTP API | External | 2-10 | 80 | Graph/Vector/AI queries |
| 7 | `data-intelligence-worker` | Worker | None | 1-3 | - | Processes graph/vector events |
| 8 | `opa-server` | Policy Engine | Internal | 2-4 | 8181 | OPA policy evaluation |
| 9 | *(Optional)* `migration-job` | Job | None | 1 | - | Database migrations |

**Total: 8-9 Container Apps** (3 APIs + 3 Workers + OPA + optional migration)

---

## ✅ Prerequisites

### Azure Resources Needed
- ✅ Azure Container Registry (ACR)
- ✅ Azure Container Apps Environment
- ✅ PostgreSQL Database
- ✅ Azure Service Bus (Queue: `outbox-task-queue`)
- ✅ Neo4j Database
- ✅ Azure Key Vault (for secrets)
- ✅ Azure OpenAI (for data intelligence)

### Local Tools
```bash
# Required
az --version          # Azure CLI
docker --version      # Docker
```

---

## 🔨 Build & Push Images

### Step 1: Login to Azure Container Registry
```bash
# Set variables
$REGISTRY_NAME="<your-registry-name>"
$RESOURCE_GROUP="<your-resource-group>"

# Login
az acr login --name $REGISTRY_NAME
```

### Step 2: Build Images

#### 2.0 OPA Server (Policy Engine)
```bash
cd C:\Projects\project-zer\shared\opa_policies
docker build -f Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/opa-server:latest `
  -t ${REGISTRY_NAME}.azurecr.io/opa-server:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/opa-server:latest
```

#### 2.1 Provisioning API
```bash
cd C:\Projects\project-zer
docker build -f provisioning_service/Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/provisioning-api:latest `
  -t ${REGISTRY_NAME}.azurecr.io/provisioning-api:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/provisioning-api:latest
```

#### 2.2 Provisioning Worker (Separate Entry Point)
```bash
# Create worker-specific Dockerfile
docker build -f provisioning_service/Dockerfile.worker `
  -t ${REGISTRY_NAME}.azurecr.io/provisioning-worker:latest `
  -t ${REGISTRY_NAME}.azurecr.io/provisioning-worker:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/provisioning-worker:latest
```

**Note**: You need to create `provisioning_service/Dockerfile.worker`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc postgresql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "provisioning_service.core.helpers.outbox_worker"]
```

#### 2.3 Orders API
```bash
docker build -f orders_service/Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/orders-api:latest `
  -t ${REGISTRY_NAME}.azurecr.io/orders-api:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/orders-api:latest
```

#### 2.5 Procurement API
```bash
docker build -f Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/procurement-api:latest `
  --build-arg SERVICE=procurement_service .
docker push ${REGISTRY_NAME}.azurecr.io/procurement-api:latest
```

#### 2.6 Data Intelligence API
```bash
docker build -f data_intelligence_service/Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest
```

#### 2.7 Data Intelligence Worker (Standalone)
```bash
docker build -f data_intelligence_service/Dockerfile.worker `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-worker:latest `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-worker:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/data-intelligence-workert
```

#### 2.5 Data Intelligence API
```bash
docker build -f data_intelligence_service/Dockerfile `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest `
  -t ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:v1.0.0 .
docker push ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest
```

### Step 3: Verify Images
```bash
az acr repository list --name $REGISTRY_NAME --output table
```

---

## 🚀 Deploy Infrastructure

### Step 1: Create Container Apps Environment
```bash
$ENVIRONMENT_NAME="zeroque-env"
$LOCATION="eastus"

az containerapp env create `
  --name $ENVIRONMENT_NAME `
  --resource-group $RESOURCE_GROUP `
  --location $LOCATION `
  --logs-workspace-id <workspace-id> `
  --logs-customer-id <customer-id>
```

### Step 2: Configure Secrets in Key Vault
```bash
$KEY_VAULT_NAME="<your-keyvault>"

# Database
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "DATABASE-URL" --value "postgresql://..."

# Service Bus
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "SB-NAMESPACE" --value "zeroque.servicebus.windows.net"

# Neo4j
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "NEO4J-URI" --value "bolt://..."

# Azure OpenAI
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "AZURE-OPENAI-KEY" --value "..."
```

---

## 📋 Deploy Services

### 0. Deploy OPA Server (Policy Engine) - Deploy First!
```bash
az containerapp create `
  --name opa-server `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/opa-server:latest `
  --target-port 8181 `
  --ingress internal `
  --min-replicas 2 `
  --max-replicas 4 `
  --cpu 0.5 `
  --memory 1.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io
```

**Important**: Get the OPA server internal FQDN:
```bash
$OPA_FQDN = az containerapp show `
  --name opa-server `
  --resource-group $RESOURCE_GROUP `
  --query "properties.configuration.ingress.fqdn" `
  --output tsv

Write-Host "OPA Server URL: http://$OPA_FQDN:8181"
```

Use this URL as `OPA_URL` environment variable for all services.

### 1. Deploy Provisioning API
```bash
az containerapp create `
  --name provisioning-api `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/provisioning-api:latest `
  --target-port 80 `
  --ingress external `
  --min-replicas 2 `
  --max-replicas 10 `
  --cpu 1.0 `
  --memory 2.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "DATABASE_URL=secretref:database-url" `
    "SB_NAMESPACE=secretref:sb-namespace" `
    "QUEUE_NAME=outbox-task-queue" `
    "ENVIRONMENT=production" `
    "OPA_URL=http://${OPA_FQDN}:8181" `
  --secrets `
    "database-url=<connection-string>" `
    "sb-namespace=zeroque.servicebus.windows.net"
```

### 2. Deploy Provisioning Worker (No Ingress)
```bash
az containerapp create `
  --name provisioning-worker `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/provisioning-worker:latest `
  --ingress none `
  --min-replicas 1 `
  --max-replicas 3 `
  --cpu 0.5 `
  --memory 1.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "DATABASE_URL=secretref:database-url" `
    "SB_NAMESPACE=secretref:sb-namespace" `
    "QUEUE_NAME=outbox-task-queue" `
  --secrets `
    "database-url=<connection-string>" `
    "sb-namespace=zeroque.servicebus.windows.net"
```
 (No Worker!)
```bash
az containerapp create `
  --name orders-api `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/orders-api:latest `
  --target-port 80 `
  --ingress external `
  --min-replicas 2 `
  --max-replicas 10 `
  --cpu 1.0 `
  --memory 2.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "DATABASE_URL=secretref:database-url" `
    "SB_NAMESPACE=secretref:sb-namespace" `
    "ORDERS_PORT=80" `
    "OPA_URL=http://${OPA_FQDN}:8181" `
  --secrets `
    "database-url=<connection-string>" `
    "sb-namespace=zeroque.servicebus.windows.net"
```

**No5e**: Worker has been extracted to standalone deployment (see next step)

### 4. Deploy Orders Worker (Standalone)
```bash
az containerapp create `
  --name orders-worker `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/orders-worker:latest `
  --ingress none `
  --min-replicas 1 `
  --max-replicas 3 `
  --cpu 0.5 `
  --memory 1.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "DATABASE_URL=secretref:database-url" `
    "SB_NAMESPACE=secretref:sb-namespaceecretref:sb-namespace" `
    "ORDERS_PORT=80" `
  --secrets `
    6. Deploy Data Intelligence API (No Worker!)
```bash
az containerapp create `
  --name data-intelligence-api `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest `
  --target-port 80 `
  --ingress external `
  --min-replicas 2 `
  --max-replicas 10 `
  --cpu 2.0 `
  --memory 4.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "POSTGRES_URL=secretref:database-url" `
    "NEO4J_URI=secretref:neo4j-uri" `
    "NEO4J_USER=neo4j" `
    "NEO4J_PASSWORD=secretref:neo4j-password" `
    "AZURE_OPENAI_API_KEY=secretref:openai-key" `
  --secrets `
    "database-url=<connection-string>" `
    "neo4j-uri=bolt://..." `
    "neo4j-password=..." `
    "openai-key=..."
```

**Note**: Worker has been extracted to standalone deployment (see next step)

### 7. Deploy Data Intelligence Worker (Standalone)
```bash
az containerapp create `
  --name data-intelligence-worker `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/data-intelligence-worker:latest `
  --ingress none `
  --min-replicas 1 `
  --max-replicas 3 `
  --cpu 1.0 `
  --memory 2.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "POSTGRES_URL=secretref:database-url" `
    "NEO4J_URI=secretref:neo4j-uri" `
    "NEO4J_USER=neo4j" `
    "NEO4J_PASSWORD=secretref:neo4j-password" `
    "POLL_INTERVAL_SECONDS=3" `
    "POLL_BATCH_SIZE=25" `
  --secrets `
    "database-url=<connection-string>" `
    "neo4j-uri=bolt://..." `
    "neo4j-password create `
  --name data-intelligence-api `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/data-intelligence-api:latest `
  --target-port 80 `
  --ingress external `
  --min-replicas 2 `
  --max-replicas 10 `
  --cpu 2.0 `
  --memory 4.0Gi `
  --registry-server ${REGISTRY_NAME}.azurecr.io `
  --env-vars `
    "POSTGRES_URL=secretref:database-url" `
    "NEO4J_URI=secretref:neo4j-uri" `
    "NEO4J_USER=neo4j" `
    "NEO4J_PASSWORD=secretref:neo4j-password" `
    "AZURE_OPENAI_API_KEY=secretref:openai-key" `
    "POLL_INTERVAL_SECONDS=3" `
    "POLL_BATCH_SIZE=25" `
  --secrets `
    "database-url=<connection-string>" `
    "neo4j-uri=bolt://..." `
    "neo4j-password=..." `
    "openai-key=..."
```

---

## ⚙️ Configuration

### Environment Variables by Service

#### Provisioning API & Worker
```
DATABASE_URL=postgresql://...
SB_NAMESPACE=zeroque.servicebus.windows.net
QUEUE_NAME=outbox-task-queue
ENVIRONMENT=production
ALLOW_ORIGINS=*
AZURE_CLIENT_ID=...
AZURE_TENANT_ID=...
AZURE_KEY_VAULT_URL=...
```

#### Orders API
```
DATABASE_URL=postgresql://...
SB_NAMESPACE=zeroque.servicebus.windows.net
ORDERS_PORT=80
ALLOW_ORIGINS=*
ENVIRONMENT=production
```

#### Procurement API
```
DATABASE_URL=postgresql://...
CORS_ALLOW_ORIGINS=*
ENVIRONMENT=production
```

#### Data Intelligence API
```
POSTGRES_URL=postgresql://...
NEO4J_URI=bolt://...
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=...
POLL_INTERVAL_SECONDS=3
POLL_BATCH_SIZE=25
```

---

## 📈 Scaling Strategy

### HTTP-Based Scaling (APIs)
```bash
# Example for provisioning-api
az containerapp update `
  --name provisioning-api `
  --resource-group $RESOURCE_GROUP `
  --scale-rule-name http-rule `
  --scale-rule-type http `
  --scale-rule-http-concurrency 100 `
  --min-replicas 2 `
  --max-replicas 10
```

### CPU-Based Scaling (Workers)
```bash
# For provisioning-worker
az containerapp update `
  --name provisioning-worker `
  --resource-group $RESOURCE_GROUP `
  --scale-rule-name cpu-rule `
  --scale-rule-type cpu `
  --scale-rule-metadata threshold=70 `
  --min-replicas 1 `
  --max-replicas 3
```

### Recommended Scaling Rules

| Service | Min | Max | Trigger | Threshold |
|---------|-----|-----|---------|-----------|
| provisioning-api | 2 | 10 | HTTP | 100 concurrent |
| provisioning-worker | 1 | 3 | CPU | 70% |
| orders-api | 2 | 10 | HTTP | 100 concurrent |
| procurement-api | 2 | 10 | HTTP | 100 concurrent |
| data-intelligence-api | 2 | 10 | HTTP + CPU | 100 / 70% |

---

## 🏥 Monitoring & Health Checks

### Configure Health Probes
```bash
az containerapp update `
  --name provisioning-api `
  --resource-group $RESOURCE_GROUP `
  --health-probe-type liveness `
  --health-probe-path /health `
  --health-probe-interval 30 `
  --health-probe-timeout 5
```

### Health Endpoints
- `GET /health` - All services
- `GET /ready` - Procurement service
- `GET /metrics` - Procurement service

### View Logs
```bash
# Stream logs
az containerapp logs show `
  --name provisioning-api `
  --resource-group $RESOURCE_GROUP `
  --follow

# View replicas
az containerapp replica list `
  --name provisioning-api `
  --resource-group $RESOURCE_GROUP
```

---

## 🔧 Database Migration Strategy

### ⚠️ Critical Issue
Your services have a **race condition** - all call `Base.metadata.create_all()` on startup.

### Recommended Solution: Migration Job

Create `migration-job` Container App Job:
```bash
az containerapp job create `
  --name migration-job `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT_NAME `
  --image ${REGISTRY_NAME}.azurecr.io/migration:latest `
  --replica-timeout 600 `
  --trigger-type Manual `
  --env-vars "DATABASE_URL=secretref:database-url"
```

Run before deployments:
```bash
az containerapp job start --name migration-job --resource-group $RESOURCE_GROUP
```

---

## 🎯 Deployment Checklist

### Pre-Deployment
- [ ] Build all Docker images
- [ ] Push images to ACR
- [ ] Create Container Apps Environment
- [ ] Configure secrets in Key Vault
- [ ] Run database migrations
- [ ] Verify PostgreSQL connectivity
- [ ] Verify Service Bus queue exists
- [ ] Verify Neo4j is accessible

### Deployment Order
1. [ ] Deploy `migration-job` (run once)
2. [ ] Deploy `provisioning-api`
3. [ ] Deploy `provisioning-worker`
4. [ ] Deploy `orders-api`
5. [ ] Deploy `procurement-api`
6. [ ] Deploy `data-intelligence-api`

### Post-Deployment
- [ ] Verify all health endpoints return 200
- [ ] Test API endpoints
- [ ] Verify worker is processing messages
- [ ] Check logs for errors
- [ ] Monitor metrics
- [ ] Test scaling behavior

---

## 🚨 Critical Recommendations

### 1. **Worker Extraction**
Consider extracting embedded workers to standalone deployments:
- **orders notification_worker** - Currently embedded, should be separate
- **data_intelligence outbox_consumer** - Currently embedded, should be separate

**Benefits:**
- Independent scaling
- Better resource utilization
- Isolated failure domains
- Easier monitoring

### 2. **Database Migration**
Implement proper migration strategy:
- Remove `Base.metadata.create_all()` from all services
- Use Alembic for migrations
- Run migrations as Container App Jobs
- Version control schema changes

### 3. **Service Mesh**
Consider Azure Service Mesh (Dapr) for:
- Service-to-service communication
- Distributed tracing
- Secrets management
- Pub/sub patterns

### 4. **Cost Optimization**
- Use **spot instances** for non-critical workers
- Scale to zero for development environments
- Use **consumption plan** for low-traffic APIs

---

## 📞 Useful Commands

### Update Container App
```bash
az containerapp update `
  --name <app-name> `
  --resource-group $RESOURCE_GROUP `
  --image ${REGISTRY_NAME}.azurecr.io/<image>:latest
```

### Scale Manually
```bash
az containerapp update `
  --name <app-name> `
  --resource-group $RESOURCE_GROUP `
  --min-replicas 3 `
  --max-replicas 15
```

### Delete Container App
```bash
az containerapp delete `
  --name <app-name> `
  --resource-group $RESOURCE_GROUP `
  --yes
```

### View All Container Apps
```bash
az containerapp list `
  --resource-group $RESOURCE_GROUP `
  --output table
```

---

## 📚 Additional Resources
- [Azure Container Apps Documentation](https://learn.microsoft.com/azure/container-apps/)
- [Scaling in Container Apps](https://learn.microsoft.com/azure/container-apps/scale-app)
- [Dapr Integration](https://learn.microsoft.com/azure/container-apps/dapr-overview)
