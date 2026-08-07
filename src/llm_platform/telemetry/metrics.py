from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram


@dataclass(frozen=True, slots=True)
class PlatformMetrics:
    requests: Counter
    route_seconds: Histogram
    request_seconds: Histogram
    queue_wait_seconds: Histogram
    active_requests: Gauge
    backend_state: Gauge
    profile_switches: Counter
    cancellations: Counter
    routing_collapses: Counter


METRICS = PlatformMetrics(
    requests=Counter("llm_platform_requests_total", "Gateway requests", ("endpoint", "status")),
    route_seconds=Histogram("llm_platform_route_seconds", "Routing decision latency"),
    request_seconds=Histogram(
        "llm_platform_request_seconds", "End-to-end request duration", ("deployment",)
    ),
    queue_wait_seconds=Histogram("llm_platform_queue_wait_seconds", "Queue wait duration"),
    active_requests=Gauge(
        "llm_platform_active_requests", "Active backend requests", ("deployment",)
    ),
    backend_state=Gauge(
        "llm_platform_backend_state", "Backend state one-hot value", ("deployment", "state")
    ),
    profile_switches=Counter("llm_platform_profile_switches_total", "Profile switches"),
    cancellations=Counter("llm_platform_cancellations_total", "Request cancellations"),
    routing_collapses=Counter(
        "llm_platform_routing_collapses_total", "Unsafe or low-diversity routing detections"
    ),
)
