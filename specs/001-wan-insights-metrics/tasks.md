---
description: "Task list for feature 001-wan-insights-metrics"
---

# Tasks: SSR WAN Insights-Equivalent Metrics

**Input**: Design documents from `specs/001-wan-insights-metrics/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/GET_gateway_port_hourly.md, contracts/GET_site_wan_link_health.md

**Tests**: One pure-function unit test is included (aggregation math). Live-API scenarios are validated manually via `quickstart.md` per plan.md § Technical Context / D-12.

**Organization**: Tasks are grouped by user story (P1 utilization, P2 performance rollup + CSV, P3 site WAN link health) plus cross-cutting docs / disclosure / review tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files or non-overlapping regions, no dependencies on incomplete tasks)
- **[Story]**: User story mapping — [US1], [US2], [US3]; omitted for Setup/Foundational/Polish
- Every task references an exact file path and, where applicable, a function or DOM anchor

## Path Conventions

Single-file-per-role Flask layout (per plan.md § Project Structure). All backend work lands in the two existing Python files at repo root, all UI work in the single existing template. No new files are created except one unit-test script for the pure aggregation helper.

- Backend: `mist_connection.py`, `app.py`
- UI: `templates/index.html`
- Docs: `README.md`, `specs/001-wan-insights-metrics/spec.md`
- Test: `tests/test_rollup_peer_metrics_simple_mean.py` (new; only file this feature creates outside the three canonical files)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the sandbox and pin the working branch. No dependency changes, no new tooling.

- [ ] T001 Verify feature branch `001-wan-insights-metrics` is checked out and `git status` is clean before editing `mist_connection.py`, `app.py`, `templates/index.html`
- [ ] T002 Confirm `requirements.txt` is UNCHANGED (no new dependencies per plan.md § Technical Context) and `python -m venv .venv && pip install -r requirements.txt` succeeds against the pinned versions
- [ ] T003 [P] Read the two contracts in `specs/001-wan-insights-metrics/contracts/` end-to-end so every subsequent implementer has the exact wire shape memorized before editing code

**Checkpoint**: Branch clean, deps unchanged, contracts reviewed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the pure aggregation helper and the retention-clipping utility that BOTH US1 and US2 depend on. These are shared building blocks; no user story route may be wired up until this phase is complete.

- [ ] T004 Implement `MistConnection.rollup_peer_metrics_simple_mean(peer_series: Dict[str, List[Dict]], hour_epochs: List[int]) -> List[Dict]` in `mist_connection.py` as a `@staticmethod` pure function. Per hour bucket: compute arithmetic mean of `avg_latency` / `avg_jitter` / `avg_loss` across ONLY the peers that reported that hour (per-peer non-reports are excluded from the denominator, NEVER counted as 0). Emit `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` as the JSON string `"N/A"` when `peer_count == 0` for that hour. Set `aggregation_method="simple_mean"` on every row. Assert `aggregation_method == "simple_mean"` before return. Reference: data-model.md § HourlyPerformanceRollup, research.md § D-2 / D-3.
- [ ] T005 Implement `MistConnection._clip_to_retention_window(requested_start: int, end: int) -> Tuple[int, bool, str]` in `mist_connection.py` returning `(clipped_start, was_clipped, retention_notice)`. Rule: `clipped_start = max(requested_start, end - 14 * 86400)`. When `was_clipped`, the notice is `"Data range clipped to the API's 14-day 1h-interval retention window (from <iso_start> to <iso_end>)."`. Reference: research.md § D-4, FR-010.
- [ ] T006 Add a `_duration_to_seconds(duration: str) -> int` helper on `MistConnection` (or as a module-level constant map) mapping `"24h" -> 86400`, `"3d" -> 259200`, `"7d" -> 604800`. Every route handler MUST use this — no duplicated math. Reference: research.md § D-4.

**Checkpoint**: Pure helpers exist and are importable. US1/US2/US3 route work can now begin in parallel.

---

## Phase 3: User Story 1 - Hourly Rx/Tx Utilization per WAN Port (Priority: P1) MVP

**Goal**: Deliver hourly Avg + Peak Rx/Tx per WAN port for the last 24h (default) up to 7d, sourced from `insights/device/{device_id}/tx_rx_bps?interval=3600`. Includes retention clipping, empty-utilization state, and the new panel appended to the existing modal.

**Independent Test**: For any SSR gateway WAN port with traffic in the last 14 days, `GET /api/gateway/<id>/port/<port_id>/hourly?site_id=...&duration=24h` returns `success: true` with a non-empty `utilization[]` where every entry has numeric `rx_avg_bps` / `rx_peak_bps` / `tx_avg_bps` / `tx_peak_bps` and a UTC `hour_iso`. Verified via `quickstart.md § Scenario 1`.

### Implementation for User Story 1

- [ ] T007 [US1] Implement `MistConnection.get_port_tx_rx_bps_hourly(site_id, device_id, port_id, start, end)` in `mist_connection.py`. Issue `GET https://{self.host}/api/v1/sites/{site_id}/insights/device/{device_id}/tx_rx_bps?port_id={port_id}&interval=3600&start={start}&end={end}` via `requests.get`, mirroring the `get_vpn_peer_stats` direct-`requests` pattern (`mist_connection.py:891-987`). Every call MUST route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. Return a `List[HourlyUtilizationSample]` (zip of `tx_bps` / `rx_bps` / `max_tx_bps` / `max_rx_bps` arrays with hour boundaries computed from `start + i * 3600`). Empty upstream → `[]`. Reference: contracts/GET_gateway_port_hourly.md § Server-side behaviour step 4, research.md § D-1.
- [ ] T008 [US1] Add Flask route `GET /api/gateway/<gateway_id>/port/<path:port_id>/hourly` in `app.py`. Validate `site_id` (required) and `duration` (enum `24h`/`3d`/`7d`, default `24h`). Compute `end = now`, `raw_start = end - _duration_to_seconds(duration)`, then apply `_clip_to_retention_window`. Call `get_port_tx_rx_bps_hourly`. Resolve `gateway_name` / `site_name` via existing helpers. Assemble the `PortHourlyResponse` envelope minus the `performance` / `peers` / `peer_breakdown` fields (US2 fills those; US1 emits `performance: []`, `peers: []`, `peer_breakdown: {}`, `empty_performance: true`). Set `empty_utilization: true` when `utilization` is `[]`. NEVER return HTTP 404 for empty data. Reference: contracts/GET_gateway_port_hourly.md § Response — `format=json`, FR-015.
- [ ] T009 [P] [US1] Append the "Hourly Avg + Peak Rx/Tx" Chart.js panel BELOW the existing `#trafficChartRate` / `#trafficChartData` panels inside `#chartModal` in `templates/index.html`. Add a `24h` (default) / `3d` / `7d` timeframe button group inside the new panel header. Wire the panel to fetch from the T008 route on port-row click and on timeframe change. Order MUST be: (a) existing rate + data-transferred charts unchanged; (b) new hourly Avg+Peak Rx/Tx chart; leave a placeholder slot for the US2 jitter/latency/loss chart directly below. Reference: research.md § D-9, FR-012.
- [ ] T010 [US1] In `templates/index.html`, render the retention notice banner between the existing data-transferred panel and the new hourly panel whenever `response.clipped === true`. Banner text: use the response's `retention_notice` string verbatim. Muted styling matches the existing modal note styles. Reference: FR-010.
- [ ] T011 [US1] In `templates/index.html`, render the empty-utilization state ("no utilization data reported for this port in the requested window") when `response.empty_utilization === true`. MUST NOT show an error banner. Reference: FR-015, Acceptance Scenario 1.4.

**Checkpoint**: A network engineer can click a WAN port, see hourly Avg+Peak Rx/Tx charted for 24h/3d/7d, and see the empty-utilization state for a port that has never carried traffic. `quickstart.md § Scenario 1` steps 1–7 pass end-to-end. The existing charts are unchanged (FR-012 / SC-007). US2 and US3 work has not started and does not block this MVP demo.

---

## Phase 4: User Story 2 - Hourly Jitter / Latency / Loss Rolled Up per WAN Port (Priority: P2)

**Goal**: Fan out `vpn_peer-metrics` calls per peer per port, aggregate client-side via `rollup_peer_metrics_simple_mean`, and expose the result via the same `/hourly` route plus a new `/hourly/csv` route. Include the peer-breakdown drilldown, the aggregation-method label, and the zero-peer `"N/A"` treatment.

**Independent Test**: For any SSR WAN port with at least one active VPN peer path reporting BFD metrics, the same `GET /api/gateway/<id>/port/<port_id>/hourly?...` returns a non-empty `performance[]` where every row has `aggregation_method: "simple_mean"`, numeric `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct`, and a `peer_count > 0`, plus a non-empty `peers[]` and `peer_breakdown`. For a zero-peer port, the same route returns `performance[]` where every row has the three metric fields as the literal JSON string `"N/A"` and `peer_count: 0`. Verified via `quickstart.md § Scenario 2`.

### Implementation for User Story 2

- [ ] T012 [US2] Implement `MistConnection.get_port_vpn_peer_metrics_hourly(site_id, device_id, port_id, peer_mac_or_router_name, peer_port_id, policy, start, end)` in `mist_connection.py`. Issue `GET https://{self.host}/api/v1/sites/{site_id}/insights/device/{device_id}/vpn_peer-metrics?port_id=...&peer_mac=...&peer_port_id=...&policy=...&interval=3600&start=...&end=...` via `requests.get`. Use `peer_router_name` as fallback when `peer_mac` is missing (research.md § D-6). Route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. Return a list of `{hour_epoch, avg_latency, avg_jitter, avg_loss}` dicts by zipping the returned arrays with `start + i * 3600`. Empty upstream → `[]`. Reference: FR-003, contracts/GET_gateway_port_hourly.md § Server-side behaviour step 6.
- [ ] T013 [US2] Extend the `GET /api/gateway/<gateway_id>/port/<path:port_id>/hourly` route in `app.py` (from T008) to also: resolve `device_mac` from existing gateway metadata; call `get_vpn_peer_stats(site_id, device_mac)` and filter its `peers_by_port` dict by `port_id` to enumerate `(peer_mac, peer_router_name, peer_port_id, policy)` tuples; SERIALLY call `get_port_vpn_peer_metrics_hourly` for each peer (bounded fanout per plan.md § Performance Goals); collect results into `{peer_key: [{hour_epoch, ...}]}` dict keyed by `f"{peer_router_name}::{peer_port_id}"`; feed the dict into `rollup_peer_metrics_simple_mean` (T004); populate `performance[]`, `peers[]`, `peer_breakdown{}`, `empty_performance`. Reference: FR-004, FR-005, research.md § D-5.
- [ ] T014 [US2] In the same route (`app.py`), populate `rate_limited.performance: true` if any peer fanout call returned a rate-limited sentinel, and populate `rate_limited.utilization: true` if the tx_rx_bps call was rate-limited. Response MUST remain HTTP 200 with `success: true` in the rate-limited case — never surface HTTP 429 to the browser. Reference: contracts/GET_gateway_port_hourly.md § 429 handling, FR-009 / SC-005.
- [ ] T015 [US2] Add Flask route `GET /api/gateway/<gateway_id>/port/<path:port_id>/hourly/csv` in `app.py`. Same query params as JSON route. Reuse the utilization + performance assembly from T008 / T013. Stream a `text/csv; charset=utf-8` response with `Content-Disposition: attachment; filename="hourly_metrics_{gateway_name}_{port_id}_{iso_utc_now}.csv"`. Header row and column order are FIXED per data-model.md § HourlyMetricsCsvRow: `site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct,aggregation_method,peer_count`. Map `"N/A"` → empty string ONLY in this writer. Assert `aggregation_method == "simple_mean"` per row before write. Sort rows ascending by `(site_name, gateway_name, port_id, hour_epoch)`. Reference: FR-011, SC-004, research.md § D-7.
- [ ] T016 [P] [US2] Append the "Hourly Jitter / Latency / Loss (client-side rollup)" Chart.js panel in `templates/index.html` in the placeholder slot from T009. Render three series (jitter / latency / loss) driven by `response.performance[]`. Above the chart, render a small label reading exactly the string `simple_mean` (from `response.aggregation_method`) plus an explainer link. Tooltip on each series point MUST show the aggregate value AND the `peer_count` for that hour. Reference: FR-005, FR-006, FR-013, Acceptance Scenario 2.3.
- [ ] T017 [P] [US2] Add the peer-breakdown drilldown in `templates/index.html`: a collapsible section under the performance panel that, when opened for a given hour, renders a table of every peer in `response.peer_breakdown` with its per-hour `avg_latency` / `avg_jitter` / `avg_loss`. Must be reachable in one click from the aggregate row per SC-003. Reference: FR-013, SC-002, SC-003.
- [ ] T018 [US2] Add the FR-006a / FR-014 zero-peer empty state in `templates/index.html`: when `response.empty_performance === true`, render `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` as the literal string `"N/A"` (never `0`, `0.0`, or blank), display the message "no VPN peer paths on this port; jitter/latency/loss are only measured on SVR peer paths", and keep the Rx/Tx (US1) panel rendering normally. Reference: FR-006a, FR-014, Acceptance Scenario 2.4.
- [ ] T019 [US2] Add the "Export Hourly Metrics" button to the `#chartModal` header in `templates/index.html`. Click handler: set `window.location = "/api/gateway/<id>/port/<port_id>/hourly/csv?site_id=...&duration=..."` reflecting the currently selected timeframe. Existing per-port CSV export button is UNCHANGED and remains at its current DOM position. Reference: FR-011, SC-004, research.md § D-7.
- [ ] T020 [US2] In `templates/index.html`, render a "temporarily rate-limited, try again shortly" banner on the performance panel when `response.rate_limited?.performance === true`, and on the utilization panel when `response.rate_limited?.utilization === true`. Panels showing rate-limited state MUST NOT show a hard error. Reference: contracts/GET_gateway_port_hourly.md § 429 handling, FR-009.

**Checkpoint**: An operator can see the hourly jitter/latency/loss chart with `simple_mean` labeling, drill into the peer breakdown in one click, export the FR-011 CSV, see the `"N/A"` state on a zero-peer port, and hit a graceful rate-limit banner if a token pool is exhausted. `quickstart.md § Scenario 2` steps 1–10 pass end-to-end. US1's utilization panel continues to work unchanged.

---

## Phase 5: User Story 3 - Site-Level "WAN Link Health %" (Priority: P3)

**Goal**: Render a site-level WAN Link Health % tile with classifier breakdown and the substitution notice for the unavailable Application Health %.

**Independent Test**: For any SSR site reporting `wan-link-health`, `GET /api/site/<site_id>/wan_link_health?duration=24h` returns `success: true`, `available: true`, numeric `health_pct`, all seven classifier keys populated, non-empty `hourly[]` with all seven `classifier_breakdown` keys in every hour, and the verbatim `substitution_notice`. For a site where `wan-link-health` returns HTTP 400/null, the same route returns HTTP 200 with `available: false`, `reason: "..."`, `health_pct: null`, `hourly: []`, and the substitution notice still present. Verified via `quickstart.md § Scenario 3`.

### Implementation for User Story 3

- [ ] T021 [US3] Implement `MistConnection.get_site_wan_link_health(site_id, start, end)` in `mist_connection.py`. Issue `GET https://{self.host}/api/v1/sites/{site_id}/sle/wan-link-health?start=...&end=...&interval=3600` via `requests.get`. Route through `_handle_rate_limit_response` / `_mark_token_rate_limited`. Return `{available: True, health_pct, classifiers: {...}, hourly: [...]}` on success; return `{available: False, reason: "wan-link-health SLE returned HTTP 400"}` (or similar) on HTTP 400 / null body. All seven classifier keys MUST always be present in the returned dict — fill missing upstream keys with `0.0`. Reference: research.md § D-8, FR-007.
- [ ] T022 [US3] Add Flask route `GET /api/site/<site_id>/wan_link_health` in `app.py`. Validate `duration` (enum `24h`/`3d`/`7d`, default `24h`). Resolve `site_name` via existing sites cache. Apply retention clipping (T005). Call `get_site_wan_link_health`. Assemble the SiteWanLinkHealth response per contracts/GET_site_wan_link_health.md — including verbatim `substitution_notice` (Acceptance Scenario 3.2 copy). When wrapper returns `available: false`, DO NOT propagate HTTP 400 — return HTTP 200 with the "unavailable" body shape. NEVER call the `application-health` SLE (FR-016, research.md § D-8). Reference: contracts/GET_site_wan_link_health.md § Server-side behaviour.
- [ ] T023 [P] [US3] Add the "WAN Link Health %" tile in the site view section of `templates/index.html`. Render `response.health_pct` prominently; show the seven classifier keys always (from the fixed key list, not from `classifiers` values). Show an "unavailable" tile state when `response.available === false` — classifier list still visible. Reference: FR-007, Acceptance Scenarios 3.1 / 3.4.
- [ ] T024 [US3] In `templates/index.html`, render the substitution notice per research.md § D-11: (a) always show an info icon next to the tile with a tooltip containing the verbatim `response.substitution_notice`; (b) on first render per browser session render the same notice inline below the tile once; use `sessionStorage.setItem("wanLinkHealthNoticeSeen", "1")` to suppress subsequent inline renders in the same session. Reference: FR-008, SC-008, Acceptance Scenario 3.2.

**Checkpoint**: The three user-story panels/tiles are wired end-to-end. `quickstart.md § Scenarios 1–3` all pass.

---

## Phase 6: Aggregation Unit Test (Cross-Cutting)

**Purpose**: The single pure-function unit test called out in the user's constraint set. Deterministic, no live API required. Anchors SC-002 arithmetic and FR-006a `"N/A"` mapping.

- [ ] T025 [P] Create `tests/test_rollup_peer_metrics_simple_mean.py` with pytest-style test functions (no fixtures, no mocks — the function has no I/O) exercising `MistConnection.rollup_peer_metrics_simple_mean`. Cases MUST cover: (a) two peers reporting all three hours → mean matches hand-computed values within 1e-9; (b) mid-window peer churn: one peer skips one hour → `peer_count` for that hour is 1, and the skipped peer is NOT counted as 0 (research.md § D-2, spec §Edge Cases § "Peer path churn"); (c) zero-peer input over three hours → every hour has `avg_latency_ms == "N/A"`, `avg_jitter_ms == "N/A"`, `avg_loss_pct == "N/A"`, `peer_count == 0`, `aggregation_method == "simple_mean"`; (d) `aggregation_method` equals the literal string `"simple_mean"` in every emitted row (FR-006 assertion). Test data MUST match the snippet in `quickstart.md § Scenario 4` exactly so quickstart and the pytest suite validate the same invariant. Run instruction: `pytest tests/test_rollup_peer_metrics_simple_mean.py -v` from repo root.

---

## Phase 7: Documentation & Customer-Facing Disclosure (Cross-Cutting)

**Purpose**: Document the new endpoints, spell out the three caveats the customer must see before shipping, and add the code-review checkpoint that enforces the 429-wrapper rule.

- [ ] T026 [P] Update the "Mist API Endpoints Used" table in `README.md` (section around line 187-204) to add three rows: (a) `/api/v1/sites/{site_id}/insights/device/{device_id}/tx_rx_bps` (GET) — "Hourly Avg + Peak Rx/Tx per WAN port (US1)"; (b) `/api/v1/sites/{site_id}/insights/device/{device_id}/vpn_peer-metrics` (GET) — "Per-peer hourly jitter/latency/loss for SVR peer paths, aggregated client-side (US2)"; (c) `/api/v1/sites/{site_id}/sle/wan-link-health` (GET) — "Site WAN Link Health % SLE, substituted for the unavailable Application Health % on SSR (US3)". Match the existing table's column style. Reference: user constraint set.
- [ ] T027 [P] Add a "Known limitations vs Mist WAN Insights (SSR) dashboard" section to `README.md` after the "Mist API Endpoints Used" section AND cross-link to it from `specs/001-wan-insights-metrics/spec.md` § Assumptions and from an in-modal "Learn more" link in `templates/index.html`. The section MUST contain three bullets, verbatim in intent: (1) "Site-level Application Health % cannot be delivered on SSR via the live Mist API; AppTrack/AppQoE-based Application Health is not implemented on SSR/SVR gateways and the live API returns HTTP 400 or null for `application-health` SLE on SSR sites. This dashboard substitutes the `wan-link-health` site SLE and labels the tile accordingly." (2) "Port-level jitter, latency, and loss shown per hour are a client-side `simple_mean` rollup of per-peer BFD measurements returned by `insights/device/{device_id}/vpn_peer-metrics`. They are NOT a native port-level Mist API metric. Traffic-weighted mean is an explicit Phase 2 follow-up." (3) "Because the aggregation is client-side and uses only the live Mist REST API, values may differ from the Snowflake-backed Mist Premium Analytics dashboard. Per SC-002, the port-level rollup values match a manual simple-arithmetic-mean recomputation of the underlying per-peer values within 1% or 0.1 ms / 0.1% (whichever is larger); the delta between this dashboard and the Snowflake dashboard can be larger than that when Snowflake applies traffic-weighting or longer-window smoothing." Reference: FR-008, FR-013, SC-002, spec.md § Assumptions.
- [ ] T028 [US3] Ensure the customer-facing text from T027 is reachable from the UI. In `templates/index.html`, wire the FR-013 "Learn more" / explainer link on the performance panel (T016) AND on the WAN Link Health tile substitution notice (T024) to anchor at the "Known limitations" section of the README (or to the same content rendered inline in an in-modal helper drawer, whichever is simpler with the existing DOM). The three disclosures MUST be reachable in at most one click from either surface. Reference: FR-008, FR-013, SC-006.
- [ ] T029 Code-review pass: walk every new call site added by T007, T012, T021 (and every subsidiary call) in `mist_connection.py` and confirm each `requests.get` invocation is followed by (a) a call to `_handle_rate_limit_response` on the response, and (b) a `_mark_token_rate_limited` path on 429, exactly mirroring `get_vpn_peer_stats` (`mist_connection.py:891-987`). Any call that bypasses the wrapper MUST be fixed before merge. Record the review outcome in the PR description with a bullet per method proving compliance. Reference: FR-009, SC-005, research.md § D-1.

---

## Phase 8: Polish & Regression

**Purpose**: Validate the additive-only guarantee and complete the manual acceptance walkthrough.

- [ ] T030 Run the aggregation snippet in `quickstart.md § Scenario 4` from the repo root with the venv active and confirm `aggregation sanity check: PASS` prints. Should be redundant against T025 but serves as the operator-facing sanity check.
- [ ] T031 Execute `quickstart.md § Scenario 5` (regression scenario): take pre-feature screenshots of the gateway list, the pre-feature chart modal, and the existing per-port CSV export; then re-run post-feature and confirm the existing surfaces are byte-identical (excluding CSV export timestamp). Any diff blocks release. Reference: FR-012, SC-007.
- [ ] T032 [P] Execute `quickstart.md § Scenarios 1, 2, 3` end-to-end on a live SSR org with all four gateway/port pre-conditions (traffic-carrying port, port with SVR peer path, port with zero SVR peers, site reporting `wan-link-health`). Record the SC-001 stopwatch numbers (95th percentile modal open ≤ 5 s) and the SC-002 tolerance check inline in the PR description.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS every user-story phase because T007/T013 need T004/T005/T006.
- **User Story 1 (Phase 3, P1)**: Depends on Phase 2. No dependency on US2 or US3.
- **User Story 2 (Phase 4, P2)**: Depends on Phase 2 AND on T008 (US1's route) because T013 extends the same route in place.
- **User Story 3 (Phase 5, P3)**: Depends on Phase 2 only. Independent of US1 and US2 (different endpoint, different UI surface).
- **Phase 6 (unit test)**: Depends on T004 only. Can run in parallel with any phase after Phase 2.
- **Phase 7 (docs / disclosure / code review)**: T026 and T027 have no code dependencies and can start immediately in parallel. T028 needs T016 and T024 landed. T029 needs T007, T012, T021 landed.
- **Phase 8 (polish / regression)**: All prior phases complete.

### User Story Dependencies

- **US1 (P1)**: Independent — this is the MVP.
- **US2 (P2)**: Backend and frontend both extend US1's route and modal panel. T013 must land after T008; T016/T017/T018/T019/T020 must land after T009's panel/timeframe scaffolding.
- **US3 (P3)**: Fully independent — different Flask route, different UI surface (site view, not port modal).

### Within Each User Story

- Backend `MistConnection` method → route → template panel → empty/rate-limit states.
- No test-first sequencing (only one unit test, isolated to a pure function; live-API tests are manual per `quickstart.md`).
- Commit after each task or logical group.

### Parallel Opportunities

Explicit [P] parallelism markers indicate independent files or independent DOM regions:

- **Setup**: T003 [P] runs alongside T001 / T002.
- **Foundational**: T004, T005, T006 can be authored in one editing pass but T004 is the only one with real logic; they land in the same file (`mist_connection.py`) so treat as one editor session.
- **US1**: T009 [P] (template) can be scaffolded while T007 (backend) is in review.
- **US2**: T016 [P] and T017 [P] land in different regions of `templates/index.html` and can be authored in parallel.
- **US3**: T023 [P] (template tile) can be authored while T021/T022 (backend + route) are in review.
- **Docs**: T025 [P] (unit test), T026 [P] (README endpoints), T027 [P] (limitations doc) are all independent files/sections and can run concurrently.
- **US1 vs US2 vs US3**: After Phase 2, three developers can pick up US1, US2, US3 in parallel with the caveat that US2's frontend depends on US1's panel scaffolding landing first.

---

## Parallel Example: User Story 2 (P2) frontend build-out

```bash
# After T012, T013, T014, T015 are merged, three UI tasks can proceed in parallel:
Task T016 [P] [US2] Performance chart panel (three-series Chart.js) in templates/index.html
Task T017 [P] [US2] Peer-breakdown drilldown table in templates/index.html
Task T018     [US2] Zero-peer N/A empty state in templates/index.html   # touches same DOM region as T016, serialize
Task T019     [US2] Export Hourly Metrics button in #chartModal header
Task T020     [US2] Rate-limit banner rendering on both panels
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. STOP and validate against `quickstart.md § Scenario 1` steps 1–7 on a live SSR org.
3. Ship if leadership approves the P1-only slice: hourly Rx/Tx utilization is a complete, independently valuable, standalone increment.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add US1 → validate Scenario 1 → deploy (MVP).
3. Add US2 → validate Scenario 2 (including the SC-002 hand-recompute and the CSV byte-check) → deploy.
4. Add US3 → validate Scenario 3 → deploy.
5. Land the T027 customer-facing disclosure BEFORE any US2 or US3 deploy — this is a hard gate.
6. T029 code review is a hard gate for every deploy.

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (single editing session on `mist_connection.py`).
2. Once Foundational is done:
   - Developer A: US1 (T007 → T008 → T009 → T010 → T011)
   - Developer B: US2 backend (blocked by T008) → US2 frontend (blocked by T009)
   - Developer C: US3 (fully independent) + docs (T026, T027)
3. Developer D (or any of A/B/C): unit test T025, code-review pass T029, regression T031.

---

## Notes

- Every new Mist API call funnels through the existing multi-token 429 wrapper on `MistConnection`. T029 is the explicit code-review checkpoint that enforces this end-to-end.
- The only new file this feature creates is `tests/test_rollup_peer_metrics_simple_mean.py`. Every other change is in `mist_connection.py`, `app.py`, `templates/index.html`, `README.md`, or `specs/001-wan-insights-metrics/spec.md`.
- No new caches are introduced in the MVP (research.md § D-10). If production load demands it, that is a follow-up.
- The `aggregation_method` string equals the literal `"simple_mean"` in every JSON row and every CSV row for the MVP release — enforced by assertion in T004 and T015.
- CSV timestamps remain UTC even if the UI shows a local-time hint (FR-011, spec §Edge Cases §Time zone).
- Customer-facing disclosure text in T027 is verbatim intent, not verbatim string; wording may be tightened during doc review as long as the three caveats survive.
