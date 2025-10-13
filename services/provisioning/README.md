# ZeroQue Provisioning Service v4.1.1

## Overview

The ZeroQue Provisioning Service is a production-ready microservice that handles the creation and management of core business entities including tenants, sites, stores, users, roles, vendors, and cost centres. It implements the Saga pattern for distributed transactions, uses the Outbox pattern for reliable event publishing, and includes comprehensive audit logging and monitoring.

## Features

✅ **Complete Saga Implementation**: All 7 entity types (Tenant, Site, Store, User, Role, Vendor, CostCentre) with compensation logic  
✅ **Outbox Pattern**: Reliable event publishing to RabbitMQ with retry logic  
✅ **Row-Level Security (RLS)**: Database-level tenant isolation  
✅ **Authentication**: API Key + JWT support with strict validation  
✅ **Subscription Limits**: Circuit breaker pattern with Redis caching  
✅ **Audit Logging**: Complete audit trail for all operations  
✅ **Celery Workers**: 5 event handlers + cleanup tasks with retry logic  
✅ **Metrics**: Prometheus metrics for monitoring  
✅ **Health Checks**: Comprehensive health and readiness endpoints

## Architecture

### Core Components

1. **FastAPI Application**: REST API with automatic OpenAPI documentation
2. **SQLAlchemy Models**: Database models with proper relationships and constraints
3. **Saga Pattern**: Distributed transaction management with compensation
4. **Outbox Pattern**: Reliable event publishing via RabbitMQ
5. **Celery Workers**: Background task processing for events and cleanup
6. **Redis Caching**: Subscription limits caching with circuit breaker
7. **Prometheus Metrics**: Request/saga duration and success metrics

### Database Schema

- `tenants_new`: Core tenant information
- `sites_new`: Sites within tenants
- `stores_new`: Stores within sites
- `users_new`: Users within tenants
- `roles_new`: System roles
- `vendors_new`: Vendors within tenants
- `cost_centres`: Cost centres for budget tracking
- `outbox_events`: Event publishing queue
- `audit_logs`: Complete audit trail

## API Endpoints

### Health & Monitoring

- `GET /health` - Service health check
- `GET /metrics` - Prometheus metrics

### Tenants

- `POST /provisioning/tenants` - Create tenant
- `GET /provisioning/tenants` - List tenants

### Sites

- `PUT /provisioning/sites/{site_id}` - Create site
- `GET /provisioning/sites` - List sites

### Stores

- `PUT /provisioning/stores/{store_id}` - Create store
- `GET /provisioning/stores` - List stores

### Users

- `PUT /provisioning/users/{user_id}` - Create user
- `GET /provisioning/users` - List users

### Roles

- `PUT /provisioning/roles/{role_id}` - Create role
- `GET /provisioning/roles` - List roles

### Vendors

- `PUT /provisioning/vendors/{vendor_id}` - Create vendor
- `GET /provisioning/vendors` - List vendors

### Cost Centres

- `POST /provisioning/cost-centres` - Create cost centre
- `GET /provisioning/cost-centres` - List cost centres

## Configuration

### Environment Variables

```bash
DATABASE_URL=postgresql://zeroque:zeroque@localhost:5432/zeroque_dev
RABBITMQ_URL=amqp://guest:guest@localhost:5672//
REDIS_URL=redis://localhost:6379/0
SUBSCRIPTIONS_SERVICE_URL=http://localhost:8010
JWT_SECRET_KEY=CHANGE-ME-IN-PRODUCTION
ALLOW_DEMO=false  # Set to true for development only
```

### Celery Configuration

The service uses `celeryconfig.py` for task routing and scheduling:

- **Event Processing**: `provisioning_events` queue
- **Maintenance Tasks**: `provisioning_maintenance` queue
- **Scheduled Tasks**: Outbox publishing (30s), cleanup (daily)

## Running the Service

### Prerequisites

1. PostgreSQL database
2. RabbitMQ message broker
3. Redis cache
4. Python 3.8+ with required dependencies

### Installation

```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary pika celery prometheus_client httpx tenacity pybreaker pyjwt redis
```

### Start the Service

```bash
# From project root
./start_provisioning_service.sh

# Or manually
cd services/provisioning
python3 main.py
```

### Start Celery Worker

```bash
cd services/provisioning
./run_worker.sh
```

### Start Celery Beat Scheduler

```bash
cd services/provisioning
./run_beat.sh
```

## Testing

### Run Comprehensive Tests

```bash
# Start the service first, then run tests
python3 test_provisioning_service.py
```

### Manual Testing Examples

```bash
# Health check
curl http://localhost:8000/health

# Create tenant (with demo API key)
curl -X POST http://localhost:8000/provisioning/tenants \
  -H "X-API-Key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{"name": "test_tenant", "tenant_type": "customer"}'

# List tenants
curl http://localhost:8000/provisioning/tenants \
  -H "X-API-Key: zq_demo_key_for_testing"
```

## Authentication

### API Key Authentication

```bash
curl -H "X-API-Key: your_api_key" http://localhost:8000/provisioning/tenants
```

### JWT Authentication

```bash
curl -H "Authorization: Bearer your_jwt_token" http://localhost:8000/provisioning/tenants
```

### Demo Mode (Development Only)

Set `ALLOW_DEMO=true` to enable demo mode with default credentials.

## Monitoring

### Metrics

The service exposes Prometheus metrics at `/metrics`:

- `prov_requests_total`: Request count by operation and status
- `prov_duration_seconds`: Request duration histogram
- `prov_saga_total`: Saga execution count by type and status
- `prov_saga_duration_seconds`: Saga execution duration

### Health Checks

- `GET /health`: Basic health check
- Database connectivity check
- Service version information

## Event Publishing

The service publishes events to RabbitMQ exchange `zeroque_events`:

- `TENANT_CREATED`
- `SITE_CREATED`
- `STORE_CREATED`
- `USER_CREATED`
- `ROLE_CREATED`
- `VENDOR_CREATED`
- `COST_CENTRE_CREATED`

## Error Handling

### Saga Compensation

All sagas implement compensation logic to rollback changes on failure:

1. Database transaction rollback
2. Outbox event cleanup
3. Audit log recording
4. Metrics recording

### Circuit Breaker

Subscription limits service calls use circuit breaker pattern:

- Max failures: 3
- Reset timeout: 30 seconds
- Fallback to default limits

### Retry Logic

- Outbox event publishing: 5 retries
- Cleanup tasks: 3 retries with exponential backoff
- Subscription limits: 3 retries with 1-second intervals

## Development

### Code Structure

```
services/provisioning/
├── main.py              # Main FastAPI application
├── celeryconfig.py      # Celery configuration
├── run_worker.sh        # Celery worker startup script
├── run_beat.sh          # Celery beat startup script
└── README.md           # This file
```

### Key Classes

- **Saga Classes**: `TenantSaga`, `SiteSaga`, `StoreSaga`, `UserSaga`, `RoleSaga`, `VendorSaga`, `CostCentreSaga`
- **Models**: SQLAlchemy models for all entities
- **Auth**: `get_user_context()` for authentication
- **RLS**: `set_rls()` for row-level security

## Production Deployment

### Security Considerations

1. **JWT Secret**: Use strong, unique JWT secret key
2. **Database**: Use connection pooling and SSL
3. **API Keys**: Implement proper API key management
4. **Demo Mode**: Disable demo mode (`ALLOW_DEMO=false`)
5. **Network**: Use HTTPS and proper firewall rules

### Scaling

1. **Horizontal Scaling**: Multiple FastAPI instances behind load balancer
2. **Database**: Read replicas for read-heavy operations
3. **Celery**: Multiple workers across different queues
4. **Redis**: Redis cluster for high availability
5. **RabbitMQ**: RabbitMQ cluster for message reliability

### Monitoring

1. **Prometheus**: Collect metrics from `/metrics` endpoint
2. **Grafana**: Create dashboards for key metrics
3. **Logging**: Structured logging with correlation IDs
4. **Alerting**: Set up alerts for error rates and latency

## Troubleshooting

### Common Issues

1. **Database Connection**: Check `DATABASE_URL` and PostgreSQL status
2. **RabbitMQ**: Verify `RABBITMQ_URL` and broker status
3. **Redis**: Check `REDIS_URL` and Redis server status
4. **Authentication**: Verify API keys or JWT tokens
5. **Outbox Events**: Check Celery worker status and logs

### Logs

The service logs important events:

- Request start/completion
- Saga execution results
- Event publishing status
- Error conditions
- Compensation actions

### Debug Mode

Set logging level to DEBUG for detailed troubleshooting:

```python
logging.basicConfig(level=logging.DEBUG)
```

## Version History

### v4.1.1 (Current)

- ✅ Fixed all indentation issues
- ✅ Added complete saga implementations for all entities
- ✅ Implemented proper JWT validation with demo mode
- ✅ Added Celery configuration with task routing
- ✅ Enhanced error handling in cleanup tasks
- ✅ Comprehensive test suite
- ✅ Production-ready with all gap fixes applied

## Support

For issues and questions:

1. Check the logs for error details
2. Verify all dependencies are installed
3. Ensure all required services are running
4. Run the test suite to identify issues
5. Check the health endpoint for service status
