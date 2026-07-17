# Phase 1 Data Model: SSR WAN Insights-Equivalent Metrics

**Feature**: `001-wan-insights-metrics`
**Date**: 2026-07-17

> **Rev 2026-07-17 cascade**: The `VpnPeerPath`, `HourlyPerformanceRollup`, and `SiteWanLinkHealth` entities have been removed. Per-port jitter/latency/loss is now sourced from the native `wan_link_health` insight metric (no fanout, no rollup, no `aggregation_method` label, no `peer_count`, no zero-peer `"N/A"` wire shape). Site-level Application Health % is a real first-class Mist SLE on SSR — no substitution, no proxy. This cascade also bumps `mistapi>=0.63.3`; new SDK helpers are preferred where available, direct-`requests` fallback otherwise. See `docs/customer_response_wan_insights.md` for the ground-truth corrections that drove this rev.

The feature adds no persistent storage. All entities below are **wire shapes and in-memory Python dict shapes** returned by new methods on `MistConnection` and by new Flask routes on `app.py`. Field types follow Python semantics; JSON serialization is the default `flask.jsonify` behavior.

Field-level validation rules are called out where they exist. There is no peer-rollup state; empty states are the plain "no data reported in window" case.

---

## Entity: WanPort

The `(site_id, device_id, port_id)` triple that anchors every per-port metric in this feature. Not a new object — this identity already exists in the current dashboard (see `get_gateway_port_stats` return in `mist_connection.py:829-889`). Documented here for clarity.

| Field | Type | Notes |
|---|---|---|
| `site_id` | `str` (UUID) | Mist site identifier |
| `device_id` | `str` (UUID) | Mist device (gateway) identifier |
| `port_id` | `str` | e.g. `ge-0/0/0`, may contain `/`; URL-decoded before use |
| `gateway_hostname` | `str` | Human-readable gateway hostname |
| `site_name` | `str` | Human-readable site name |

**Source**: Already discovered by the existing gateway/port dashboard. New feature routes accept `device_id` + `port_id` (as URL path) plus `site_id` (query string) and derive the rest server-side.

---

## Entity: HourlyUtilizationSample

A 1-hour rollup bucket for one WAN port's utilization. One instance per hour bucket per port.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | `int` | UTC Unix seconds at hour boundary (bucket start) |
| `hour_iso` | `str` | ISO 8601 UTC (`YYYY-MM-DDTHH:00:00Z`) |
| `rx_bps` | `float` | From `rx_bps[i]` |
| `max_rx_bps` | `float` | From `max_rx_bps[i]` |
| `tx_bps` | `float` | From `tx_bps[i]` |
| `max_tx_bps` | `float` | From `max_tx_bps[i]` |

**Source**: `MistConnection.get_gateway_hourly_bandwidth(site_id, device_id, port_id, start, end)` — wraps `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port_id}&interval=1h&start=&end=` (URL per spec.md § FR-001 / `docs/customer_response_wan_insights.md`). Where `mistapi>=0.63.3` exposes a typed helper for this metric set, prefer it; otherwise fall back to direct `requests.get` mirroring `get_vpn_peer_stats`. Zips the four returned arrays with the timestamp array constructed from `start + i * 3600`.

**Validation**: If the upstream response has zero-length arrays across all four series, the wrapper returns `[]` (empty list). The route surfaces this to the UI via an empty `hourly` list.

**State**: Immutable snapshot; no transitions.

---

## Entity: HourlyPortWanLinkHealth

A 1-hour bucket for one WAN port's native jitter / latency / loss, sourced directly from the `wan_link_health` insight metric. **No `peer_count`, no `aggregation_method`, no `"N/A"` sentinel — the metric is native per port.**

| Field | Type | Notes |
|---|---|---|
| `timestamp` | `int` | UTC Unix seconds at hour boundary |
| `port_id` | `str` | Port identifier this sample belongs to |
| `avg_latency_ms` | `float \| None` | From `wan_link_health.<port>.avg_latency[i]`; `None` when the upstream slot is missing/null |
| `avg_jitter_ms` | `float \| None` | From `wan_link_health.<port>.avg_jitter[i]`; `None` when the upstream slot is missing/null |
| `avg_loss_pct` | `float \| None` | From `wan_link_health.<port>.avg_loss[i]`; `None` when the upstream slot is missing/null |

**Source**: `MistConnection.get_gateway_hourly_wan_link_health(site_id, device_id, port_id, start, end)` — wraps `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port_id}&interval=1h&start=&end=` (URL per spec.md § FR-003 / `docs/customer_response_wan_insights.md`). The API returns per-port `avg_latency` / `avg_jitter` / `avg_loss` arrays natively (device scope, keyed-timeseries, 14-day retention at 1h). No client-side fanout, no peer discovery, no rollup.

**Validation**: If the upstream response has all-empty arrays for a given port (port has never reported `wan_link_health` in the window — e.g. a direct-internet WAN uplink with no measured link-health telemetry), the wrapper returns `[]` for that port. No aggregation is applied. No `peer_count` field exists. No `"N/A"` sentinel exists.

**State**: Immutable snapshot; no transitions.

---

## Entity: PortHourlyResponse (envelope)

The top-level object returned by `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly`.

| Field | Type | Notes |
|---|---|---|
| `success` | `bool` | Matches the existing route-envelope convention |
| `port_id` | `str` | Echoed from request |
| `device_id` | `str` | Echoed from request (gateway UUID) |
| `gateway_hostname` | `str` | Resolved server-side |
| `site_id` | `str` | Echoed from request |
| `site_name` | `str` | Resolved server-side |
| `start` | `int` | Actual start epoch after clipping |
| `end` | `int` | Actual end epoch |
| `interval` | `int` | Always `3600` for MVP |
| `clipped` | `bool` | `true` when the requested start was earlier than `end - 14d` (FR-010) |
| `retention_notice` | `str` | Human-readable notice, non-empty when `clipped` is `true` |
| `hourly` | `List[Object]` | Merged per-hour rows — each row contains both bandwidth (`tx_bps`, `rx_bps`, `max_tx_bps`, `max_rx_bps`) and native wan_link_health (`avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct`) fields for one hour bucket. Ordered ascending by `timestamp`. Empty list when Mist returned zero samples in the window |
| `port_app_health` | `Object \| null` | Per-port slice from the site's Application Health SLE. Shape: `{summary_pct, threshold_pct}`. `null` when the site does not report application-health |
| `hourly_app_health` | `List[Object]` | Per-hour Application Health series for this port, sourced from the site's `summary-trend`. Each row: `{timestamp, pct}`. Empty list when the site does not report application-health |

**Dropped fields** (present in the pre-cascade envelope, removed in this rev): `peers`, `peer_breakdown`, `aggregation_method`, `empty_performance`.

**Validation**: `success == true` iff all upstream calls succeeded OR rate-limited responses were handled (the response is still returned but with populated `rate_limited: true` on individual sub-sections; caller inspects). On hard errors (non-429 non-200), the route returns `{success: false, error: <str>}` with HTTP 500. When application-health is unavailable for the site, `port_app_health` is `null` and `hourly_app_health` is `[]`; the bandwidth and wan_link_health portions of `hourly` continue to render normally.

---

## Entity: SiteApplicationHealth

Response body for `GET /api/v1/sites/<site_id>/application-health-summary`. Sourced from the four native Mist Application Health SLE endpoints on SSR — no substitution, no proxy.

| Field | Type | Notes |
|---|---|---|
| `site_id` | `str` | Mist site identifier |
| `summary_pct` | `float \| null` | Current site-level Application Health % from `.../summary`. `null` when unavailable |
| `threshold_pct` | `float \| null` | SLE goal for the benchmark ring (e.g. 96.0) from `.../threshold`. `null` when unavailable |
| `trend` | `List[Object]` | Per-hour series from `.../summary-trend?interval=3600`. Each row: `{timestamp, pct}`. Empty list when unavailable |
| `impacted_interfaces` | `List[Object]` | Per-port rows from `.../impacted-interfaces`. Each row: `{interface_name, gateway_hostname, gateway_mac, duration, degraded, total}`. Empty list when unavailable |
| `clipped` | `bool` | `true` when the requested start was earlier than `end - 14d` |
| `retention_notice` | `str \| null` | Human-readable clip notice, non-null when `clipped` is `true` |

**Classifiers**: Mist aggregates six classifiers server-side into every `summary` / `summary-trend` sample — `jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`. The client does NOT enumerate them per-sample; each hour's `pct` is the already-aggregated site-wide Application Health value.

**Validation**:

- When Mist returns HTTP 400 or null across the four endpoints (site does not report application-health), `summary_pct` and `threshold_pct` MUST be `null`, `trend` MUST be `[]`, `impacted_interfaces` MUST be `[]`.
- No `substitution_notice` field. No proxy metric. No session-storage notice. The tile is labelled "Application Health %" verbatim.

---

## Entity: HourlyMetricsCsvRow

One row of the new "Export Hourly Metrics" CSV. Column order is FIXED and enforced by the server-side CSV writer. **Exactly 12 columns.**

| Column (in order) | Type | Notes |
|---|---|---|
| `site_name` | `str` | |
| `gateway_name` | `str` | Human-readable gateway hostname |
| `port_id` | `str` | |
| `hour_epoch` | `int` | UTC seconds at hour boundary — MUST remain UTC even if UI shows local time |
| `hour_iso` | `str` | ISO 8601 UTC (`YYYY-MM-DDTHH:00:00Z`) — MUST remain UTC |
| `rx_avg_bps` | `float` | From `HourlyUtilizationSample.rx_bps` |
| `rx_peak_bps` | `float` | From `HourlyUtilizationSample.max_rx_bps` |
| `tx_avg_bps` | `float` | From `HourlyUtilizationSample.tx_bps` |
| `tx_peak_bps` | `float` | From `HourlyUtilizationSample.max_tx_bps` |
| `jitter_avg_ms` | `float \| ""` | Empty string when the underlying `wan_link_health` hour bucket is null/missing (plain no-data) |
| `latency_avg_ms` | `float \| ""` | Empty string when the underlying `wan_link_health` hour bucket is null/missing |
| `loss_avg_pct` | `float \| ""` | Empty string when the underlying `wan_link_health` hour bucket is null/missing |

**Explicitly dropped**: `peer_count` and `aggregation_method` columns. Both were rollup-metadata artifacts of the (now-removed) client-side aggregation. Also dropped from the pre-cascade draft: `site_id` (not in the canonical spec column set).

**Column authority**: The column list, order, and names above are governed by spec.md § FR-011 and match the canonical CSV in `docs/customer_response_wan_insights.md` line 219. Any drift from that column set is a spec violation.

**Validation**: The CSV writer emits every row through a single formatter that maps `None` to `""` for the three performance columns.

**Ordering**: Rows sorted ascending by `(site_name, gateway_name, port_id, hour_epoch)`. This makes diffs across exports deterministic.

---

## Relationships

```
WanPort  1 ── N  HourlyUtilizationSample                (one per hour bucket in window)
WanPort  1 ── N  HourlyPortWanLinkHealth                (one per hour bucket in window; native wan_link_health)
Site     1 ── 1  SiteApplicationHealth                  (one wrapper response per site request)
Site     1 ── N  SiteApplicationHealth.impacted_interfaces  (per-port rows; each row keyed by (gateway_hostname, interface_name))
PortHourlyResponse.hourly           →  HourlyPortWanLinkHealth[]           (merged with bandwidth per hour bucket)
PortHourlyResponse.hourly_app_health ← SiteApplicationHealth.trend         (site-scoped, filtered per port)
```

No `VpnPeerPath` relationship exists. No object references anywhere in the wire shape — the identity keys are inlined into the response for the frontend's convenience.

---

## Validation Rules Summary

| Rule | Enforced Where | Source |
|------|----------------|--------|
| Requested `start` clipped to `end - 14d` | `MistConnection.get_gateway_hourly_bandwidth` / `get_gateway_hourly_wan_link_health` / `get_site_application_health` / route handler | FR-010 |
| `clipped == true` implies `retention_notice` non-empty | Route handler | FR-010 |
| Every new API call goes through `_handle_rate_limit_response` / `_mark_token_rate_limited` | `MistConnection` methods (SDK or direct-`requests`) | FR-009, SC-005 |
| CSV hour timestamps remain UTC | CSV writer | FR-011, spec §Edge Cases §Time zone |
| No-data case: `hourly` is `[]`; `clipped` reflects whether retention window forced a clamp | Route handler | FR-015 |
| `application-health` unavailable → `summary_pct` / `threshold_pct` null, `trend` / `impacted_interfaces` empty | `get_site_application_health` wrapper + route handler | FR-007 |
| Site tile is labelled "Application Health %" verbatim — no substitution notice, no proxy | `templates/index.html` site tile | FR-007 |

No entity has state transitions in the MVP. All entities are immutable snapshots produced per request.

---

## Changelog

- **2026-07-17 cascade rewrite**: removed peer-rollup (`VpnPeerPath`, `HourlyPerformanceRollup`, `aggregation_method`, `peer_count`, `"N/A"` sentinel); added native `wan_link_health` entity (`HourlyPortWanLinkHealth`); added real Application Health SLE entity (`SiteApplicationHealth`) — no substitution; simplified CSV to 12 columns; bumped `mistapi>=0.63.3` (prefer typed SDK helpers, direct-`requests` fallback). Ground-truth source: `docs/customer_response_wan_insights.md`.
