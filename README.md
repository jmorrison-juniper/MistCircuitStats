# MistCircuitStats

A Flask web application that displays Gateway WAN port statistics for every gateway in a Juniper Mist organization.

![License](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)

---

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Mist API Endpoints](#mist-api-endpoints)
- [HTTP Routes](#http-routes)
- [Quality Gates](#quality-gates)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- Gateway WAN port statistics for the entire organization (org-wide fan-out, cached & paginated)
- Interactive time-series charts — click any RX/TX cell in the main table
- Chart timeframes: **1h · 6h · 24h · 7d**, with sub-hourly `10m` buckets for the 1h view
- Site & gateway search / filter
- Per-port detail: config type (DHCP / static), VLAN, MAC, speed, uptime, counters, VPN peer paths
- **WAN Insights panel** — per-port hourly Rx/Tx (avg + peak), native `wan_link_health` jitter / latency / loss, native Application Health SLE
- WAN Insights timeframes: **1h · 6h · 24h · 3d · 7d**
- CSV export for the main gateway table **and** per-port hourly metrics (canonical 12-column layout)
- Multi-token support with automatic **429 rate-limit rotation** (60 s per-token backoff)
- Responsive dark-theme UI
- Multi-architecture Docker (amd64 / arm64)

---

## Quick Start

### Prerequisites

- **Python 3.13+** (enforced by `pyproject.toml` and the CI matrix)
- Juniper Mist API token(s) with read access to Org, Sites, Device Statistics, Insights, and Site SLE
- Docker / Podman (optional, for container deployment)

### Local Development

```bash
# 1. Clone
git clone https://github.com/jmorrison-juniper/MistCircuitStats.git
cd MistCircuitStats

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
cp .env.example .env                # then edit .env with your Mist token(s)

# 5. Run
python app.py
```

Then open <http://localhost:5000>.

### Docker (published image)

```bash
cp .env.example .env                # edit as above
docker compose up -d
```

Image: `ghcr.io/jmorrison-juniper/mistcircuitstats:latest`
Base: `python:3.13-slim` · non-root · gunicorn · `HEALTHCHECK` on `/health` every 30 s.

### Docker (build locally)

```bash
docker compose -f docker-compose.dev.yml up -d
```

### Podman

```bash
podman-compose up -d
# or
podman run -d -p 5000:5000 --env-file .env ghcr.io/jmorrison-juniper/mistcircuitstats:latest
```

---

## Configuration

### Environment variables

| Variable        | Required | Default          | Description                                              |
| --------------- | -------- | ---------------- | -------------------------------------------------------- |
| `MIST_APITOKEN` | Yes      | —                | Mist API token(s) — comma-separated for multiple tokens  |
| `MIST_ORG_ID`   | No       | *auto-detect*    | Organization ID                                          |
| `MIST_HOST`     | No       | `api.mist.com`   | Mist API host                                            |
| `PORT`          | No       | `5000`           | Web server port                                          |
| `LOG_LEVEL`     | No       | `INFO`           | Logging level (`DEBUG` also enables Flask debug mode)    |

### Mist API hosts

| Region    | Host                |
| --------- | ------------------- |
| Global    | `api.mist.com`      |
| EU        | `api.eu.mist.com`   |
| GovCloud  | `api.gc1.mist.com`  |

### Multiple API tokens (rate-limit protection)

Configure comma-separated tokens to avoid 429s. When one token is rate-limited, the app switches to the next and applies a **60-second per-token backoff**.

```bash
# Single token
MIST_APITOKEN=your_token_here

# Multiple tokens
MIST_APITOKEN=token1,token2,token3
```

> All tokens must belong to the same organization.

### Required API permissions

- Read — Organization and Sites
- Read — Device Statistics (gateways)
- Read — Insights (WAN Insights bandwidth + `wan_link_health`)
- Read — Site SLE (Application Health)

---

## Architecture

```text
MistCircuitStats/
├── app.py                      # Flask entry point + WAN Insights routes
├── mist_connection.py          # Mist API wrapper (mistapi SDK)
├── templates/
│   └── index.html              # Single-page UI (chart modal, WAN Insights)
├── requirements.txt            # Flask, mistapi, gunicorn, python-dotenv
├── pyproject.toml              # Python >= 3.13 + tool configs
├── Dockerfile                  # python:3.13-slim, non-root, gunicorn
├── docker-compose.yml          # Runs the published GHCR image
├── docker-compose.dev.yml      # Local build
├── .github/workflows/          # Quality Gates, Auto-merge, Build & push
└── README.md
```

---

## Mist API Endpoints

Every Mist call goes through the `mistapi` Python SDK. Each call is wrapped by a shared 429 handler that marks the current token with a 60 s cooldown and rotates to the next available token; paginated list calls use `mistapi.get_all(limit=1000)`.

> All 429 responses are handled transparently: the current token is marked with a 60 s cooldown and the next available token is used. If every token is exhausted, callers receive `success: true, rate_limited: {…}` with empty arrays — never a 429 exception.

<details open>
<summary><b>1. <code>getSelf</code> — discover org(s) the token can access</b></summary>

**Path:** `mistapi.api.v1.self.self.getSelf`
Also used to **auto-detect `org_id`** at startup when `MIST_ORG_ID` is not set — the first `privileges[].org_id` wins.
</details>

<details>
<summary><b>2. <code>getOrg</code> — basic org metadata</b></summary>

**Path:** `mistapi.api.v1.orgs.orgs.getOrg`
Name, created / updated time. Displayed in the UI header.
</details>

<details>
<summary><b>3. <code>listOrgSites</code> — list all sites</b></summary>

**Path:** `mistapi.api.v1.orgs.sites.listOrgSites`
Paginated with `limit=1000`. **Cached in-process for 300 s** (`SITES_CACHE_TTL`) to avoid a full re-fetch on every page load.
</details>

<details>
<summary><b>4. <code>getOrgInventory</code> — resolve <code>deviceprofile_id</code> / <code>site_id</code> per gateway</b></summary>

**Path:** `mistapi.api.v1.orgs.inventory.getOrgInventory` (`type="gateway"`)
Batched — one call per page render instead of one per gateway. Its output is what decides Hub vs Spoke config resolution (see #5 vs #6).
</details>

<details>
<summary><b>5. <code>getOrgDeviceProfile</code> — Hub gateway config</b></summary>

**Path:** `mistapi.api.v1.orgs.deviceprofiles.getOrgDeviceProfile`
WAN port names, static IPs, VLANs for **Hub** gateways.
Called only for gateways whose `deviceprofile_id` refers to a device profile. **Cached per profile for 600 s** (`PROFILE_CACHE_TTL`).
</details>

<details>
<summary><b>6. <code>getOrgGatewayTemplate</code> — Spoke / Branch gateway config</b></summary>

**Path:** `mistapi.api.v1.orgs.gatewaytemplates.getOrgGatewayTemplate`
Called only for gateways whose site device record references `gatewaytemplate_id`. Same 600 s cache.
**Split from #5** because Mist stores the two families in different objects.
</details>

<details>
<summary><b>7. <code>listOrgDevicesStats</code> — org-wide gateway devices</b></summary>

**Path:** `mistapi.api.v1.orgs.stats.listOrgDevicesStats` (`type="gateway"`)
Current status, model, version, uptime. Paginated.
Also used with `mac=<12-char tail>` to resolve a single `gateway_id` back to a device record for the port-detail modal.
</details>

<details>
<summary><b>8. <code>searchOrgSwOrGwPorts</code> — org-wide port stats</b></summary>

**Path:** `mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts`
**Uses org scope, not site scope.** WAN ports are filtered client-side by `port_usage == "wan"`.
Chosen over the site-scoped variant because it builds the entire org's port map with one paginated call instead of N-per-site.
</details>

<details>
<summary><b>9. <code>getSiteDevice</code> — site-level device object</b></summary>

**Path:** `mistapi.api.v1.sites.devices.getSiteDevice`
Static-IP overrides that override the profile / template. Called per gateway during page assembly.
</details>

<details>
<summary><b>10. <code>searchSiteDevices</code> — live per-port <code>if_stat</code></b></summary>

**Path:** `mistapi.api.v1.sites.devices.searchSiteDevices` (`type="gateway"`, `mac=`, `stats=True`)
Runtime **DHCP-assigned** IPs / netmasks / `address_mode`.
Only rows with `port_usage == "wan"` and a non-empty `ips[0]` in `"<ip>/<cidr>"` form are consumed. CIDR is converted to dotted-quad for the UI.
</details>

<details>
<summary><b>11. <code>getSiteDeviceStats</code> — detailed per-port stats</b></summary>

**Path:** `mistapi.api.v1.sites.stats.getSiteDeviceStats`
`port_stat` / `if_stat` bytes, packets, errors, speed, MAC, duplex — one gateway. Backs the **Port Details** modal.
Also carries the gateway's `last_seen` timestamp used for the freshness label.
</details>

<details>
<summary><b>12. VPN peer paths — <code>searchOrgPeerPathStats</code></b></summary>

**Path:** `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats` (`org_id`, `site_id=`, `mac=`)

Per-gateway peer-path stats: latency, loss, jitter, MOS, uptime, MTU, hop count per peer.
Results are **grouped by `port_id`** on the client so the UI can render the count next to each WAN port.
</details>

<details>
<summary><b>13. WAN Insights bandwidth — <code>getSiteInsightMetricsForGateway</code></b></summary>

**Path:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` (`site_id`, `device_id`, `metrics="tx_bps,rx_bps,max_tx_bps,max_rx_bps"`, `port_id=`, `interval=`, `start=`, `end=`)

Per-port **bandwidth**, average and peak, both directions.

- `metrics=` is exactly those four names — avg + peak give the WAN Insights chart its "avg vs peak" pair.
- `interval="1h"` is the default; the 1h view sends `interval="10m"` for six buckets.
- Response arrays are aligned to `start + i * interval`.
</details>

<details>
<summary><b>14. WAN link health — <code>getSiteInsightMetricsForDevice</code> (metric=<code>wan_link_health</code>)</b></summary>

**Path:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice` (`site_id`, `metric="wan_link_health"`, `device_mac=`, `port_id=`, `interval=`, `start=`, `end=`)

Native per-port **jitter / latency / loss**.

- **The `wan_link_health` insight is *device*-scoped, not gateway-scoped.** The metric name is the second positional argument, and `device_mac = device_id.replace("-", "")[-12:]` (12-character lowercase tail, no separators). This is why it goes through the `ForDevice` SDK function, not `ForGateway`.
- Response payloads use top-level `avg_latency` / `avg_jitter` / `avg_loss` arrays; older shapes (nested `wan_link_health` dict / list) are tolerated.
</details>

<details>
<summary><b>15. Application Health SLE — <code>getSiteSleSummaryTrend</code></b></summary>

**Path:** `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`, `start=`, `end=`)

Native **Application Health SLE** — the summary percentage *and* the hourly trend both derive from this single payload.

> **Non-obvious API quirk:** the standard `getSiteSleSummary` function returns HTTP 400 (`"unknown"`) for the `application-health` metric on the target org. `getSiteSleSummaryTrend` returns 200 with `sle.samples.{total, degraded, value}` arrays instead.
> The app computes `summary_pct = 100 * (Σtotal − Σdegraded) / Σtotal` and uses `values[]` (falling back to per-bucket `(total-degraded)/total`) for the trend.
> The SDK function does not accept an `interval` argument (Mist's API default of 3600 s applies).
</details>

<details>
<summary><b>16. SLE impacted interfaces — <code>listSiteSleImpactedInterfaces</code></b></summary>

**Path:** `mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`, `start=`, `end=`)

Gateways × WAN interfaces contributing to SLE degradation. Surfaced per-port so the WAN Insights panel can flag "impacted" for the current port.
</details>

<details>
<summary><b>17. SLE threshold — <code>getSiteSleThreshold</code></b></summary>

**Path:** `mistapi.api.v1.sites.sle.getSiteSleThreshold` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`)

Configured SLE goal (e.g. `95`). Displayed next to the summary %. `null` when the SLE is not configured on the site.
</details>

<details>
<summary><b>18. Legacy chart traffic — <code>getSiteInsightMetricsForGateway</code> (RX/TX only)</b></summary>

**Path:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` (`site_id`, `gateway_id`, `metrics="rx_bps,tx_bps"`, `port_id=`, `interval=`, `start=`, `end=`)

Backs the click-a-cell chart popup on the main gateway table.
Kept alongside #13 because the chart modal wants a lighter single-metric-pair series at sub-hourly buckets (default 600 s). Reached through the `MistConnection.get_gateway_port_traffic_series` wrapper.
</details>

---

## HTTP Routes

Public JSON routes served by `app.py`:

| Method | Route                                                                        | Description                                       |
| ------ | ---------------------------------------------------------------------------- | ------------------------------------------------- |
| GET    | `/`                                                                          | Main dashboard page                               |
| GET    | `/health`                                                                    | Container health probe                            |
| GET    | `/api/organization`                                                          | Current org info (SDK #2)                         |
| GET    | `/api/organizations`                                                         | Orgs the token can access (SDK #1)                |
| GET    | `/api/sites`                                                                 | Site list (SDK #3)                                |
| GET    | `/api/gateways`                                                              | Gateway summary + WAN port map (SDK #3–#10)       |
| GET    | `/api/gateway/<gateway_id>/ports`                                            | Per-port stats for one gateway (SDK #7 + #11)     |
| GET    | `/api/gateway/<gateway_id>/port/<port_id>/traffic`                           | Legacy chart-modal traffic (REST #18)             |
| GET    | `/api/gateway/<gateway_id>/vpn_peers`                                        | VPN peer paths grouped by port (REST #12)         |
| GET    | `/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly`        | Hourly bandwidth + WLH + SLE slice (REST #13–#17) |
| GET    | `/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly/export` | CSV export (12 canonical columns)                 |
| GET    | `/api/v1/sites/<site_id>/application-health-summary`                         | Site Application Health SLE                       |

**Query parameters**

- `/api/gateways` — `site_id`, `duration ∈ {15m, 1h, 1d, 7d}`
- WAN Insights routes — `duration ∈ {1h, 6h, 24h, 3d, 7d}` (HTTP 400 otherwise). The `1h` view is served at `interval=10m` (600 s); every other window uses `1h` (3600 s).

**CSV export columns (canonical 12-column layout):**

```
site_name, gateway_name, port_id,
hour_epoch, hour_iso,
rx_avg_bps, rx_peak_bps, tx_avg_bps, tx_peak_bps,
jitter_avg_ms, latency_avg_ms, loss_avg_pct
```

### Known limitations (WAN Insights)

- **14-day retention window** — start times older than 14 days are clipped server-side. Response includes `clipped: true` and a `retention_notice` string.
- **Application Health SLE is native on SSR** — sites without the SLE return `summary_pct: null`, `threshold_pct: null`, `trend: []`, `impacted_interfaces: []`.
- **Rate limits never fail the request** — the endpoint returns HTTP 200 with `success: true` and per-section `rate_limited: {bandwidth, wan_link_health, app_health}` flags. The UI shows a banner and preserves the last successful data.

---

## Quality Gates

CI runs on every push to `main` and every PR via `.github/workflows/quality-gates.yml`. All gates must pass:

| Gate                 | Tool          | Threshold / Notes                                                                                    |
| -------------------- | ------------- | ---------------------------------------------------------------------------------------------------- |
| Lint                 | `ruff`        | Selects `E, F, W, I, UP, B`. `E402` ignored (env-var load ordering in `app.py`).                     |
| Format               | `black`       | Line length 120, `target-version = py313`.                                                            |
| Security             | `bandit`      | `-ll` (medium+); excludes `.github`, `.specify`, `docs`, `specs`, `templates`.                       |
| CVE scan             | `pip-audit`   | Runs against `requirements.txt`.                                                                     |
| Complexity           | `radon`       | Cyclomatic complexity **≤ 15** per function (hard fail above).                                       |
| Dead code            | `vulture`     | Minimum confidence 90.                                                                                |
| Docstring coverage   | `interrogate` | **≥ 90 %** (`fail-under = 90` in `pyproject.toml`).                                                   |
| Docstring quality    | `pydoclint`   | Google style. `arg-type-hints-in-signature = true`, `skip-checking-short-docstrings = true`.          |

**Auto-issue automation on `main`:** failing gates open a `bug,ci,quality-gate` issue (one per failing gate); passing gates auto-close the corresponding open issue with a completion comment.

### Docstring policy

Every public and private function, method, class, and module must have a docstring. First line is a short summary; a `Why:` line follows for anything non-trivial; parameters, returns, and raises use Google-style sections. The `interrogate` gate enforces the ≥ 90 % floor.

---

## Troubleshooting

**Connection issues**

1. Verify your API token is correct and not expired
2. Confirm `MIST_HOST` matches your Mist cloud region
3. Ensure network connectivity to the Mist API

**No gateways showing**

- Verify your organization has gateways deployed
- Check the browser console for JavaScript errors
- Set `LOG_LEVEL=DEBUG` to see verbose application logs

**Chart issues**

- Ensure the gateway is actively reporting statistics
- Confirm WAN ports have recent traffic data
- Verify the selected timeframe has available metrics
- For the 1h view, the port must have samples in the last hour (10-minute buckets)

**WAN Insights returns empty jitter / latency / loss**

- `wan_link_health` requires the WAN link to be actively probing (typically SSR / SRX with SLA probes). Non-probed circuits return empty arrays.
- Sites without the Application Health SLE configured return `summary_pct: null` — expected on non-SSR sites.

---

## Contributing

Contributions are welcome — issues and pull requests both. All PRs must pass the quality gates listed above.

## License

Licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0)**.
See [LICENSE](LICENSE) for full details.

## Author

Joseph Morrison &lt;jmorrison@juniper.net&gt;

## Related Projects

- [MistGuestAuthorizations](https://github.com/jmorrison-juniper/MistGuestAuthorizations) — Mist Guest WiFi Pre-Authorization Portal
- [MistSiteDashboard](https://github.com/jmorrison-juniper/MistSiteDashboard) — Mist Site Health Dashboard
- [MistHelper](https://github.com/jmorrison-juniper/MistHelper) — Mist API Helper Tools

---

Made with ❤️ for the Juniper Mist community
