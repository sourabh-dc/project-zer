# ZeroQue V2 - Multi-Tenant Marketplace Platform

## 🚀 Overview

ZeroQue V2 is a comprehensive **multi-tenant marketplace platform** for retail operations, built as a microservices architecture with enhanced capabilities for vendor management, marketplace operations, and advanced pricing. The system implements a **flexible multi-tenant model** where tenants can have multiple sites, stores can belong to multiple sites, and vendors can serve multiple stores.

## 🏗️ Architecture

### Core Services (V2)

| Service          | Port | Description                                | Status                  |
| ---------------- | ---- | ------------------------------------------ | ----------------------- |
| **Provisioning** | 8201 | Tenant, site, store, user management       | ✅ **Production Ready** |
| **Orders**       | 8203 | Order processing with saga orchestration   | ✅ **Production Ready** |
| **Pricing**      | 8209 | Advanced pricing with pricebooks and rules | ✅ **Production Ready** |

### Infrastructure Services

| Service        | Port | Description                 |
| -------------- | ---- | --------------------------- |
| **PostgreSQL** | 5000 | Primary database with RLS   |
| **Redis**      | 4000 | Caching and event streaming |

## 🎯 Key Features

### Multi-Tenancy

- **Complete Tenant Isolation**: Row-Level Security (RLS) on all tables
- **Flexible Hierarchies**: Parent-child tenant relationships
- **Shared Resources**: Sites and stores can serve multiple tenants

### Marketplace Model

- **Vendor Management**: Complete vendor onboarding and management
- **Product Catalog**: Master products with variants and vendor-specific offers
- **Assortment Management**: Store-specific product assortments
- **Customer Segmentation**: Targeted pricing and promotions

### Advanced Pricing

- **Pricebook System**: Hierarchical pricing with assignments
- **Dynamic Rules**: Complex pricing rules with conditions
- **Promotions**: Time-based promotional pricing
- **Multi-Currency**: Exchange rate support with currency conversion

### Order Management

- **Saga Pattern**: Distributed transaction management
- **Sub-Orders**: Vendor-specific order splitting
- **Vendor Splits**: Commission and settlement tracking
- **Returns & Refunds**: Complete return management

### Event-Driven Architecture

- **Service Bus**: Redis Streams for inter-service communication
- **Event Sourcing**: Complete audit trail
- **Circuit Breaker**: Resilient external service calls
- **Health Monitoring**: Comprehensive service health checks

## 🛠️ Technology Stack

### Backend

- **Python 3.13** - Core runtime
- **FastAPI** - Web framework with automatic OpenAPI documentation
- **SQLAlchemy** - ORM with advanced features
- **Pydantic** - Data validation and serialization
- **Alembic** - Database migrations

### Database

- **PostgreSQL 15** - Primary database with advanced features
- **Row-Level Security (RLS)** - Tenant isolation
- **Partitioning** - Performance optimization
- **JSONB** - Flexible data storage
- **Custom Types** - Type safety with enums

### Caching & Events

- **Redis 7** - Caching and event streaming
- **Redis Streams** - Event bus implementation
- **Celery** - Asynchronous task processing

### Monitoring & Observability

- **OpenTelemetry** - Distributed tracing
- **Prometheus** - Metrics collection
- **Structured Logging** - JSON-formatted logs
- **Health Checks** - Service monitoring

## 📋 Prerequisites

- **Python 3.13+**
- **PostgreSQL 15+**
- **Redis 7+**
- **Docker & Docker Compose** (optional)

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd zeroque-sprint15-working-copy
```

### 2. Setup Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Database Setup

```bash
# Start PostgreSQL and Redis
docker-compose up postgres redis -d

# Run migrations
alembic upgrade head

# Verify database
psql -h localhost -p 5000 -U zeroque -d zeroque_dev -c "\dt"
```

### 4. Start Services

```bash
# Start all V2 services
docker-compose up provisioning orders pricing -d

# Or start individually
uvicorn services.provisioning.main:app --port 8201 --reload
uvicorn services.orders.main:app --port 8203 --reload
uvicorn services.pricing.main:app --port 8209 --reload
```

### 5. Verify Installation

```bash
# Health check
curl http://localhost:8201/health  # Provisioning
curl http://localhost:8203/health  # Orders
curl http://localhost:8209/health  # Pricing

# API documentation
open http://localhost:8201/docs  # Provisioning API
open http://localhost:8203/docs  # Orders API
open http://localhost:8209/docs  # Pricing API
```

## 📚 API Documentation

### Provisioning Service (Port 8201)

- **Base URL**: `http://localhost:8201`
- **Documentation**: `http://localhost:8201/docs`
- **Endpoints**:
  - `GET/POST /provisioning/v2/tenants` - Tenant management
  - `GET/POST /provisioning/v2/sites` - Site management
  - `GET/POST /provisioning/v2/stores` - Store management
  - `GET/POST /provisioning/v2/users` - User management

### Orders Service (Port 8203)

- **Base URL**: `http://localhost:8203`
- **Documentation**: `http://localhost:8203/docs`
- **Endpoints**:
  - `POST /orders/v2` - Create orders with saga orchestration
  - `GET /orders/v2` - List orders
  - `GET /orders/v2/{order_id}` - Get order details
  - `POST /orders/v2/returns` - Create returns
  - `POST /orders/v2/refunds` - Create refunds

### Pricing Service (Port 8209)

- **Base URL**: `http://localhost:8209`
- **Documentation**: `http://localhost:8209/docs`
- **Endpoints**:
  - `POST /pricing/v2/resolve` - Resolve prices
  - `GET/POST /pricing/v2/pricebooks` - Pricebook management
  - `GET/POST /pricing/v2/price-rules` - Price rule management
  - `GET /pricing/v2/calculated-prices` - Cached prices

## 🧪 Testing

### Unit Tests

```bash
# Run tests for all services
pytest services/provisioning/tests/
pytest services/orders/tests/
pytest services/pricing/tests/
```

### Integration Tests

```bash
# Test API endpoints
curl -X POST "http://localhost:8201/provisioning/v2/tenants" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Tenant", "type": "marketplace", "active": true}'

curl -X POST "http://localhost:8203/orders/v2" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "store_id": "550e8400-e29b-41d4-a716-446655440002",
    "customer_id": "550e8400-e29b-41d4-a716-446655440001",
    "currency": "GBP",
    "items": [{"offer_id": "579ad27d-48f0-430a-84f5-bfec84524756", "quantity": 2}]
  }'
```

### Load Testing

```bash
# Use scripts for comprehensive testing
./scripts/test_all_endpoints.sh
./scripts/health_check.sh
```

## 🔧 Development

### Project Structure

```
zeroque-sprint15-working-copy/
├── services/
│   ├── provisioning/          # Tenant, site, store management
│   ├── orders/                # Order processing with sagas
│   └── pricing/               # Advanced pricing engine
├── packages/
│   └── zeroque_common/        # Shared utilities and models
├── alembic/                   # Database migrations
├── scripts/                   # Utility scripts
├── docker-compose.yml         # Service orchestration
└── README_v2.md              # This file
```

### Database Migrations

```bash
# Create new migration
alembic revision -m "description of changes"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# Check current revision
alembic current
```

### Adding New Services

1. Create service directory: `services/new_service/`
2. Add `main.py` with FastAPI app
3. Update `docker-compose.yml`
4. Add service to scripts
5. Update documentation

## 📊 Monitoring

### Health Checks

```bash
# Check all services
curl http://localhost:8201/health
curl http://localhost:8203/health
curl http://localhost:8209/health

# Detailed health information
curl http://localhost:8201/health/detailed
```

### Metrics

- **Prometheus**: `http://localhost:9090`
- **Service Metrics**: Available at `/metrics` endpoint
- **Custom Metrics**: Business-specific metrics in each service

### Logging

```bash
# View service logs
docker-compose logs provisioning
docker-compose logs orders
docker-compose logs pricing

# Follow logs in real-time
docker-compose logs -f provisioning
```

## 🔒 Security

### Row-Level Security (RLS)

- All tables have RLS policies for tenant isolation
- Automatic tenant context setting in all operations
- Secure multi-tenant data access

### Authentication & Authorization

- JWT-based authentication (planned)
- Role-based access control (RBAC)
- Permission-based authorization

### Data Protection

- Sensitive data encryption at rest
- Secure communication between services
- Audit logging for all operations

## 🚀 Deployment

### Docker Deployment

```bash
# Build and start all services
docker-compose up --build -d

# Scale services
docker-compose up --scale orders=3 -d

# Stop services
docker-compose down
```

### Production Considerations

- **Environment Variables**: Configure via `.env` files
- **Secrets Management**: Use secure secret management
- **Load Balancing**: Deploy behind load balancer
- **Monitoring**: Set up comprehensive monitoring
- **Backup**: Regular database backups

## 📈 Performance

### Database Optimization

- **Indexing**: Comprehensive indexes on all foreign keys
- **Partitioning**: Large tables partitioned by date
- **Connection Pooling**: Optimized connection management
- **Query Optimization**: Efficient queries with proper joins

### Caching Strategy

- **Redis Caching**: Frequently accessed data cached
- **Price Caching**: Calculated prices cached with TTL
- **Session Caching**: User sessions cached
- **Query Result Caching**: Expensive query results cached

### Scalability

- **Horizontal Scaling**: Services can be scaled independently
- **Database Sharding**: Planned for future scaling
- **Microservices**: Independent service scaling
- **Event-Driven**: Asynchronous processing

## 🤝 Contributing

### Development Workflow

1. **Fork** the repository
2. **Create** feature branch: `git checkout -b feature/new-feature`
3. **Commit** changes: `git commit -m "Add new feature"`
4. **Push** to branch: `git push origin feature/new-feature`
5. **Create** Pull Request

### Code Standards

- **Python**: Follow PEP 8 style guide
- **Type Hints**: Use type hints for all functions
- **Documentation**: Document all public APIs
- **Testing**: Write tests for new features
- **Linting**: Use black, flake8, mypy

### Pull Request Process

1. Ensure all tests pass
2. Update documentation if needed
3. Add tests for new features
4. Request code review
5. Address feedback
6. Merge after approval

## 📞 Support

### Documentation

- **API Documentation**: Available at `/docs` endpoint for each service
- **Architecture Documentation**: See `architecture_v4.1.md`
- **Database Schema**: See `status_quo.md`
- **ER Diagram**: See `er_diagram.md`

### Troubleshooting

- **Common Issues**: Check service logs
- **Health Checks**: Verify service health endpoints
- **Database Issues**: Check migration status
- **Performance Issues**: Monitor metrics and logs

### Getting Help

- **Issues**: Create GitHub issues for bugs
- **Discussions**: Use GitHub discussions for questions
- **Documentation**: Check existing documentation first

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🎉 Acknowledgments

- **FastAPI** - Modern web framework for Python
- **SQLAlchemy** - Powerful ORM for Python
- **PostgreSQL** - Advanced open-source database
- **Redis** - In-memory data structure store
- **Docker** - Containerization platform

---

**ZeroQue V2** - Building the future of retail technology 🚀
