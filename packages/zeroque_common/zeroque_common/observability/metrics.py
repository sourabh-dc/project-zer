# packages/zeroque_common/zeroque_common/observability/metrics.py
"""
Metrics collection and monitoring for ZeroQue services
"""
import time
import psutil
import threading
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict, deque
import logging

log = logging.getLogger("metrics")

@dataclass
class MetricPoint:
    """A single metric data point"""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)
    unit: str = ""

@dataclass
class Counter:
    """Counter metric that only increases"""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    
    def inc(self, amount: float = 1.0):
        self.value += amount
    
    def get_point(self) -> MetricPoint:
        return MetricPoint(
            name=self.name,
            value=self.value,
            timestamp=datetime.now(timezone.utc),
            labels=self.labels
        )

@dataclass
class Gauge:
    """Gauge metric that can increase or decrease"""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    
    def set(self, value: float):
        self.value = value
    
    def inc(self, amount: float = 1.0):
        self.value += amount
    
    def dec(self, amount: float = 1.0):
        self.value -= amount
    
    def get_point(self) -> MetricPoint:
        return MetricPoint(
            name=self.name,
            value=self.value,
            timestamp=datetime.now(timezone.utc),
            labels=self.labels
        )

@dataclass
class Histogram:
    """Histogram metric for measuring distributions"""
    name: str
    buckets: Dict[float, int] = field(default_factory=dict)
    count: int = 0
    sum: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        # Default buckets for common latencies
        if not self.buckets:
            self.buckets = {
                0.001: 0,  # 1ms
                0.005: 0,  # 5ms
                0.01: 0,   # 10ms
                0.05: 0,   # 50ms
                0.1: 0,    # 100ms
                0.5: 0,    # 500ms
                1.0: 0,    # 1s
                5.0: 0,    # 5s
                10.0: 0,   # 10s
                float('inf'): 0
            }
    
    def observe(self, value: float):
        self.count += 1
        self.sum += value
        
        for bucket in sorted(self.buckets.keys()):
            if value <= bucket:
                self.buckets[bucket] += 1
                break
    
    def get_points(self) -> list[MetricPoint]:
        points = []
        timestamp = datetime.now(timezone.utc)
        
        # Add count
        points.append(MetricPoint(
            name=f"{self.name}_count",
            value=self.count,
            timestamp=timestamp,
            labels=self.labels
        ))
        
        # Add sum
        points.append(MetricPoint(
            name=f"{self.name}_sum",
            value=self.sum,
            timestamp=timestamp,
            labels=self.labels
        ))
        
        # Add bucket counts
        for bucket, count in self.buckets.items():
            if bucket != float('inf'):
                points.append(MetricPoint(
                    name=f"{self.name}_bucket",
                    value=count,
                    timestamp=timestamp,
                    labels={**self.labels, "le": str(bucket)}
                ))
        
        return points

class MetricsCollector:
    """Central metrics collector for ZeroQue services"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.counters: Dict[str, Counter] = {}
        self.gauges: Dict[str, Gauge] = {}
        self.histograms: Dict[str, Histogram] = {}
        self.custom_metrics: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        
        # System metrics collection
        self._start_system_metrics()
    
    def _start_system_metrics(self):
        """Start collecting system metrics"""
        def collect_system_metrics():
            while True:
                try:
                    # CPU usage
                    cpu_percent = psutil.cpu_percent(interval=1)
                    self.gauge("system_cpu_percent").set(cpu_percent)
                    
                    # Memory usage
                    memory = psutil.virtual_memory()
                    self.gauge("system_memory_percent").set(memory.percent)
                    self.gauge("system_memory_mb").set(memory.used / 1024 / 1024)
                    
                    # Disk usage
                    disk = psutil.disk_usage('/')
                    self.gauge("system_disk_percent").set(disk.percent)
                    self.gauge("system_disk_mb").set(disk.used / 1024 / 1024)
                    
                    time.sleep(30)  # Collect every 30 seconds
                except Exception as e:
                    log.error("Error collecting system metrics: %s", str(e))
                    time.sleep(60)
        
        thread = threading.Thread(target=collect_system_metrics, daemon=True)
        thread.start()
    
    def counter(self, name: str, labels: Dict[str, str] = None) -> Counter:
        """Get or create a counter metric"""
        key = f"{name}:{str(labels or {})}"
        with self._lock:
            if key not in self.counters:
                self.counters[key] = Counter(name, labels=labels or {})
            return self.counters[key]
    
    def gauge(self, name: str, labels: Dict[str, str] = None) -> Gauge:
        """Get or create a gauge metric"""
        key = f"{name}:{str(labels or {})}"
        with self._lock:
            if key not in self.gauges:
                self.gauges[key] = Gauge(name, labels=labels or {})
            return self.gauges[key]
    
    def histogram(self, name: str, labels: Dict[str, str] = None) -> Histogram:
        """Get or create a histogram metric"""
        key = f"{name}:{str(labels or {})}"
        with self._lock:
            if key not in self.histograms:
                self.histograms[key] = Histogram(name, labels=labels or {})
            return self.histograms[key]
    
    def add_custom_metric(self, name: str, collector: Callable[[], MetricPoint]):
        """Add a custom metric collector"""
        self.custom_metrics[name] = collector
    
    def get_all_metrics(self) -> list[MetricPoint]:
        """Get all collected metrics"""
        metrics = []
        
        with self._lock:
            # Collect counter metrics
            for counter in self.counters.values():
                metrics.append(counter.get_point())
            
            # Collect gauge metrics
            for gauge in self.gauges.values():
                metrics.append(gauge.get_point())
            
            # Collect histogram metrics
            for histogram in self.histograms.values():
                metrics.extend(histogram.get_points())
        
        # Collect custom metrics
        for name, collector in self.custom_metrics.items():
            try:
                metrics.append(collector())
            except Exception as e:
                log.error("Error collecting custom metric %s: %s", name, str(e))
        
        return metrics
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics"""
        metrics = self.get_all_metrics()
        
        summary = {
            "service": self.service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_metrics": len(metrics),
            "metrics_by_type": defaultdict(int),
            "metrics": {}
        }
        
        for metric in metrics:
            metric_type = metric.name.split('_')[-1] if '_' in metric.name else 'gauge'
            summary["metrics_by_type"][metric_type] += 1
            
            if metric.name not in summary["metrics"]:
                summary["metrics"][metric.name] = {
                    "value": metric.value,
                    "labels": metric.labels,
                    "unit": metric.unit,
                    "timestamp": metric.timestamp.isoformat()
                }
        
        return dict(summary)

# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None

def init_metrics(service_name: str) -> MetricsCollector:
    """Initialize the global metrics collector"""
    global _metrics_collector
    _metrics_collector = MetricsCollector(service_name)
    return _metrics_collector

def get_metrics() -> MetricsCollector:
    """Get the global metrics collector"""
    if _metrics_collector is None:
        raise RuntimeError("Metrics not initialized. Call init_metrics() first.")
    return _metrics_collector

def counter(name: str, labels: Dict[str, str] = None) -> Counter:
    """Get a counter metric"""
    return get_metrics().counter(name, labels)

def gauge(name: str, labels: Dict[str, str] = None) -> Gauge:
    """Get a gauge metric"""
    return get_metrics().gauge(name, labels)

def histogram(name: str, labels: Dict[str, str] = None) -> Histogram:
    """Get a histogram metric"""
    return get_metrics().histogram(name, labels)

class MetricsMiddleware:
    """Middleware to automatically collect HTTP metrics"""
    
    def __init__(self, app, service_name: str):
        self.app = app
        self.service_name = service_name
        self.request_counter = counter("http_requests_total", {"service": service_name})
        self.request_duration = histogram("http_request_duration_seconds", {"service": service_name})
        self.active_requests = gauge("http_active_requests", {"service": service_name})
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        self.active_requests.inc()
        
        try:
            await self.app(scope, receive, send)
        finally:
            duration = time.time() - start_time
            self.request_duration.observe(duration)
            self.active_requests.dec()
            
            # Increment request counter
            self.request_counter.inc()
