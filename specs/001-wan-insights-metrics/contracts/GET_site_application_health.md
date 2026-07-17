# Contract: GET /api/v1/sites/{site_id}/application-health-summary (backend proxy for Mist Application Health SLE)

**Feature**: `001-wan-insights-metrics`
**Route**: `app.py` — new
**Purpose**: Return the site-level "Application Health %" tile data, sourced from the **real, native** Mist Application Health SLE on SSR. No substitution, no proxy metric, no session-storage notice. Covers User Story 3 (P3) end-to-end.

**Runtime**: `mistapi>=0.63.3`. Where the SDK exposes typed helpers for the `sle/site/{id}/metric/application-health/*` endpoints, the backend uses them; otherwise it falls back to the direct `requests.get` pattern already established by `get_vpn_peer_stats` in `mist_connection.py`. All calls funnel through `_handle_rate_limit_response` / `_mark_token_rate_limited`.

**Upstream Mist endpoints** (all called sequentially by this backend route):

- `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary`
- `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend?interval=3600&start=&end=`
- `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/impacted-interfaces?start=&end=`
- `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/threshold`

---

## Request

**Method**: `GET`

**Path**: `/api/v1/sites/{site_id}/application-health-summary`

- `{site_id}` — Mist site UUID (path segment).

**Query parameters**:

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `duration` | enum(`24h`,`3d`,`7d`) | No | `24h` | Rolling window ending at "now". Same clipping rule as the port hourly route |

---

## Response — success

**Status**: `200 OK`

**Content-Type**: `application/json`

**Body** (schema; types per data-model.md § SiteApplicationHealth):

```jsonc
{
  "site_id": "00000000-0000-0000-0000-000000000000",
  "summary_pct": 98.7,
  "threshold_pct": 96.0,
  "trend": [
    {
      "timestamp": 1752624000,
      "pct": 99.1
    }
    // ... one entry per hour bucket, ascending
  ],
  "impacted_interfaces": [
    {
      "interface_name": "ge-0/0/0",
      "gateway_hostname": "site-a-gw-01",
      "gateway_mac": "aabbccddeeff",
      "duration": 3600,
      "degraded": 120,
      "total": 3600
    }
    // ... one row per (gateway, interface) that reported any degradation
  ],
  "clipped": false
}
```

**Classifiers**: Mist aggregates six classifiers server-side into every `summary` and `summary-trend` sample — `jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`. The response does NOT enumerate them per-sample; each `pct` value is the already-aggregated site-wide Application Health %.

**No-data / unavailable case**: When Mist returns HTTP 400 or null across the four endpoints (site does not report application-health), `summary_pct` and `threshold_pct` are `null`, `trend` is `[]`, `impacted_interfaces` is `[]`, and `clipped` reflects retention behavior. No "N/A" sentinel string. No `substitution_notice` field.

```jsonc
{
  "site_id": "00000000-0000-0000-0000-000000000000",
  "summary_pct": null,
  "threshold_pct": null,
  "trend": [],
  "impacted_interfaces": [],
  "clipped": false
}
```

**Clipped case (FR-010)**: `clipped: true` reflects that the requested `start` was clamped to `now - 14 * 86400` before hitting Mist. The route still returns HTTP 200.

---

## Error responses

| Status | Body | Trigger |
|---|---|---|
| `400 Bad Request` | `{"success": false, "error": "duration must be one of: 24h, 3d, 7d"}` | Invalid `duration` |
| `500 Internal Server Error` | `{"success": false, "error": "<message>"}` | Unhandled upstream error (non-429 non-200 non-400) |

**429 handling**: NEVER returned to the caller. All four Mist calls route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. If all tokens are rate-limited, the response is HTTP 200 with the unavailable-case body plus `rate_limited: true`. FR-009 / SC-005.

---

## Server-side behaviour

1. Validate `duration`.
2. Compute clipping window (same rule as the port hourly contract): `start = max(end - duration_seconds, end - 14 * 86400)`; set `clipped` accordingly.
3. Sequentially call the four Mist Application Health SLE endpoints listed at the top of this file:
   - `summary` → populates `summary_pct`
   - `summary-trend?interval=3600` → populates `trend[]`
   - `impacted-interfaces` → populates `impacted_interfaces[]`
   - `threshold` → populates `threshold_pct`
4. Merge into the response envelope. Return HTTP 200 in all cases (including unavailable). Do NOT propagate upstream HTTP 400 to the caller.

**This is a native SLE** — the route MUST NOT fall back to `wan-link-health`, MUST NOT emit a `substitution_notice`, MUST NOT set any session-storage flag on the frontend contract side.

**Concurrency**: No shared mutable state. Idempotent.

---

## Traceability

| Requirement | Where satisfied |
|---|---|
| FR-007 | Native Application Health SLE — `summary_pct` + `threshold_pct` + `trend[]` + `impacted_interfaces[]` from the four Mist endpoints |
| FR-009 | 429 handling documented above |
| FR-010 | `clipped` (same rule as port hourly) |
| FR-016 | No Snowflake / Premium Analytics endpoint touched — Application Health is a live, native SLE on SSR |

The six classifiers Mist aggregates server-side are noted above under the response schema. Pre-cascade references to substitution notice / `wan-link-health` proxy / session-storage gate / SRX-only forward-compat hook have been removed from this contract.
