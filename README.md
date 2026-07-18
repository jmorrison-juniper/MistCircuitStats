# MistCircuitStats

A Flask web application that displays Gateway WAN port statistics from all gateways in a Juniper Mist organization.

![License](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)

## Features

- 📊 Gateway WAN port statistics for the entire organization (org-wide fan-out, cached and paginated)
- 📈 Interactive time-series charts (click any RX/TX cell to open)
- ⏱️ In-chart timeframe filtering: **1 hour, 6 hours, 24 hours, 7 days** (chart modal)
- 📐 Dynamic resolution: sub-hourly buckets (`10m`) for the 1h view, hourly (`1h`) otherwise
- 🌐 Organization-wide gateway overview with site and gateway search/filter
- 📱 Responsive dark theme UI with T-Mobile magenta accents
- 🎯 Per-port detail: config type (DHCP/static), VLAN, MAC, speed, uptime, counters, VPN peer paths
- 📥 CSV export for the gateway table (all displayed columns, including peer-path counts)
- 📡 **WAN Insights panel** — per-port hourly Rx/Tx (avg + peak), native `wan_link_health` jitter / latency / loss, and the site's native Application Health SLE. Timeframes: **1h / 6h / 24h / 3d / 7d**. Per-port hourly CSV export (canonical 12-column layout).
- 🛡️ Multi-token support with automatic 429 rate-limit rotation across every API call (60s per-token backoff)
- 🐳 Multi-architecture Docker support (amd64/arm64)

## Quick Start

### Prerequisites

- **Python 3.13+** (enforced by `pyproject.toml` `requires-python = ">=3.13"` and the CI matrix)
- Juniper Mist API Token(s) with read access to Org, Sites, and Device Statistics
- (Optional) Docker or Podman for containerized deployment

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/jmorrison-juniper/MistCircuitStats.git
   cd MistCircuitStats
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your Mist API credentials
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

6. **Access the application**
   Open http://localhost:5000 in your browser

### Docker Deployment

#### Option 1: Pull from GitHub Container Registry (Recommended)

```bash
# Configure environment
cp .env.example .env
# Edit .env with your Mist API credentials

# Pull and run
docker compose up -d
```

The container image is available at:
```
ghcr.io/jmorrison-juniper/mistcircuitstats:latest
```

The image is based on `python:3.13-slim` and runs `gunicorn` as a non-root user on port 5000. A `HEALTHCHECK` polls `/health` every 30 s.

#### Option 2: Build Locally

```bash
# Configure environment
cp .env.example .env
# Edit .env with your Mist API credentials

# Build and run locally
docker compose -f docker-compose.dev.yml up -d
```

**Access the application**: Open http://localhost:5000 in your browser

#### Podman Alternative

```bash
podman-compose up -d
# or
podman run -d -p 5000:5000 --env-file .env ghcr.io/jmorrison-juniper/mistcircuitstats:latest
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MIST_APITOKEN` | Yes | - | Mist API token(s) — comma-separated for multiple tokens |
| `MIST_ORG_ID` | No | Auto-detect | Organization ID |
| `MIST_HOST` | No | `api.mist.com` | Mist API host |
| `PORT` | No | `5000` | Web server port |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG` also enables Flask debug mode) |

### Multiple API Tokens (Rate-Limit Protection)

To avoid API rate limiting (429 errors), you can configure multiple API tokens. When one token is rate limited, the application automatically switches to the next available token and applies a **60-second per-token backoff** before retrying that token.

```bash
# Single token
MIST_APITOKEN=your_token_here

# Multiple tokens (comma-separated)
MIST_APITOKEN=token1,token2,token3
```

**Note:** All tokens must belong to the same organization.

### Mist API Hosts
| Region | Host |
|--------|------|
| Global | `api.mist.com` |
| EU | `api.eu.mist.com` |
| GovCloud | `api.gc1.mist.com` |

### Required API Permissions

Your Mist API token needs:
- **Read** access to Organization and Sites
- **Read** access to Device Statistics (gateways)
- **Read** access to Insights (for WAN Insights bandwidth + `wan_link_health`)
- **Read** access to Site SLE (for the Application Health SLE panel)

## Architecture

```
MistCircuitStats/
├── app.py                            # Flask entry point + WAN Insights routes
├── mist_connection.py                # Mist API wrapper (SDK + direct REST)
├── templates/
│   └── index.html                    # Single-page UI (chart modal, WAN Insights panel)
├── requirements.txt                  # Runtime deps: Flask, mistapi, gunicorn, python-dotenv, requests
├── pyproject.toml                    # Python ≥3.13, ruff/black/bandit/interrogate/pydoclint config
├── Dockerfile                        # python:3.13-slim, non-root, gunicorn
├── docker-compose.yml                # Runs the published GHCR image
├── docker-compose.dev.yml            # Local build
├── .github/workflows/quality-gates.yml  # Ruff/Black/Bandit/pip-audit/Radon/Vulture/Interrogate/Pydoclint
└── README.md                         # This file
```

## Mist API Endpoints Used

The application talks to Mist in two ways:

1. **`mistapi` Python SDK** — for endpoints with first-class SDK coverage. Every call uses `mistapi.get_all(...)` for automatic pagination (`limit=1000`) and is wrapped by a shared 429 handler that rotates tokens transparently.
2. **Direct `requests` calls** — for Insights and SLE endpoints not (yet) covered by the SDK. These implement the same 429/token-rotation pattern inline.

### SDK-based endpoints

| # | Endpoint (SDK path) | Purpose | Non-obvious usage notes |
|---|---------------------|---------|-------------------------|
| 1 | `mistapi.api.v1.self.self.getSelf` | Discover the org(s) the token can access | Also used to **auto-detect `org_id`** at startup when `MIST_ORG_ID` is not set — the first `privileges[].org_id` wins. |
| 2 | `mistapi.api.v1.orgs.orgs.getOrg` | Basic org metadata (name, created/updated time) | Displayed in the UI header. |
| 3 | `mistapi.api.v1.orgs.sites.listOrgSites` | List all sites in the org | Paginated with `limit=1000`. **Cached in-process for 300 s** (`SITES_CACHE_TTL`) to avoid a full re-fetch on every page load. |
| 4 | `mistapi.api.v1.orgs.inventory.getOrgInventory` (`type="gateway"`) | Look up `deviceprofile_id` and `site_id` per gateway MAC | Batched — one call per page render instead of one per gateway. Result is the input that decides Hub vs Spoke config resolution (see #5 vs #6). |
| 5 | `mistapi.api.v1.orgs.deviceprofiles.getOrgDeviceProfile` | Fetch **Hub** gateway config (WAN port names, static IPs, VLANs) | Called only for gateways whose `deviceprofile_id` refers to a device profile. **Cached per profile for 600 s** (`PROFILE_CACHE_TTL`). |
| 6 | `mistapi.api.v1.orgs.gatewaytemplates.getOrgGatewayTemplate` | Fetch **Spoke / Branch** gateway config | Called only for gateways whose site device record references `gatewaytemplate_id`. Same 600 s cache. Split from #5 because Mist stores the two families in different objects. |
| 7 | `mistapi.api.v1.orgs.stats.listOrgDevicesStats` (`type="gateway"`) | Org-wide list of all gateway devices with current status, model, version, uptime | Paginated. Also used with `mac=<12-char tail>` to resolve a single `gateway_id` back to a device record for the port-detail modal. |
| 8 | `mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts` | Org-wide port statistics for all switches and gateways in a single call | **Uses org scope, not site scope.** WAN ports are filtered client-side by `port_usage == "wan"`. Chosen over the site-scoped variant because it lets us build the whole org's port map with one paginated call instead of N-per-site. |
| 9 | `mistapi.api.v1.sites.devices.getSiteDevice` | Site-level device object (static-IP overrides that override the profile / template) | Called per gateway during the page assembly. |
| 10 | `mistapi.api.v1.sites.devices.searchSiteDevices` (`type="gateway"`, `mac=`, `stats=True`) | Live per-port `if_stat` including runtime **DHCP-assigned** IPs / netmasks / address_mode | Only rows with `port_usage == "wan"` and a non-empty `ips[0]` in `"<ip>/<cidr>"` form are consumed. The CIDR is converted to dotted-quad for the UI. |
| 11 | `mistapi.api.v1.sites.stats.getSiteDeviceStats` | Detailed per-port stats for one gateway (`port_stat` / `if_stat` bytes, packets, errors, speed, MAC, duplex) | Backs the "Port Details" modal. Also carries the gateway's `last_seen` timestamp used for the freshness label. |

### Direct REST endpoints (called via `requests`)

| # | Endpoint | Purpose | Non-obvious usage notes |
|---|----------|---------|-------------------------|
| 12 | `GET /api/v1/orgs/{org_id}/stats/vpn_peers/search?site_id=&mac=` | Per-gateway VPN peer-path stats (latency / loss / jitter / MOS / uptime / MTU / hop count per peer) | Results are **grouped by `port_id`** on the client so the UI can render the count next to each WAN port. Not exposed by the SDK today, hence direct call. |
| 13 | `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats` with `?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps&port_id=&interval=&start=&end=` | Per-port hourly (or 10-minute) **bandwidth** — average and peak, in both directions | The `metrics=` list is exactly four names — average and peak give the WAN Insights chart its "avg vs peak" pair. `interval=1h` is the default; the 1h chart view sends `interval=10m` for six buckets. Response arrays are aligned to `start + i*interval`. |
| 14 | `GET /api/v1/sites/{site_id}/insights/device/{mac}/wan_link_health` with `?port_id=&interval=&start=&end=` | Native per-port **jitter / latency / loss** for the WAN link | **The `wan_link_health` insight is *device*-scoped, not gateway-scoped**, so the metric name is embedded in the URL path (`.../device/{mac}/wan_link_health`), and `mac` is derived as `device_id.replace("-", "")[-12:]`. Response payloads use the top-level `avg_latency` / `avg_jitter` / `avg_loss` arrays; older shapes (nested `wan_link_health` dict or list) are tolerated. |
| 15 | `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend` with `?interval=&start=&end=` | Native **Application Health SLE** — both the summary percentage *and* the hourly trend derive from this one payload | **Non-obvious API quirk**: the standard `.../metric/application-health/summary` endpoint returns HTTP 400 (`"unknown"`) for the `application-health` metric. `/summary-trend` returns 200 with `sle.samples.{total, degraded, value}` arrays instead. We compute `summary_pct = 100 * (Σtotal − Σdegraded) / Σtotal` and use `values[]` (falling back to per-bucket `(total-degraded)/total`) for the trend. |
| 16 | `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/impacted-interfaces` | Which gateways × WAN interfaces are contributing to SLE degradation | Sub-path of the same SLE root. Results are surfaced per-port so the WAN Insights panel can flag "impacted" for the current port. |
| 17 | `GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/threshold` | Configured SLE goal (e.g. "95 %") for the site | Displayed next to the summary %. `null` when the SLE is not configured on the site. |
| 18 | `GET /api/v1/sites/{site_id}/insights/gateway/{gateway_id}/stats?metrics=rx_bps,tx_bps` | Legacy chart-modal traffic series (RX / TX only) | Used by the click-a-cell chart popup on the main gateway table. Kept alongside the newer #13 call because the chart modal targets a lighter, single-metric-pair series. |

> All Insights and SLE calls funnel through the same 429/token-rotation logic used by the SDK calls: a 429 response marks the current token with a 60 s cooldown, an alternate token is picked if available, and if every token is exhausted the response comes back as `success: true, rate_limited: {...}` with empty arrays. Callers never see a 429 exception.

### App-Exposed HTTP Routes

Public JSON routes served by `app.py`:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Main dashboard page |
| GET | `/health` | Container-orchestration health probe (`{"status":"healthy","timestamp":...}`) |
| GET | `/api/organization` | Current org info (SDK #2) |
| GET | `/api/organizations` | Orgs the token has access to (SDK #1) |
| GET | `/api/sites` | Site list (SDK #3) |
| GET | `/api/gateways?site_id=&duration=15m\|1h\|1d\|7d` | Gateway summary with WAN port map (SDK #3–#10 fan-out) |
| GET | `/api/gateway/<gateway_id>/ports` | Detailed per-port stats for one gateway (SDK #7 + #11) |
| GET | `/api/gateway/<gateway_id>/port/<port_id>/traffic?site_id=&start=&end=&interval=` | Legacy time-series traffic for chart modal (REST #18) |
| GET | `/api/gateway/<gateway_id>/vpn_peers?site_id=&mac=` | VPN peer paths grouped by port (REST #12) |
| GET | `/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly?duration=1h\|6h\|24h\|3d\|7d` | Per-port hourly bandwidth (avg + peak) + native `wan_link_health` J/L/L + per-port slice of Application Health SLE (REST #13, #14, #15–17) |
| GET | `/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly/export?duration=...` | CSV export, canonical 12 columns: `site_name,gateway_name,port_id,hour_epoch,hour_iso,rx_avg_bps,rx_peak_bps,tx_avg_bps,tx_peak_bps,jitter_avg_ms,latency_avg_ms,loss_avg_pct` |
| GET | `/api/v1/sites/<site_id>/application-health-summary?duration=...` | Site-level Application Health SLE (summary %, threshold %, hourly trend, impacted interfaces) |

`duration` for WAN Insights routes is validated against the allow-list `{1h, 6h, 24h, 3d, 7d}`; anything else returns HTTP 400. The 1h view is served at a `10m` (600 s) sample interval; all other windows use `1h` (3600 s).

### Known Limitations (WAN Insights)

- **14-day / 1h-interval retention window** — requested start times older than 14 days are clipped server-side. When clipping happens, the response sets `clipped: true` and includes a `retention_notice` string that the UI surfaces above the charts.
- **Application Health SLE is native on SSR** — sites without the SLE configured (typically non-SSR sites) return `summary_pct: null`, `threshold_pct: null`, `trend: []`, `impacted_interfaces: []`. No substitute metric is computed.
- **Rate-limit handling never fails the request** — if every configured token is in cool-down, the endpoint still returns HTTP 200 with `success: true` and per-section `rate_limited: {bandwidth, wan_link_health, app_health}` flags. The UI shows a "temporarily rate-limited" banner and preserves the last successful data.

## Quality Gates

CI runs on every push to `main` and every pull request via `.github/workflows/quality-gates.yml`. All gates must pass:

| Gate | Tool | Threshold / Notes |
|------|------|-------------------|
| Lint | `ruff` | `pyproject.toml` `[tool.ruff.lint]` selects `E, F, W, I, UP, B`. `E402` ignored (env-var load ordering in `app.py`). |
| Format | `black` | Line length 120, `target-version = py313`. |
| Security | `bandit` | `-ll` (medium+); scans everything except `.github`, `.specify`, `docs`, `specs`, `templates`. |
| CVE scan | `pip-audit` | Runs against pinned `requirements.txt`. |
| Complexity | `radon` | Cyclomatic complexity **≤ 15** per function (post-processed in the workflow, hard fail above the threshold). |
| Dead code | `vulture` | Minimum confidence 90. |
| Docstring coverage | `interrogate` | **≥ 90 %** (`fail-under = 90` in `pyproject.toml`). Enforces the DOCS.md policy. |
| Docstring quality | `pydoclint` | Google style. `arg-type-hints-in-signature = true`, `skip-checking-short-docstrings = true`, `skip-checking-raises = true`. |

On `main`, gate failures **auto-open a GitHub issue** labeled `bug,ci,quality-gate` (one per failing gate), and passing gates **auto-close** the corresponding open issue with a completion comment. See the `create_failure_issues` and `close_resolved_issues` jobs in the workflow.

### Docstring policy (per `~/.claude/DOCS.md`)

Every public and private function, method, class, and module must have a docstring. First line is a short summary; a `Why:` line follows for anything non-trivial; parameters, returns, and raises use Google-style sections. The `interrogate` gate enforces the ≥ 90 % floor.

## Troubleshooting

### Connection Issues

1. Verify your API token is correct and has not expired
2. Check that `MIST_HOST` matches your Mist cloud region
3. Ensure network connectivity to the Mist API

### No Gateways Showing

- Verify your organization has gateways deployed
- Check the browser console for JavaScript errors
- Review application logs with `LOG_LEVEL=DEBUG`

### Chart Issues

- Ensure the gateway is actively reporting statistics
- Check that WAN ports have recent traffic data
- Verify the selected timeframe has available metrics
- For the 1h view, confirm the port has samples in the last hour (10-minute buckets)

### WAN Insights returns empty jitter / latency / loss

- `wan_link_health` requires the WAN link to be actively probing (typically SSR/SRX with SLA probes). Non-probed circuits will return empty arrays.
- Sites without the Application Health SLE configured return `summary_pct: null`. This is expected on non-SSR sites.

## Contributing

Contributions are welcome — please submit issues and pull requests. All PRs must pass the quality gates listed above.

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0)**.

See the [LICENSE](LICENSE) file for full details.

## Author

Joseph Morrison <jmorrison@juniper.net>

## Related Projects

- [MistGuestAuthorizations](https://github.com/jmorrison-juniper/MistGuestAuthorizations) - Mist Guest WiFi Pre-Authorization Portal
- [MistSiteDashboard](https://github.com/jmorrison-juniper/MistSiteDashboard) - Mist Site Health Dashboard
- [MistHelper](https://github.com/jmorrison-juniper/MistHelper) - Mist API Helper Tools

---

Made with ❤️ for the Juniper Mist community
