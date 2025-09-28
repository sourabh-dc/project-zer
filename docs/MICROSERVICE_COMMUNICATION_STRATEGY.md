# ZeroQue Microservice Communication Strategy

## Current Architecture Assessment

### ✅ Strengths of Current System

- **Redis Streams**: Reliable event streaming with consumer groups
- **Celery**: Robust async task processing with specialized queues
- **Event Bus**: Centralized event publishing/subscribing
- **HTTP APIs**: Direct service-to-service communication
- **Service Discovery**: Built-in health checks and monitoring

### 🎯 Recommendation: Enhance Current System

Rather than replacing your current architecture, we recommend **enhancing** it with additional communication patterns.

## Enhanced Communication Patterns

### 1. **Event-Driven Communication (Primary)**

#### Current Implementation

```python
# Event Publishing
event = Event(
    event_type=EventType.ORDER_CREATED,
    tenant_id="tenant-123",
    data={"order_id": "123", "total": 1000}
)
await event_bus.publish(event)

# Event Processing
@celery_app.task(queue="orders")
def process_order_event(event_data):
    # Process order event
    pass
```

#### Enhanced Implementation

```python
# Service-to-Service Events
class ServiceEventBus:
    def __init__(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.service_streams = {
            "orders": "zeroque:orders:events",
            "inventory": "zeroque:inventory:events",
            "pricing": "zeroque:pricing:events",
            "billing": "zeroque:billing:events"
        }

    async def publish_service_event(self, service: str, event_type: str, data: dict):
        stream_name = self.service_streams[service]
        event_data = {
            "event_type": event_type,
            "service": service,
            "data": json.dumps(data),
            "timestamp": datetime.now().isoformat()
        }
        return self.redis_client.xadd(stream_name, event_data)

    async def subscribe_to_service(self, service: str, handler: callable):
        stream_name = self.service_streams[service]
        consumer_group = f"{service}_consumers"

        # Create consumer group
        try:
            self.redis_client.xgroup_create(stream_name, consumer_group, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            pass

        # Start consuming
        while True:
            messages = self.redis_client.xreadgroup(
                consumer_group,
                f"consumer_{os.getpid()}",
                {stream_name: ">"},
                count=10
            )

            for stream, msgs in messages:
                for msg_id, fields in msgs:
                    await handler(fields)
                    self.redis_client.xack(stream_name, consumer_group, msg_id)
```

### 2. **Saga Pattern for Distributed Transactions**

#### Implementation

```python
class OrderSaga:
    def __init__(self):
        self.steps = [
            "validate_inventory",
            "reserve_inventory",
            "process_payment",
            "update_inventory",
            "send_notification"
        ]
        self.compensation_steps = [
            "release_inventory",
            "refund_payment",
            "restore_inventory"
        ]

    async def execute_saga(self, order_data: dict):
        executed_steps = []

        try:
            for step in self.steps:
                result = await self.execute_step(step, order_data)
                executed_steps.append((step, result))

                # Publish step completion event
                await event_bus.publish(Event(
                    event_type=EventType.SAGA_STEP_COMPLETED,
                    data={"step": step, "result": result}
                ))

        except Exception as e:
            # Compensate executed steps
            await self.compensate(executed_steps)
            raise

    async def execute_step(self, step: str, data: dict):
        if step == "validate_inventory":
            return await self.validate_inventory(data)
        elif step == "reserve_inventory":
            return await self.reserve_inventory(data)
        # ... other steps

    async def compensate(self, executed_steps: list):
        for step, result in reversed(executed_steps):
            compensation_step = self.get_compensation_step(step)
            if compensation_step:
                await self.execute_step(compensation_step, result)
```

### 3. **Circuit Breaker Pattern**

#### Implementation

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    async def call_service(self, service_url: str, payload: dict):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(service_url, json=payload)
                response.raise_for_status()

                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    self.failure_count = 0

                return response.json()

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

            raise e

# Usage in services
circuit_breaker = CircuitBreaker()

async def call_pricing_service(self, payload: dict):
    try:
        return await circuit_breaker.call_service(
            "http://localhost:8209/pricing/calculate",
            payload
        )
    except Exception as e:
        # Fallback to cached pricing or default logic
        return await self.get_fallback_pricing(payload)
```

### 4. **Service Mesh Integration**

#### Istio Service Mesh Configuration

```yaml
# istio-config.yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: zeroque-services
spec:
  http:
    - match:
        - uri:
            prefix: /provisioning/
      route:
        - destination:
            host: provisioning-service
            port:
              number: 8201
    - match:
        - uri:
            prefix: /orders/
      route:
        - destination:
            host: orders-service
            port:
              number: 8208
---
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: zeroque-services
spec:
  host: "*.zeroque.svc.cluster.local"
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        http1MaxPendingRequests: 10
        maxRequestsPerConnection: 2
    circuitBreaker:
      consecutiveErrors: 3
      interval: 30s
      baseEjectionTime: 30s
```

### 5. **API Gateway Integration**

#### Kong API Gateway Configuration

```yaml
# kong-config.yaml
services:
  - name: zeroque-provisioning
    url: http://provisioning-service:8201
    routes:
      - name: provisioning-route
        paths:
          - /provisioning
        plugins:
          - name: rate-limiting
            config:
              minute: 100
          - name: circuit-breaker
            config:
              threshold: 5
              timeout: 60

  - name: zeroque-orders
    url: http://orders-service:8208
    routes:
      - name: orders-route
        paths:
          - /orders
        plugins:
          - name: rate-limiting
            config:
              minute: 200
          - name: request-transformer
            config:
              add:
                headers:
                  - "X-Service: orders"
```

## Implementation Roadmap

### Phase 1: Enhanced Event System (Week 1-2)

1. **Service-Specific Event Streams**

   - Create dedicated Redis streams for each service
   - Implement service-to-service event publishing
   - Add event versioning and schema validation

2. **Event Sourcing**
   - Store all events in event store
   - Implement event replay capabilities
   - Add event snapshots for performance

### Phase 2: Saga Pattern (Week 3-4)

1. **Distributed Transaction Management**

   - Implement saga orchestrator
   - Add compensation logic
   - Create saga monitoring dashboard

2. **Event Choreography**
   - Replace some HTTP calls with events
   - Implement event-driven workflows
   - Add event correlation IDs

### Phase 3: Resilience Patterns (Week 5-6)

1. **Circuit Breakers**

   - Add circuit breaker to all service calls
   - Implement fallback mechanisms
   - Create circuit breaker monitoring

2. **Retry and Timeout**
   - Add exponential backoff retry
   - Implement request timeouts
   - Add dead letter queues

### Phase 4: Advanced Features (Week 7-8)

1. **Service Mesh**

   - Deploy Istio service mesh
   - Configure traffic management
   - Add security policies

2. **API Gateway**
   - Deploy Kong API gateway
   - Configure routing and plugins
   - Add authentication and authorization

## Monitoring and Observability

### Event System Monitoring

```python
class EventMonitor:
    def __init__(self):
        self.redis_client = redis.from_url(REDIS_URL)

    def get_event_metrics(self):
        metrics = {}
        for service in ["orders", "inventory", "pricing", "billing"]:
            stream_name = f"zeroque:{service}:events"
            try:
                info = self.redis_client.xinfo_stream(stream_name)
                metrics[service] = {
                    "length": info.get("length", 0),
                    "first_entry": info.get("first-entry"),
                    "last_entry": info.get("last-entry"),
                    "groups": info.get("groups", 0)
                }
            except redis.exceptions.ResponseError:
                metrics[service] = {"error": "Stream not found"}
        return metrics

    def get_celery_metrics(self):
        inspect = celery_app.control.inspect()
        return {
            "active_tasks": inspect.active(),
            "scheduled_tasks": inspect.scheduled(),
            "reserved_tasks": inspect.reserved(),
            "stats": inspect.stats()
        }
```

### Service Health Monitoring

```python
class ServiceHealthMonitor:
    def __init__(self):
        self.services = {
            "provisioning": "http://localhost:8201",
            "catalog": "http://localhost:8202",
            "orders": "http://localhost:8208",
            "pricing": "http://localhost:8209",
            "billing": "http://localhost:8206"
        }

    async def check_all_services(self):
        health_status = {}
        for service_name, url in self.services.items():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{url}/health")
                    health_status[service_name] = {
                        "status": "healthy" if response.status_code == 200 else "unhealthy",
                        "response_time": response.elapsed.total_seconds(),
                        "timestamp": datetime.now().isoformat()
                    }
            except Exception as e:
                health_status[service_name] = {
                    "status": "unreachable",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }
        return health_status
```

## Benefits of Enhanced Architecture

### 1. **Reliability**

- Circuit breakers prevent cascade failures
- Saga pattern ensures data consistency
- Event sourcing provides audit trail

### 2. **Scalability**

- Redis Streams handle high throughput
- Celery workers can scale horizontally
- Service mesh provides load balancing

### 3. **Observability**

- Comprehensive event monitoring
- Service health tracking
- Performance metrics collection

### 4. **Maintainability**

- Clear separation of concerns
- Event-driven architecture
- Centralized configuration

## Conclusion

Your current Redis Streams + Celery architecture is **excellent** and doesn't need to be replaced. Instead, we recommend enhancing it with:

1. **Service-specific event streams** for better isolation
2. **Saga pattern** for distributed transactions
3. **Circuit breakers** for resilience
4. **Service mesh** for advanced traffic management
5. **API gateway** for centralized API management

This approach will give you the benefits of modern microservice communication patterns while building on your existing, proven infrastructure.
