# Changelog

All notable changes to **MistCircuitStats** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres loosely to [Semantic Versioning](https://semver.org/)
during the pre-1.0 phase (breaking changes may still land in minor bumps).

## [Unreleased]

### Added
- **Short-window WAN Insights timeframes.** The per-port hourly WAN Insights
  panel now supports **1h** and **6h** in addition to the existing 24h / 3d /
  7d selections. The 1h view uses a `10m` (600 s) sample interval — six
  buckets — so short-lived events are still visible; every other window keeps
  the `1h` (3600 s) interval. Validated by
  `mist_connection.duration_to_seconds()` and `interval_for_duration()`; the
  allow-list `{1h, 6h, 24h, 3d, 7d}` is enforced by both the JSON hourly route
  and the CSV export route (HTTP 400 otherwise).
- **Interrogate + Pydoclint quality gates.** Two new CI gates enforce the
  docstring policy defined in `~/.claude/DOCS.md`:
  - `interrogate` — minimum **90 %** docstring coverage across every
    function, method, class, and module (excluding `.github`, `.specify`,
    `docs`, `specs`, `templates`).
  - `pydoclint` — Google-style docstring validation
    (`arg-type-hints-in-signature = true`,
    `skip-checking-short-docstrings = true`,
    `skip-checking-raises = true`).
- **Auto-file / auto-close CI issue automation.** On `main`, any failing
  quality gate opens a labelled GitHub issue (`bug,ci,quality-gate`), and a
  subsequent passing run auto-closes the corresponding issue with a
  completion comment. See the `create_failure_issues` and
  `close_resolved_issues` jobs in `.github/workflows/quality-gates.yml`.
- **Auto GitHub release on `main` build.** A successful main-branch build
  now cuts a GitHub release; `gh release create` is allowed to create the
  underlying tag directly so no committer identity is required in CI (#29,
  #30).

### Changed
- **Unified Mist API access under the `mistapi` SDK.** Retired the last 7
  direct-REST call sites in `mist_connection.py` and `app.py` so every Mist
  Cloud call now funnels through `MistConnection._handle_rate_limit_response`
  and inherits the shared multi-token 60-second per-token 429 rotation:
  - `get_vpn_peer_stats` → `searchOrgPeerPathStats`
  - `_insights_gateway_stats` → `getSiteInsightMetricsForGateway`
  - `_insights_device_wan_link_health` →
    `getSiteInsightMetricsForDevice(metric="wan_link_health")`
  - `_sle_app_health_get` → `getSiteSleSummaryTrend` /
    `listSiteSleImpactedInterfaces` / `getSiteSleThreshold`
  - `app.py::get_port_traffic` (legacy chart-modal route) now delegates to a
    new `MistConnection.get_gateway_port_traffic_series` wrapper backed by
    `getSiteInsightMetricsForGateway` — meaning the click-a-cell chart popup
    on the main gateway table finally benefits from shared token rotation
    instead of bypassing it with an inline `requests.get`.

  Response shapes served to `templates/index.html` (both JSON envelopes and
  CSV export columns) remain byte-identical modulo timestamps and rate-limit
  counters. `import requests` is dropped from both files; `requests` remains
  only as a transitive dependency of Flask / `mistapi`.
- **Backfilled docstrings across the codebase** to clear the ≥90 %
  interrogate floor and satisfy pydoclint. Every public and private function
  in `app.py` and `mist_connection.py` now carries a Google-style docstring
  with a summary line and — where non-trivial — a `Why:` explanation of the
  design motivation or non-obvious constraint.
- **README rewrite.** Documented every Mist API endpoint the app calls (11
  SDK-based + 7 direct REST) with a *"Non-obvious usage notes"* column that
  explains the specific metric names, SLE paths, scope quirks, and cache
  TTLs. Added a "Quality Gates" section listing all 8 gates and their
  thresholds, plus a "Docstring policy" subsection. Also corrected several
  stale claims: Python **3.13+** (not 3.9+), the port-stats endpoint is
  `searchOrgSwOrGwPorts` (org-scope, not site-scope), and the
  `wan_link_health` insight is **device-scoped** — not gateway-scoped.
- **CI base bumps.** Upgraded `actions/checkout` 4 → 7 (#27),
  `docker/setup-qemu-action` 3 → 4 (#28), `docker/login-action` 3 → 4 (#25),
  `docker/metadata-action` 5 → 6 (#24), `docker/build-push-action` 5 → 7
  (#23), `github/codeql-action` 3 → 4 (#22).

### Fixed
- Nothing outstanding since the last tagged build.

## [0.1.0] — 2026-07-17

First tagged release; consolidates all pre-release work.

### Added
- **WAN Insights panel (#15).** Per-port hourly Rx / Tx (avg + peak),
  native per-port jitter / latency / loss from the `wan_link_health`
  insight, and the site's native Application Health SLE. Non-obvious
  implementation details:
  - `wan_link_health` is *device*-scoped, not gateway-scoped; the request
    path is `.../insights/device/{mac}/wan_link_health` where
    `mac = device_id.replace("-", "")[-12:]`.
  - The standard `.../sle/.../application-health/summary` endpoint returns
    HTTP 400; the app calls `/summary-trend` and computes
    `summary_pct = 100 * (Σtotal − Σdegraded) / Σtotal` client-side.
  - 14-day retention window is enforced server-side via
    `clip_to_retention_window()`; when clipping happens the JSON payload
    sets `clipped: true` and includes a `retention_notice` string.
  - Per-port CSV export uses the canonical 12-column layout
    (`site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,`
    `rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,`
    `loss_avg_pct`).
- **Multi-token API-key support with automatic 429 rotation** (72542fb,
  99fc5c6, 6fff554). Tokens are supplied comma-separated via
  `MIST_APITOKEN`; any 429 marks the current token with a 60-second cooldown
  and rotates to the next available token. Applied uniformly to every SDK
  call *and* every direct REST call.
- **Loading progress indicator with elapsed-time tracking** (d70b989).
- **VPN peer-path statistics column** with per-port grouping (1cba6ef,
  37f314b, 2b13a82, 9c7f862). Uses the direct REST endpoint
  `GET /api/v1/orgs/{org_id}/stats/vpn_peers/search?site_id=&mac=` — not
  covered by the SDK today.
- **CSV export for the main gateway table** (101d2b2, 8c636a3, 513148a,
  04f7323) with all displayed columns including peer-path counts.
- **Dynamic-resolution traffic chart** (cfdea1f, 959e7e8) — sub-hourly
  buckets for the 1h view, hourly otherwise; responsive design.
- **Interactive time-series chart modal** on the main gateway table
  (f68b78f) — click any RX/TX cell to open. Backed by the legacy
  `/api/gateway/<>/port/<>/traffic` route (single `metrics=rx_bps,tx_bps`
  pair on `/insights/gateway/{device_id}/stats`).
- **Screenshot folder** for repository documentation (ecdb5ac).
- **Mirror of MistHelper CI/CD and quality gates** (#21). Establishes
  ruff, black, bandit, pip-audit, radon (CC ≤ 15), and vulture as the
  initial quality gate baseline.

### Changed
- **Global pagination + rate-limit tracking** (75053fc, e58be6c, a19d431)
  — every paginated endpoint now goes through `mistapi.get_all(limit=1000)`
  and shares a common rate-limit state.
- **60 % API-call reduction** via org-scope calls and per-page batching
  (b0d02e1). `getOrgInventory` is now called once per page render instead
  of once per gateway.
- **Switched to `searchOrgSwOrGwPorts`** (7d07fe9) — org-scope port
  statistics filtered client-side by `port_usage == "wan"`, replacing the
  N-per-site pattern.
- **`mistapi` log levels** dampened (02d20b6) to reduce debug noise.
- **README streamlined** to match the standard repository format (2c159fd)
  and re-updated with the new chart features (959e7e8).

### Fixed
- **`get_gateway_port_stats` device resolution** (#19) — now resolves the
  device via `listOrgDevicesStats` with the 12-character MAC tail instead
  of the previous fragile lookup path.
- **`/api/gateways` HTTP 500** (#18) — dropped unsupported `start`/`end`
  kwargs from the SDK call that surfaced after a `mistapi` update.
- **CI build failure from pinned requirements** (#20) — unpinned
  `requirements.txt` so `pip-audit` and container builds resolve
  compatible transitive versions.
- **`mistapi` method rename** (7e72642) — `listOrgStats` →
  `listOrgDevicesStats`.
- **`load_dotenv()` ordering** (ab6ec95) — environment variables now load
  before `mistapi` is imported (this is the reason `E402` is ignored in
  `pyproject.toml`).
- **Container image tag casing** (652c05e) — force lowercase for GHCR.
- **Workflow tag trigger** (27db1f5) — match the `YY.MM.DD.HH.MM`
  timestamp format used for image tags.
- **VLAN-tagged interface matching** in the peer-paths display (37f314b).
- **Empty uptime column** in CSV export (04f7323).
- **UI display issues** across the gateway table (2dec7dc).

### Security
- **`bandit -ll` (medium+) scan** added as a required gate.
- **`pip-audit`** CVE scan added as a required gate against pinned
  `requirements.txt`.

---

[Unreleased]: https://github.com/jmorrison-juniper/MistCircuitStats/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jmorrison-juniper/MistCircuitStats/releases/tag/v0.1.0
