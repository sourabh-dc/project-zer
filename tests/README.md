# ZeroQue Tests - Production Ready

This directory contains production-ready test suites for the ZeroQue microservices platform.

## Structure

```
tests/
├── test_config.py          # Centralized test configuration
├── test_health_checks.py   # Health check tests for all services
├── test_integration.py     # Integration flow tests
├── integration/            # Service-specific integration tests
├── load/                   # Load testing with Locust
└── README.md              # This file
```

## Running Tests

### Health Checks
```bash
python test_health_checks.py
```

### Integration Tests
```bash
python test_integration.py
```

### Load Tests
```bash
cd load
locust -f locustfile.py --host=http://localhost:8212
```

## Test Configuration

All test configurations are centralized in `test_config.py`:
- Service ports and endpoints
- Test data (tenant IDs, user IDs, etc.)
- Timeout and retry settings

## Service Ports

The tests use the following service ports:
- Provisioning: 8212
- Catalog: 8215
- Entry: 8218
- Orders: 8224
- Identity: 8219
- Pricing: 8226
- Payments: 8225
- Billing: 8214
- Ledger: 8220
- Events: 8211
- Notifications: 8222
- Monitoring: 8221
- Observability: 8223
- Reports: 8227
- Approvals: 8213
- CV Connector: 8216
- CV Gateway: 8217
- Usage: 8210
- Entitlements: 8209
- Subscriptions: 8208
- Service Registry: 8207

## Production Readiness

This test suite is designed for production use with:
- Centralized configuration
- Proper error handling
- Timeout and retry logic
- Comprehensive health checks
- Integration flow validation
- Load testing capabilities
