import json
import sys

# Regenerate: python3 scripts/gen_dashboards.py grafana/dashboards
OUT = sys.argv[1]
VM = {"type": "prometheus", "uid": "victoriametrics"}
VL = {"type": "victoriametrics-logs-datasource", "uid": "victorialogs"}
TEMPO = {"type": "tempo", "uid": "tempo"}


def stat(title, expr, unit, x, w=6, thresholds=None, decimals=None):
    p = {
        "type": "stat", "title": title, "datasource": VM,
        "gridPos": {"x": x, "y": 0, "w": w, "h": 4},
        "targets": [{"refId": "A", "datasource": VM, "expr": expr, "instant": True}],
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area"},
    }
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


def ts(title, targets, unit, gp, stack=False, maxv=None):
    return {
        "type": "timeseries", "title": title, "datasource": VM, "gridPos": gp,
        "targets": [{"refId": chr(65 + i), "datasource": VM, "expr": e, "legendFormat": l} for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"fillOpacity": 10, "lineWidth": 2,
                                                              "stacking": {"mode": "normal" if stack else "none"}},
                                     **({"min": 0, "max": maxv} if maxv is not None else {})},
                        "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max"]},
                    "tooltip": {"mode": "multi"}},
    }


def dash(uid, title, panels, desc):
    return {
        "uid": uid, "title": title, "description": desc, "editable": True, "schemaVersion": 41,
        "time": {"from": "now-30m", "to": "now"}, "refresh": "10s", "tags": ["observability-stack"],
        "templating": {"list": []}, "annotations": {"list": []}, "panels": panels,
        "links": [{"title": "Dashboards", "type": "dashboards", "tags": ["observability-stack"], "asDropdown": False}],
    }


H = "http_server_request_duration_seconds"
service = dash("service-overview", "Service Overview (RED + SLO)", [
    stat("Requests / s", "sum(service:requests:rate5m)", "reqps", 0, decimals=1),
    stat("Error rate (5m)", "max(service:errors:ratio_rate5m)", "percentunit", 6, decimals=2,
         thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.01}, {"color": "red", "value": 0.03}]),
    stat("p95 latency (5m)", "max(service:latency:p95_5m)", "s", 12, decimals=0,
         thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.3}, {"color": "red", "value": 0.5}]),
    stat("Error budget burn rate (1h, SLO 99%)", "max(service:errors:ratio_rate1h) / 0.01", "x", 18, decimals=1,
         thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 14.4}]),
    ts("Request rate by route and status",
       [(f"sum by (http_route, http_response_status_code) (rate({H}_count[1m]))", "{{http_route}} {{http_response_status_code}}")],
       "reqps", {"x": 0, "y": 4, "w": 12, "h": 8}, stack=True),
    ts("Latency by route",
       [(f"histogram_quantile({q}, sum by (le, http_route) (rate({H}_bucket[5m])))", f"p{int(q*100)} {{{{http_route}}}}")
        for q in (0.5, 0.95, 0.99)],
       "s", {"x": 12, "y": 4, "w": 12, "h": 8}),
    ts("Orders by result", [("sum by (result) (rate(checkout_orders_total[1m]))", "{{result}}")],
       "ops", {"x": 0, "y": 12, "w": 8, "h": 8}, stack=True),
    ts("Operation p95 from traces (spanmetrics)",
       [("histogram_quantile(0.95, sum by (le, span_name) (rate(traces_span_metrics_duration_milliseconds_bucket[5m])))", "{{span_name}}")],
       "ms", {"x": 8, "y": 12, "w": 16, "h": 8}),
    {
        "type": "logs", "title": "Error logs (VictoriaLogs). Expand a line to see its trace_id", "datasource": VL,
        "gridPos": {"x": 0, "y": 20, "w": 12, "h": 10},
        "targets": [{"refId": "A", "datasource": VL, "expr": "service.name:checkout AND severity:ERROR", "queryType": "instant"}],
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True},
    },
    {
        "type": "table", "title": "Failed traces (Tempo). Click a trace ID to open it", "datasource": TEMPO,
        "gridPos": {"x": 12, "y": 20, "w": 12, "h": 10},
        "targets": [{"refId": "A", "datasource": TEMPO, "queryType": "traceql", "query": "{ status = error }", "limit": 20, "tableType": "traces"}],
    },
], "Golden signals for the demo checkout service, with SLO burn rate, logs and traces on one screen.")

pipeline = dash("pipeline-health", "Telemetry Pipeline Health", [
    stat("Logs/s to VictoriaLogs (new)", 'sum(rate(otelcol_exporter_sent_log_records_total{exporter="otlphttp/victorialogs"}[5m]))', "short", 0, decimals=1),
    stat("Logs/s to legacy back end", 'sum(rate(otelcol_exporter_sent_log_records_total{exporter="file/legacy"}[5m]))', "short", 6, decimals=1),
    stat("Dual-ship parity (new ÷ legacy)",
         'sum(increase(otelcol_exporter_sent_log_records_total{exporter="otlphttp/victorialogs"}[15m])) / sum(increase(otelcol_exporter_sent_log_records_total{exporter="file/legacy"}[15m]))',
         "percentunit", 12, decimals=1,
         thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.98}, {"color": "green", "value": 0.999}]),
    stat("Firing alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', "short", 18,
         thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
    ts("Items sent per exporter",
       [('sum by (exporter) (rate({__name__=~"otelcol_exporter_sent_.+_total"}[1m]))', "{{exporter}}")],
       "short", {"x": 0, "y": 4, "w": 12, "h": 8}),
    ts("Send failures per exporter",
       [('sum by (exporter) (rate({__name__=~"otelcol_exporter_send_failed_.+_total"}[1m]))', "{{exporter}}")],
       "short", {"x": 12, "y": 4, "w": 12, "h": 8}),
    ts("Persistent queue usage", [("max by (exporter) (otelcol_exporter_queue_size / otelcol_exporter_queue_capacity)", "{{exporter}}")],
       "percentunit", {"x": 0, "y": 12, "w": 12, "h": 8}, maxv=1),
    ts("Probe duration (Blackbox)", [("probe_duration_seconds", "{{instance}}")], "s", {"x": 12, "y": 12, "w": 12, "h": 8}),
    {
        "type": "table", "title": "Synthetic checks", "datasource": VM, "gridPos": {"x": 0, "y": 20, "w": 12, "h": 8},
        "targets": [{"refId": "A", "datasource": VM, "expr": "probe_success", "instant": True, "format": "table"}],
        "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "job": True},
                                                          "renameByName": {"instance": "Endpoint", "Value": "Up"}}}],
        "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                                                                "1": {"text": "UP", "color": "green"}}}],
                                     "custom": {"cellOptions": {"type": "color-background"}}}, "overrides": []},
    },
    {
        "type": "table", "title": "Firing alerts", "datasource": VM, "gridPos": {"x": 12, "y": 20, "w": 12, "h": 8},
        "targets": [{"refId": "A", "datasource": VM, "expr": 'ALERTS{alertstate="firing"}', "instant": True, "format": "table"}],
        "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "Value": True, "alertstate": True}}}],
    },
], "Is the monitoring itself healthy? Exporter throughput and failures, queue usage, migration parity, and probes.")

for d in (service, pipeline):
    with open(f"{OUT}/{d['uid']}.json", "w") as f:
        json.dump(d, f, indent=2)
print("ok")
