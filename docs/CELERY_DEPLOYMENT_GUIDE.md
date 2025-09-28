# ZeroQue Celery Workers Deployment Guide

## Overview

ZeroQue uses Celery workers for asynchronous event processing across all microservices. This guide covers deployment strategies, worker types, and monitoring.

## Architecture

### Event Flow

```
Service → Event Bus → Redis Stream → Celery Worker → Processing Task
```

### Worker Types

| Worker                  | Queues                               | Concurrency | Purpose                        | Priority |
| ----------------------- | ------------------------------------ | ----------- | ------------------------------ | -------- |
| **orders-worker**       | orders                               | 8           | Order processing, fulfillment  | High     |
| **inventory-worker**    | inventory                            | 4           | Stock updates, movements       | High     |
| **pricing-worker**      | pricing                              | 6           | Price calculations, rules      | Medium   |
| **notification-worker** | notifications                        | 4           | Email, SMS, push notifications | Medium   |
| **webhook-worker**      | webhooks                             | 2           | External API webhooks          | Low      |
| **catalog-worker**      | catalog                              | 3           | Product updates, search index  | Medium   |
| **analytics-worker**    | analytics                            | 2           | Reporting, metrics             | Low      |
| **general-worker**      | default,budget,provisioning,identity | 4           | General tasks                  | Low      |

## Deployment Options

### 1. Development (Single Machine)

```bash
# Start all workers with one command
./scripts/celery_workers.sh

# Or start individual workers
celery -A zeroque_common.events.celery_app worker --queues=orders --concurrency=4
```

### 2. Production (Docker Compose)

```bash
# Start all workers with Docker
docker-compose -f docker-compose.workers.yml up -d

# Scale specific workers
docker-compose -f docker-compose.workers.yml up -d --scale celery-orders=3
```

### 3. Kubernetes Deployment

```yaml
# Example Kubernetes deployment for orders worker
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-orders-worker
spec:
  replicas: 3
  selector:
    matchLabels:
      app: celery-orders-worker
  template:
    metadata:
      labels:
        app: celery-orders-worker
    spec:
      containers:
        - name: celery-worker
          image: zeroque:latest
          command:
            ["celery", "-A", "zeroque_common.events.celery_app", "worker"]
          args: ["--queues=orders", "--concurrency=8", "--loglevel=info"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: zeroque-secrets
                  key: database-url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: zeroque-secrets
                  key: redis-url
          resources:
            requests:
              memory: "512Mi"
              cpu: "500m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
```

## Worker Configuration

### Concurrency Settings

```python
# Optimal concurrency based on task type
HIGH_IO_TASKS = 2-4    # Webhooks, notifications
CPU_INTENSIVE = 4-8    # Pricing calculations, analytics
DATABASE_HEAVY = 2-4    # Order processing, inventory
```

### Resource Allocation

| Worker Type   | Memory | CPU       | Storage |
| ------------- | ------ | --------- | ------- |
| Orders        | 1GB    | 1 core    | 10GB    |
| Inventory     | 512MB  | 0.5 core  | 5GB     |
| Pricing       | 1GB    | 1 core    | 5GB     |
| Notifications | 512MB  | 0.5 core  | 2GB     |
| Webhooks      | 256MB  | 0.25 core | 1GB     |
| Catalog       | 512MB  | 0.5 core  | 5GB     |
| Analytics     | 512MB  | 0.5 core  | 10GB    |
| General       | 512MB  | 0.5 core  | 2GB     |

## Monitoring & Observability

### Health Checks

```bash
# Check worker status
celery -A zeroque_common.events.celery_app inspect active

# Check queue lengths
curl http://localhost:8200/events/queues/status

# Check Redis stream
redis-cli -h localhost -p 4000 XLEN zeroque:events
```

### Metrics Collection

```python
# Worker metrics to monitor
- Task execution time
- Queue length
- Worker memory usage
- Failed task count
- Retry attempts
- Dead letter queue size
```

### Logging

```bash
# View worker logs
tail -f /tmp/celery_*.log

# Docker logs
docker logs zeroque_celery_orders

# Kubernetes logs
kubectl logs -f deployment/celery-orders-worker
```

## Scaling Strategies

### Horizontal Scaling

```bash
# Scale orders workers for high load
docker-compose -f docker-compose.workers.yml up -d --scale celery-orders=5

# Scale pricing workers during peak hours
kubectl scale deployment celery-pricing-worker --replicas=8
```

### Vertical Scaling

```bash
# Increase concurrency for high-performance workers
celery -A zeroque_common.events.celery_app worker --queues=orders --concurrency=16
```

### Auto-scaling (Kubernetes)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: celery-orders-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: celery-orders-worker
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

## Performance Optimization

### Queue Routing

```python
# Route tasks to appropriate queues
task_routes = {
    'zeroque_common.events.tasks.process_order_event': {'queue': 'orders'},
    'zeroque_common.events.tasks.process_inventory_event': {'queue': 'inventory'},
    'zeroque_common.events.tasks.process_pricing_event': {'queue': 'pricing'},
}
```

### Task Optimization

```python
# Use task retry with exponential backoff
@celery_app.task(bind=True, max_retries=3)
def process_order_event(self, event_data):
    try:
        # Process event
        pass
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

### Memory Management

```python
# Configure worker memory limits
worker_max_memory_per_child = 200000  # 200MB
worker_max_tasks_per_child = 1000     # Restart after 1000 tasks
```

## Troubleshooting

### Common Issues

1. **Workers not processing tasks**

   ```bash
   # Check Redis connection
   redis-cli -h localhost -p 4000 ping

   # Check worker registration
   celery -A zeroque_common.events.celery_app inspect active
   ```

2. **High memory usage**

   ```bash
   # Monitor worker memory
   celery -A zeroque_common.events.celery_app inspect stats

   # Restart workers
   docker-compose -f docker-compose.workers.yml restart celery-orders
   ```

3. **Task failures**

   ```bash
   # Check failed tasks
   celery -A zeroque_common.events.celery_app inspect failed

   # Retry failed tasks
   celery -A zeroque_common.events.celery_app control retry_failed
   ```

### Debugging

```bash
# Enable debug logging
celery -A zeroque_common.events.celery_app worker --loglevel=debug

# Monitor task execution
celery -A zeroque_common.events.celery_app events

# Check queue status
celery -A zeroque_common.events.celery_app inspect reserved
```

## Security Considerations

### Network Security

```yaml
# Docker network isolation
networks:
  zeroque-internal:
    driver: bridge
    internal: true
```

### Access Control

```python
# Redis authentication
REDIS_URL = "redis://:password@localhost:4000/0"

# Database connection pooling
DATABASE_URL = "postgresql://user:password@localhost:5000/zeroque_dev?sslmode=require"
```

### Task Security

```python
# Validate task data
@celery_app.task
def process_sensitive_event(event_data):
    # Validate event data
    if not validate_event_data(event_data):
        raise ValueError("Invalid event data")

    # Process with proper error handling
    try:
        process_event(event_data)
    except Exception as e:
        log_error(e)
        raise
```

## Best Practices

1. **Use appropriate concurrency** based on task type
2. **Monitor queue lengths** and scale accordingly
3. **Implement proper error handling** and retry logic
4. **Use dead letter queues** for failed tasks
5. **Monitor resource usage** and optimize accordingly
6. **Implement circuit breakers** for external service calls
7. **Use task priorities** for critical operations
8. **Implement graceful shutdown** for workers

## Production Checklist

- [ ] Redis cluster configured for high availability
- [ ] Database connection pooling configured
- [ ] Worker health checks implemented
- [ ] Monitoring and alerting configured
- [ ] Log aggregation configured
- [ ] Backup and recovery procedures tested
- [ ] Security policies implemented
- [ ] Performance benchmarks established
- [ ] Disaster recovery plan documented
- [ ] Load testing completed
