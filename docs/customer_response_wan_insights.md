# Response: WAN Insights-Equivalent Metrics on MistCircuitStats

**To**: Asya (Juniper SE) / T-Mobile customer contact
**From**: Joseph Morrison
**Date**: 2026-07-17
**Feature branch**: `001-wan-insights-metrics`
**Full design**: `specs/001-wan-insights-metrics/` in this repo

---

## TL;DR

All three requested surfaces are achievable against the **live Mist REST API** — no Snowflake / Premium Analytics access required, and **no client-side aggregation or substitution required**. Every metric the customer sees maps 1:1 to a live-API response.

This corrects an earlier draft of this document that incorrectly assumed (a) per-port jitter/latency/loss required a client-side rollup across VPN peer paths, and (b) Application Health % was unavailable on SSR and required a WAN Link Health substitute. **Both assumptions were wrong.** The corrections were established by direct verification against the live API and against the Mist UI's own network trace.

| Customer ask | Live-API answer | Approach |
|---|---|---|
| Hourly per-port Rx/Tx Avg + Peak (Mbps) | Fully supported natively | `insights/gateway/{id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id=...&interval=1h` |
| Hourly per-port Jitter / Latency / Loss | **Fully supported natively** (correction from prior draft) | `insights/gateway/{id}/stats?metrics=wan_link_health&port_id=...&interval=1h` |
| Site-level Application Health % + per-port breakdown | **Fully supported natively** (correction from prior draft) | `sle/site/{site_id}/metric/application-health/{summary,summary-trend,impacted-interfaces}` |

---

## 1. Utilization (Rx/Tx Avg + Peak, hourly)

**Endpoint**:

```
GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats
    ?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps
    &port_id={port_id}
    &interval=1h
    &start={epoch}
    &end={epoch}
```

**Returns**: per-hour `tx_bps` / `rx_bps` (averages) and `max_tx_bps` / `max_rx_bps` (peaks) time-series.

**Retention**: `1h` interval is retained for the last **14 days** (`max_age: 1209600` in the `insight_metrics` registry). Requested windows beyond 14 days are server-side clipped and the UI shows a clipping notice. MVP window selector is **24h / 3d / 7d** — all within retention.

**This is a first-class native metric.** No aggregation.

---

## 2. Jitter / Latency / Loss (hourly, per port)

**CORRECTION vs earlier draft.** The earlier draft claimed port-level jitter/latency/loss required a client-side rollup across VPN peer paths using `insights/device/{device_id}/vpn_peer-metrics`. That was wrong. The `wan_link_health` insight metric, keyed by port, returns per-hour `avg_latency` / `avg_jitter` / `avg_loss` directly.

**Endpoint**:

```
GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats
    ?metrics=wan_link_health
    &port_id={port_id}
    &interval=1h
    &start={epoch}
    &end={epoch}
```

**Returns** (from the `insight_metrics` registry description of `wan_link_health`):

```json
{
  "wan_link_health": {
    "avg_latency": [39.5, 50.33, 54.25, ...],
    "avg_jitter":  [0.58, 0.08, 0.5,   ...],
    "avg_loss":    [0.0,  0.0,  0.0,   ...]
  }
}
```

- `type`: `keyed-timeseries`
- `scope`: `device`
- Intervals: `10m` (retained 1 day) and `1h` (retained 14 days). MVP uses `1h`.

**No client-side aggregation.** No peer fanout. No `simple_mean`. No `peer_count`. The port-level values are what the Mist backend already computes across the SVR peer paths on that port — the same numbers the Mist WAN Insights (SSR) dashboard shows in its Timeline view.

**Empty-state**: if a port has never reported `wan_link_health` in the window (e.g. a direct-internet WAN uplink with no SVR peer paths), the arrays are empty and the UI renders the standard empty state ("no jitter/latency/loss reported for this port in the requested window"). Rx/Tx utilization for the same port continues to render normally from §1.

---

## 3. Site-level Application Health % + per-port breakdown

**CORRECTION vs earlier draft.** The earlier draft claimed Application Health % was **not available on SSR/SVR via the live API** and required substituting the WAN Link Health SLE. That was wrong. `application-health` is a standard SLE metric — it plugs into the generic SLE URL template `/sle/{scope}/{scope_id}/metric/{metric}/*` and returns real data on SSR sites. The earlier draft missed this because it searched the `insight_metrics` registry (`/api/v1/const/insight_metrics`) — but `application-health` is an SLE metric, not an insight metric, so it lives in a different registry.

The Mist UI's own "Application Health" tile and the "Root Cause Analysis" Timeline view are populated from the same endpoints listed below. No Snowflake dependency.

### 3.1 Site-level tile — `summary`

**Endpoint**:

```
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary
    ?start={epoch}
    &end={epoch}
```

**Returns**: overall Application Health % for the site over the window. This is the number that goes on the site view tile — labelled **"Application Health %"** (no substitution notice, no asterisk, no WAN Link Health proxy).

### 3.2 Hourly time-series with classifier breakdown — `summary-trend`

**Endpoint**:

```
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend
    ?start={epoch}
    &end={epoch}
    &interval=3600
```

**Returns**: per-hour SLE trend with the classifier decomposition — the same shape the Mist UI plots as the stacked "Timeline" chart on the Application Health Root Cause Analysis view.

Classifiers exposed on Application Health:

- `jitter`
- `latency`
- `loss`
- `application-services-application-bandwidth`
- `application-services-slow-application`
- `application-services-application-disconnects`

Every hour bucket carries the site-level health % plus per-classifier degraded/total values. This drives (a) the site tile hourly-trend micro-chart and (b) the classifier breakdown panel inside the per-port modal.

### 3.3 Per-port slice — `impacted-interfaces`

**Endpoint**:

```
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/impacted-interfaces
    ?start={epoch}
    &end={epoch}
```

**Returns**: per-port breakdown. Each row is a `(gateway_hostname, port_id)` pair with `duration` / `degraded` / `total` values expressing how much this port contributed to Application Health degradation over the window. Example (verbatim shape from the customer's own live capture on their test site):

```json
{
  "results": [
    {"interface": "ge-0/0/0.0", "device_hostname": "SRX-320", "duration": ..., "degraded": ..., "total": ...},
    {"interface": "ge-0/0/1.0", "device_hostname": "SRX-320", "duration": ..., "degraded": ..., "total": ...},
    {"interface": "ge-0/0/2.0", "device_hostname": "SRX-320", "duration": ..., "degraded": ..., "total": ...},
    {"interface": "ge-0/0/3.0", "device_hostname": "SRX-320", "duration": ..., "degraded": ..., "total": ...}
  ]
}
```

When the per-port modal is open for `(gateway_id, port_id)`, we filter this results list to the matching row and expose it as a "This port's contribution to Application Health" widget alongside the hourly summary-trend chart from §3.2.

### 3.4 Additional adjacent SLE endpoints (used but not surfaced in MVP)

- `.../application-health/threshold` — the SLE goal (e.g. 96%) used to size the tile ring / benchmark line.
- `.../application-health/histogram` — distribution across the window; useful for a future "SLE distribution" panel; not surfaced in MVP.
- `.../application-health/impacted-applications` — per-application breakdown; useful for a future drilldown; not surfaced in MVP.
- `.../application-health/impacted-gateways` — per-gateway breakdown; not surfaced in MVP.

---

## 4. What changed vs the earlier draft

| Section | Earlier draft said | Correction |
|---|---|---|
| §2 J/L/L | Required per-peer fanout via `vpn_peer-metrics` and a client-side `simple_mean` rollup, with `peer_count` and `aggregation_method` fields plus a peer-breakdown drilldown | **None of that**. `wan_link_health` insight metric returns per-port hourly values natively; no fanout, no rollup, no aggregation label, no peer drilldown |
| §2 empty state | Zero-peer ports render `"N/A"` per FR-006a to avoid mistaking `0` for real data | No longer applicable in the "peer" sense. Empty state is now the plain "no data reported in window" case that already covers §1 |
| §2 CSV | Extra columns `aggregation_method` and `peer_count`; empty-string mapping for zero-peer rows | Removed. CSV carries just the six utilization + three performance columns |
| §3 tile | "WAN Link Health % (Application Health substitution)" with a permanent substitution notice | Real "Application Health %" tile. No substitution notice. No proxy |
| §3 per-port view | Not available (Application Health was assumed unavailable end-to-end) | New: `impacted-interfaces` slice for this port + `summary-trend` classifier chart embedded in the modal |
| §3 forward-compat hook | "SRX behaviour is a non-goal" hedge for a hypothetical future Application Health source | Removed. Application Health works on the customer's SSR site today per their own live capture |
| §5 traffic-weighted Phase 2 | Phase 2 upgrade to traffic-weighted mean deferred | Removed. No aggregation exists to weight |

---

## 5. On Premium Analytics / Snowflake

Premium Analytics data is served from a Snowflake pipeline that has no public REST API. The bits that live only in Premium Analytics (long-window historical rollups, cross-site trend correlations, some app-level correlations) are still not reachable from a third-party integration.

However, **the specific tiles and Timeline chart the customer pointed at in the WAN Insights (SSR) dashboard** — hourly Rx/Tx, hourly jitter/latency/loss per port, and Application Health % — are all live-API-backed, not Snowflake-backed. The earlier draft conflated the two.

---

## 6. All Mist API Endpoints This Feature Will Use

Every endpoint below is called server-side by MistCircuitStats through the existing `MistConnection` wrapper, which handles multi-token 429 rotation and rate-limit backoff. No new authentication surface, no new caches in the MVP.

### Already used today

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/self` | Token identity / privileges |
| `GET /api/v1/orgs/{org_id}` | Org details |
| `GET /api/v1/orgs/{org_id}/sites` | Site enumeration |
| `GET /api/v1/orgs/{org_id}/stats/devices` | Gateway inventory + status |
| `GET /api/v1/sites/{site_id}/stats/ports/search` | Instantaneous WAN port stats |
| `GET /api/v1/sites/{site_id}/devices/{device_id}` | Static IP / port config |
| `GET /api/v1/orgs/{org_id}/stats/vpn_peers/search` | Instantaneous VPN peer list (existing peer-view feature; **no longer used by US2**) |
| `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats` | Existing 7-day per-port byte-count chart (unchanged; US1 also uses this endpoint with `metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps` for hourly Avg+Peak) |

### New for this feature

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id=...&interval=1h` | **Hourly jitter / latency / loss per port**, native (US2) |
| `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary` | Site-level Application Health % tile value (US3) |
| `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend` | Hourly Application Health with per-classifier breakdown (US3 site tile + per-port modal classifier chart) |
| `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/impacted-interfaces` | Per-port Application Health contribution (US3 per-port slice, embedded in modal) |
| `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/threshold` | SLE goal for the tile benchmark (US3) |

All new endpoints are documented in the "Mist API Endpoints Used" section of `README.md` when the feature ships.

---

## 7. What the Customer Will See in the App

- Existing per-port chart modal, **unchanged** for the current 7-day byte-count view.
- Below the existing charts, three new panels:
  1. **Hourly Rx/Tx Avg + Peak** (Chart.js) with a 24h / 3d / 7d selector.
  2. **Hourly Jitter / Latency / Loss** (Chart.js) — native values, no aggregation label.
  3. **This port's contribution to Application Health** (from `impacted-interfaces`) + a small hourly Application Health classifier breakdown chart (from `summary-trend`, filtered to the jitter/latency/loss classifiers most relevant to a port view).
- A new **"Export Hourly Metrics" CSV** button (RFC 4180, UTC timestamps). Columns: `site_name`, `gateway_name`, `port_id`, `hour_epoch`, `hour_iso`, `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps`, `jitter_avg_ms`, `latency_avg_ms`, `loss_avg_pct`.
- On the site view: a real **"Application Health %"** tile with the hourly summary-trend micro-chart underneath, colour-coded by classifier.
- A retention notice ("last 14 days only for hourly data") visible whenever the user selects a window near or beyond retention.

Existing behaviors preserved: existing 7-day byte-count charts, existing per-port CSV export, existing peer-path detail view, existing multi-token 429 handling.

---

## 8. What the Customer Should NOT Expect

- **Not** an exact byte-for-byte match with Premium Analytics dashboards. Premium Analytics may apply longer-window smoothing or cross-source correlation that the live API does not. For the specific tiles listed in §7, the live-API values should match the Mist WebUI's own Monitor → WAN and Monitor → Application views (which are live-API-backed) exactly.
- **Not** minute-level historical granularity. Mist's `10m` interval for `wan_link_health` is retained only 1 day; MVP is fixed at 1-hour buckets which is the WAN Insights default and gives 14 days of retention.
- **Not** more than 14 days of hourly history. Anything older ages out of the `1h`-interval retention.
- **Not** per-application drilldown yet. `impacted-applications` is reachable and will be added as a follow-up panel; MVP focuses on the three tiles the customer asked about.

---

## 9. Next Steps

1. Confirm this corrected plan is acceptable to the T-Mobile team. The corrections make the feature strictly better (no substitutions, no client-side math, native numbers), so nothing they asked for is lost.
2. Implementation follows the phased task list at `specs/001-wan-insights-metrics/tasks.md` — MVP (User Story 1: hourly utilization) is independently shippable, followed by User Story 2 (native hourly J/L/L + CSV) and User Story 3 (Application Health tile + per-port slice).
3. Because the earlier peer-rollup narrative is gone, the previously-planned Phase 2 traffic-weighted mean upgrade is also gone — there is no rollup to weight. If the customer wants any of the currently-deferred surfaces (`impacted-applications`, `impacted-gateways`, per-application drilldown, SLE distribution histogram), those are additive follow-ups.

Full technical spec, decisions log, wire contracts, and quickstart walkthrough are in `specs/001-wan-insights-metrics/`. All artifacts have been updated to reflect the corrections above.
