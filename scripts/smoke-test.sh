#!/usr/bin/env bash
# End-to-end check: metrics, logs and traces all reach their back ends, and
# the dual-ship pipeline delivers logs with no exporter failures.
set -euo pipefail

VM="http://localhost:${VM_PORT:-8428}"
VL="http://localhost:${VL_PORT:-9428}"
GRAFANA="http://localhost:${GRAFANA_PORT:-3000}"
deadline=$((SECONDS + ${TIMEOUT:-180}))

query() {
  curl -fsS "$VM/api/v1/query" --data-urlencode "query=$1" |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)'
}

grafana_up() { curl -fsS "$GRAFANA/api/health" >/dev/null 2>&1 && echo 1 || echo 0; }
logs_found() { curl -fsS "$VL/select/logsql/query" --data-urlencode 'query=service.name:checkout | limit 1' | grep -c . || true; }

wait_for() {
  local name=$1; shift
  until [ "$("$@")" != "0" ]; do
    [ $SECONDS -lt $deadline ] || { echo "FAIL: $name"; exit 1; }
    sleep 5
  done
  echo "ok   $name"
}

wait_for "Grafana is healthy"             grafana_up
wait_for "app metrics in VictoriaMetrics" query 'count(http_server_request_duration_seconds_count)'
wait_for "span metrics from traces"       query 'count(traces_span_metrics_calls_total)'
wait_for "traces delivered to Tempo"      query 'sum(otelcol_exporter_sent_spans_total{exporter="otlp/tempo"})'
wait_for "logs in VictoriaLogs"           logs_found
wait_for "blackbox probes running"        query 'count(probe_success)'
wait_for "recording rules evaluated"      query 'count(service:requests:rate5m)'

new=$(query 'sum(otelcol_exporter_sent_log_records_total{exporter="otlphttp/victorialogs"})')
legacy=$(query 'sum(otelcol_exporter_sent_log_records_total{exporter="file/legacy"})')
failed=$(query 'sum({__name__=~"otelcol_exporter_send_failed_.+_total"})')
echo "     dual-ship: new=$new legacy=$legacy failed=$failed"
[ "$failed" = "0" ] || { echo "FAIL: exporter failures"; exit 1; }
echo "All checks passed."
