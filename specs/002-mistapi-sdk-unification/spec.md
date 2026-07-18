# Feature Specification: Unify Mist API Access Under the `mistapi` SDK

**Feature Branch**: `002-mistapi-sdk-unification`

**Created**: 2026-07-17

**Status**: Draft

**Input**: User description: "Migrate the 7 remaining direct-REST Mist call sites in MistCircuitStats to the `mistapi` Python SDK, so that every Mist Cloud call goes through one path, is covered by the shared multi-token 429 rotation wrapper, and the README/architecture story collapses to a single SDK path."

## Assumptions & Clarifications

### Session 2026-07-17

- Q: Are any dependency or CI changes required? → A: No. `mistapi` 0.63.3 is already installed, and no changes to `pyproject.toml`, `requirements.txt`, or `.github/workflows/quality-gates.yml` are in scope.
- Q: Are the HTTP response shapes served by the Flask app to `templates/index.html` allowed to change? → A: No. All JSON envelopes and CSV export columns MUST remain byte-identical (modulo timestamps). The response-shape contract with the frontend is preserved.
- Q: The current `getSiteSleSummaryTrend` SDK function does not accept `interval`, but existing callers pass `interval=3600` (also the Mist API default). Is dropping the parameter acceptable? → A: Yes, provided a manual spot-check confirms the payload shape and hour-bucket cadence are unchanged versus the direct-REST response.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Every Mist API Call Is Rate-Limit-Rotation-Covered (Priority: P1)

A network operations engineer is operating the dashboard against a Mist org with multiple API tokens configured for token rotation. Under normal load they never see this — but when Mist Cloud returns HTTP 429 on any call the app makes, the app MUST rotate to the next healthy token, log `Switching to token N/M`, and keep serving the request. Today, one code path (the legacy chart-modal port-traffic route in `app.py`) makes an inline `requests.get` that bypasses the multi-token wrapper. That means a 429 on the legacy path surfaces as a hard failure to the user instead of triggering rotation. After this migration, every Mist call — including the legacy chart-modal path — routes through `MistConnection._handle_rate_limit_response(response)` and benefits from the shared 60-second per-token cooldown.

**Why this priority**: This is the reason the migration exists as a feature and not as an incremental cleanup. Rate-limit rotation is a load-bearing operational guarantee for customers running against production Mist orgs with sustained traffic. Any bypass path is a latent outage waiting for a 429 spike. Without unifying the paths, the operator cannot truthfully say "all Mist calls are rate-limit-protected" — which is a claim the README currently makes.

**Independent Test**: Configure two or more Mist API tokens for token rotation. Force a 429 response on each of the 7 migrated endpoints in turn (e.g. by exhausting a token). Verify that a `Switching to token N/M` log line appears for each endpoint, and that the HTTP response to the frontend returns `success: true` with a `rate_limited` marker and empty arrays — never a 429 exception. This is testable independently of User Story 2 and User Story 3.

**Acceptance Scenarios**:

1. **Given** the app has 2 API tokens configured and token #1 has just returned a 429, **When** the operator triggers the legacy chart-modal port-traffic route on a gateway port, **Then** the app rotates to token #2, logs `Switching to token 2/2`, and returns a successful JSON response with per-second RX/TX time series.
2. **Given** all configured tokens are currently cooling down after 429s, **When** the operator triggers any of the 7 migrated endpoints (VPN peer stats, gateway insights, WAN link health, SLE summary-trend, SLE impacted-interfaces, SLE threshold, port traffic), **Then** the response is `success: true, rate_limited: {…}` with empty data arrays and the UI shows the existing empty state — no 429 exception surfaces to the frontend.
3. **Given** a normal request against any of the 7 migrated endpoints, **When** the SDK function is invoked, **Then** the response is served through `MistConnection._handle_rate_limit_response(response)` and the response object exposes the same rate-limit headers the direct-REST path did.

---

### User Story 2 — Frontend Sees Zero Behavior Change (Priority: P1)

The same operator opens the dashboard after the migration ships. They load the gateway list, click a WAN Insights port to open the modal, cycle through all 5 duration presets (1h / 6h / 24h / 3d / 7d), watch RX/TX/jitter/latency/loss render, and export the hourly CSV. They click a cell in the main gateway table to open the click-a-cell chart popup. Every one of these actions MUST behave exactly as it did before the migration. No column reordering. No timestamp drift. No new fields. No missing fields. No error banners the user did not see before. The migration is invisible to the frontend.

**Why this priority**: This is co-priority with User Story 1 because breaking the frontend contract would immediately regress every user. The migration has zero customer-facing value if it changes the wire shape. The response-shape contract with `templates/index.html` is the hard boundary of this feature.

**Independent Test**: Capture the JSON responses of each of the 7 migrated endpoints (and the CSV export payload) on the pre-migration `main` branch. After the migration lands, replay the same requests and diff the responses. Timestamps and rate-limit counters are allowed to differ; every other byte MUST match. This is testable end-to-end without User Story 1 or User Story 3 being verified first — it is a pure regression check.

**Acceptance Scenarios**:

1. **Given** the pre-migration dashboard on `main`, **When** the operator loads the gateway list and opens the WAN Insights modal for any gateway, **Then** RX/TX/jitter/latency/loss render across all 5 duration presets (1h, 6h, 24h, 3d, 7d) and every value matches what the pre-migration branch returned for the same time window.
2. **Given** the WAN Insights modal is open, **When** the operator triggers `.../hourly/export?duration=24h`, **Then** the exported CSV has the canonical 12-column layout (`site_name`, `gateway_name`, `port_id`, `hour_epoch`, `hour_iso`, `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps`, `jitter_avg_ms`, `latency_avg_ms`, `loss_avg_pct`) in that exact order.
3. **Given** the main gateway table is loaded, **When** the operator clicks any cell that opens the click-a-cell chart popup, **Then** the popup renders per-second RX/TX time series exactly as it did pre-migration — the legacy chart-modal route still works.
4. **Given** any of the 7 migrated endpoints, **When** the response is compared byte-for-byte against the pre-migration response for the same input parameters, **Then** the responses are identical modulo timestamps and rate-limit counters.

---

### User Story 3 — Documentation Tells the Truth (Priority: P2)

A new engineer joins the project and reads `README.md` to understand how the app talks to Mist. Today the README describes two paths ("the application talks to Mist in two ways") — the `mistapi` SDK for 11 endpoints and inline `requests.get` for 7. After this migration, there is only one path. The "Direct REST endpoints" heading in the README is gone. The Mist API Endpoints section is a single flat list. The Architecture section no longer describes a bifurcated call path. `CHANGELOG.md` has an `[Unreleased] → Changed` entry describing the unification. Anyone auditing the codebase can read the docs, grep for `requests.get`, and find zero Mist-directed hits.

**Why this priority**: This is P2 rather than P1 because the code migration in Stories 1 and 2 is the load-bearing change. The documentation cleanup is necessary but not sufficient — it only becomes true once the code migration lands. It sequences after because it depends on the code state being final.

**Independent Test**: `grep -R "requests.get" mist_connection.py app.py` returns zero Mist-directed hits. `grep -R "Direct REST endpoints" README.md` returns zero hits. The Architecture section describes a single SDK path. `CHANGELOG.md` has an entry under `[Unreleased] → Changed` naming the unification. This is testable independently as a docs-and-search check once Stories 1 and 2 are done.

**Acceptance Scenarios**:

1. **Given** the migrated codebase, **When** an engineer runs `grep -Rn "requests\.get" mist_connection.py app.py`, **Then** zero Mist-directed hits are returned (any remaining `requests.get` calls are non-Mist and clearly labeled as such).
2. **Given** the migrated README, **When** an engineer reads the "Mist API Endpoints" section, **Then** it describes a single SDK path with a single flat list of endpoints — no "Direct REST endpoints" subheading and no "two ways" framing.
3. **Given** the migrated CHANGELOG, **When** an engineer reads the top of `CHANGELOG.md`, **Then** the `[Unreleased] → Changed` section names the unification and explains that the legacy chart-modal traffic route now benefits from shared token rotation.

---

### Edge Cases

- **All tokens cooling down simultaneously**: When every configured token has recently returned 429 and is inside its 60-second cooldown, any migrated endpoint MUST still return `success: true, rate_limited: {tokens_cooling_down: N, retry_after_seconds: X}` with empty data arrays. The frontend already handles this shape; the migration MUST preserve it.
- **`getSiteSleSummaryTrend` `interval` parameter drop**: The SDK function does not accept `interval`, whereas the direct-REST call passed `interval=3600`. Since `3600` is the API default, the payload should be unchanged — but the spot-check MUST confirm this on at least one live site before the migration is considered verified. If any bucket cadence differs, the migration for that endpoint MUST be blocked pending SDK support or documented via a follow-up.
- **`wan_link_health` scope quirk**: The direct-REST path uses the *device*-scoped `wan_link_health` endpoint (`/sites/{site_id}/insights/device/{mac}/wan_link_health`), not the gateway-stats metrics endpoint. The SDK equivalent (`getSiteInsightMetricsForDevice(metric="wan_link_health")`) MUST be called with the same device MAC and the same metric name — the Why-line docstring must record this quirk so a future reader does not mistakenly re-route it through `getSiteInsightMetricsForGateway`.
- **SLE `/summary-trend` used instead of `/summary`**: The current code uses `/summary-trend` because `/summary` returns HTTP 400 on this org. The migrated code MUST keep calling `getSiteSleSummaryTrend`, not `getSiteSleSummary`. This constraint MUST be preserved verbatim in the migrated method's docstring Why-line.
- **14-day retention boundary**: The SLE and insights endpoints have a 14-day 1h-interval retention window. That behavior is upstream of the SDK vs. direct-REST choice and MUST NOT change post-migration.
- **`get_gateway_port_traffic_series` name collision**: The new wrapper method on `MistConnection` MUST have a name that does not clash with the existing `get_port_traffic` route in `app.py`. The proposed name is `get_gateway_port_traffic_series` — the migration MUST verify no existing symbol collision before adopting the name.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MistConnection.get_vpn_peer_stats` MUST call `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats` in place of the current direct-REST call to `/orgs/{org_id}/stats/vpn_peers/search`. The response payload returned to callers MUST be byte-identical (modulo timestamps and rate-limit counters).
- **FR-002**: `MistConnection._insights_gateway_stats` MUST call `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` in place of the current direct-REST call to `/sites/{site_id}/insights/gateway/{device_id}/stats`. The `metrics`, `port_id`, `interval`, `start`, `end`, and `duration` query parameters MUST be forwarded to the SDK function with identical semantics.
- **FR-003**: `MistConnection._insights_device_wan_link_health` MUST call `mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice(metric="wan_link_health")` in place of the current direct-REST call to `/sites/{site_id}/insights/device/{mac}/wan_link_health`. The device-scoped Why-line quirk MUST be preserved in the docstring.
- **FR-004**: `MistConnection._sle_app_health_get` MUST call `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend`, `mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces`, and `mistapi.api.v1.sites.sle.getSiteSleThreshold` in place of the current direct-REST calls to `.../application-health/summary-trend`, `.../application-health/impacted-interfaces`, and `.../application-health/threshold`. The `/summary-trend`-not-`/summary` Why-line workaround MUST be preserved in the docstring.
- **FR-005**: A new wrapper method `MistConnection.get_gateway_port_traffic_series` MUST be added that calls `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` with `metrics=rx_bps,tx_bps`. The `app.py::get_port_traffic` route MUST be reduced to a single call to this new method — no inline `requests.get` may remain in the route body.
- **FR-006**: All 7 migrated call paths MUST route through `MistConnection._handle_rate_limit_response(response)` and benefit from the shared multi-token 60-second per-token cooldown. No migrated call path may bypass the wrapper.
- **FR-007**: When all configured tokens are cooling down, every migrated endpoint MUST return the existing graceful-degradation envelope: `success: true, rate_limited: {tokens_cooling_down: N, retry_after_seconds: X}` with empty data arrays. A 429 exception MUST NOT propagate to the frontend.
- **FR-008**: Every migrated method's docstring MUST name the SDK function it now calls and MUST preserve all pre-existing Why-line quirks (device-scoped `wan_link_health`, `/summary-trend` in place of `/summary`, 14-day retention). The `interrogate` ≥90% and `pydoclint --style=google` gates MUST continue to pass on the migrated files.
- **FR-009**: The `README.md` "Direct REST endpoints" heading MUST be removed. The "Mist API Endpoints" section MUST become a single flat list of SDK-backed endpoints. The Architecture section MUST describe a single SDK path — no "two ways" framing.
- **FR-010**: `CHANGELOG.md` MUST have an entry under `[Unreleased] → Changed` describing the unification, explicitly noting that the legacy chart-modal port-traffic route now benefits from the shared token rotation wrapper.
- **FR-011**: The HTTP response shapes served by the app to `templates/index.html` — both JSON envelopes and CSV export columns — MUST remain byte-identical (modulo timestamps and rate-limit counters). No frontend template changes are permitted in this feature.
- **FR-012**: The following files MUST NOT be modified as part of this feature: `pyproject.toml`, `requirements.txt`, `.github/workflows/quality-gates.yml`, `templates/index.html`. Any change to these files invalidates the feature scope and requires a re-scope.
- **FR-013**: The migration MUST verify — via manual spot-check on at least one live site — that dropping the `interval=3600` parameter from `getSiteSleSummaryTrend` does not change the returned bucket cadence. If the cadence changes, the SLE `/summary-trend` migration MUST be reverted and a follow-up filed.

### Key Entities

- **Migrated Call Site**: One of the 7 pre-migration direct-REST call locations (5 in `mist_connection.py`, 1 in `app.py`, plus 1 new wrapper method on `MistConnection`). Each has a pre-migration endpoint path, a target SDK function, and a Why-line docstring quirk to preserve.
- **Rate-Limit Rotation Wrapper**: The existing `MistConnection._handle_rate_limit_response(response)` code path that applies the multi-token 60-second per-token cooldown. After migration, all 7 call sites route through it.
- **Response-Shape Contract**: The JSON envelope and CSV column contract between the Flask app and `templates/index.html`. The migration MUST preserve it byte-for-byte modulo timestamps and rate-limit counters.
- **Graceful-Degradation Envelope**: The `success: true, rate_limited: {…}` response shape returned when all tokens are cooling down. Preserved as-is by the migration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `grep -Rn "requests\.get" mist_connection.py app.py` returns zero Mist-directed hits after the migration. Any remaining `requests.get` in these files (if any) is non-Mist and clearly annotated.
- **SC-002**: For each of the 7 migrated endpoints, a captured pre-migration JSON response and post-migration JSON response for identical input parameters differ only in timestamps and rate-limit counters. Verified by byte-diff on at least one representative sample per endpoint.
- **SC-003**: With 2 or more tokens configured, forcing a 429 on any of the 7 migrated endpoints (including the legacy chart-modal port-traffic route) causes a `Switching to token N/M` log line to appear and the request to succeed against the next healthy token. 100% of the 7 endpoints exhibit this behavior — verified endpoint by endpoint.
- **SC-004**: When all configured tokens are cooling down, every migrated endpoint returns `success: true, rate_limited: {…}` with empty data arrays. No 429 exception reaches the frontend for any of the 7 endpoints.
- **SC-005**: All 8 quality gates pass on the migrated branch: `ruff`, `black`, `bandit`, `pip-audit`, `radon` CC≤15, `vulture` confidence≥90, `interrogate` ≥90%, `pydoclint --style=google`.
- **SC-006**: Manual smoke test passes end to end: the dashboard loads the gateway list; clicking a WAN Insights port opens the modal and renders RX/TX/jitter/latency/loss across all 5 duration presets (1h, 6h, 24h, 3d, 7d); the click-a-cell chart popup on the main gateway table still works; CSV export via `.../hourly/export?duration=24h` returns the canonical 12-column layout in the documented order.
- **SC-007**: `README.md` has no "Direct REST endpoints" heading, no "two ways" framing in the Architecture section, and a single flat list under "Mist API Endpoints". `CHANGELOG.md` has an `[Unreleased] → Changed` entry naming the unification.
- **SC-008**: Manual spot-check confirms that `getSiteSleSummaryTrend` (without the previously-passed `interval=3600`) returns the same hour-bucket cadence as the direct-REST predecessor. Recorded in the PR description or a linked verification note.

## Assumptions

- `mistapi` 0.63.3 is already installed in the project's Python environment; no `pyproject.toml` / `requirements.txt` change is required to reach the target SDK functions.
- The SDK functions named in FR-001 through FR-005 exist and are stable in `mistapi` 0.63.3. This was confirmed against the installed package before this feature was scoped.
- The frontend (`templates/index.html`) consumes the pre-migration response shapes and does not need to change; response-shape parity is enforced by FR-011.
- The existing multi-token rate-limit rotation wrapper (`MistConnection._handle_rate_limit_response`) is the correct integration point for all migrated call sites; no changes to the wrapper itself are in scope.
- The Mist API's 14-day 1h-interval retention window is upstream of the migration and is unchanged by this feature.
- The `/summary-trend`-instead-of-`/summary` workaround is a stable characteristic of the customer's Mist org and does not need to be re-verified as part of this feature.
- Manual smoke-testing against a live Mist org is the acceptance path for SC-002, SC-003, SC-004, SC-006, and SC-008. No new automated integration tests are in scope for this feature.

## Out of Scope

- Any change to `pyproject.toml`, `requirements.txt`, or `.github/workflows/quality-gates.yml`.
- Any change to `templates/index.html` or any other frontend template. Response-shape parity is enforced by FR-011.
- Migrating any of the 11 endpoints that are already routed through the SDK. Those are unchanged.
- Adding new endpoints, new UI surfaces, or new metrics. This feature is purely a migration.
- Refactoring `MistConnection._handle_rate_limit_response` itself. The wrapper is the integration point; it is not the target of the migration.
- New automated integration tests against Mist Cloud. Acceptance is via the manual smoke test defined in SC-006 plus the byte-diff check in SC-002.
- Any docstring rewrite beyond naming the SDK function and preserving the pre-existing Why-line quirks. Broader docstring or docs cleanups are separate work.
- Rewriting the app to a different framework or language.

## Notes / References

- The 7 endpoints and their target SDK functions are enumerated in the feature description input; the mapping is authoritative and MUST be honored verbatim.
- The prior feature spec at `specs/001-wan-insights-metrics/` established the multi-token 429 wrapper as the required integration point for all Mist calls (FR-009 in that spec). This feature closes the last remaining bypass path.
