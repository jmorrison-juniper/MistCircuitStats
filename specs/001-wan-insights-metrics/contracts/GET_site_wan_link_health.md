# Contract: GET /api/site/{site_id}/wan_link_health

**Feature**: `001-wan-insights-metrics`
**Route**: `app.py` — new
**Purpose**: Return the site-level "WAN Link Health %" tile data, sourced from the `wan-link-health` site SLE endpoint, plus a substitution notice explaining that this metric stands in for the (unavailable) "Application Health %" on SSR/SVR sites. Covers User Story 3 (P3) end-to-end.

---

## Request

**Method**: `GET`

**Path**: `/api/site/{site_id}/wan_link_health`

- `{site_id}` — Mist site UUID (path segment).

**Query parameters**:

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `duration` | enum(`24h`,`3d`,`7d`) | No | `24h` | Rolling window ending at "now". Same clipping rule as the port hourly route |

---

## Response — success

**Status**: `200 OK`

**Content-Type**: `application/json`

**Body**:

```jsonc
{
  "success": true,
  "available": true,
  "reason": null,
  "site_id": "00000000-0000-0000-0000-000000000000",
  "site_name": "Site A",

  "health_pct": 98.7,

  "classifiers": {
    "network-jitter": 0.4,
    "network-loss": 0.2,
    "network-latency": 0.1,
    "interface-congestion": 0.3,
    "network-vpn-path-down": 0.2,
    "isp-reachability-arp": 0.05,
    "isp-reachability-dhcp": 0.05
  },

  "hourly": [
    {
      "hour_epoch": 1752624000,
      "hour_iso": "2026-07-17T00:00:00Z",
      "health_pct": 99.1,
      "classifier_breakdown": {
        "network-jitter": 0.3,
        "network-loss": 0.1,
        "network-latency": 0.1,
        "interface-congestion": 0.2,
        "network-vpn-path-down": 0.1,
        "isp-reachability-arp": 0.05,
        "isp-reachability-dhcp": 0.05
      }
    }
    // ... one entry per hour bucket, ascending
  ],

  "substitution_notice": "Substituted for Application Health %. True Application Health is AppTrack/AppQoE-based and is not implemented on SSR/SVR gateways; the live Mist API returns HTTP 400 or null for `application-health` SLE on SSR sites.",

  "duration": "24h",
  "start_epoch": 1752624000,
  "end_epoch": 1752710400,
  "clipped": false,
  "retention_notice": null
}
```

**Rules**:

- `classifiers` MUST include ALL seven keys, always, in the order shown. Missing upstream keys are emitted as `0.0`.
- `hourly[i].classifier_breakdown` MUST also include all seven keys, always.
- `substitution_notice` is verbatim from Acceptance Scenario 3.2. Never localize, never abbreviate.

---

## Response — unavailable (SSR without health data)

When the Mist `wan-link-health` SLE endpoint returns HTTP 400 or a null body (SSR site with no reporting WAN uplinks):

**Status**: `200 OK` (NOT 400 to the caller — the substitution is graceful, per Acceptance Scenario 3.4)

**Body**:

```jsonc
{
  "success": true,
  "available": false,
  "reason": "wan-link-health SLE returned HTTP 400",
  "site_id": "00000000-0000-0000-0000-000000000000",
  "site_name": "Site A",
  "health_pct": null,
  "classifiers": {
    "network-jitter": 0.0,
    "network-loss": 0.0,
    "network-latency": 0.0,
    "interface-congestion": 0.0,
    "network-vpn-path-down": 0.0,
    "isp-reachability-arp": 0.0,
    "isp-reachability-dhcp": 0.0
  },
  "hourly": [],
  "substitution_notice": "Substituted for Application Health %. True Application Health is AppTrack/AppQoE-based and is not implemented on SSR/SVR gateways; the live Mist API returns HTTP 400 or null for `application-health` SLE on SSR sites.",
  "duration": "24h",
  "start_epoch": 1752624000,
  "end_epoch": 1752710400,
  "clipped": false,
  "retention_notice": null
}
```

The frontend renders the "unavailable" tile state with the classifier list still visible (from the fixed key set) per Acceptance Scenario 3.4.

---

## Error responses

| Status | Body | Trigger |
|---|---|---|
| `400 Bad Request` | `{"success": false, "error": "duration must be one of: 24h, 3d, 7d"}` | Invalid `duration` |
| `500 Internal Server Error` | `{"success": false, "error": "<message>"}` | Unhandled upstream error (non-429 non-200 non-400) |

**429 handling**: same as the port hourly contract — never surfaced to caller. If rate-limited, the response is HTTP 200 with `rate_limited: true` added and `available: false`, `reason: "rate limited across all tokens"`. FR-009 / SC-005.

---

## Server-side behaviour

1. Validate `duration`.
2. Resolve `site_name` from `MistConnection.get_sites()` (cached).
3. Compute clipping window (same rule as port hourly).
4. Call `MistConnection.get_site_wan_link_health(site_id, start, end)`.
5. When the wrapper returns `{available: false, ...}`, assemble the "unavailable" body per above. **Do NOT** propagate the upstream HTTP 400 to the caller.
6. When available, map the upstream SLE response into the `classifiers` + `hourly` shape defined above. Fill any missing classifier keys with `0.0`.
7. `application-health` SLE is intentionally NOT called by this route. Acceptance Scenario 3.3 (SRX-based sites showing true Application Health) is documented as a forward-compatibility hook only and is out of MVP scope.

**Concurrency**: No shared mutable state. Idempotent.

---

## Traceability

| Requirement | Where satisfied |
|---|---|
| FR-007 | `health_pct` + `classifiers` + `hourly` schema |
| FR-008 | `substitution_notice` verbatim in every response |
| FR-009 | 429 handling documented above |
| FR-010 | `clipped` + `retention_notice` (same rule as port hourly) |
| FR-016 | No Snowflake / Premium Analytics endpoint touched |
| Acceptance 3.1 | `hourly[]` populated with per-hour user-minutes-degraded by classifier |
| Acceptance 3.2 | Substitution notice string verbatim |
| Acceptance 3.3 | Forward-compat hook documented; MVP does not fetch `application-health` |
| Acceptance 3.4 | "unavailable" body shape keeps classifier list visible |
| SC-008 | Frontend renders substitution notice within same viewport as tile (frontend concern, but data contract supports it) |
