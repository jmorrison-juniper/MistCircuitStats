---
description: "Task list for feature 001-wan-insights-metrics"
---

# Tasks: SSR WAN Insights-Equivalent Metrics

**Input**: Design documents from `specs/001-wan-insights-metrics/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/GET_gateway_port_hourly.md, contracts/GET_site_application_health.md

**Tests**: No unit test is added by this feature — the previously-planned aggregation helper no longer exists (per-port jitter/latency/loss is native via the `wan_link_health` insight metric; there is no client-side rollup math). Live-API scenarios are validated manually via `quickstart.md` per plan.md § Technical Context / research.md § D-12.

**Organization**: Tasks are grouped by user story (P1 hourly Rx/Tx utilization, P2 native jitter/latency/loss + CSV, P3 site Application Health % tile) plus cross-cutting docs / disclosure / review tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files or non-overlapping regions, no dependencies on incomplete tasks)
- **[Story]**: User story mapping — [US1], [US2], [US3]; omitted for Setup/Foundational/Polish
- Every task references an exact file path and, where applicable, a function or DOM anchor

## Path Conventions

Single-file-per-role Flask layout (per plan.md § Project Structure). All backend work lands in the two existing Python files at repo root, all UI work in the single existing template. No new files are created by this feature.

- Backend: `mist_connection.py`, `app.py`
- UI: `templates/index.html`
- Docs: `README.md`, `specs/001-wan-insights-metrics/spec.md`
- Deps: `requirements.txt` (bumped `mistapi>=0.63.3`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Bump the SDK, pin the working branch, and confirm no signature drift on the existing `MistConnection` surface.

- [ ] T000 Bump `mistapi` in `requirements.txt` from `0.44.3` to `>=0.63.3`. Reinstall the venv (`pip install -r requirements.txt`). Regression-smoke-test all existing `MistConnection` SDK calls (`getSelf`, `getOrg`, `listOrgSites`, `listOrgDevicesStats`, `searchOrgSwOrGwPorts`, `getSiteDevice`, `searchSiteDevices`, `searchOrgDevices`, `getOrgInventory`, `getOrgDeviceProfile`, `getOrgGatewayTemplate`) against 0.63.3 by loading the dashboard and clicking through the existing gateway list + chart modal. Capture any signature drift in the same commit that bumps the pin. Verify which of the new insight/SLE endpoints (`insights/gateway/{id}/stats?metrics=...` for `tx_bps`/`rx_bps`/`max_*` and `wan_link_health`; `sle/site/{id}/metric/application-health/{summary,summary-trend,impacted-interfaces,threshold}`) expose typed helpers in 0.63.3; those with helpers use the helper, those without use the direct-`requests` fallback pattern from `get_vpn_peer_stats`. Reference: research.md § D-1, plan.md § Technical Context Note.
- [ ] T001 Verify feature branch `001-wan-insights-metrics` is checked out and `git status` is clean before editing `mist_connection.py`, `app.py`, `templates/index.html`.
- [ ] T002 Confirm the venv is running against `mistapi>=0.63.3` (`pip show mistapi`) and that the existing dashboard loads cleanly after the T000 bump.
- [ ] T003 [P] Read the two contracts in `specs/001-wan-insights-metrics/contracts/` end-to-end so every subsequent implementer has the exact wire shape memorized before editing code.

**Checkpoint**: SDK bumped, existing surface still works, contracts reviewed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the shared retention-clipping and duration helpers that all three user-story routes depend on. No aggregation helper is needed (removed with the corrections).

- [ ] T004 *(removed — the aggregation helper `rollup_peer_metrics_simple_mean` is no longer part of this feature. Per-port jitter/latency/loss is native via `wan_link_health`; there is no rollup math.)*
- [ ] T005 Implement `MistConnection._clip_to_retention_window(requested_start: int, end: int) -> Tuple[int, bool, str]` in `mist_connection.py` returning `(clipped_start, was_clipped, retention_notice)`. Rule: `clipped_start = max(requested_start, end - 14 * 86400)`. When `was_clipped`, the notice is `"Data range clipped to the API's 14-day 1h-interval retention window (from <iso_start> to <iso_end>)."`. Reference: research.md § D-4, FR-010.
- [ ] T006 Add a `_duration_to_seconds(duration: str) -> int` helper on `MistConnection` (or as a module-level constant map) mapping `"24h" -> 86400`, `"3d" -> 259200`, `"7d" -> 604800`. Every route handler MUST use this — no duplicated math. Reference: research.md § D-4.

**Checkpoint**: Shared helpers exist and are importable. US1/US2/US3 route work can now begin in parallel.

---

## Phase 3: User Story 1 - Hourly Rx/Tx Utilization per WAN Port (Priority: P1) MVP

**Goal**: Deliver hourly Avg + Peak Rx/Tx per WAN port for the last 24h (default) up to 7d, sourced from the `insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&interval=3600` endpoint. Includes retention clipping, empty-utilization state, and the new panel appended to the existing modal.

**Independent Test**: For any SSR gateway WAN port with traffic in the last 14 days, `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly?duration=24h` returns `success: true` with a non-empty `hourly[]` where every entry has numeric `tx_bps` / `rx_bps` / `max_tx_bps` / `max_rx_bps` and a UTC `hour_iso`. Verified via `quickstart.md § Scenario 1`.

### Implementation for User Story 1

- [ ] T007 [US1] Implement `MistConnection.get_gateway_hourly_bandwidth(site_id, device_id, port_id, start, end)` in `mist_connection.py`. Where `mistapi>=0.63.3` exposes a typed helper for the gateway insights endpoint with the `metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps` set at `interval=1h`, use it; otherwise issue `GET https://{self.host}/api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port_id}&interval=1h&start={start}&end={end}` via `requests.get`, mirroring the `get_vpn_peer_stats` direct-`requests` pattern (`mist_connection.py:891-987`). Every call MUST route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. Return a list of `HourlyUtilizationSample` dicts (zip of `tx_bps` / `rx_bps` / `max_tx_bps` / `max_rx_bps` arrays with hour boundaries computed from `start + i * 3600`). Empty upstream → `[]`. Reference: spec.md § FR-001, contracts/GET_gateway_port_hourly.md § Server-side behaviour step 4, research.md § D-1, data-model.md § HourlyUtilizationSample.
- [ ] T008 [US1] Add Flask route `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly` in `app.py`. Validate `duration` (enum `24h`/`3d`/`7d`, default `24h`). URL-decode `port_id` with `urllib.parse.unquote` (matches the existing `/api/gateway/<gateway_id>/port/<path:port_id>/traffic` pattern). Compute `end = now`, `raw_start = end - _duration_to_seconds(duration)`, then apply `_clip_to_retention_window`. Call `get_gateway_hourly_bandwidth`. Resolve `gateway_hostname` / `site_name` via existing helpers. Assemble the `PortHourlyResponse` envelope with `hourly[]` populated from T007. US2 fills the jitter/latency/loss fields on the same row; US3 fills the `port_app_health` / `hourly_app_health` fields. Set `hourly: []` when the upstream returned no samples. NEVER return HTTP 404 for empty data. Reference: contracts/GET_gateway_port_hourly.md § Server-side behaviour, FR-015.
- [ ] T009 [P] [US1] Append the "Hourly Avg + Peak Rx/Tx" Chart.js panel BELOW the existing `#trafficChartRate` / `#trafficChartData` panels inside `#chartModal` in `templates/index.html`. Add a `24h` (default) / `3d` / `7d` timeframe button group inside the new panel header. Wire the panel to fetch from the T008 route on port-row click and on timeframe change. Order MUST be: (a) existing rate + data-transferred charts unchanged; (b) new hourly Avg+Peak Rx/Tx chart; leave a placeholder slot for the US2 jitter/latency/loss chart directly below and for the US3 per-port Application Health slice further below. Reference: research.md § D-9, FR-012.
- [ ] T010 [US1] In `templates/index.html`, render the retention notice banner between the existing data-transferred panel and the new hourly panel whenever `response.clipped === true`. Banner text: use the response's `retention_notice` string verbatim. Muted styling matches the existing modal note styles. Reference: FR-010.
- [ ] T011 [US1] In `templates/index.html`, render the empty-utilization state ("no utilization data reported for this port in the requested window") when the utilization fields of `response.hourly` are all missing/zero for the window. MUST NOT show an error banner. Reference: FR-015, Acceptance Scenario 1.4.

**Checkpoint**: A network engineer can click a WAN port, see hourly Avg+Peak Rx/Tx charted for 24h/3d/7d, and see the empty-utilization state for a port that has never carried traffic. `quickstart.md § Scenario 1` steps 1–7 pass end-to-end. The existing charts are unchanged (FR-012 / SC-007). US2 and US3 work has not started and does not block this MVP demo.

---

## Phase 4: User Story 2 - Hourly Jitter / Latency / Loss per WAN Port (Priority: P2)

**Goal**: Wire the native `wan_link_health` insight metric per port into the same `/hourly` route plus a new `/hourly/export` CSV sibling route. No peer discovery, no fanout, no client-side rollup, no `aggregation_method` label, no `peer_count`, no zero-peer `"N/A"` sentinel. Empty state is the plain "no data reported in this window" case.

**Independent Test**: For any SSR WAN port for which the API reports `wan_link_health`, `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly?duration=24h` returns a non-empty `hourly[]` where each row has numeric `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` alongside the bandwidth fields from US1. For a port with no `wan_link_health` telemetry in the window, the three fields are absent/null on each row (rendered as empty string in CSV) and the panel shows the plain empty state. Verified via `quickstart.md § Scenario 2`.

### Implementation for User Story 2

- [ ] T012 [US2] Implement `MistConnection.get_gateway_hourly_wan_link_health(site_id, device_id, port_id, start, end)` in `mist_connection.py`. Where `mistapi>=0.63.3` exposes a typed helper for the gateway insights endpoint with `metrics=wan_link_health` at `interval=1h`, use it; otherwise issue `GET https://{self.host}/api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port_id}&interval=1h&start={start}&end={end}` via `requests.get`. All calls MUST route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. The upstream returns per-port `avg_latency` / `avg_jitter` / `avg_loss` arrays natively — return a list of `HourlyPortWanLinkHealth` dicts for the requested `port_id` by zipping the arrays with `start + i * 3600`. Missing/null slots stay as `None` (never zeroed). Port with no telemetry in the window → `[]`. No fanout, no peer discovery. Reference: spec.md § FR-003, FR-004, contracts/GET_gateway_port_hourly.md § Server-side behaviour step 5, data-model.md § HourlyPortWanLinkHealth.
- [ ] T013 [US2] Extend the `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly` route in `app.py` (from T008) to also call `get_gateway_hourly_wan_link_health(site_id, device_id, port_id, start, end)`, which returns a list of per-hour samples already scoped to the requested port (the upstream URL carries `&port_id={port}`; no client-side selection needed). Merge those samples into the same `hourly[]` list produced by T008 by aligning on `timestamp`. When the port reports no `wan_link_health` telemetry in the window, leave `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` as `None` on each row. Reference: contracts/GET_gateway_port_hourly.md § Server-side behaviour steps 5 and 7.
- [ ] T014 [US2] In the same route (`app.py`), populate `rate_limited.bandwidth: true` if the T007 call returned a rate-limited sentinel, and populate `rate_limited.wan_link_health: true` if the T012 call was rate-limited. Response MUST remain HTTP 200 with `success: true` in the rate-limited case — never surface HTTP 429 to the browser. Reference: contracts/GET_gateway_port_hourly.md § 429 handling, FR-009 / SC-005.
- [ ] T015 [US2] Add Flask route `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly/export` in `app.py`. Same query params as the JSON route. Reuse the same server-side pipeline from T008 / T013. Stream a `text/csv; charset=utf-8` response with `Content-Disposition: attachment; filename="hourly_metrics_{gateway_hostname}_{port_id}_{iso_utc_now}.csv"`. Header row and column order are FIXED per spec.md § FR-011 and data-model.md § HourlyMetricsCsvRow — exactly 12 columns: `site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct`. Map `None` → empty string for the three performance columns ONLY in this writer. No `aggregation_method` column. No `peer_count` column. No `site_id` column. Sort rows ascending by `(site_name, gateway_name, port_id, hour_epoch)`. Timestamps remain UTC. Reference: FR-011, research.md § D-7, `docs/customer_response_wan_insights.md` line 219.
- [ ] T016 [P] [US2] Append the "Hourly Jitter / Latency / Loss" Chart.js panel in `templates/index.html` in the placeholder slot from T009. Render three series (jitter / latency / loss) driven by the per-row `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` values in `response.hourly`. No "aggregation method" label above the chart. No `simple_mean` string anywhere. Tooltip shows the raw hourly value only — no `peer_count`. When every row in the window has all three fields null, render the plain empty state "no jitter/latency/loss data reported for this port in the requested window". Reference: FR-003, FR-004.
- [ ] T017 *(removed — no peer-breakdown drilldown. Per-port jitter/latency/loss is native, so there are no per-peer contributor rows to drill into.)*
- [ ] T018 *(removed — no zero-peer `"N/A"` state. Empty state is the plain "no data reported in this window" case, handled at the end of T016.)*
- [ ] T019 [US2] Add the "Export Hourly Metrics" button to the `#chartModal` header in `templates/index.html`. Click handler: set `window.location = "/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly/export?duration=..."` reflecting the currently selected timeframe. Existing per-port CSV export button is UNCHANGED and remains at its current DOM position. Reference: FR-011, research.md § D-7.
- [ ] T020 [US2] In `templates/index.html`, render a "temporarily rate-limited, try again shortly" banner on the bandwidth panel when `response.rate_limited?.bandwidth === true`, and on the performance panel when `response.rate_limited?.wan_link_health === true`. Panels showing rate-limited state MUST NOT show a hard error. Reference: contracts/GET_gateway_port_hourly.md § 429 handling, FR-009.

**Checkpoint**: An operator can see the hourly jitter/latency/loss chart from the native `wan_link_health` metric, export the 12-column CSV, see the plain empty state on a port that reports no `wan_link_health` samples, and hit a graceful rate-limit banner if a token pool is exhausted. `quickstart.md § Scenario 2` passes end-to-end. US1's bandwidth panel continues to work unchanged.

---

## Phase 5: User Story 3 - Site-Level "Application Health %" tile (Priority: P3)

**Goal**: Render a real site-level Application Health % tile fed by the native Mist Application Health SLE endpoints on SSR. No substitution, no proxy, no session-storage notice, no substitution text.

**Independent Test**: For any SSR site reporting `application-health`, `GET /api/v1/sites/<site_id>/application-health-summary?duration=24h` returns HTTP 200 with a numeric `summary_pct` and `threshold_pct`, a non-empty `trend[]`, and an `impacted_interfaces[]` list. For a site that does not report `application-health`, the same route returns HTTP 200 with `summary_pct: null`, `threshold_pct: null`, `trend: []`, `impacted_interfaces: []`. Verified via `quickstart.md § Scenario 3`.

### Implementation for User Story 3

- [ ] T021 [US3] Implement `MistConnection.get_site_application_health(site_id, start, end)` in `mist_connection.py`. Sequentially call the four native Mist Application Health SLE endpoints: `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary`, `.../summary-trend?interval=3600&start=&end=`, `.../impacted-interfaces?start=&end=`, `.../threshold`. Where `mistapi>=0.63.3` exposes typed helpers, use them; otherwise fall back to direct `requests.get`. All four calls MUST route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. Return a normalized dict matching data-model.md § SiteApplicationHealth: `{site_id, summary_pct, threshold_pct, trend[], impacted_interfaces[], clipped, retention_notice}`. When any of the four endpoints returns HTTP 400 or null (site does not report application-health), set the corresponding field to `null` / `[]` — DO NOT propagate the HTTP 400. Reference: research.md § D-8, FR-007, contracts/GET_site_application_health.md § Server-side behaviour.
- [ ] T022 [US3] Add Flask route `GET /api/v1/sites/<site_id>/application-health-summary` in `app.py`. Validate `duration` (enum `24h`/`3d`/`7d`, default `24h`). Apply retention clipping (T005) to set `start` / `end`. Call `get_site_application_health`. Return HTTP 200 in all cases (including the unavailable case). Also expose an internal helper that the US2 route (T013) uses to enrich the per-port response with `port_app_health` (`{summary_pct, threshold_pct}` from the site summary/threshold + the impacted-interfaces row matching `(gateway_hostname, port_id)`) and `hourly_app_health` (the site `trend[]` filtered/aligned to this port's hour buckets). Reference: contracts/GET_site_application_health.md § Server-side behaviour, FR-007.
- [ ] T023 [P] [US3] Add the "Application Health %" tile in the site view section of `templates/index.html`. Render `response.summary_pct` prominently. Render a small micro-chart below the tile driven by `response.trend[]`. Optionally render an "SLE goal: X%" line derived from `response.threshold_pct` when present. When `summary_pct` is `null`, render an "Application Health unavailable for this site" state — no substitution notice, no proxy tile, no session-storage-gated banner. Tile is labelled "Application Health %" VERBATIM. Below the site view, wire the per-port modal (T009 slot) to render a small "This port's contribution to Application Health" strip using the `port_app_health` and `hourly_app_health` fields from the T013-extended `/hourly` response. Reference: FR-007, Acceptance Scenarios 3.1 / 3.4, research.md § D-9.
- [ ] T024 *(removed — no substitution notice. Application Health % is a real first-class Mist SLE on SSR; the tile is labelled "Application Health %" with no proxy, no asterisk, no session-storage-gated banner.)*

**Checkpoint**: The three user-story panels/tiles are wired end-to-end. `quickstart.md § Scenarios 1–3` all pass.

---

## Phase 6: (removed)

- [ ] T025 *(removed — the pure-function aggregation helper unit test is no longer part of this feature. The helper does not exist; per-port jitter/latency/loss is native via `wan_link_health`. Per research.md § D-12, this feature ships with manual acceptance-scenario walkthroughs only.)*

---

## Phase 7: Documentation & Code Review (Cross-Cutting)

**Purpose**: Document the new endpoints and add the code-review checkpoint that enforces the 429-wrapper rule.

- [ ] T026 [P] Update the "Mist API Endpoints Used" table in `README.md` (section around line 187-204) to add four rows: (a) `/api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps` (GET) — "Hourly Avg + Peak Rx/Tx per gateway port (US1)"; (b) `/api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health` (GET) — "Native per-port hourly jitter/latency/loss (US2)"; (c) `/api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/{summary,summary-trend,impacted-interfaces,threshold}` (GET) — "Site Application Health % SLE (US3)"; (d) `mistapi>=0.63.3` typed SDK helpers used where available for (a)–(c); direct `requests.get` fallback otherwise. Match the existing table's column style. Reference: user constraint set, research.md § D-1.
- [ ] T027 [P] Add a "Known limitations vs Mist WAN Insights (SSR) dashboard" section to `README.md` after the "Mist API Endpoints Used" section AND cross-link to it from `specs/001-wan-insights-metrics/spec.md` § Assumptions and from an in-modal "Learn more" link in `templates/index.html`. The section MUST document these caveats: (1) "Hourly data is retained by the Mist API for 14 days at 1h interval; requests older than that are clipped server-side and the operator sees a visible retention notice." (2) "This dashboard uses only live, native Mist REST endpoints — no Snowflake / Premium Analytics fetch, no client-side aggregation, no substitution metric. Per-port jitter/latency/loss is the native `wan_link_health` insight metric; site Application Health % is the native Mist Application Health SLE on SSR." (3) "Values may still differ from the Snowflake-backed Mist Premium Analytics dashboard because Snowflake applies longer-window smoothing and traffic-weighting that the live API does not." Reference: FR-007, FR-016, spec.md § Assumptions.
- [ ] T028 [US3] Ensure the customer-facing text from T027 is reachable from the UI. In `templates/index.html`, wire a "Learn more" link on the modal header AND on the Application Health % tile pointing to the "Known limitations" section of the README (or to the same content rendered inline in an in-modal helper drawer, whichever is simpler with the existing DOM). Reference: FR-016, SC-006.
- [ ] T029 Code-review pass: walk every new call site added by T007, T012, T021 (and every subsidiary call) in `mist_connection.py` and confirm each SDK/`requests.get` invocation is followed by (a) a call to `_handle_rate_limit_response` on the response, and (b) a `_mark_token_rate_limited` path on 429, exactly mirroring `get_vpn_peer_stats` (`mist_connection.py:891-987`). Any call that bypasses the wrapper MUST be fixed before merge. Record the review outcome in the PR description with a bullet per method proving compliance. Reference: FR-009, SC-005, research.md § D-1.

---

## Phase 8: Polish & Regression

**Purpose**: Validate the additive-only guarantee and complete the manual acceptance walkthrough.

- [ ] T030 *(removed — no aggregation sanity check snippet exists. Scenario 4 of the pre-cascade quickstart has been deleted along with the aggregation helper.)*
- [ ] T031 Execute `quickstart.md § Scenario 5` (regression scenario): take pre-feature screenshots of the gateway list, the pre-feature chart modal, and the existing per-port CSV export; then re-run post-feature and confirm the existing surfaces are byte-identical (excluding CSV export timestamp). Any diff blocks release. Reference: FR-012, SC-007.
- [ ] T032 [P] Execute `quickstart.md § Scenarios 1, 2, 3` end-to-end on a live SSR org with all three pre-conditions (traffic-carrying port, port with `wan_link_health` samples, site reporting `application-health`). Record the SC-001 stopwatch numbers (95th percentile modal open ≤ 5 s) inline in the PR description.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start with T000 (SDK bump).
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS every user-story phase because T007/T012/T021 need T005/T006.
- **User Story 1 (Phase 3, P1)**: Depends on Phase 2. No dependency on US2 or US3.
- **User Story 2 (Phase 4, P2)**: Depends on Phase 2 AND on T008 (US1's route) because T013 extends the same route in place.
- **User Story 3 (Phase 5, P3)**: Depends on Phase 2. T023's per-port slice inside the modal also depends on T013 having landed so the extended `/hourly` route can pipe through `port_app_health` / `hourly_app_health`.
- **Phase 7 (docs / disclosure / code review)**: T026 and T027 have no code dependencies and can start immediately in parallel. T028 needs T009 and T023 landed. T029 needs T007, T012, T021 landed.
- **Phase 8 (polish / regression)**: All prior phases complete.

### User Story Dependencies

- **US1 (P1)**: Independent — this is the MVP.
- **US2 (P2)**: Backend and frontend both extend US1's route and modal panel. T013 must land after T008; T016/T019/T020 must land after T009's panel/timeframe scaffolding.
- **US3 (P3)**: The site tile is fully independent of US1/US2. The per-port Application Health strip inside the modal (part of T023) depends on the T013 route extension.

### Within Each User Story

- Backend `MistConnection` method → route → template panel → empty/rate-limit states.
- No test-first sequencing (no pure logic to unit-test; live-API tests are manual per `quickstart.md`).
- Commit after each task or logical group.

### Parallel Opportunities

Explicit [P] parallelism markers indicate independent files or independent DOM regions:

- **Setup**: T003 [P] runs alongside T001 / T002.
- **Foundational**: T005 and T006 land in the same file (`mist_connection.py`) so treat as one editor session.
- **US1**: T009 [P] (template) can be scaffolded while T007 (backend) is in review.
- **US2**: T016 [P] can be authored in parallel with T019/T020 in different DOM regions of `templates/index.html`.
- **US3**: T023 [P] (template tile) can be authored while T021/T022 (backend + route) are in review.
- **Docs**: T026 [P] (README endpoints), T027 [P] (limitations doc) are independent sections and can run concurrently.
- **US1 vs US2 vs US3**: After Phase 2, three developers can pick up US1, US2, US3 in parallel with the caveat that US2's frontend depends on US1's panel scaffolding landing first, and US3's per-port strip depends on T013.

---

## Parallel Example: User Story 2 (P2) frontend build-out

```bash
# After T012, T013, T014, T015 are merged, these UI tasks can proceed in parallel:
Task T016 [P] [US2] Hourly jitter/latency/loss chart panel (three-series Chart.js) in templates/index.html
Task T019     [US2] Export Hourly Metrics button in #chartModal header
Task T020     [US2] Rate-limit banner rendering on both panels
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (Setup, including T000 SDK bump) → Phase 2 (Foundational) → Phase 3 (US1).
2. STOP and validate against `quickstart.md § Scenario 1` on a live SSR org.
3. Ship if leadership approves the P1-only slice: hourly Rx/Tx utilization is a complete, independently valuable, standalone increment.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add US1 → validate Scenario 1 → deploy (MVP).
3. Add US2 → validate Scenario 2 (including CSV column check) → deploy.
4. Add US3 → validate Scenario 3 → deploy.
5. T029 code review is a hard gate for every deploy.

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup (T000 SDK bump is a single-owner task) + Foundational together (single editing session on `mist_connection.py`).
2. Once Foundational is done:
   - Developer A: US1 (T007 → T008 → T009 → T010 → T011)
   - Developer B: US2 backend (blocked by T008) → US2 frontend (blocked by T009)
   - Developer C: US3 (fully independent for the site tile) + docs (T026, T027)
3. Developer D (or any of A/B/C): code-review pass T029, regression T031.

---

## Notes

- Every new Mist API call funnels through the existing multi-token 429 wrapper on `MistConnection`. T029 is the explicit code-review checkpoint that enforces this end-to-end.
- No new file is created by this feature. Every change is in `mist_connection.py`, `app.py`, `templates/index.html`, `requirements.txt`, `README.md`, or `specs/001-wan-insights-metrics/spec.md`.
- No new caches are introduced in the MVP (research.md § D-10). If production load demands it, that is a follow-up.
- No `aggregation_method` string, no `peer_count` column, no `"N/A"` sentinel, no substitution notice, no session-storage flag — all removed by the 2026-07-17 cascade correction. See data-model.md § Changelog and research.md § D-2/D-3/D-5/D-6/D-11 for the removed stubs.
- CSV timestamps remain UTC even if the UI shows a local-time hint (FR-011, spec §Edge Cases §Time zone).
- T004, T017, T018, T024, T025, T030 are intentionally kept as one-line removed stubs so downstream references to `T-NNN` numbers do not shift.
