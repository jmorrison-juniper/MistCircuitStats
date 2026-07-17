# Quickstart: SSR WAN Insights-Equivalent Metrics

**Feature**: `001-wan-insights-metrics`
**Purpose**: End-to-end validation guide proving the feature works against a live SSR org. This is the primary verification artifact for the feature (the project has no automated test harness — see plan.md § Technical Context).

Every scenario below traces to at least one spec requirement or success criterion.

---

## Prerequisites

1. **Live Mist org** with at least one SSR/SVR gateway that has:
   - one WAN port carrying traffic in the last 14 days (for User Story 1),
   - one WAN port with at least one active VPN peer path reporting BFD metrics (for User Story 2),
   - one WAN port with zero VPN peer paths (for FR-006a / FR-014 empty-state validation), and
   - one site reporting the `wan-link-health` SLE (for User Story 3).
2. **Environment variables** set as documented in `.env.example`:
   - `MIST_APITOKEN` — one or more comma-separated tokens (multi-token 429 rotation is required).
   - `MIST_ORG_ID` — optional; auto-detected if omitted.
   - `MIST_HOST` — defaults to `api.mist.com`.
   - `LOG_LEVEL` — set to `DEBUG` when running through scenarios so token rotation is visible in stderr.
3. **No new dependencies**. `requirements.txt` is unchanged; existing `python -m venv .venv && pip install -r requirements.txt` remains the setup path.

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
5. The panel refetches from `GET /api/gateway/<id>/port/<port_id>/hourly?site_id=...&duration=7d` and re-renders. Verify no error, no empty state.
6. From the browser dev-tools network tab, inspect the JSON response:
   - `success: true`, `duration: "7d"`, `interval_seconds: 3600`.
   - `utilization[]` has at least one entry.
   - Each entry has numeric `rx_avg_bps`, `rx_peak_bps`, `tx_avg_bps`, `tx_peak_bps` and a UTC `hour_iso`.
   - `clipped: false` when `end - start < 14 * 86400`.
7. **Empty-utilization case (FR-015)**: repeat step 1 for a WAN port that has never carried traffic in 14 days. Verify the new panel shows the message "no utilization data reported for this port in the requested window" and NOT an error banner.
8. **Clipping case (FR-010)**: manually craft the URL `?duration=7d` at exactly 14 days back from a low-traffic port to confirm the boundary; also craft a `?duration=14d` request (should be rejected as 400 — enum) and confirm the enum guard fires.
9. **SC-001**: time the interval from click to visible chart across ~20 clicks. Confirm at least 19/20 (95%) are ≤ 5 s under normal API conditions.

Expected outcome: FR-001, FR-002 verified via the network payload; FR-012 verified via the modal DOM; SC-001, SC-007 verified via stopwatch.

---

## Scenario 2 — Hourly jitter / latency / loss rollup (User Story 2, P2)

**Traces**: US2 acceptance scenarios 1–5; FR-003, FR-004, FR-005, FR-006, FR-006a, FR-011, FR-013, FR-014; SC-002, SC-003, SC-004, SC-005.

1. Repeat Scenario 1 steps 1–2 for a port with at least one active VPN peer path.
2. Scroll to the third panel: **"Hourly Jitter / Latency / Loss (client-side rollup)"**. Verify Chart.js renders three series (jitter, latency, loss) over hourly buckets.
3. Verify the small "aggregation method" label above the chart reads exactly `simple_mean` (FR-006, SC-002 wire-shape check).
4. Verify the explainer link (FR-013) is present and its target text names the aggregation math ("mean across VPN peer paths reporting in each hour").
5. Hover a series point. Verify a tooltip shows the aggregate value and the `peer_count` for that hour.
6. Click "Show peer breakdown" (drilldown per SC-003). Verify a per-peer table renders with each contributing peer's `avg_latency`, `avg_jitter`, `avg_loss` for the hovered hour. Manually verify:
   - `avg_latency_ms` in the aggregate row equals the arithmetic mean of the per-peer values in the peer breakdown for the same hour, within the tolerance of 1% or 0.1 ms per SC-002.
7. **Empty-peer case (FR-006a, FR-014)**: repeat step 1 for a port with zero VPN peer paths. Verify:
   - The panel renders with `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct` shown as the literal string `"N/A"` — NOT `0`, `0.0`, or blank.
   - The message "no VPN peer paths on this port; jitter/latency/loss are only measured on SVR peer paths" is visible.
   - Utilization (Rx/Tx) for the same port continues to render normally in the Rx/Tx panel above.
   - Network response JSON shows `"avg_latency_ms": "N/A"` (JSON string) and `peer_count: 0` for every hour.
8. **CSV export (FR-011, SC-004)**: click "Export Hourly Metrics". Verify:
   - A file downloads with name matching `hourly_metrics_<gateway>_<port>_<iso>.csv`.
   - Header row is exactly: `site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct,aggregation_method,peer_count`.
   - Every row's `aggregation_method` column equals literal `simple_mean` (SC-004).
   - Zero-peer rows have jitter/latency/loss columns as EMPTY STRING (not `0`, not `null`, not `"N/A"`), per FR-006a.
   - Row count equals the sum of returned hour buckets across the selected port (no silent row loss).
9. **Existing per-port CSV unchanged (SC-004)**: separately, click the pre-existing per-port CSV export button (outside the modal). Verify its column set and row shape are identical to before the feature was merged (visual diff against a saved pre-feature sample).
10. **Rate-limit funnel (FR-009, SC-005)**: with `LOG_LEVEL=DEBUG` and only 1 token configured, throttle the wrapper by manually setting `MistConnection._rate_limited_tokens[<token>] = time.time() + 60` in a debugger. Re-request the port hourly view. Verify the response contains `rate_limited.performance: true` and the frontend renders a "temporarily rate-limited, try again shortly" banner rather than a hard error.

Expected outcome: FR-003 through FR-006a, FR-011, FR-013, FR-014 verified via UI + JSON + CSV inspection; SC-002 verified by hand-recomputation; SC-003 verified via one-click drilldown; SC-004 verified by CSV structure; SC-005 verified by throttling harness.

---

## Scenario 3 — Site-level WAN Link Health % tile (User Story 3, P3)

**Traces**: US3 acceptance scenarios 1–4; FR-007, FR-008, FR-016; SC-008.

1. Load the dashboard, navigate to a site view for an SSR site with `wan-link-health` SLE data available.
2. Verify a new tile labelled "WAN Link Health %" appears in the site view, with a numeric percentage.
3. Hover the tile. Verify a tooltip shows verbatim: `Substituted for Application Health %. True Application Health is AppTrack/AppQoE-based and is not implemented on SSR/SVR gateways; the live Mist API returns HTTP 400 or null for application-health SLE on SSR sites.` (FR-008, Acceptance 3.2).
4. On first render in a fresh browser session, verify an inline body-text substitution notice appears near the tile (using `sessionStorage`). Reload the page in the same session; verify the inline notice is not shown a second time (icon+tooltip remains).
5. Verify the classifier breakdown lists all seven classifiers: `network-jitter`, `network-loss`, `network-latency`, `interface-congestion`, `network-vpn-path-down`, `isp-reachability-arp`, `isp-reachability-dhcp` (FR-007).
6. Inspect the network response for `GET /api/site/<site_id>/wan_link_health`. Verify `available: true`, `hourly[]` non-empty, all seven `classifier_breakdown` keys present in every hour entry.
7. **Unavailable case (Acceptance 3.4)**: request the same route for a site where `wan-link-health` returns HTTP 400 or null upstream. Verify the tile shows an "unavailable" state, the classifier list is still rendered from the fixed key set, and the substitution notice is still visible.
8. **No Snowflake fetch (FR-016)**: confirm the network tab shows NO request to any `application-health` endpoint. The route MUST NOT call it.
9. **SC-008 viewport check**: at 1280 px width, verify the substitution notice is within the same viewport as the tile (no scrolling required).

Expected outcome: FR-007, FR-008, FR-016 verified; SC-008 verified via viewport measurement.

---

## Scenario 4 — Aggregation helper sanity check (`rollup_peer_metrics_simple_mean`)

**Traces**: FR-005, FR-006, FR-006a; SC-002 (deterministic check independent of a live org).

This is a Python snippet, not a UI check. Run from the repo root with the venv active:

```python
from mist_connection import MistConnection

# Two peers, three hours; peer B has no data for hour 2 (peer path churn)
peer_series = {
    "peerA::ge-0/0/1": [
        {"hour_epoch": 1000, "avg_latency": 10.0, "avg_jitter": 1.0, "avg_loss": 0.0},
        {"hour_epoch": 2000, "avg_latency": 20.0, "avg_jitter": 2.0, "avg_loss": 0.1},
        {"hour_epoch": 3000, "avg_latency": 30.0, "avg_jitter": 3.0, "avg_loss": 0.2},
    ],
    "peerB::ge-0/0/2": [
        {"hour_epoch": 1000, "avg_latency": 20.0, "avg_jitter": 2.0, "avg_loss": 0.2},
        # hour 2000 missing on purpose (peer churn)
        {"hour_epoch": 3000, "avg_latency": 40.0, "avg_jitter": 4.0, "avg_loss": 0.4},
    ],
}

# Zero-peer port
empty_series = {}

hours_1000_to_3000 = [1000, 2000, 3000]

# Method is a pure function on the class; instantiate to call it, or call as staticmethod
# depending on final signature.
result = MistConnection.rollup_peer_metrics_simple_mean(peer_series, hours_1000_to_3000)

# hour 1000: mean of (10, 20) = 15.0, peer_count 2
assert result[0]["avg_latency_ms"] == 15.0
assert result[0]["peer_count"] == 2
assert result[0]["aggregation_method"] == "simple_mean"

# hour 2000: only peerA -> mean = 20.0, peer_count 1 (peerB excluded, NOT counted as 0)
assert result[1]["avg_latency_ms"] == 20.0
assert result[1]["peer_count"] == 1

# hour 3000: mean of (30, 40) = 35.0, peer_count 2
assert result[2]["avg_latency_ms"] == 35.0
assert result[2]["peer_count"] == 2

# Zero-peer port over the same window: every hour is N/A
empty_result = MistConnection.rollup_peer_metrics_simple_mean(empty_series, hours_1000_to_3000)
for hour in empty_result:
    assert hour["avg_latency_ms"] == "N/A"
    assert hour["avg_jitter_ms"] == "N/A"
    assert hour["avg_loss_pct"] == "N/A"
    assert hour["peer_count"] == 0
    assert hour["aggregation_method"] == "simple_mean"

print("aggregation sanity check: PASS")
```

Expected outcome: script prints `aggregation sanity check: PASS`. Confirms FR-005, FR-006, FR-006a, spec §Edge Cases §"Peer path churn" (peer B not counted as 0 in hour 2), and SC-002 arithmetic.

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
| SC-002 | Scenario 2 step 6 + Scenario 4 |
| SC-003 | Scenario 2 step 6 (one-click drilldown) |
| SC-004 | Scenario 2 steps 8–9 |
| SC-005 | Scenario 2 step 10 |
| SC-006 | Every scenario traces to a specific endpoint in the contracts/ folder |
| SC-007 | Scenario 1 step 2 + Scenario 5 |
| SC-008 | Scenario 3 step 9 |

## Requirements coverage

| FR | Scenario |
|----|----------|
| FR-001, FR-002 | 1 |
| FR-003, FR-004, FR-005 | 2 |
| FR-006 | 2 (step 3 + step 8) |
| FR-006a | 2 (step 7 + step 8) |
| FR-007, FR-008 | 3 |
| FR-009 | 2 (step 10) — applies to all three routes |
| FR-010 | 1 (step 8) |
| FR-011 | 2 (step 8) |
| FR-012 | 1 (step 2) + 5 |
| FR-013 | 2 (step 4) |
| FR-014 | 2 (step 7) |
| FR-015 | 1 (step 7) |
| FR-016 | 3 (step 8) |
| FR-017, FR-018 | Non-behavioral (verified by code review against plan.md § Technical Context) |

If any scenario step fails, block the release and file a follow-up on the corresponding FR/SC before shipping.
