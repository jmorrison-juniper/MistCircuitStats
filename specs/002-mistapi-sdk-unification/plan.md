# Implementation Plan: Unify Mist API Access Under the `mistapi` SDK

**Branch**: `002-mistapi-sdk-unification` | **Date**: 2026-07-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification at `specs/002-mistapi-sdk-unification/spec.md`

## Summary

Retire the last 7 direct-REST call sites in the app and route every Mist Cloud call through the `mistapi` Python SDK, so that:

1. All Mist traffic funnels through `MistConnection._handle_rate_limit_response` and inherits the shared multi-token 60-second per-token 429 rotation (the legacy inline `requests.get` in `app.py::get_port_traffic` is the last bypass path; closing it eliminates the "hard 429 to the frontend" outage class).
2. The README/architecture story collapses from "two ways to talk to Mist" to one SDK path — matching the code state.
3. The HTTP response shapes served to `templates/index.html` (both JSON envelopes and CSV export columns) remain byte-identical modulo timestamps and rate-limit counters. No frontend template change is required or permitted.

The technical design (which SDK function replaces each REST path) was validated against installed `mistapi` 0.63.3 in a prior session via `inspect.signature`. This plan records the mapping and the invariants a migrating engineer must preserve; it does not re-explore the design space.

## Technical Context

**Language/Version**: Python 3.11+ (Flask app), vanilla ES modules + Chart.js in `templates/index.html` (untouched by this feature).

**Primary Dependencies**: Flask 3.0.0, `mistapi>=0.63.3` SDK (already the pinned floor from feature 001; no change), `python-dotenv`, `gunicorn`. **`requests` is being demoted**: it remains a transitive dependency (Flask/`mistapi` still use it) but `mist_connection.py` and `app.py` MUST no longer import it directly for Mist traffic. Drop the `import requests` lines that become dead after migration.

**Storage**: N/A. In-memory caches on `MistConnection` are unchanged.

**Testing**: No automated test harness exists. Acceptance is (a) byte-diff of pre/post JSON responses for the 7 endpoints (spec SC-002), (b) manual smoke test of the WAN Insights modal and click-a-cell chart popup across the 5 duration presets (spec SC-006), and (c) forced-429 rotation check per endpoint (spec SC-003). Recorded in `spec.md` §Success Criteria — no new automated tests in scope (spec §Out of Scope).

**Target Platform**: Same as existing app — Flask 3.0 dev server or Gunicorn container. No new deployment surface.

**Project Type**: Single-file Flask web app. `app.py` is the Flask entrypoint, `mist_connection.py` is the sole Mist wrapper module, `templates/index.html` embeds all JS + CSS.

**Performance Goals**: No new perf goals introduced. The SDK path is a thin transport swap over the same HTTP calls — network cost is unchanged. Adds one dict-copy in `response.data` handling; negligible.

**Constraints**:

- All 7 migrated calls MUST route through `MistConnection._handle_rate_limit_response(response)` (spec FR-006, SC-003).
- Response shapes to `templates/index.html` MUST remain byte-identical modulo timestamps and rate-limit counters (spec FR-011, SC-002).
- `pyproject.toml`, `requirements.txt`, `.github/workflows/quality-gates.yml`, and `templates/index.html` MUST NOT be modified (spec FR-012).
- Migrated method docstrings MUST name the SDK function they call and preserve pre-existing Why-line quirks: device-scoped `wan_link_health`, `/summary-trend` in place of `/summary`, 14-day retention (spec FR-008). `interrogate` ≥90% and `pydoclint --style=google` must continue to pass.

**Scale/Scope**: 4 method migrations in `mist_connection.py`, 1 new public wrapper method on `MistConnection`, 1 route-body reduction in `app.py`, plus README/CHANGELOG updates. Net code delta: approximately −50 to −100 lines Python (SDK calls are shorter than the manual `requests.get` + 429 pattern), zero HTML/JS/CSS delta.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Constitution status**: The project constitution at `.specify/memory/constitution.md` is an unfilled template (all `[PRINCIPLE_*]` and `[SECTION_*]` placeholders). Per the same convention used in feature 001, this is non-blocking for this plan.

In the absence of a ratified constitution, this migration is evaluated against the sensible defaults established by feature 001 and reinforced by this spec:

| Provisional Gate | Result | Notes |
|---|---|---|
| Simplicity / YAGNI (no new stacks, no new frameworks) | PASS | No new deps, no new modules, no new templates. Swaps one transport for another that is already the majority path. |
| Single-file-per-role structure (`mist_connection.py`, `app.py`, `templates/index.html`) | PASS | All code changes land in the first two files. Third is explicitly untouched (spec FR-012). |
| Rate-limit funnel (429 wrapper) | PASS **(strengthened)** | The migration exists precisely to bring the last 7 call paths inside the funnel (spec FR-006, User Story 1). |
| Cache discipline | PASS | No caches added or removed. |
| Additive-only for the frontend | PASS | Zero template change (spec FR-011, FR-012). |
| No new auth / RBAC | PASS | Auth is still the shared `MistConnection.apisession` object; token rotation is unchanged. |
| Docstring quality (≥90% `interrogate`, `pydoclint --style=google`) | PASS | Docstring rewrites required by FR-008 preserve or increase coverage; each migrated method names the SDK function it now calls. |

**Gate outcome**: PASS. Proceed to Phase 0. Re-check after Phase 1 design (see bottom of file).

## Project Structure

### Documentation (this feature)

```text
specs/002-mistapi-sdk-unification/
├── plan.md              # This file
├── spec.md              # (already present)
├── checklists/          # (already present)
└── tasks.md             # created by /speckit.tasks, NOT this command
```

No `research.md`, `data-model.md`, `contracts/`, or `quickstart.md` are produced for this feature:

- **`research.md`**: The design is settled — SDK function names and signatures were validated against installed `mistapi` 0.63.3 in the prior session via `inspect.signature` (results captured inline in the SDK Mapping Table below). There is no unknown left to research.
- **`data-model.md`**: No schema change. The SDK's `response.data` returns the same JSON shape as the prior direct-REST `response.json()`, and every downstream parser (`get_gateway_hourly_bandwidth`, `_parse_wan_link_health_arrays`, `_extract_sle_samples`, `_parse_app_health_*`, `get_site_application_health`) is unchanged by design (spec FR-011).
- **`contracts/`**: Wire contracts are unchanged. The two contract files from feature 001 (`GET_gateway_port_hourly.md`, `GET_site_application_health.md`) continue to describe the JSON envelope that the migrated code must reproduce byte-for-byte.
- **`quickstart.md`**: The manual smoke test in spec SC-006 is the runbook; duplicating it here would drift.

### Source Code (repository root)

This feature is a **transport-swap migration**. No new source files are introduced; only two Python files change, plus the two docs files.

```text
MistCircuitStats/                      # repo root
├── app.py                             # Reduce ONE route body — no new routes
│                                        - remove inline `import requests`, `unquote`, headers/url/params blocks from get_port_traffic
│                                        + single call: mist.get_gateway_port_traffic_series(site_id, gateway_id, port_id, start, end, interval)
│                                        + preserve the pre-migration JSON envelope: {timestamps, rx_bps, tx_bps}
├── mist_connection.py                 # 4 method migrations + 1 new public wrapper
│                                        ~ get_vpn_peer_stats              → searchOrgPeerPathStats
│                                        ~ _insights_gateway_stats         → getSiteInsightMetricsForGateway
│                                        ~ _insights_device_wan_link_health → getSiteInsightMetricsForDevice(metric="wan_link_health")
│                                        ~ _sle_app_health_get              → getSiteSleSummaryTrend / listSiteSleImpactedInterfaces / getSiteSleThreshold
│                                        + get_gateway_port_traffic_series (new public wrapper for app.py)
│                                        - drop `import requests` at top-of-file if nothing else in the module still uses it (verify with grep)
├── README.md                          # Merge "Direct REST endpoints" into a single "Mist API Endpoints" list
│                                        - remove "two ways" framing from Architecture
│                                        - remove "Direct REST endpoints" subheading
├── CHANGELOG.md                       # [Unreleased] → Changed entry naming the unification
│                                        + note that the legacy chart-modal port-traffic route now benefits from shared token rotation
├── pyproject.toml                     # UNCHANGED (spec FR-012)
├── requirements.txt                   # UNCHANGED (spec FR-012)
├── .github/workflows/quality-gates.yml# UNCHANGED (spec FR-012)
└── templates/index.html               # UNCHANGED (spec FR-011, FR-012)
```

**Structure Decision**: Keep the single-file-per-role layout inherited from feature 001. No new files. Every migrated call collapses to fewer lines because the SDK path already handles URL construction and headers, and the multi-token 429 rotation wrapper (`_handle_rate_limit_response` + `_mark_token_rate_limited`) is already the idiomatic retry-on-429 pattern used by the module's other 11 SDK-backed methods.

## SDK Mapping Table

The 7 direct-REST call sites and their target SDK functions. Signatures were verified against installed `mistapi` 0.63.3 via `inspect.signature` in the prior session and re-confirmed at plan time — they are stable.

| # | Current call site (file:approx-line) | Direct REST path (pre-migration) | Target SDK function |
|---|---|---|---|
| 12 | `mist_connection.py::get_vpn_peer_stats` (~L899-975) | `POST/GET /api/v1/orgs/{org_id}/stats/vpn_peers/search` | `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats(session, org_id, mac=…, site_id=…)` |
| 13 | `mist_connection.py::_insights_gateway_stats` (~L981-1033) | `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats` | `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(session, site_id, device_id, metrics=…, port_id=…, interval=…, start=…, end=…)` |
| 14 | `mist_connection.py::_insights_device_wan_link_health` (~L1035-1080) | `GET /api/v1/sites/{site_id}/insights/device/{mac}/wan_link_health` | `mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice(session, site_id, metric="wan_link_health", device_mac=mac, port_id=…, interval=…, start=…, end=…)` |
| 15 | `mist_connection.py::_sle_app_health_get` (summary-trend) (~L1269-1307) | `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend` | `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend(session, site_id, "site", site_id, "application-health", start=…, end=…)` |
| 16 | `mist_connection.py::_sle_app_health_get` (impacted-interfaces) (same helper) | `GET .../application-health/impacted-interfaces` | `mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces(session, site_id, "site", site_id, "application-health", start=…, end=…)` |
| 17 | `mist_connection.py::_sle_app_health_get` (threshold) (same helper) | `GET .../application-health/threshold` | `mistapi.api.v1.sites.sle.getSiteSleThreshold(session, site_id, "site", site_id, "application-health")` |
| 18 | `app.py::get_port_traffic` inline `requests.get` (~L122-167) | `GET /api/v1/sites/{site_id}/insights/gateway/{gateway_id}/stats?metrics=rx_bps,tx_bps` | Same SDK function as #13, reached through a new `MistConnection.get_gateway_port_traffic_series(site_id, gateway_id, port_id, start, end, interval)` wrapper method |

Verified SDK signatures (from `inspect.signature`, `mistapi` 0.63.3):

```text
searchOrgPeerPathStats(session, org_id, mac=None, site_id=None, type=None, limit=None, start=None, end=None, duration=None, sort=None, search_after=None)
getSiteInsightMetricsForGateway(session, site_id, device_id, metrics, port_id=None, start=None, end=None, duration=None, interval=None, limit=None, page=None)
getSiteInsightMetricsForDevice(session, site_id, metric, device_mac, port_id=None, start=None, end=None, duration=None, interval=None, limit=None, page=None)
getSiteSleSummaryTrend(session, site_id, scope, scope_id, metric, start=None, end=None, duration=None)
listSiteSleImpactedInterfaces(session, site_id, scope, scope_id, metric, start=None, end=None, duration=None, classifier=None)
getSiteSleThreshold(session, site_id, scope, scope_id, metric)
```

Notes:

- Call site "#12" onward continues the count from feature 001's contract inventory; call sites #1–#11 were already SDK-backed and are out of scope.
- Because #15/#16/#17 all pass through the same `_sle_app_health_get` helper today, the migration collapses that helper's single `requests.get` call into a small dispatch on `sub_path` that picks the right SDK function. See migration pattern below.
- `_insights_device_wan_link_health` currently derives the 12-char MAC from `device_id.replace("-", "")[-12:]`. Keep that computation and pass the result as the SDK's `device_mac` argument.

## Migration Pattern

The file already uses this idiom throughout for its existing 11 SDK-backed methods; the migration replicates it verbatim:

```python
response = mistapi.api.v1.<module>.<fn>(self.apisession, ...)
if self._handle_rate_limit_response(response):
    # _mark_token_rate_limited has already rotated self.apisession by now
    response = mistapi.api.v1.<module>.<fn>(self.apisession, ...)  # retry
if response.status_code == 200:
    return {"success": True, "rate_limited": False, "data": response.data}
```

Invariants a migrating engineer must preserve:

- **`_mark_token_rate_limited` rebuilds `self.apisession`** with the rotated token (`mist_connection.py:182`). No extra plumbing is needed after a 429 rotation — the retry call sees the new session automatically.
- **`response.data` == the prior `response.json()` payload**. The SDK unwraps JSON eagerly; downstream parsers do not change.
- **Return envelope stays identical to the pre-migration shape**. Each method returns `{"success": True, "rate_limited": False, "data": …}` on 200, `{"success": False, "rate_limited": True, "data": None}` on all-tokens-cooling-down, and `{"success": False, "rate_limited": False, "data": None}` on other non-200 statuses (spec FR-007, edge case §"All tokens cooling down simultaneously").

## Known Caveats to Preserve

- **`getSiteSleSummaryTrend` does not accept `interval`** (verified via `inspect.signature`). The current caller passes `interval=3600`, which is Mist's API default. Expected to be a no-op, but flagged for spot-check per spec SC-008 / FR-013 — capture one hour of `/summary-trend` output pre- and post-migration on a live site and verify bucket cadence is unchanged.
- **`_insights_device_wan_link_health` is device-scoped, not gateway-scoped** (spec §Edge Cases "wan_link_health scope quirk"). The migrated SDK call MUST target `getSiteInsightMetricsForDevice` — never `getSiteInsightMetricsForGateway` — with `metric="wan_link_health"` in the path. Preserve this in the docstring Why-line.
- **`_sle_app_health_get` uses `/summary-trend`, not `/summary`** (spec §Edge Cases "SLE `/summary-trend` used instead of `/summary`"). The migrated code MUST call `getSiteSleSummaryTrend`, not `getSiteSleSummary` — the latter returns HTTP 400 on the target org. Preserve this in the docstring Why-line.
- **14-day 1h-interval retention** is a Mist API property, upstream of transport choice. Unchanged by this feature. Preserve any existing "last 14 days only" language in the docstring.
- **`get_gateway_port_traffic_series` symbol name**: the new wrapper method on `MistConnection` MUST NOT collide with the existing `app.py::get_port_traffic` route function name. `get_gateway_port_traffic_series` is available (verified — no such symbol currently exists in the repo).

## Response-Shape Contracts (Preserved, Not Renegotiated)

The following contracts from feature 001 continue to describe the wire shapes the migrated code MUST reproduce byte-for-byte modulo timestamps and rate-limit counters:

- `specs/001-wan-insights-metrics/contracts/GET_gateway_port_hourly.md` — hourly RX/TX/jitter/latency/loss envelope. Backed by call sites #13 and #14 post-migration.
- `specs/001-wan-insights-metrics/contracts/GET_site_application_health.md` — Application Health tile envelope. Backed by call sites #15, #16, #17 post-migration.

Additionally, the legacy chart-modal `get_port_traffic` route (call site #18) returns the envelope:

```json
{"success": true, "data": {"timestamps": [...], "rx_bps": [...], "tx_bps": [...]}}
```

which is not documented in a contract file but MUST be preserved verbatim — the templated JS in `index.html` reads exactly these three keys.

## Complexity Tracking

No constitution-check violations — this section is empty by design.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)*  |            |                                     |

## Post-Design Constitution Re-Check

There is no separate design phase for this feature (no new schemas, no new contracts, no new template surfaces). The Constitution Check above is therefore the final check.

- Simplicity / YAGNI: still PASS. Zero new files, zero new dependencies. Net code delta is negative.
- Single-file-per-role: still PASS. Changes land in `mist_connection.py` and `app.py` only.
- Rate-limit funnel: still PASS **(strengthened)** — this is the point of the feature.
- Cache discipline: still PASS. No caches touched.
- Additive-only for the frontend: still PASS. `templates/index.html` is on the FR-012 do-not-touch list.
- No new auth: still PASS.
- Docstring quality: still PASS. FR-008 explicitly requires each migrated docstring to name the SDK function and preserve pre-existing Why-line quirks; the two gates (`interrogate` ≥90% and `pydoclint --style=google`) continue to enforce this at CI.

**Re-check outcome**: PASS.
