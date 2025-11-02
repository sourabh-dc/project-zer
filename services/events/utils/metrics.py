from prometheus_client import Counter, Gauge, Histogram

from .events_logger import logger
# Prometheus metrics - initialize as None first
event_publish_total = None
event_publish_duration = None
event_consume_total = None
event_retry_total = None
queue_length = None
queue_latency = None
consumer_failures = None
event_processing_duration = None

# Register metrics with unique names
try:
    from prometheus_client import CollectorRegistry, REGISTRY

    registry = CollectorRegistry()

    event_publish_total = Counter('events_publish_total', 'Total events published', ['event_type', 'status'],
                                  registry=registry)
    event_publish_duration = Histogram('events_publish_duration_seconds', 'Event publish duration', ['event_type'],
                                       registry=registry)
    event_consume_total = Counter('events_consume_total', 'Total events consumed', ['event_type', 'status'],
                                  registry=registry)
    event_retry_total = Counter('events_retry_total', 'Total event retries', ['event_type'], registry=registry)
    queue_length = Gauge('events_queue_length', 'Current queue length', ['queue_name'], registry=registry)
    queue_latency = Gauge('events_queue_latency_seconds', 'Queue processing latency', ['queue_name', 'event_type'],
                          registry=registry)
    consumer_failures = Counter('events_consumer_failures_total', 'Total consumer failures',
                                ['service_name', 'event_type', 'reason'], registry=registry)
    event_processing_duration = Histogram('events_processing_duration_seconds', 'Event processing duration',
                                          ['service_name', 'event_type'], registry=registry)

    # Merge with default registry
    for metric in registry.collect():
        REGISTRY.register(metric)

except Exception as e:
    logger.warning(f"Failed to register Prometheus metrics: {e}")