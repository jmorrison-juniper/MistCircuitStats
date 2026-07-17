# Phase 1 Data Model: SSR WAN Insights-Equivalent Metrics

**Feature**: `001-wan-insights-metrics`
**Date**: 2026-07-17

The feature adds no persistent storage. All entities below are **wire shapes and in-memory Python dict shapes** returned by new methods on `MistConnection` and by new Flask routes on `app.py`. Field types follow Python semantics; JSON serialization is the default `flask.jsonify` behavior.

Field-level validation rules and state transitions are called out where they exist. The zero-peer rendering rule (FR-006a) is the only non-trivial state distinction.

---

## Entity: WanPort

The `(site_id, device_id, port_id)` triple that anchors every per-port metric in this feature. Not a new object — this identity already exists in the current dashboard (see `get_gateway_port_stats` return in `mist_connection.py:829-889`). Documented here for clarity.

| Field | Type | Notes |
|---|---|---|
| `site_id` | `str` (UUID) | Mist site identifier |
| `device_id` | `str` (UUID) | Mist device (gateway) identifier |
| `port_id` | `str` | e.g. `ge-0/0/0`, may contain `/`; URL-decoded before use |
| `gateway_name` | `str` | Human-readable gateway hostname |
| `site_name` | `str` | Human-readable site name |

**Source**: Already discovered by the existing gateway/port dashboard. New feature routes accept `gateway_id` + `port_id` (as URL path) plus `site_id` (query string) and derive the rest server-side.

---

## Entity: VpnPeerPath

An active SVR peer relationship between a local port and a remote router port. Identifies the fanout target for `vpn_peer-metrics` calls.

| Field | Type | Notes |
|---|---|---|
| `port_id` | `str` | Local port carrying the peer path |
| `peer_router_name` | `str` | Remote router hostname (Mist API returns this) |
| `peer_mac` | `str \| None` | Remote device MAC when known |
| `peer_port_id` | `str` | Remote port carrying the peer side |
| `policy` | `str \| None` | Peer-path policy name when present in the peer record |

**Source**: Returned by `MistConnection.get_vpn_peer_stats(site_id, device_mac)` (existing method). Field names above match its returned dict keys (`mist_connection.py:960-972`) with the addition of `peer_mac` and `policy` when the upstream API includes them.

**Validation**: At least one of `peer_router_name` or `peer_mac` MUST be non-empty before a `vpn_peer-metrics` request is fanned out. Records failing this filter are logged and skipped (not silently zero-included).

---

## Entity: HourlyUtilizationSample

A 1-hour rollup bucket for one WAN port's utilization. One instance per hour bucket per port.

| Field | Type | Notes |
|---|---|---|
| `hour_epoch` | `int` | UTC Unix seconds at hour boundary (bucket start) |
| `hour_iso` | `str` | ISO 8601 UTC (`YYYY-MM-DDTHH:00:00Z`) |
| `rx_avg_bps` | `float` | From `tx_rx_bps.rx_bps[i]` |
| `rx_peak_bps` | `float` | From `tx_rx_bps.max_rx_bps[i]` |
| `tx_avg_bps` | `float` | From `tx_rx_bps.tx_bps[i]` |
| `tx_peak_bps` | `float` | From `tx_rx_bps.max_tx_bps[i]` |

**Source**: `MistConnection.get_port_tx_rx_bps_hourly(site_id, device_id, port_id, start, end)` -> zips the four timeseries arrays returned by `insights/device/{device_id}/tx_rx_bps?interval=3600` with the timestamp array constructed from `start` + `i * 3600`.

**Validation**: If the upstream response has zero-length arrays across all four series, the wrapper returns `[]` (empty list). The route serializes `[]` with `empty: true` in the envelope so the UI renders the FR-015 empty state.

**State**: Immutable snapshot; no transitions.

---

## Entity: HourlyPerformanceRollup

A 1-hour aggregated rollup bucket for one WAN port's jitter / latency / loss, computed client-side by `rollup_peer_metrics_simple_mean` across every contributing peer path.

| Field | Type | Notes |
|---|---|---|
| `hour_epoch` | `int` | UTC Unix seconds at hour boundary |
| `hour_iso` | `str` | ISO 8601 UTC |
| `avg_latency_ms` | `float \| "N/A"` | Simple mean across peers reporting in this hour; `"N/A"` if zero peers reported this hour (FR-006a) |
| `avg_jitter_ms` | `float \| "N/A"` | Same rule |
| `avg_loss_pct` | `float \| "N/A"` | Same rule |
| `aggregation_method` | `str` | Literal `"simple_mean"` in the MVP (FR-006) |
| `peer_count` | `int` | Number of peers that reported a value **in this hour** (0 when N/A) |

**Source**: `rollup_peer_metrics_simple_mean(peer_hourly_series)` — a pure function on `MistConnection` (no I/O). Input is a dict `{ peer_key: [{hour_epoch, avg_latency, avg_jitter, avg_loss}, ...] }`. Output is a list of `HourlyPerformanceRollup` dicts, one per hour bucket in the requested window.

**Validation**:

- `aggregation_method` MUST equal `"simple_mean"` in every emitted row for MVP (FR-006). A code-level assertion enforces this before returning.
- The `float | "N/A"` union is enforced at emit time: if `peer_count == 0` for that hour, all three metric fields MUST be the JSON string `"N/A"`; otherwise all three MUST be finite floats. No mixed rows.
- CSV emit path maps `"N/A"` -> empty string per FR-006a; this is the ONLY place the mapping lives.

**State**: Immutable snapshot; no transitions.

---

## Entity: PortHourlyResponse (envelope)

The top-level object returned by `GET /api/gateway/<id>/port/<port_id>/hourly?...`.

| Field | Type | Notes |
|---|---|---|
| `success` | `bool` | Matches the existing route-envelope convention |
| `port_id` | `str` | Echoed from request |
| `gateway_id` | `str` | Echoed from request |
| `gateway_name` | `str` | Resolved server-side |
| `site_id` | `str` | Echoed from request |
| `site_name` | `str` | Resolved server-side |
| `duration` | `str` | Echoed (`"24h"`, `"3d"`, or `"7d"`) |
| `interval_seconds` | `int` | Always `3600` for MVP |
| `start_epoch` | `int` | Actual start after clipping |
| `end_epoch` | `int` | Actual end |
| `clipped` | `bool` | `true` when the requested start was earlier than `end - 14d` (FR-010) |
| `retention_notice` | `str` | Human-readable notice, non-empty when `clipped` is `true` |
| `utilization` | `List[HourlyUtilizationSample]` | Ordered ascending by `hour_epoch` |
| `performance` | `List[HourlyPerformanceRollup]` | Ordered ascending by `hour_epoch` |
| `peers` | `List[VpnPeerPath]` | Contributing peers over the window (union, not per-hour); empty list when port has no peers |
| `peer_breakdown` | `Dict[str, List[Dict]]` | Optional, per-peer hourly series keyed by `f"{peer_router_name}::{peer_port_id}"` — enables SC-003 one-click drilldown |
| `aggregation_method` | `str` | Top-level echo of `"simple_mean"` for convenience |
| `empty_utilization` | `bool` | `true` when `utilization` is empty; drives FR-015 empty state |
| `empty_performance` | `bool` | `true` when `peers` is empty; drives FR-014 empty state |

**Validation**: `success == true` iff all upstream calls succeeded OR rate-limited responses were handled (the response is still returned but with populated `rate_limited: true` on individual sub-sections; caller inspects). On hard errors (non-429 non-200), the route returns `{success: false, error: <str>}` with HTTP 500.

---

## Entity: SiteWanLinkHealth

Response body for `GET /api/site/<site_id>/wan_link_health`.

| Field | Type | Notes |
|---|---|---|
| `success` | `bool` | |
| `available` | `bool` | `false` when Mist returned HTTP 400 or null for the SLE (SSR without health data) |
| `reason` | `str \| None` | Populated only when `available == false` — e.g. `"wan-link-health SLE returned HTTP 400"` |
| `site_id` | `str` | |
| `site_name` | `str` | Resolved server-side |
| `health_pct` | `float \| None` | Site-level rollup percentage; null when unavailable |
| `classifiers` | `Dict[str, float]` | Keys: `network-jitter`, `network-loss`, `network-latency`, `interface-congestion`, `network-vpn-path-down`, `isp-reachability-arp`, `isp-reachability-dhcp`. Values are percentages. All keys always present; unavailable classifiers report `0.0` and the UI hides them |
| `hourly` | `List[Dict]` | One entry per hour bucket: `{hour_epoch, hour_iso, health_pct, classifier_breakdown: Dict[str, float]}` |
| `substitution_notice` | `str` | Verbatim FR-008 / Acceptance Scenario 3.2 copy |
| `retention_notice` | `str \| None` | Same clipping rule as `PortHourlyResponse` |
| `clipped` | `bool` | |

**Validation**:

- When `available == false`, `hourly` MUST be `[]` and `health_pct` MUST be `null`. The UI renders the "unavailable" tile state with the classifier list still visible per Acceptance Scenario 3.4 (the list is rendered from the fixed classifier-key set, not from `classifiers` values).
- When `available == true`, `hourly` MUST be non-empty and all classifier keys MUST be present in every hour's `classifier_breakdown`.

---

## Entity: HourlyMetricsCsvRow

One row of the new "Export Hourly Metrics" CSV. Column order is FIXED and enforced by the server-side CSV writer.

| Column (in order) | Type | Notes |
|---|---|---|
| `site_name` | `str` | |
| `gateway_name` | `str` | |
| `port_id` | `str` | |
| `hour_epoch` | `int` | UTC seconds |
| `hour_iso` | `str` | UTC ISO 8601 (`YYYY-MM-DDTHH:00:00Z`) — MUST remain UTC even if UI shows local time |
| `rx_avg_bps` | `float` | From `HourlyUtilizationSample.rx_avg_bps` |
| `rx_peak_bps` | `float` | From `HourlyUtilizationSample.rx_peak_bps` |
| `tx_avg_bps` | `float` | From `HourlyUtilizationSample.tx_avg_bps` |
| `tx_peak_bps` | `float` | From `HourlyUtilizationSample.tx_peak_bps` |
| `jitter_avg_ms` | `float \| ""` | Empty string when `peer_count == 0` for that hour (FR-006a) |
| `latency_avg_ms` | `float \| ""` | Empty string when `peer_count == 0` for that hour |
| `loss_avg_pct` | `float \| ""` | Empty string when `peer_count == 0` for that hour |
| `aggregation_method` | `str` | Literal `simple_mean` in every row for MVP |
| `peer_count` | `int` | 0 allowed (indicates the three columns above are empty string) |

**Validation**: The CSV writer emits every row through a single formatter that maps `"N/A"` (from the JSON layer) or `None` to `""`. `aggregation_method` MUST equal `simple_mean` in every row; a code-level assertion enforces this.

**Ordering**: Rows sorted ascending by `(site_name, gateway_name, port_id, hour_epoch)`. This makes diffs across exports deterministic.

---

## Relationships

```
WanPort  1 ── N  VpnPeerPath              (a port carries 0..N peer paths)
WanPort  1 ── N  HourlyUtilizationSample  (one per hour bucket in window)
WanPort  1 ── N  HourlyPerformanceRollup  (one per hour bucket in window; rolled up from VpnPeerPath per-peer hourly series)
Site     1 ── N  SiteWanLinkHealth        (one wrapper response per site request)
```

No object references anywhere in the wire shape — the identity keys are inlined into the response for the frontend's convenience.

---

## Validation Rules Summary

| Rule | Enforced Where | Source |
|------|----------------|--------|
| `aggregation_method == "simple_mean"` in every row (MVP) | `rollup_peer_metrics_simple_mean` + CSV writer assertion | FR-006 |
| Zero-peer hour -> `"N/A"` in JSON, empty string in CSV; never `0`/`null` | `rollup_peer_metrics_simple_mean` emit path + CSV formatter | FR-006a, FR-014 |
| Requested `start` clipped to `end - 14d` | `MistConnection.get_port_tx_rx_bps_hourly` and route handler | FR-010 |
| `clipped == true` implies `retention_notice` non-empty | Route handler | FR-010 |
| Peers with no reporting for an hour excluded from that hour's mean denominator | `rollup_peer_metrics_simple_mean` | Spec §Edge Cases §Peer path churn |
| Every new API call goes through `_handle_rate_limit_response` | `MistConnection` methods | FR-009, SC-005 |
| CSV hour timestamps remain UTC | CSV writer | FR-011, spec §Edge Cases §Time zone |
| `application-health` unavailable does NOT block WAN Link Health tile | Route handler | FR-007, Acceptance 3.4 |

No entity has state transitions in the MVP. All entities are immutable snapshots produced per request.
