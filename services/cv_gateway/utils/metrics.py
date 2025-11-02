# Metrics for CV Gateway (temporarily disabled to avoid conflicts)
class MetricStub:
    def labels(self, **kwargs):
        return self
    def inc(self): pass
    def observe(self, val): pass

cv_gateway_requests_total = MetricStub()
cv_gateway_request_duration = MetricStub()
cv_order_processing_total = MetricStub()
cv_order_processing_duration = MetricStub()
cv_saga_steps_total = MetricStub()
cv_unknown_items_total = MetricStub()