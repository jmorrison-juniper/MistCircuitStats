# Phase 0 Research: SSR WAN Insights-Equivalent Metrics

**Feature**: `001-wan-insights-metrics`
**Date**: 2026-07-17

> **Rev 2026-07-17 cascade**: D-2, D-3, D-5, D-6, D-11 removed; D-8 replaced; D-12 simplified. Corrections were established by direct verification against the live Mist REST API and against the Mist WebUI's own network trace, and are documented in `docs/customer_response_wan_insights.md`. The two invalidated assumptions were: (a) per-port jitter/latency/loss requires a client-side rollup across VPN peer paths, and (b) Application Health % is unavailable on SSR and requires a WAN Link Health substitute. **Both were wrong**. Native `wan_link_health` insight metric returns per-port hourly values directly, and `application-health` is a live SLE metric on SSR sites.

The spec has already been through a clarifications pass (Session 2026-07-17). This document records the remaining technical decisions needed to implement it and rules out alternatives so the design phase can proceed without further reopening.

There are **no NEEDS CLARIFICATION markers** in the Technical Context — the user-provided constraints resolved language, framework, storage, auth, testing posture, and structure. Research below is limited to endpoint mechanics and integration-with-existing-code choices.

---

## D-1: Direct `requests` vs. `mistapi` SDK helpers for the new insight/SLE endpoints

**Decision**: Use direct `requests.get(...)` calls from methods on `MistConnection`, mirroring the pattern already established by `get_vpn_peer_stats` (see `mist_connection.py:891-987`). Auth header is `Authorization: Token {self.api_token}`. Every call funnels through `_handle_rate_limit_response` / `_mark_token_rate_limited`.

**Rationale**:

- The pinned SDK version (`mistapi==0.44.3` in `requirements.txt`) does not expose typed helpers for `insights/gateway/{id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps`, `insights/gateway/{id}/stats?metrics=wan_link_health`, or the `application-health` site SLE endpoints.
- `get_vpn_peer_stats` already demonstrates the direct-`requests` pattern coexisting cleanly with the SDK-based methods, using the same token, host, and 429-handling.
- The user's explicit constraint says "no framework changes" and "new API calls must funnel through the same 429 pattern". Direct `requests` satisfies both without a dependency bump.

**Alternatives considered**:

- Bump `mistapi` to a newer version and use SDK helpers. **Rejected**: adds a dependency-upgrade PR blast radius (unrelated behavior changes in the SDK, breaking-change risk to existing methods that already work) that this feature does not benefit from.
- Wrap `requests` in a new internal HTTP client. **Rejected**: YAGNI. Two direct-`requests` methods already exist in the file; a third does not justify extracting an abstraction.

---

## D-4: Timeframe defaults and clipping (FR-010)

**Decision**: New hourly-view panels default to a 24-hour window on first modal open. The timeframe selector inside the modal exposes buttons for `24h` (default), `3d`, and `7d`. Requests are always clipped server-side to `now - 14 days` before hitting the Mist API; if the operator's requested `start` predates the retention window, the backend clamps it, sets `clipped: true` in the response, and the UI renders a visible banner ("Data range clipped to the API's 14-day 1h-interval retention window").

**Rationale**: Encodes clarification Q3 (Session 2026-07-17) and FR-010. Server-side clipping (rather than client-side) means the retention notice is authoritative even if a caller constructs the URL directly (e.g., a curl user or a future integration). The 14-day retention applies to both `wan_link_health` (per the insight_metrics registry `max_age: 1209600`) and to `application-health` summary-trend at 1h interval.

**Alternatives considered**:

- Client-side-only clipping. **Rejected**: silently drops the guarantee for non-browser callers of the same route.
- Return the raw API error when the range is out of bounds. **Rejected**: spec explicitly requires "clip and notify", not "error and abort".

---

## D-7: CSV export delivery mechanism

**Decision**: Add a NEW route `GET /api/gateway/<gateway_id>/port/<port_id>/hourly/csv?site_id=...&duration=...` on `app.py`. It calls the same `MistConnection` methods as the JSON endpoint, then emits `text/csv` with `Content-Disposition: attachment; filename="hourly_metrics_{gateway}_{port}_{iso}.csv"`. The frontend triggers the download by setting `window.location = <url>` when the operator clicks "Export Hourly Metrics". The existing per-port CSV export path is not touched.

**Rationale**: Additive per FR-011. Keeping CSV generation server-side (rather than building it in JS from the JSON response) keeps the column-ordering logic in a single place and matches the pattern used by other Flask dashboards where CSV is a first-class content type.

**Column set** (fixed order): `site_name, gateway_name, port_id, hour_epoch, hour_iso, rx_avg_bps, rx_peak_bps, tx_avg_bps, tx_peak_bps, jitter_avg_ms, latency_avg_ms, loss_avg_pct`. No `aggregation_method` or `peer_count` columns — those were rollup-metadata artifacts of the (now-removed) client-side aggregation. When `wan_link_health` reports no value for an hour, the three performance columns are emitted as empty string.

**Alternatives considered**:

- Generate the CSV client-side from the already-loaded JSON. **Rejected**: duplicates the column-ordering logic, and Python is a much cleaner place to enforce the empty-string mapping for unreported hours.

---

## D-8: `application-health` SLE endpoint shape (REPLACED)

**Decision**: Add four wrapper methods on `MistConnection` covering the site-level Application Health SLE:

- `get_site_application_health_summary(site_id, start, end)` → `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary` — returns the overall Application Health % for the window.
- `get_site_application_health_summary_trend(site_id, start, end, interval=3600)` → `GET .../metric/application-health/summary-trend` — hourly SLE trend with the classifier decomposition. Classifiers exposed: `jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`.
- `get_site_application_health_impacted_interfaces(site_id, start, end)` → `GET .../metric/application-health/impacted-interfaces` — per-port breakdown, one row per `(gateway_hostname, interface)`, values `duration` / `degraded` / `total`.
- `get_site_application_health_threshold(site_id)` → `GET .../metric/application-health/threshold` — SLE goal (e.g. 96 %) used to size the tile ring / benchmark line.

Each wrapper returns a normalized shape with `available: bool` and `reason: str | None`. When the API returns HTTP 400 or null (site does not report `application-health`), the wrapper returns `{available: false, reason: <string>}` and the UI shows an "unavailable" tile state. All four wrappers route through `_handle_rate_limit_response` / `_mark_token_rate_limited`.

**Rationale**: The customer's own live capture confirms `application-health` returns real data on their SSR site (see `docs/customer_response_wan_insights.md` §3). The earlier draft searched the `insight_metrics` registry (`/api/v1/const/insight_metrics`) and did not find `application-health` — but `application-health` is an **SLE metric**, not an insight metric, so it lives under `/sle/{scope}/{scope_id}/metric/{metric}/*`. The Mist WebUI's "Application Health" tile and "Root Cause Analysis" Timeline are populated from these same endpoints.

Splitting into four wrappers (rather than one aggregator method) keeps each call independently rate-limited and independently cache-invalidatable, and mirrors the granularity of the four Mist endpoints.

**Alternatives considered**:

- Substitute the `wan-link-health` SLE and label the tile "WAN Link Health % (Application Health substitution)". **Rejected — this was the previous plan and it was wrong**. The substitution premise (Application Health unavailable on SSR) was incorrect.
- One combined wrapper that fans out to all four endpoints internally. **Rejected**: obscures per-endpoint rate-limit reporting and forces the modal to fail-open or fail-closed as a group when a subset degrades.
- Return raw SLE JSON to the frontend. **Rejected**: the frontend then has to know the Mist SLE schema, which couples this feature to internal Mist API shapes.

---

## D-9: Frontend integration points

**Decision**: Two additive surfaces:

1. **Per-port modal** (`#chartModal` in `templates/index.html`) gains three new Chart.js `<canvas>` panels positioned *below* the existing `#trafficChartRate` and `#trafficChartData` panels: (a) hourly Rx/Tx Avg+Peak from `wan_link_health`-adjacent `tx_bps/rx_bps/max_tx_bps/max_rx_bps` metrics; (b) hourly jitter/latency/loss from the native `wan_link_health` insight metric; (c) "This port's contribution to Application Health" summarizing the `impacted-interfaces` row for the port plus a small hourly classifier chart derived from `summary-trend`. Modal header gains a timeframe button group (24h/3d/7d) and an "Export Hourly Metrics" button.
2. **Site view** gains a real **"Application Health %"** tile fed by `application-health/summary`, with a small hourly micro-chart underneath from `application-health/summary-trend`.

No substitution notice on the site tile. No aggregation label on the port performance panel. No peer-breakdown drilldown.

**Rationale**: FR-012 requires the extension to be additive within the existing modal, one-click workflow preserved. The current modal already has a chart-timeframe button group so operators are already trained on the pattern. The site tile is a new element in the site view but does not remove or reorder anything.

**Alternatives considered**:

- Create a new full-page hourly view. **Rejected**: FR-012 explicitly forbids it.
- Put the new panels *above* the existing ones. **Rejected**: FR-012 mandates the order (a) existing, (b) new Rx/Tx hourly, (c) new jitter/latency/loss, (d) new Application Health slice.

---

## D-10: Caching for the new endpoints

**Decision**: **No new class-level caches in the MVP.** Each modal open re-fetches. Each site-view Application Health tile refresh re-fetches. If the customer reports measurable strain on the shared token budget in production, add an in-memory TTL cache keyed by `(site_id, device_id, port_id, duration, start_bucket)` in Phase 2; keying by `start_bucket` (rounded to the hour) makes invalidation trivial.

**Rationale**: The user's constraint explicitly says "introduce new caches only if TTL and invalidation are clear." For a single-operator workflow, per-open freshness is preferable to stale hourly data. Native (no fanout) endpoint calls are cheap. No cache-shaped problem exists today.

**Alternatives considered**:

- Cache the tx/rx and `wan_link_health` responses for 5 minutes. **Rejected on YAGNI**: no measured pressure, and per-open freshness is a feature (the operator's mental model is "click = fresh").
- Cache the site Application Health tile. **Rejected**: same reasoning; the tile is one API call.

---

## D-12: Testing posture for this feature

**Decision**: This feature ships with a **manual acceptance-scenario walkthrough** documented in `quickstart.md`. No pytest suite is added. No aggregation helper exists to unit-test — the correction removed the only pure-function candidate (`rollup_peer_metrics_simple_mean`) because port-level jitter/latency/loss is now native.

**Rationale**: Every metric the customer sees maps 1:1 to a live-API response. There is no non-trivial pure logic that benefits from an isolated unit test. Broader test-harness scope (Mist API mocking, fixtures, CI) remains out of scope, matching the existing project posture and the "no framework changes" constraint.

**Alternatives considered**:

- Introduce pytest with fixture-based Mist mock in this feature. **Rejected**: scope creep. Would double or triple the delta size for zero regression-net value because there is no non-trivial pure logic.
- Ship the previously-planned isolated pytest for `rollup_peer_metrics_simple_mean`. **Rejected**: the helper no longer exists.

---

## Summary of Decisions

| ID | Area | Decision | Locks |
|----|------|----------|-------|
| D-1 | HTTP client | Direct `requests` on `MistConnection`, matching `get_vpn_peer_stats` | FR-009 |
| D-4 | Timeframe defaults | 24h default, 3d/7d selector, server-side clip to 14d | FR-010 |
| D-7 | CSV delivery | New `/hourly/csv` route on `app.py`; server-generated; fixed column set with no aggregation metadata | FR-011 |
| D-8 | Application Health shape | Four wrappers (`summary`, `summary-trend`, `impacted-interfaces`, `threshold`); each returns `{available, reason?, ...}` | FR-007 |
| D-9 | Frontend location | Three new panels in `#chartModal`, one new tile in site view; order fixed | FR-012 |
| D-10 | Caching | No new caches in MVP | User constraint |
| D-12 | Testing | Manual acceptance walkthrough only; no pytest | Existing project posture |

D-2 (aggregation math), D-3 (zero-peer wire shape), D-5 (peer discovery), D-6 (`vpn_peer-metrics` params), D-11 (substitution notice) are **removed** — all five encoded assumptions the corrections invalidated.

All decisions above are consistent with the user-supplied constraints and the clarified spec. There are no remaining unknowns that block Phase 1.
