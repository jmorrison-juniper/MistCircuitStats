# Contract: GET /api/gateway/{gateway_id}/port/{port_id}/hourly

**Feature**: `001-wan-insights-metrics`
**Route**: `app.py` — new
**Purpose**: Return the per-port hourly Rx/Tx utilization and per-port hourly aggregated jitter / latency / loss for a single WAN port over a 24-hour, 3-day, or 7-day window (clipped server-side to the API's 14-day retention limit).

---

## Request

**Method**: `GET`

**Path**: `/api/gateway/{gateway_id}/port/{port_id}/hourly`

- `{gateway_id}` — Mist device UUID (path segment). Must be a gateway.
- `{port_id}` — Local port identifier. May contain `/` (e.g. `ge-0/0/0`); the route uses Flask `<path:port_id>` and calls `urllib.parse.unquote` before use, matching the existing `/api/gateway/<gateway_id>/port/<path:port_id>/traffic` route.

**Query parameters**:

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `site_id` | UUID string | Yes | — | Mist site UUID (existing dashboard already has this in context) |
| `duration` | enum(`24h`,`3d`,`7d`) | No | `24h` | Rolling window ending at "now". Values outside the enum -> HTTP 400 |

**Headers**: none required beyond default. Auth is server-side via `MistConnection`'s token.

**CSV export**: served by a sibling route, `GET /api/gateway/{gateway_id}/port/{port_id}/hourly/csv` (same path params + `site_id` + `duration`). This JSON route does NOT accept a `format` query param. See plan.md § Project Structure for the route list, and data-model.md § HourlyMetricsCsvRow for the CSV column order and formatting rules.

---

## Response — JSON (this route)

**Status**: `200 OK` on success (including per-section rate-limit degradations, see below).

**Content-Type**: `application/json`

**Body** (schema; types per data-model.md):

```jsonc
{
  "success": true,
  "port_id": "ge-0/0/0",
  "gateway_id": "00000000-0000-0000-0000-000000000000",
  "gateway_name": "site-a-gw-01",
  "site_id": "00000000-0000-0000-0000-000000000000",
  "site_name": "Site A",
  "duration": "24h",
  "interval_seconds": 3600,
  "start_epoch": 1752624000,
  "end_epoch": 1752710400,
  "clipped": false,
  "retention_notice": "",

  "utilization": [
    {
      "hour_epoch": 1752624000,
      "hour_iso": "2026-07-17T00:00:00Z",
      "rx_avg_bps": 1234567.0,
      "rx_peak_bps": 2345678.0,
      "tx_avg_bps": 987654.0,
      "tx_peak_bps": 1500000.0
    }
    // ... one entry per hour bucket, ascending
  ],

  "performance": [
    {
      "hour_epoch": 1752624000,
      "hour_iso": "2026-07-17T00:00:00Z",
      "avg_latency_ms": 12.4,
      "avg_jitter_ms": 1.8,
      "avg_loss_pct": 0.02,
      "aggregation_method": "simple_mean",
      "peer_count": 3
    }
    // ... one entry per hour bucket, ascending
  ],

  "peers": [
    {
      "port_id": "ge-0/0/0",
      "peer_router_name": "site-b-gw-01",
      "peer_mac": "aabbccddeeff",
      "peer_port_id": "ge-0/0/1",
      "policy": "default"
    }
  ],

  "peer_breakdown": {
    "site-b-gw-01::ge-0/0/1": [
      {
        "hour_epoch": 1752624000,
        "avg_latency": 12.4,
        "avg_jitter": 1.8,
        "avg_loss": 0.02
      }
    ]
  },

  "aggregation_method": "simple_mean",
  "empty_utilization": false,
  "empty_performance": false
}
```

**Zero-peer / no-VPN-peers case (FR-006a, FR-014)**: `peers` is `[]`, `empty_performance` is `true`, and every `performance[i]` entry has `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` set to the JSON string `"N/A"` and `peer_count: 0`. `utilization` renders normally.

```jsonc
"performance": [
  {
    "hour_epoch": 1752624000,
    "hour_iso": "2026-07-17T00:00:00Z",
    "avg_latency_ms": "N/A",
    "avg_jitter_ms": "N/A",
    "avg_loss_pct": "N/A",
    "aggregation_method": "simple_mean",
    "peer_count": 0
  }
]
```

**Empty-utilization case (FR-015)**: `utilization` is `[]`, `empty_utilization` is `true`. Route MUST NOT return HTTP 404.

**Clipped case (FR-010)**: `clipped: true`, `retention_notice: "Data range clipped to the API's 14-day 1h-interval retention window (from YYYY-MM-DDTHH:MM:SSZ to YYYY-MM-DDTHH:MM:SSZ)."`, `start_epoch` reflects the CLAMPED start (not the requested one).

---

## CSV export — sibling route

CSV export is served by `GET /api/gateway/{gateway_id}/port/{port_id}/hourly/csv` (documented for reference here — a full separate contract is not maintained; this route is a thin wrapper around the same server-side pipeline as the JSON route above).

**Status**: `200 OK` on success.

**Content-Type**: `text/csv; charset=utf-8`

**Headers**: `Content-Disposition: attachment; filename="hourly_metrics_{gateway_name}_{port_id}_{iso_utc_now}.csv"`

**Body**: RFC 4180 CSV. First row is a header. Subsequent rows follow the column order and formatting fixed by data-model.md § HourlyMetricsCsvRow:

```
site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct,aggregation_method,peer_count
Site A,site-a-gw-01,ge-0/0/0,1752624000,2026-07-17T00:00:00Z,1234567.0,2345678.0,987654.0,1500000.0,1.8,12.4,0.02,simple_mean,3
Site A,site-a-gw-01,ge-0/0/0,1752627600,2026-07-17T01:00:00Z,1200000.0,2200000.0,900000.0,1400000.0,,,,simple_mean,0
```

Second data row shows a zero-peer hour: performance columns are empty string, `aggregation_method` still `simple_mean`, `peer_count` is `0`.

**Ordering**: rows sorted by `(site_name, gateway_name, port_id, hour_epoch)` ascending.

---

## Error responses

| Status | Body | Trigger |
|---|---|---|
| `400 Bad Request` | `{"success": false, "error": "site_id is required"}` | Missing `site_id` |
| `400 Bad Request` | `{"success": false, "error": "duration must be one of: 24h, 3d, 7d"}` | Invalid `duration` |
| `500 Internal Server Error` | `{"success": false, "error": "<message>"}` | Unhandled upstream error (non-429 non-200) |

**429 handling**: NEVER returned to the caller. All new `MistConnection` methods route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. If all tokens are rate-limited, the route returns HTTP 200 with populated `success: true` and a per-section `rate_limited: true` flag on `utilization` or `performance`, matching the pattern established by `get_vpn_peer_stats` (`mist_connection.py:891-987`).

Example rate-limited section:

```jsonc
{
  "success": true,
  "utilization": [],
  "rate_limited": {
    "utilization": true,
    "performance": false
  },
  "empty_utilization": true,
  "empty_performance": false
  // ... other fields
}
```

The frontend renders a "temporarily rate-limited, try again shortly" banner for any section marked rate-limited.

---

## Server-side behaviour

1. Validate `site_id`, `duration`.
2. Compute `end = now`, `raw_start = end - duration_seconds`.
3. Compute `start = max(raw_start, end - 14 * 86400)`. If `start != raw_start`, set `clipped = true` and populate `retention_notice`.
4. Call `MistConnection.get_port_tx_rx_bps_hourly(site_id, device_id=gateway_id, port_id, start, end)`.
5. Call `MistConnection.get_vpn_peer_stats(site_id, device_mac)` to enumerate peers on the port. `device_mac` is resolved from `get_gateway_stats` or from cached gateway metadata. Filter peers by `port_id`.
6. For each peer, call `MistConnection.get_port_vpn_peer_metrics_hourly(site_id, device_id, port_id, peer_mac_or_router_name, peer_port_id, policy, start, end)`. Calls are serialized to respect the shared token-rate budget.
7. Pass the collected per-peer hourly series to `MistConnection.rollup_peer_metrics_simple_mean(...)`.
8. Assemble the `PortHourlyResponse` envelope. If `format=csv`, stream it through the CSV writer instead of `jsonify`.

**Concurrency**: One request at a time per port modal. No shared mutable state introduced.

**Idempotency**: Fully idempotent. Same `(gateway_id, port_id, site_id, duration)` returns the same window boundaries (with hour bucket contents varying only as underlying data ages out of the 14-day window).

---

## Traceability

| Requirement | Where satisfied |
|---|---|
| FR-001, FR-002 | `utilization[]` schema + `MistConnection.get_port_tx_rx_bps_hourly` |
| FR-003, FR-004, FR-005 | Peer discovery + fanout + `rollup_peer_metrics_simple_mean` |
| FR-006 | `aggregation_method: "simple_mean"` in every row |
| FR-006a, FR-014 | Zero-peer JSON `"N/A"` / CSV empty string mapping |
| FR-009 | Every upstream call goes through `_handle_rate_limit_response` |
| FR-010 | `clipped`, `retention_notice`, server-side clamp |
| FR-011 | CSV branch, column order, filename convention |
| FR-012 | Frontend consumes this route from the extended existing modal (see quickstart.md) |
| FR-013 | `aggregation_method` + `peer_breakdown` enable client-side explainer |
| FR-015 | `empty_utilization` empty-state signal |
| SC-002 | `peer_breakdown` allows manual recomputation |
| SC-003 | Per-peer breakdown reachable one click from aggregate row |
| SC-005 | 429 handling documented above |
