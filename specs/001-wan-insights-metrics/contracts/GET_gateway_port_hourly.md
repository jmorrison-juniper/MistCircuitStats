# Contract: GET /api/v1/sites/{site_id}/gateways/{device_id}/ports/{port_id}/hourly

**Feature**: `001-wan-insights-metrics`
**Route**: `app.py` — new
**Purpose**: Return per-port hourly Rx/Tx utilization and per-port hourly jitter / latency / loss for a single WAN port over a 24-hour, 3-day, or 7-day window (clipped server-side to the API's 14-day retention limit). Per-port jitter/latency/loss is sourced from the **native `wan_link_health` insight metric** — no peer discovery, no fanout, no client-side rollup. The response also carries a per-port slice of the site's real Application Health SLE.

**Runtime**: `mistapi>=0.63.3`. Where the SDK exposes typed helpers for the new insight/SLE endpoints, the backend uses them; otherwise it falls back to the direct `requests.get` pattern already established by `get_vpn_peer_stats` in `mist_connection.py`. All calls funnel through `_handle_rate_limit_response` / `_mark_token_rate_limited`.

---

## Request

**Method**: `GET`

**Path**: `/api/v1/sites/{site_id}/gateways/{device_id}/ports/{port_id}/hourly`

- `{site_id}` — Mist site UUID (path segment).
- `{device_id}` — Mist device UUID (path segment). Must be a gateway.
- `{port_id}` — Local port identifier. May contain `/` (e.g. `ge-0/0/0`); the route uses Flask `<path:port_id>` and calls `urllib.parse.unquote` before use, matching the existing `/api/gateway/<gateway_id>/port/<path:port_id>/traffic` route.

**Query parameters**:

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `duration` | enum(`24h`,`3d`,`7d`) | No | `24h` | Rolling window ending at "now". Values outside the enum -> HTTP 400 |

**Headers**: none required beyond default. Auth is server-side via `MistConnection`'s token.

**CSV export**: served by a sibling route, `GET /api/v1/sites/{site_id}/gateways/{device_id}/ports/{port_id}/hourly/export` (same path params + `duration`). This JSON route does NOT accept a `format` query param. See plan.md § Project Structure for the route list, and data-model.md § HourlyMetricsCsvRow for the CSV column order and formatting rules.

---

## Response — JSON (this route)

**Status**: `200 OK` on success (including per-section rate-limit degradations, see below).

**Content-Type**: `application/json`

**Body** (schema; types per data-model.md § PortHourlyResponse):

```jsonc
{
  "success": true,
  "port_id": "ge-0/0/0",
  "device_id": "00000000-0000-0000-0000-000000000000",
  "gateway_hostname": "site-a-gw-01",
  "site_id": "00000000-0000-0000-0000-000000000000",
  "site_name": "Site A",
  "start": 1752624000,
  "end": 1752710400,
  "interval": 3600,
  "clipped": false,
  "retention_notice": "",

  "hourly": [
    {
      "timestamp": 1752624000,
      "hour_iso": "2026-07-17T00:00:00Z",
      "tx_bps": 987654.0,
      "rx_bps": 1234567.0,
      "max_tx_bps": 1500000.0,
      "max_rx_bps": 2345678.0,
      "avg_latency_ms": 12.4,
      "avg_jitter_ms": 1.8,
      "avg_loss_pct": 0.02
    }
    // ... one entry per hour bucket, ascending
  ],

  "port_app_health": {
    "summary_pct": 98.7,
    "threshold_pct": 96.0
  },

  "hourly_app_health": [
    {
      "timestamp": 1752624000,
      "pct": 99.1
    }
    // ... one entry per hour bucket, ascending
  ]
}
```

**Dropped fields** (present in the pre-cascade envelope, removed in this rev): `peers`, `peer_breakdown`, `aggregation_method`, `peer_count`, `empty_performance`.

**No-data-in-window case**: `hourly` is `[]` and `hourly_app_health` is `[]`. No `"N/A"` sentinel, no `peer_count: 0` row. `clipped` reflects whether retention forced a clamp. Route MUST NOT return HTTP 404.

```jsonc
{
  "success": true,
  "hourly": [],
  "hourly_app_health": [],
  "port_app_health": null,
  "clipped": false,
  "retention_notice": ""
  // ... other envelope fields as above
}
```

**Clipped case (FR-010)**: `clipped: true`, `retention_notice: "Data range clipped to the API's 14-day 1h-interval retention window (from YYYY-MM-DDTHH:MM:SSZ to YYYY-MM-DDTHH:MM:SSZ)."`, `start` reflects the CLAMPED start (not the requested one).

---

## CSV export — sibling route

CSV export is served by `GET /api/v1/sites/{site_id}/gateways/{device_id}/ports/{port_id}/hourly/export` (documented for reference here — a full separate contract is not maintained; this route is a thin wrapper around the same server-side pipeline as the JSON route above).

**Status**: `200 OK` on success.

**Content-Type**: `text/csv; charset=utf-8`

**Headers**: `Content-Disposition: attachment; filename="hourly_metrics_{gateway_hostname}_{port_id}_{iso_utc_now}.csv"`

**Body**: RFC 4180 CSV. First row is a header. Subsequent rows follow the 12-column order and formatting fixed by data-model.md § HourlyMetricsCsvRow (governed by spec.md § FR-011 and `docs/customer_response_wan_insights.md` line 219):

```
site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct
Site A,site-a-gw-01,ge-0/0/0,1752624000,2026-07-17T00:00:00Z,1234567.0,2345678.0,987654.0,1500000.0,1.8,12.4,0.02
Site A,site-a-gw-01,ge-0/0/0,1752627600,2026-07-17T01:00:00Z,1200000.0,2200000.0,900000.0,1400000.0,,,
```

Second data row shows an hour with no `wan_link_health` telemetry: the three performance columns are empty string. No `aggregation_method` column. No `peer_count` column. No `site_id` column. Exactly 12 columns.

**Ordering**: rows sorted by `(site_name, gateway_name, port_id, hour_epoch)` ascending.

---

## Error responses

| Status | Body | Trigger |
|---|---|---|
| `400 Bad Request` | `{"success": false, "error": "duration must be one of: 24h, 3d, 7d"}` | Invalid `duration` |
| `500 Internal Server Error` | `{"success": false, "error": "<message>"}` | Unhandled upstream error (non-429 non-200) |

**429 handling**: NEVER returned to the caller. All new `MistConnection` methods route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. If all tokens are rate-limited, the route returns HTTP 200 with `success: true` and a per-section `rate_limited` flag, matching the pattern established by `get_vpn_peer_stats` (`mist_connection.py:891-987`).

Example rate-limited section:

```jsonc
{
  "success": true,
  "hourly": [],
  "hourly_app_health": [],
  "port_app_health": null,
  "rate_limited": {
    "bandwidth": true,
    "wan_link_health": false,
    "app_health": false
  }
  // ... other fields
}
```

The frontend renders a "temporarily rate-limited, try again shortly" banner for any section marked rate-limited.

---

## Server-side behaviour

1. Validate `duration`.
2. Compute `end = now`, `raw_start = end - duration_seconds`.
3. Compute `start = max(raw_start, end - 14 * 86400)`. If `start != raw_start`, set `clipped = true` and populate `retention_notice`.
4. Call `MistConnection.get_gateway_hourly_bandwidth(site_id, device_id, port_id, start, end)` → returns per-hour bandwidth samples for this port. Wraps `GET .../insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port_id}&interval=1h&start=&end=` (SDK helper preferred, direct-`requests` fallback).
5. Call `MistConnection.get_gateway_hourly_wan_link_health(site_id, device_id, port_id, start, end)` — the `wan_link_health` insight metric is a native per-port series (device scope, keyed-timeseries). Wraps `GET .../insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port_id}&interval=1h&start=&end=`. No peer discovery, no fanout, no rollup.
6. Call `MistConnection.get_site_application_health(site_id, start, end)` and extract the per-port slice for this `(gateway_hostname, port_id)` into `port_app_health`, plus the site-wide hourly trend filtered to this port view into `hourly_app_health`. This is the real Mist Application Health SLE (native on SSR) — no substitution.
7. Merge steps 4–5 into the `hourly` list by aligning on `timestamp`. Assemble the `PortHourlyResponse` envelope. CSV export is served by the sibling `/export` route (thin wrapper around the same server-side pipeline that streams through the CSV writer instead of `jsonify`); this JSON route never returns CSV.

**Concurrency**: One request at a time per port modal. No shared mutable state introduced.

**Idempotency**: Fully idempotent. Same `(site_id, device_id, port_id, duration)` returns the same window boundaries (with hour bucket contents varying only as underlying data ages out of the 14-day window).

---

## Traceability

| Requirement | Where satisfied |
|---|---|
| FR-001, FR-002 | `hourly[].tx_bps` / `rx_bps` / `max_tx_bps` / `max_rx_bps` schema + `get_gateway_hourly_bandwidth` |
| FR-003, FR-004 | `hourly[].avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` from native `wan_link_health` — no fanout, no rollup |
| FR-007 | `port_app_health` + `hourly_app_health` slices of the native Application Health SLE (site-scope) |
| FR-009 | Every upstream call goes through `_handle_rate_limit_response` |
| FR-010 | `clipped`, `retention_notice`, server-side clamp |
| FR-011 | CSV sibling route, 12-column order, filename convention |
| FR-012 | Frontend consumes this route from the extended existing modal (see quickstart.md) |
| FR-015 | Empty `hourly: []` empty-state signal |
| SC-005 | 429 handling documented above |

The corrected FR list is authoritative in `spec.md`. Pre-cascade references to FR-005/6/6a/13/14 (peer rollup, `"N/A"` sentinel, aggregation-method label, peer breakdown UI) have been removed from this contract.
