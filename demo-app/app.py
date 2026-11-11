"""A small 'checkout' service that emits traces, metrics and logs over OTLP.

Instrumentation is written by hand (no auto-instrumentation) so it is obvious
where each signal comes from.
"""

import logging
import os
import random
import time

from flask import Flask, jsonify
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

ERROR_RATE = float(os.getenv("ERROR_RATE", "0.05"))
resource = Resource.create({"service.name": os.getenv("SERVICE_NAME", "checkout"), "deployment.environment": "demo"})

# OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://otel-gateway:4318) is read by every exporter.
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(tracer_provider)

metrics.set_meter_provider(
    MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), 10_000)])
)

logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
set_logger_provider(logger_provider)

log = logging.getLogger("checkout")
log.setLevel(logging.INFO)
log.addHandler(LoggingHandler(logger_provider=logger_provider))
log.addHandler(logging.StreamHandler())

tracer = trace.get_tracer("checkout")
meter = metrics.get_meter("checkout")
# Bucket boundaries in seconds. The SDK defaults (0, 5, 10, 25...) suit
# milliseconds and would put every request in the first bucket.
duration = meter.create_histogram(
    "http.server.request.duration",
    unit="s",
    description="HTTP request latency",
    explicit_bucket_boundaries_advisory=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
)
orders = meter.create_counter("checkout.orders", description="Orders processed, by result")

app = Flask(__name__)


def handle(route, work):
    start = time.perf_counter()
    status = 200
    with tracer.start_as_current_span(f"GET {route}", kind=trace.SpanKind.SERVER) as span:
        span.set_attribute("http.route", route)
        try:
            body = work(span)
        except Exception as exc:  # demo: turn failures into 500s and record them
            status = 500
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            log.error("request failed route=%s error=%s", route, exc)
            body = {"error": str(exc)}
        span.set_attribute("http.response.status_code", status)
    attrs = {"http.route": route, "http.response.status_code": status}
    duration.record(time.perf_counter() - start, attrs)
    return jsonify(body), status


def checkout(span):
    with tracer.start_as_current_span("inventory.reserve"):
        time.sleep(random.uniform(0.01, 0.08))
    with tracer.start_as_current_span("payment.charge") as pay:
        latency = random.expovariate(1 / 0.12)
        pay.set_attribute("payment.provider", random.choice(["card", "mobile-money"]))
        time.sleep(min(latency, 2.0))
        if random.random() < ERROR_RATE:
            orders.add(1, {"result": "failed"})
            raise RuntimeError("payment provider timeout")
    orders.add(1, {"result": "ok"})
    order_id = random.randint(100000, 999999)
    span.set_attribute("order.id", order_id)
    log.info("order placed order_id=%s", order_id)
    return {"order_id": order_id}


@app.get("/checkout")
def checkout_route():
    return handle("/checkout", checkout)


@app.get("/products")
def products_route():
    return handle("/products", lambda span: (time.sleep(random.uniform(0.005, 0.03)), {"items": 42})[1])


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
