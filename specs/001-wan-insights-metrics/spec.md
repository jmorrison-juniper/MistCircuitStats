# Feature Specification: SSR WAN Insights-Equivalent Metrics

**Feature Branch**: `001-wan-insights-metrics`

**Created**: 2026-07-17

**Status**: Draft (rev 2026-07-17 cascade)

**Input**: User description: "Add per-port WAN performance and utilization metrics to the existing gateway/port dashboard, matching the Juniper Mist 'WAN Insights - SSR' dashboard as closely as the LIVE Mist API allows (Premium Analytics/Snowflake is out of scope)."

## Assumptions & Clarifications

### Session 2026-07-17

- Q: What is the default timeframe for the new hourly rollup view? → A: 24 hours. A timeframe selector inside the new view MUST allow the operator to extend the range up to the full 7 days (still within the API's 14-day retention window).
- Q: Where in the UI does the new hourly rollup live? → A: Extend the EXISTING chart modal by appending new panels below the current RX/TX chart in this order: (a) existing RX/TX rate + data-transferred charts unchanged; (b) NEW hourly Avg+Peak Rx/Tx chart sourced from the `insights/gateway/{id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps` insight-metric endpoint; (c) NEW hourly jitter/latency/loss chart sourced from the native `wan_link_health` insight metric on the same endpoint; (d) NEW Application Health per-port contribution widget + hourly classifier breakdown chart sourced from the `application-health` SLE endpoints. The one-click workflow from a port row to the modal MUST be preserved.
- Q: How does CSV export change? → A: The existing per-port CSV MUST remain unchanged. Add a NEW "Export Hourly Metrics" button in the extended modal that produces a SEPARATE CSV with one row per port per hour bucket. Columns (in order): `site_name`, `gateway_name`, `port_id`, `hour_epoch`, `hour_iso`, `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps`, `jitter_avg_ms`, `latency_avg_ms`, `loss_avg_pct`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Hourly Rx/Tx Utilization per WAN Port (Priority: P1)

A network operations engineer at a T-Mobile-scale customer opens the MistCircuitStats dashboard, drills into a specific SSR gateway, and clicks a WAN port row. They see an hourly rollup of downlink (Rx) and uplink (Tx) bandwidth for that port over the last 14 days, showing both the average and the peak observed within each hour. They export the rollup to CSV so they can audit reported capacity against the raw values used by the Mist WAN Insights (SSR) dashboard.

**Why this priority**: This is the metric family the Mist API supports natively and accurately (native `max_tx_bps` / `max_rx_bps` and `tx_bps` / `rx_bps` timeseries). It delivers the largest customer-visible slice of parity with the SSR dashboard on day one, with no aggregation math the customer needs to reconcile. Without this, there is no viable MVP because Rx/Tx utilization is the anchor of the requested view.

**Independent Test**: For any SSR gateway with at least one WAN port carrying traffic in the last 14 days, requesting the hourly utilization view for that port MUST return at least one hour bucket with numeric `avg_rx_bps`, `avg_tx_bps`, `peak_rx_bps`, `peak_tx_bps` values, and CSV export MUST include those columns. This is testable end-to-end without any other user story being implemented.

**Acceptance Scenarios**:

1. **Given** an SSR gateway with a WAN port that has carried traffic within the retention window, **When** the operator opens the hourly utilization view for that port, **Then** the UI displays a per-hour table or chart of `avg_rx_bps`, `peak_rx_bps`, `avg_tx_bps`, `peak_tx_bps` sourced from `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port}&interval=1h`.
2. **Given** the hourly utilization view is loaded, **When** the operator triggers CSV export, **Then** the exported file contains one row per hour bucket with columns for timestamp, port_id, avg_rx_bps, peak_rx_bps, avg_tx_bps, peak_tx_bps.
3. **Given** a request that spans more than 14 days back from now, **When** the view is rendered, **Then** the UI clips the range to the 14-day retention window and displays a note stating the API only retains 1h-interval data for 14 days.
4. **Given** a WAN port that has never carried traffic, **When** the operator opens the hourly utilization view, **Then** the UI shows an empty state that clearly says "no utilization data reported for this port in the requested window" rather than an error.

---

### User Story 2 - Hourly Jitter / Latency / Loss per WAN Port (Priority: P2)

The same engineer wants to see WAN performance (jitter, latency, loss) alongside utilization. The Mist `wan_link_health` insight metric returns per-hour `avg_latency` / `avg_jitter` / `avg_loss` arrays natively for each WAN port on a gateway — the Mist backend has already rolled up the SVR peer-path measurements into port-level values before the API responds. No client-side aggregation is performed by this feature.

**Why this priority**: This is the second requested metric family and is a native, first-class port-level metric. It sequences after User Story 1 only because it uses a different `metrics=` parameter on the same underlying endpoint and warrants its own panel and empty-state handling.

**Independent Test**: For any SSR gateway with a WAN port that reports `wan_link_health` in the requested window, requesting the hourly performance view for that port MUST return at least one hour bucket with numeric `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` values sourced directly from the `wan_link_health` insight metric. This can be tested without User Story 1 being implemented.

**Acceptance Scenarios**:

1. **Given** an SSR gateway with a WAN port reporting `wan_link_health`, **When** the operator opens the hourly performance view for that port, **Then** the UI displays a per-hour `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` chart sourced from a single call to `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port}&interval=1h`.
2. **Given** the performance view is loaded, **When** the operator inspects any hour data point, **Then** the UI shows the value as reported by the Mist API — no aggregation-method label, no per-peer breakdown link.
3. **Given** a port that has no `wan_link_health` telemetry in the window (e.g. a direct-internet WAN uplink with no SVR peer paths), **When** the operator opens the performance view, **Then** the panel shows an empty state reading "no jitter/latency/loss reported for this port in the requested window". Utilization (Rx/Tx) for the same port MUST continue to render normally.
4. **Given** the performance view is loaded, **When** the operator triggers the new "Export Hourly Metrics" CSV export, **Then** the exported file contains one row per port per hour bucket with columns matching FR-011 exactly (`site_name`, `gateway_name`, `port_id`, `hour_epoch`, `hour_iso`, `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps`, `jitter_avg_ms`, `latency_avg_ms`, `loss_avg_pct`).

---

### User Story 3 - Site-Level "Application Health %" with Per-Port Contribution (Priority: P3)

The engineer wants the site-level "Application Health %" tile shown on the Mist WAN Insights (SSR) dashboard, plus a per-port contribution view when they drill into a specific port. Application Health is a standard Mist SLE metric that plugs into the generic SLE URL template (`/sle/site/{site_id}/metric/application-health/{summary|summary-trend|impacted-interfaces|threshold}`) and returns real data on SSR sites via the live REST API. There is no substitution and no proxy — every displayed number is a first-class Mist SLE value.

**Why this priority**: Site-level health is a single tile relative to the per-port metrics, and it is the newest surface being wired into the dashboard, so it sequences after the port-level utilization and performance panels are proven.

**Independent Test**: For any SSR site reporting `application-health`, requesting the site health tile MUST return a numeric Application Health percentage, the SLE goal for the ring benchmark, an hourly classifier breakdown (`jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`), and a per-port impacted-interfaces list. For any port modal opened on a site that reports `application-health`, the modal MUST show the port's contribution row plus the hourly classifier breakdown chart.

**Acceptance Scenarios**:

1. **Given** an SSR site reporting `application-health`, **When** the operator opens the site view, **Then** the UI shows an "Application Health %" tile whose value comes from `/api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary`, with the SLE goal ring populated from `.../application-health/threshold` and an hourly micro-chart underneath sourced from `.../application-health/summary-trend`.
2. **Given** the site view is loaded, **When** the operator inspects the hourly micro-chart, **Then** the chart decomposes each hour bucket into the six Application Health classifiers (`jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`).
3. **Given** the operator has opened a port modal on the same site, **When** the modal loads, **Then** a "This port's contribution to Application Health" widget renders the port's row from `.../application-health/impacted-interfaces` (matching by `(gateway_hostname, interface_name)`), and a small hourly classifier breakdown chart renders below it from `.../application-health/summary-trend` filtered to the jitter/latency/loss classifiers most relevant to a port view.
4. **Given** a site that does NOT report `application-health` (e.g. a non-SSR site type), **When** the operator opens the site view, **Then** the tile shows a "not reported for this site type" placeholder and the corresponding port-modal widgets show an equivalent empty state. No error banner is shown.

---

### Edge Cases

- API rate limiting: hitting 429 on any of the new endpoints (`insights/gateway/{id}/stats`, `sle/site/{id}/metric/application-health/*`) MUST be handled by the existing multi-token 429 rotation wrapper. New endpoints must not bypass that wrapper.
- Retention boundary: requests that span past the 14-day 1h-interval retention window MUST be clipped and the UI MUST tell the operator the window was clipped, not silently return partial data.
- Port without `wan_link_health` telemetry: the performance panel shows a plain "no jitter/latency/loss reported for this port in the requested window" empty state. Utilization (Rx/Tx) for the same port MUST continue to render normally.
- Site does not report `application-health` SLE: the site-level Application Health tile shows a "not reported for this site type" placeholder; the port-modal Application Health widgets show an equivalent empty state. Neither blocks the rest of the view.
- Port without a matching insight response: the `tx_bps,rx_bps,max_tx_bps,max_rx_bps` insight-metric returns empty for ports that never carried traffic — the UI must render an empty state, not an error.
- Time zone: hour buckets are UTC-anchored as returned by the API. The UI MUST label the axis with the time zone in effect and MUST NOT silently convert to local time in exported CSVs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST fetch hourly Rx/Tx utilization per WAN port from `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id={port}&interval=1h`, capturing `tx_bps`, `rx_bps`, `max_tx_bps`, `max_rx_bps` timeseries.
- **FR-002**: System MUST surface `max_tx_bps` as "Peak Tx (bps)" and `max_rx_bps` as "Peak Rx (bps)" per hour, and `tx_bps`/`rx_bps` as "Avg Tx (bps)" and "Avg Rx (bps)" per hour, in a per-port hourly view.
- **FR-003**: System MUST fetch native per-port hourly jitter / latency / loss from `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats?metrics=wan_link_health&port_id={port}&interval=1h`, capturing the `avg_latency`, `avg_jitter`, and `avg_loss` arrays returned by the `wan_link_health` insight metric (type `keyed-timeseries`, scope `device`, `1h` interval, 14-day retention).
- **FR-004**: System MUST render the `wan_link_health` per-port values without any client-side aggregation, without any aggregation-method label, and without any per-peer drilldown UI. The Mist backend has already produced port-level values; this feature surfaces them as-is.
- *(FR-005 removed in cascade rewrite 2026-07-17 — no client-side rollup exists.)*
- *(FR-006 removed in cascade rewrite 2026-07-17 — no aggregation-method label.)*
- *(FR-006a removed in cascade rewrite 2026-07-17 — the zero-peer `"N/A"` wire shape no longer applies; ports without `wan_link_health` telemetry render a plain empty state.)*
- **FR-007**: System MUST render a site-level "Application Health %" tile sourced from `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary`, with a ring benchmark from `.../application-health/threshold` and an hourly classifier breakdown micro-chart sourced from `.../application-health/summary-trend`. Classifiers exposed: `jitter`, `latency`, `loss`, `application-services-application-bandwidth`, `application-services-slow-application`, `application-services-application-disconnects`. When the port modal is open for a site that reports `application-health`, the modal MUST also render (a) a "This port's contribution to Application Health" widget populated from `.../application-health/impacted-interfaces` filtered to the port's `(gateway_hostname, interface_name)` row, and (b) an hourly classifier breakdown chart populated from `.../application-health/summary-trend`. When the site does NOT report `application-health`, the tile and the two per-port widgets render a plain "not reported for this site type" empty state (no error, no substitution notice).
- *(FR-008 removed in cascade rewrite 2026-07-17 — no substitution occurs; Application Health % is a first-class metric.)*
- **FR-009**: All new API calls MUST use the existing 429-handling multi-token rotation wrapper. No new endpoint may bypass that wrapper.
- **FR-010**: System MUST clip requested time ranges to the 14-day 1h-interval retention window and MUST display a visible notice to the operator when clipping occurred. The extended chart modal MUST default the new hourly rollup panels to a 24-hour window on first open, and MUST expose a timeframe selector allowing the operator to extend the range up to 7 days without leaving the modal.
- **FR-011**: The existing per-port CSV export MUST remain unchanged. A NEW "Export Hourly Metrics" button MUST be added inside the extended chart modal that produces a SEPARATE CSV with one row per port per hour bucket and the following columns in this exact order: `site_name`, `gateway_name`, `port_id`, `hour_epoch`, `hour_iso`, `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps`, `jitter_avg_ms`, `latency_avg_ms`, `loss_avg_pct`.
- **FR-012**: The existing 7-day Rx/Tx byte-count display and its chart modal MUST continue to work unchanged. The new hourly view MUST be additive and MUST be delivered as new panels appended below the current RX/TX chart inside the SAME existing chart modal, in this order: (a) existing RX/TX rate + data-transferred charts unchanged; (b) new hourly Avg+Peak Rx/Tx chart from the `tx_bps,rx_bps,max_tx_bps,max_rx_bps` insight-metric endpoint; (c) new hourly jitter/latency/loss chart from the native `wan_link_health` insight metric; (d) new Application Health per-port contribution widget + hourly classifier breakdown chart (when the site reports `application-health`). The one-click workflow from a port row to the modal MUST be preserved.
- *(FR-013 removed in cascade rewrite 2026-07-17 — no aggregation explainer needed.)*
- *(FR-014 removed in cascade rewrite 2026-07-17 — no `"N/A"` CSV mapping.)*
- **FR-015**: The empty-state UI for a port with no utilization data MUST state that no utilization was reported in the window — it MUST NOT display an error.
- **FR-016**: The system MUST NOT attempt to call or surface data from the Premium Analytics / Snowflake dashboard; that path has no public REST API and is explicitly out of scope.
- **FR-017**: The system MUST NOT introduce new authentication, authorization, or RBAC beyond the tokens already configured for the existing wrapper.
- **FR-018**: Implementation MUST remain within the current Python/Flask stack; no rewrite to Node or an alternate framework is in scope.

### Key Entities

- **WAN Port**: A physical or logical uplink on an SSR/SVR gateway identified by `(site_id, device_id, port_id)`. Anchors all per-port metrics in this feature.
- **Hourly Utilization Sample**: A 1h bucket for one WAN port containing `avg_rx_bps`, `peak_rx_bps`, `avg_tx_bps`, `peak_tx_bps`, and its UTC timestamp.
- **Hourly Port WAN Link Health**: A 1h bucket for one WAN port containing `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` as returned by the `wan_link_health` insight metric. No aggregation label, no peer count.
- **Site Application Health**: A site-level response containing the tile percentage from `application-health/summary`, the SLE goal from `application-health/threshold`, the hourly classifier breakdown from `application-health/summary-trend`, and the per-port impacted-interfaces list from `application-health/impacted-interfaces`. When the site does not report `application-health`, an `available: false` marker replaces the data payload.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can open any SSR WAN port with traffic in the last 14 days and see hourly Avg + Peak Rx/Tx within 5 seconds of clicking the port row, for at least 95% of clicks under normal API conditions.
- *(SC-002 removed in cascade rewrite 2026-07-17 — no aggregation to reconcile.)*
- *(SC-003 removed in cascade rewrite 2026-07-17 — no peer breakdown drilldown to reach.)*
- *(SC-004 removed in cascade rewrite 2026-07-17 — no `aggregation_method` CSV column to enforce; the FR-011 column list is enforced by the CSV writer.)*
- **SC-005**: 100% of API calls introduced by this feature route through the existing 429-handling multi-token wrapper, verified by code review and by observing token rotation under induced 429 pressure.
- **SC-006**: When the customer audits the implementation against the Mist WAN Insights (SSR) dashboard, every displayed number can be traced to a specific documented endpoint listed in this spec. No client-side aggregation exists in the MVP.
- **SC-007**: The existing 7-day Rx/Tx byte-count display continues to render for every gateway that rendered it before this feature, with no regressions in load time or content.
- **SC-008**: The Application Health % tile is visible on the site view without scrolling for at least 95% of desktop viewport widths at or above 1280 px on first paint.

## Assumptions

- The target deployment is SSR/SVR gateways; SRX behavior is not the target of this feature, though the `application-health` SLE endpoints return data on SRX sites as well and this feature will render that data naturally when the site type reports it.
- The existing multi-token 429 rotation wrapper is the correct integration point for all new API calls; no changes to that wrapper are required.
- The Mist API's 1h-interval retention of 14 days is a hard limit; no attempt will be made to backfill or cache older data beyond what the live API returns.
- All new hourly data is UTC-anchored as returned by the API; the UI may present a local-time hint but exports MUST remain UTC.
- The existing gateway/port dashboard already exposes the `(site_id, device_id, port_id)` context that new views need — no new discovery pass is required.
- Application Health % is available via the live Mist REST API on the customer's SSR site type (verified against the customer's own live capture); non-SSR site types that do not report `application-health` render a plain "not reported for this site type" placeholder.

## Out of Scope

- Reproducing the Mist Premium Analytics / Snowflake dashboard's cross-site historical trends, longer-window smoothing, or other Snowflake-only surfaces — no public REST API exists.
- Per-application drilldown from Application Health (`.../application-health/impacted-applications`) — reachable and documented as a future add, but not surfaced in the MVP.
- SLE distribution histogram from Application Health (`.../application-health/histogram`) — reachable and documented as a future add, but not surfaced in the MVP.
- Any addition of, or change to, authentication or RBAC.
- Any rewrite of the current Python/Flask app to another stack.
- Extending retention beyond the API's 14-day 1h-interval window (no caching layer for older hourly data).

## Changelog / Corrections

- **Rev 2026-07-17 cascade**: Removed peer-rollup framing (FR-005, FR-006, FR-006a, FR-013, FR-014, SC-002, SC-003, SC-004) because jitter / latency / loss are returned natively per port by the `wan_link_health` insight metric. No client-side aggregation, no per-peer fanout, no `aggregation_method` label, no `peer_count` field.
- **Rev 2026-07-17 cascade**: Removed WAN Link Health substitution framing (FR-008, prior US3 substitution notice, prior SC-008 substitution-visibility assertion) because Application Health % is a first-class Mist SLE metric available via the live REST API on SSR sites. FR-007 rewritten to describe the four `application-health` SLE endpoints (summary, summary-trend, impacted-interfaces, threshold) that back the tile and the per-port modal widgets.
- Both corrections were established by direct verification against the live Mist API and against the Mist UI's own network trace. See `docs/customer_response_wan_insights.md` §4 for the full changelog.
