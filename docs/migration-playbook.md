# Playbook: moving monitoring off a legacy platform with no gap

This is the process for moving services from a commercial log/metrics platform (Splunk, for example) to an open-source stack, **one service at a time, with no period where a service is unmonitored**.

## Principles

1. **One way in.** Applications send only to the OpenTelemetry gateway, never directly to a back end. The migration is then a change to the gateway's routing, and no application has to be redeployed.
2. **Dual-ship first, cut over later.** For each service, data goes to both platforms until the new one has been proven equivalent.
3. **Move one service at a time.** A problem with one service never puts monitoring for everything else at risk.
4. **Measure parity; don't assume it.** Compare record counts, dashboards and alert behaviour before switching off the old path.

## Per-service steps

| # | Step | Done when |
|---|---|---|
| 1 | **Inventory.** List the service's log sources, saved searches, dashboards, alerts and who uses them. | Every legacy object has an owner and a "keep / rebuild / drop" decision |
| 2 | **Route through the gateway.** Point the service's agent or forwarder at the gateway. The gateway exports to the **legacy back end only**. | Legacy dashboards look the same as before (nothing changed for users) |
| 3 | **Turn on dual-ship.** Add the new back end as a second exporter for this service's data. | Both back ends receive data |
| 4 | **Check parity.** Compare record counts per source (the *Dual-ship parity* panel), look at field extraction, and spot-check queries side by side. | Parity ≥ 99.9% for 7 days; there are no `send_failed` errors |
| 5 | **Rebuild.** Recreate the needed dashboards in Grafana and the alerts in vmalert. Translate SPL into LogsQL/MetricsQL. | Owners sign off; new alerts fire in a game-day test |
| 6 | **Switch users over.** Announce the change; links in runbooks and in the ITSM tool now point to Grafana. | No one uses the legacy dashboards for this service any more |
| 7 | **Stop the legacy export.** Remove the legacy exporter for this service. | Legacy ingest volume falls by the expected amount |
| 8 | **Decommission.** When every service has reached step 7, cancel or reduce the licence. | Licence cost removed |

## Rolling back

At any step up to 7, rolling back means reverting the gateway config commit. The legacy platform has kept receiving data the whole time, so there is nothing to backfill.

## Common translations

| Splunk SPL | VictoriaLogs LogsQL |
|---|---|
| `index=app service=checkout level=ERROR` | `service.name:checkout severity:ERROR` |
| `... \| stats count by host` | `... \| stats by (host) count()` |
| `... \| timechart span=5m count` | `... \| stats by (_time:5m) count()` |
| `... "timeout" NOT "retry"` | `... "timeout" -"retry"` |

## Things that catch teams out

- **Field names change.** OTel uses dotted names (`service.name`), while legacy fields are often flat. Map them in the gateway, not in each dashboard.
- **Plan capacity for double the egress.** Dual-shipping doubles outbound traffic from the gateway for as long as it runs.
- **Alert fatigue during the overlap.** Send new alerts to a silent receiver until they have been validated, so on-call engineers aren't paged twice.
- **Retention and compliance.** Make sure retention on the new platform meets audit requirements *before* the legacy data ages out.
