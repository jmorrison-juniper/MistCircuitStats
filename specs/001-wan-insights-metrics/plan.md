# Implementation Plan: SSR WAN Insights-Equivalent Metrics

**Branch**: `001-wan-insights-metrics` | **Date**: 2026-07-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification at `specs/001-wan-insights-metrics/spec.md`

## Summary

Extend the existing gateway/port dashboard with three additive surfaces that mirror the Juniper Mist "WAN Insights - SSR" dashboard using only live, native Mist REST endpoints (no Snowflake / Premium Analytics, no client-side aggregation, no substitution):

1. Per-port hourly Avg + Peak Rx/Tx utilization sourced from `insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port_id}&interval=1h`.
2. Per-port hourly jitter / latency / loss sourced from the **native** `wan_link_health` insight metric on `insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port_id}&interval=1h` — the API returns per-port arrays natively; no peer discovery, no fanout, no client-side rollup.
3. Site-level "Application Health %" tile sourced from the **real, native** Mist Application Health SLE on SSR: `sle/site/{site_id}/metric/application-health/{summary,summary-trend,impacted-interfaces,threshold}`. No substitution, no proxy.

Delivered as new panels **appended to the existing chart modal** and a new "Export Hourly Metrics" CSV button. No new framework, no new persistence, no changes to auth, no changes to the existing 7-day byte-count charts or existing per-port CSV. All new API calls funnel through the existing multi-token 429 rotation wrapper on `MistConnection`.

## Technical Context

**Language/Version**: Python 3.11+ (Flask app), vanilla ES modules + Chart.js in the single `templates/index.html`.

**Primary Dependencies**: Flask 3.0.0, `mistapi>=0.63.3` SDK (bumped from 0.44.3 as part of this feature — see Note below), `requests==2.31.0`, `python-dotenv`, `gunicorn`. Frontend uses the Chart.js instance already loaded in `index.html`. **No new dependencies** are introduced by this feature.

> Note: this feature bumps `mistapi` from 0.44.3 → `>=0.63.3` per the constraint set at spec-lock. Existing `MistConnection` calls (`getSelf`, `getOrg`, `listOrgSites`, `listOrgDevicesStats`, `searchOrgSwOrGwPorts`, `getSiteDevice`, `searchSiteDevices`, `searchOrgDevices`, `getOrgInventory`, `getOrgDeviceProfile`, `getOrgGatewayTemplate`) must be regression-tested against 0.63.3. Where 0.63.3 exposes typed helpers for the new insight/SLE endpoints (`insights/gateway/{id}/stats?metrics=...`, `sle/site/{id}/metric/application-health/*`), prefer those helpers; otherwise fall back to the existing direct `requests.get` pattern already used by `get_vpn_peer_stats` (same auth header + 429 rotation flow). SDK helper availability is verified in the T-000 upgrade task in `tasks.md` and captured in D-1 of `research.md`.

**Storage**: N/A. Only in-memory class-level caches on `MistConnection` (`_sites_cache`, `_device_profile_cache`, `_gateway_template_cache`). This feature adds **no new caches** in the MVP (see Research §Caching).

**Testing**: The existing project has no automated test harness. Testing for this feature is **manual smoke + acceptance-scenario walkthrough** documented in `quickstart.md`. Adding a full pytest suite is out of scope for this feature and is a documented follow-up.

**Target Platform**: Same as existing app — Flask 3.0 dev server (`python app.py`) or Gunicorn container (`Dockerfile`, `docker-compose.yml`). Runs on Linux/macOS/Windows dev environments; production is the existing container image. No new deployment surface.

**Project Type**: Single-file Flask web app (server-rendered index + client-side Chart.js). `app.py` is the Flask entrypoint, `mist_connection.py` is the sole SDK/HTTP wrapper module, `templates/index.html` embeds all JS + CSS.

**Performance Goals**: SC-001 requires 95th-percentile modal open ≤ 5 s under normal API conditions. The dominant cost is three sequential Mist calls per port (bandwidth + native wan_link_health + site application-health slice); no per-peer fanout is needed since `wan_link_health` returns per-port arrays natively. No new concurrency primitives are introduced.

**Constraints**:

- All new calls MUST route through `MistConnection` and use the same `_handle_rate_limit_response` / `_mark_token_rate_limited` retry pattern documented at `mist_connection.py:141-155` (FR-009, SC-005).
- No new Python module, no new template file, no new JS/CSS file. New backend methods land on the existing `MistConnection` class; new routes land on `app.py`; new UI panels are appended inside the existing `#chartModal` in `templates/index.html`.
- 14-day / 1-hour-interval retention is a hard API limit; requested ranges MUST be clipped and the operator MUST see a visible clipping notice (FR-010).
- UTC-anchored hour buckets; CSV export MUST remain UTC even if UI shows a local-time hint (FR-011, spec §Edge Cases).

**Scale/Scope**: Single-tenant per app instance. Scope of one operator opening one port modal at a time; no multi-user coordination. Total code delta target: ~250-400 lines Python across `mist_connection.py` + `app.py`, ~200-350 lines HTML/JS/CSS appended to `templates/index.html`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Constitution status**: The project constitution at `.specify/memory/constitution.md` is an **unfilled template** (all `[PRINCIPLE_*]` and `[SECTION_*]` placeholders). Per the instruction in the task input, this is **non-blocking** for this plan.

In the absence of a ratified constitution, this plan is evaluated against the sensible defaults implied by the existing codebase and the user's stated tech-stack constraints. These defaults are treated as *provisional* gates:

| Provisional Gate | Result | Notes |
|---|---|---|
| Simplicity / YAGNI (no new stacks, no new frameworks) | PASS | No React, no SPA, no DB, no new deps. Adds methods to an existing class, routes to an existing Flask app, panels to an existing modal. |
| Single-file-per-role structure (`mist_connection.py`, `app.py`, `templates/index.html`) | PASS | All new code lands in these three files. No new backend modules or template files are created. |
| Rate-limit funnel (429 wrapper) | PASS | All three new endpoints route through `MistConnection` and the existing `_handle_rate_limit_response` / `_mark_token_rate_limited` pattern. FR-009 / SC-005. |
| Cache discipline (TTL + invalidation must be explicit) | PASS | Feature introduces **zero new caches** in the MVP. Insight and SLE results are computed on-demand per modal open. Cache addition is a documented Phase 2 concern, gated on measured load. |
| Additive-only UI change (existing 7-day byte-count charts unchanged) | PASS | New panels are appended *below* the existing charts in the same modal; existing per-port CSV export is untouched. FR-012, SC-007. |
| No new auth / RBAC | PASS | FR-017. |

**Gate outcome**: PASS. Proceed to Phase 0. Re-check after Phase 1 design (see bottom of file).

## Project Structure

### Documentation (this feature)

```text
specs/001-wan-insights-metrics/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── GET_gateway_port_hourly.md
│   └── GET_site_application_health.md
├── spec.md              # (already present)
├── checklists/
│   └── requirements.md
└── tasks.md             # created by /speckit.tasks, NOT this command
```

### Source Code (repository root)

This feature is an **additive extension** to the existing single-file layout. No new source files are introduced.

```text
MistCircuitStats/                      # repo root
├── app.py                             # Flask app - ADD new routes only
│                                        + GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly
│                                        + GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly/export
│                                        + GET /api/v1/sites/<site_id>/application-health-summary
├── mist_connection.py                 # Single MistConnection class - ADD new methods only
│                                        + get_gateway_hourly_bandwidth(site_id, device_id, start, end) -> dict
│                                        + get_gateway_hourly_wan_link_health(site_id, device_id, start, end) -> dict
│                                        + get_site_application_health(site_id, start, end) -> dict
├── templates/
│   └── index.html                     # Single template - APPEND to existing #chartModal
│                                        + hourly Avg+Peak Rx/Tx panel (Chart.js)
│                                        + hourly jitter/latency/loss panel (Chart.js) — native wan_link_health
│                                        + timeframe selector (24h default, up to 7d)
│                                        + "Export Hourly Metrics" button
│                                        + retention notice ("last 14 days only")
│                                        + Application Health % tile (site view) — real SLE, no substitution
├── requirements.txt                   # BUMPED: mistapi>=0.63.3 (from 0.44.3)
├── docs/                              # existing product docs, unchanged
└── specs/001-wan-insights-metrics/    # this feature's spec + plan artifacts
```

**Structure Decision**: Keep the current single-file-per-role layout. Every new capability lands in one of the three existing files. No new Python module, no new template file, no new client-side asset file. This directly matches the user's stated non-negotiable constraint ("Single-file backend module `mist_connection.py`, single Flask app `app.py`, single template `templates/index.html` (embedded JS + CSS)").

## Complexity Tracking

No constitution-check violations — this section is empty by design.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)*  |            |                                     |

## Post-Design Constitution Re-Check

After Phase 1 artifacts (`data-model.md`, `contracts/`, `quickstart.md`) were drafted:

- Simplicity / YAGNI: still PASS. Data model has 6 lightweight entity shapes (WanPort, HourlyUtilizationSample, HourlyPortWanLinkHealth, PortHourlyResponse, SiteApplicationHealth, HourlyMetricsCsvRow), all defined inline in Python dicts on the wire; no new class hierarchy.
- Single-file-per-role: still PASS. Contracts confirm all wire shapes are produced by methods added to `MistConnection` and served by routes added to `app.py`.
- Rate-limit funnel: still PASS. Every contract explicitly documents the 429 retry path and error shape.
- Cache discipline: still PASS. No caches added.
- Additive-only UI: still PASS. Quickstart validates the existing 7-day byte-count charts and existing per-port CSV export are unchanged.
- No new auth: still PASS.

**Re-check outcome**: PASS. Design is consistent with the pre-Phase-0 gate.
