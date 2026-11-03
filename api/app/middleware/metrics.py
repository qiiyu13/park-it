"""Prometheus metrics middleware and endpoint."""

import time

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Request metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Business metrics
payment_attempts_total = Counter(
    "payment_attempts_total",
    "Total payment attempts",
    ["method"],  # cash, rfid, emoney
)

payment_success_total = Counter(
    "payment_success_total",
    "Total successful payments",
    ["method"],
)

# Settlement files are produced by the background worker, a different process
# from the API that serves /metrics. Counter objects are process-local, so the
# worker INCRs a Redis key and each scrape mirrors the absolute value into this
# gauge. A gauge (not counter) keeps the value identical across gunicorn
# workers instead of each replaying the delta into its own registry.
settlement_files_generated_total = Gauge(
    "settlement_files_generated_total",
    "Total settlement files generated (mirrored from the worker via Redis)",
)

SETTLEMENT_METRIC_KEY = "metrics:settlement_files_generated"

# Worker metrics
print_jobs_total = Counter(
    "print_jobs_total",
    "Total print jobs",
    ["kind", "result"],  # kind=ticket|receipt, result=success|failure
)

snapshot_jobs_total = Counter(
    "snapshot_jobs_total",
    "Total snapshot jobs",
    ["snapshot_type", "result"],  # snapshot_type=entry|exit, result=success|failure
)

# Queue metrics (scraped on demand)
arq_queue_depth = Gauge(
    "arq_queue_depth",
    "Current depth of ARQ queue",
    ["queue"],
)

# Gate health
gate_online = Gauge(
    "gate_online",
    "1 if gate daemon heartbeat key is fresh in Redis, 0 if missing or unparseable",
    ["gate_id"],
)


async def refresh_queue_depths() -> None:
    """Sample ARQ queue depths into the gauge. Cheap zcard on the sorted-set."""
    try:
        from shared.redis import redis_client

        await redis_client.connect()
        redis = redis_client.client
        for queue in ("arq:queue:critical", "arq:queue:background"):
            try:
                depth = await redis.zcard(queue)
                arq_queue_depth.labels(queue=queue).set(depth)
            except Exception:
                continue
    except Exception:
        # Metrics scrape must never crash the endpoint.
        return


async def refresh_gate_online() -> None:
    """Sample gate liveness keys (`gate:heartbeat:{gate_id}`) into the gauge.

    Daemon writes a 60s-TTL key on every heartbeat. Key present = online.
    """
    try:
        from shared.redis import redis_client

        await redis_client.connect()
        redis = redis_client.client
        seen: set[str] = set()
        async for key in redis.scan_iter(match="gate:heartbeat:*"):
            gate_id = key.split(":", 2)[-1]
            seen.add(gate_id)
            try:
                # Key exists with TTL? mark online.
                ttl = await redis.ttl(key)
                gate_online.labels(gate_id=gate_id).set(1 if ttl > 0 else 0)
            except Exception:
                gate_online.labels(gate_id=gate_id).set(0)
        # Existing labels whose keys disappeared = offline. Prometheus client
        # keeps the label until we explicitly clear, so set them to 0.
        for label_tuple in list(gate_online._metrics.keys()):  # type: ignore[attr-defined]
            gid = label_tuple[0]
            if gid not in seen:
                gate_online.labels(gate_id=gid).set(0)
    except Exception:
        return


async def refresh_settlement_files_metric() -> None:
    """Replay the worker's Redis settlement counter into this process.

    ``increase(settlement_files_generated_total[26h])`` in the alert rules
    previously evaluated a permanently-zero series (the counter was never
    incremented anywhere), firing NoSettlementGenerated constantly.
    """
    try:
        from shared.redis import redis_client

        await redis_client.connect()
        raw = await redis_client.get(SETTLEMENT_METRIC_KEY)
        settlement_files_generated_total.set(int(raw or 0))
    except Exception:
        # Metrics scrape must never crash the endpoint.
        return


def get_metrics_response() -> Response:
    """Return Prometheus metrics as HTTP response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


async def metrics_middleware(request: Request, call_next):
    """Record request metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    path = request.url.path
    method = request.method
    status = str(response.status_code)

    # Skip metrics endpoint itself
    if path == "/metrics":
        return response

    http_requests_total.labels(method=method, endpoint=path, status_code=status).inc()
    http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)

    return response
