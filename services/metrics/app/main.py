"""metrics-service FastAPI app.

Exposes `/metrics` for Prometheus scraping and a small root endpoint for sanity checks.
"""

import os
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest


app = FastAPI(title="metrics-service")

START_TIME = time.time()

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["path", "method"],
)

service_uptime_seconds = Gauge(
    "service_uptime_seconds",
    "Service uptime in seconds",
)


@app.middleware("http")
async def metrics_middleware(request, call_next):
    response = await call_next(request)
    http_requests_total.labels(path=request.url.path, method=request.method).inc()
    return response


@app.get("/metrics")
def metrics() -> Response:
    service_uptime_seconds.set(time.time() - START_TIME)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root() -> dict:
    return {
        "service": "metrics-service",
        "metrics": "/metrics",
        "port": int(os.getenv("METRICS_SERVICE_PORT", "9100")),
    }
