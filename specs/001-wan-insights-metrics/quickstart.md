# Quickstart: SSR WAN Insights-Equivalent Metrics

**Feature**: `001-wan-insights-metrics`
**Purpose**: End-to-end validation guide proving the feature works against a live SSR org. This is the primary verification artifact for the feature (the project has no automated test harness — see plan.md § Technical Context and research.md § D-12).

Every scenario below traces to at least one spec requirement or success criterion.

> **Rev 2026-07-17 cascade**: Scenario 2 has been rewritten to validate the native `wan_link_health` insight metric (no peer discovery, no rollup, no `"N/A"` sentinel). Scenario 3 has been rewritten to validate the real native Mist Application Health SLE (no substitution, no proxy tile, no session-storage notice). The pre-cascade Scenario 4 (aggregation helper sanity check) has been REMOVED because the aggregation helper no longer exists. Scenario numbering after Scenario 3 is preserved so cross-references from spec/tasks stay stable.

---

## Prerequisites

1. **Live Mist org** with at least one SSR/SVR gateway that has:
   - one WAN port carrying traffic in the last 14 days (for User Story 1),
   - one WAN port for which the API reports `wan_link_health` telemetry in the window (for User Story 2),
   - one WAN port for which the API reports NO `wan_link_health` telemetry in the window (for the plain empty-state validation on the performance panel), and
   - one site reporting the `application-health` SLE (for User Story 3).
2. **Environment variables** set as documented in `.env.example`:
   - `MIST_APITOKEN` — one or more comma-separated tokens (multi-token 429 rotation is required).
   - `MIST_ORG_ID` — optional; auto-detected if omitted.
   - `MIST_HOST` — defaults to `api.mist.com`.
   - `LOG_LEVEL` — set to `DEBUG` when running through scenarios so token rotation is visible in stderr.
3. **SDK bumped to `mistapi>=0.63.3`** per T000 in `tasks.md`. `pip show mistapi` should print `>= 0.63.3`.

---

## Setup

From the repo root:

```
python -m venv .venv
. .venv/bin/activate           # or `.venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

Copy `.env.example` -> `.env` and fill in real values.

Start the Flask dev server:

```
python app.py
```

Open `http://localhost:5000/` in a desktop browser at a viewport width ≥ 1280 px (SC-008).

---

## Scenario 1 — Hourly Rx/Tx utilization (User Story 1, P1)

**Traces**: US1 acceptance scenarios 1–4; FR-001, FR-002, FR-010, FR-012, FR-015; SC-001, SC-007.

1. Load the dashboard, navigate to the site holding the SSR gateway, click a WAN port row that has carried traffic in the last 14 days.
2. The existing chart modal opens. Verify — **the existing RX/TX rate chart and data-transferred chart render exactly as before** (SC-007, FR-012 pre-condition).
3. Scroll below the existing charts. Verify a **new "Hourly Avg + Peak Rx/Tx" Chart.js panel** appears below the existing charts, defaulting to a 24-hour window (FR-010).
4. Verify the timeframe selector inside the new panel exposes `24h`, `3d`, `7d` buttons. Click `7d`.
5. The panel refetches from `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly?duration=7d` and re-renders. Verify no error, no empty state.
6. From the browser dev-tools network tab, inspect the JSON response:
   - `success: true`, `interval: 3600`.
   - `hourly[]` has at least one entry.
   - Each entry has numeric `tx_bps`, `rx_bps`, `max_tx_bps`, `max_rx_bps` and a UTC `hour_iso`.
   - `clipped: false` when `end - start < 14 * 86400`.
7. **Empty-utilization case (FR-015)**: repeat step 1 for a WAN port that has never carried traffic in 14 days. Verify the new panel shows the message "no utilization data reported for this port in the requested window" and NOT an error banner.
8. **Clipping case (FR-010)**: manually craft a `?duration=7d` URL for a port with a low-traffic tail to confirm the clip boundary; also craft a `?duration=14d` request (should be rejected as HTTP 400 — enum) and confirm the enum guard fires.
9. **SC-001**: time the interval from click to visible chart across ~20 clicks. Confirm at least 19/20 (95%) are ≤ 5 s under normal API conditions.

Expected outcome: FR-001, FR-002 verified via the network payload; FR-012 verified via the modal DOM; SC-001, SC-007 verified via stopwatch.

---

## Scenario 2 — Hourly jitter / latency / loss (User Story 2, P2)

**Traces**: US2 acceptance scenarios; FR-003, FR-004, FR-011; SC-005.

Per-port jitter / latency / loss is the **native `wan_link_health` insight metric**. There is NO peer discovery, NO fanout, NO client-side rollup, NO `aggregation_method` label, NO `peer_count`, NO `"N/A"` sentinel.

1. Repeat Scenario 1 steps 1–2 for a port for which the API reports `wan_link_health`.
2. Scroll to the third panel: **"Hourly Jitter / Latency / Loss"**. Verify Chart.js renders three series (jitter, latency, loss) over hourly buckets.
3. Verify there is **no "aggregation method" label** above the chart, **no `simple_mean` string anywhere** in the panel, and **no peer-breakdown drilldown**. Tooltip on a series point shows the raw hourly value only — no `peer_count`.
4. Inspect the JSON response for `GET /api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly?duration=24h` in the network tab. Verify:
   - `hourly[]` rows each carry `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` as numbers (or `null` for hours where the upstream slot was missing).
   - The response contains NO `peers`, NO `peer_breakdown`, NO `aggregation_method`, NO `peer_count`, NO `empty_performance` fields (all removed by the 2026-07-17 cascade).
5. **Empty performance case**: repeat step 1 for a WAN port that reports no `wan_link_health` telemetry in the window (for example, a direct-internet uplink with no measured link-health). Verify:
   - The panel renders the plain empty state "no jitter/latency/loss data reported for this port in the requested window".
   - The response JSON has `avg_latency_ms` / `avg_jitter_ms` / `avg_loss_pct` as `null` (or absent) on every row — NOT the literal string `"N/A"`.
   - The bandwidth (Rx/Tx) panel above continues to render normally for the same port.
6. **CSV export (FR-011)**: click "Export Hourly Metrics". Verify:
   - A file downloads with name matching `hourly_metrics_<gateway_hostname>_<port_id>_<iso>.csv`.
   - Header row is exactly (12 columns): `site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct`.
   - There is NO `aggregation_method` column, NO `peer_count` column, NO `site_id` column.
   - Rows for hours where `wan_link_health` was not reported have the three performance columns as EMPTY STRING (not `0`, not `null`, not `"N/A"`).
   - `hour_epoch` is UTC seconds at the hour boundary even if the UI shows a local-time hint; `hour_iso` is the matching UTC ISO 8601 (`YYYY-MM-DDTHH:00:00Z`).
   - Row count equals the sum of returned hour buckets across the selected port (no silent row loss).
7. **Existing per-port CSV unchanged**: separately, click the pre-existing per-port CSV export button (outside the modal). Verify its column set and row shape are identical to before the feature was merged (visual diff against a saved pre-feature sample).
8. **Rate-limit funnel (FR-009, SC-005)**: with `LOG_LEVEL=DEBUG` and only 1 token configured, throttle the wrapper by manually setting `MistConnection._rate_limited_tokens[<token>] = time.time() + 60` in a debugger. Re-request the port hourly view. Verify the response contains `rate_limited.wan_link_health: true` (or `rate_limited.bandwidth: true`, as applicable) and the frontend renders a "temporarily rate-limited, try again shortly" banner rather than a hard error. Also verify NO peer-discovery request appears in the network tab (there is no fanout).

Expected outcome: FR-003, FR-004, FR-011 verified via UI + JSON + CSV inspection; SC-005 verified by throttling harness. No aggregation math, no substitution — the port panel is a direct rendering of the native `wan_link_health` metric.

---

## Scenario 3 — Site-level Application Health % tile (User Story 3, P3)

**Traces**: US3 acceptance scenarios; FR-007, FR-016; SC-008.

Application Health % is the **native Mist Application Health SLE on SSR**. There is NO substitution, NO proxy tile, NO session-storage-gated banner, NO substitution notice text.

1. Load the dashboard, navigate to a site view for an SSR site with `application-health` SLE data available.
2. Verify a new tile labelled exactly **"Application Health %"** appears in the site view, with a numeric percentage. Verify there is **no asterisk, no info-icon substitution notice, no inline "substituted for..." body text**. The label is literal.
3. Verify a small hourly micro-chart appears below the tile, driven by the site `summary-trend` at 1h interval.
4. Optionally verify an "SLE goal: X%" line/ring derived from the site `threshold` value (when the site exposes one).
5. Inspect the JSON response for `GET /api/v1/sites/<site_id>/application-health-summary?duration=24h`. Verify:
   - `summary_pct` is a number and `threshold_pct` is a number (or `null` if the site doesn't expose a threshold).
   - `trend[]` is a non-empty list of `{timestamp, pct}` rows.
   - `impacted_interfaces[]` is present (possibly empty); when non-empty, each row has `interface_name`, `gateway_hostname`, `gateway_mac`, `duration`, `degraded`, `total`.
   - The response body has NO `substitution_notice` field, NO `classifier_breakdown` per-sample keys (Mist aggregates the six classifiers server-side into every `pct` value), NO `available` field.
6. **Unavailable case**: request the same route for a site where all four `application-health` upstream endpoints return HTTP 400 or null. Verify:
   - The route returns HTTP 200 with `summary_pct: null`, `threshold_pct: null`, `trend: []`, `impacted_interfaces: []`.
   - The tile shows an "Application Health unavailable for this site" state.
   - There is NO substitution notice text, NO fallback tile, NO session-storage flag written to `window.sessionStorage`.
7. **Per-port strip in the modal**: open a WAN port on the same site inside the chart modal (Scenario 1 step 1). Verify a small "This port's contribution to Application Health" strip appears near the bottom of the modal, driven by the `port_app_health` (`{summary_pct, threshold_pct}`) and `hourly_app_health` (`[{timestamp, pct}]`) fields on the `/hourly` response.
8. **No Snowflake / Premium Analytics fetch (FR-016)**: confirm the network tab shows requests ONLY to `.../sle/site/.../metric/application-health/{summary,summary-trend,impacted-interfaces,threshold}` for this tile. No `insights/...` fallback, no `wan-link-health` substitute call, no Snowflake endpoint.
9. **SC-008 viewport check**: at 1280 px width, verify the tile and its micro-chart are visible in the same viewport as the rest of the site header (no scrolling required).

Expected outcome: FR-007 verified end-to-end from the four native SLE endpoints; FR-016 verified by the network tab (no substitute call); SC-008 verified via viewport measurement. The tile is a first-class native metric, not a proxy.

---

## Scenario 4 — (removed)

*The pre-cascade Scenario 4 "Aggregation helper sanity check" has been removed. The `rollup_peer_metrics_simple_mean` helper no longer exists — per-port jitter/latency/loss is sourced from the native `wan_link_health` insight metric with no client-side aggregation. There is no pure function left in the feature to sanity-check offline. See research.md § D-2 / D-12 for the rationale.*

---

## Scenario 5 — Regression: existing dashboard unchanged

**Traces**: FR-012, SC-007.

1. Before pulling this feature branch, capture screenshots of:
   - the gateway list view,
   - the port-row click -> chart modal (existing RX/TX rate + data-transferred charts only),
   - the existing per-port CSV export file.
2. After pulling this feature branch and starting the app, repeat those three interactions.
3. Verify:
   - Gateway list view is visually identical.
   - Chart modal opens on the same one-click workflow. Existing RX/TX rate + data-transferred charts render identically. **New panels appear BELOW them, never above.**
   - The existing per-port CSV file is byte-identical (excluding timestamp of export).

Expected outcome: FR-012 and SC-007 verified as no-regression.

---

## Success criteria coverage

| SC | Scenario |
|----|----------|
| SC-001 | Scenario 1 step 9 |
| SC-005 | Scenario 2 step 8 |
| SC-006 | Every scenario traces to a specific endpoint in the contracts/ folder |
| SC-007 | Scenario 1 step 2 + Scenario 5 |
| SC-008 | Scenario 3 step 9 |

## Requirements coverage

| FR | Scenario |
|----|----------|
| FR-001, FR-002 | 1 |
| FR-003, FR-004 | 2 |
| FR-007 | 3 |
| FR-009 | 2 (step 8) — applies to all three routes |
| FR-010 | 1 (step 8) |
| FR-011 | 2 (step 6) |
| FR-012 | 1 (step 2) + 5 |
| FR-015 | 1 (step 7) |
| FR-016 | 3 (step 8) |
| FR-017, FR-018 | Non-behavioral (verified by code review against plan.md § Technical Context) |

If any scenario step fails, block the release and file a follow-up on the corresponding FR/SC before shipping.

---

## Changelog

- **2026-07-17 cascade rewrite**: Scenario 2 rewritten for native `wan_link_health` (removed peer discovery, rollup, `"N/A"` sentinel, `aggregation_method` label, `peer_count`, peer-breakdown drilldown, and the SC-002/SC-003/SC-004 hand-recompute steps that depended on aggregation math). Scenario 3 rewritten for the real native Mist Application Health SLE (removed substitution notice, `wan-link-health` proxy tile, seven-classifier list, `available` field, session-storage-gated banner, and the SC-008 substitution-notice viewport check). Scenario 4 (aggregation sanity check) deleted — the helper no longer exists; the section header is preserved as a one-line stub so cross-references to "Scenario 5" remain stable. Success-criteria and requirements coverage tables trimmed to the surviving FR/SC set. Ground-truth source: `docs/customer_response_wan_insights.md`.
