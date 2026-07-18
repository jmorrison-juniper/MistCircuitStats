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

This section explains **every request the dashboard sends to the Mist cloud**.
It is written for network engineers who are new to Python or to the Mist API.
You do **not** need to read the source code to understand what is happening here.

If a word in this section is new to you, check the glossary directly below
before reading the endpoint list.

### Glossary (read this first)

- **API** — Application Programming Interface. A way for one computer program
  to ask another computer program a question and get an answer. In our case,
  the dashboard asks Mist for information and Mist replies with data.
- **Endpoint** — One specific web address at Mist that answers one specific
  question. For example, "list every site in my organization" is one
  endpoint, and "give me the WAN statistics for one gateway" is a different
  endpoint. The dashboard uses 18 endpoints in total.
- **Request** — When the dashboard asks an endpoint for information, that is
  called making a request. When Mist answers, that is called the response.
- **SDK** — Software Development Kit. `mistapi` is a Python library provided
  by Juniper. It already knows the correct web address of every Mist endpoint.
  Our code calls a Python function like `getSelf()` and the SDK sends the
  network request for us. You do not need to build the URL yourself.
- **Token (or API token)** — Your secret key for the Mist API. You put it in
  the `.env` file when you install the dashboard. Every request the dashboard
  sends includes this token so that Mist knows who is asking. If someone
  steals your token they can read your Mist data, so do not share it.
- **Rate limit / "HTTP 429"** — Mist counts how many requests each token
  sends per minute. If a token asks too much, Mist replies with an error
  called "429 Too Many Requests". This does **not** mean the token is broken.
  It only means "please wait a moment and try again". The dashboard handles
  this for you: if you configured more than one token in `MIST_APITOKEN`, it
  waits 60 seconds on the tired token and switches to the next one
  automatically. This is called **token rotation**.
- **Pagination** — Some Mist answers are very large, for example when you ask
  for every gateway in a big organization. To keep responses fast, Mist splits
  the answer into pages. Page 1 might contain the first 1,000 items, page 2
  the next 1,000, and so on. The dashboard uses a helper called
  `mistapi.get_all(limit=1000)` that reads every page for you and joins the
  results together into one list.
- **Cache / TTL** — After the dashboard reads certain data (like the list of
  sites), it keeps a copy in memory. The next time the same information is
  needed, it uses the copy instead of asking Mist again. This makes the page
  load much faster. **TTL** ("Time To Live") is how long the copy stays
  valid, measured in seconds. When the TTL expires, the next request goes
  back to Mist to get a fresh copy.
- **Org / Site / Device (the three levels of Mist)** — Mist organizes
  everything into three levels:
  - **Org** (organization) is the top level. Usually one company = one org.
  - **Site** is one physical location, for example one branch office or one
    retail store. An org contains many sites.
  - **Device** is one piece of hardware, for example one gateway or one
    switch. A site contains many devices.
  Some endpoints work at the org level, some at the site level, and some at
  the device level. The dashboard prefers org-level endpoints when they exist
  because one org-level request replaces many site-level requests.
- **Gateway** — The WAN router at a site. This is usually a Juniper SSR or an
  SRX firewall. The main table in the dashboard shows one row per gateway.
- **WAN port** — One physical uplink on a gateway that connects to the
  internet or to a WAN circuit (MPLS, LTE, broadband, etc.). A gateway
  typically has between 1 and 4 WAN ports.
- **MAC address** — The hardware address of a device, written as 12 hex
  characters (like `5c5b350a1b2c`). Some Mist endpoints identify a device by
  its full ID (with dashes, like `00000000-0000-0000-1000-5c5b350a1b2c`) and
  others by only the last 12 characters of that ID with the dashes removed.
  When the dashboard has to convert one to the other you will see the code
  `device_id.replace("-", "")[-12:]`.
- **Insight** — A Mist analytics feature. Insights already do the math
  (averages, peaks, jitter, latency, loss) on Mist's side, so the dashboard
  only reads the numbers and draws them.
- **SLE** — Service Level Expectation. A Mist score, from 0 to 100 percent,
  that says how well a service is working compared to what was configured as
  "good enough". This dashboard uses the **Application Health SLE** which
  measures how well applications are reaching users through each WAN
  interface.

### How the dashboard talks to Mist (one paragraph)

Every request goes through the `mistapi` Python SDK. Every request is wrapped
by the same short program (called a "handler") that watches for the HTTP 429
error. If a 429 arrives, the handler puts the current token to sleep for 60
seconds and tries the next token you listed in `MIST_APITOKEN`. If **all**
tokens are on cooldown, the handler does not raise an error to the browser.
Instead the response comes back as `success: true` with an empty list of data
and a flag `rate_limited: {...}` set to `true`. The web page shows a small
banner and keeps the last data it had. This way, a temporary rate limit
never crashes the page.

### The 18 endpoints

Each entry below follows the same pattern:

- **What it does** — plain-language description
- **Why the dashboard needs it** — which feature uses this information
- **What comes back** — the fields you actually see
- **When it runs** — how often, and whether the answer is cached
- **Notes** — anything else worth knowing

The first entry is expanded by default so you can see the pattern; click any
other title to expand it.

<details open>
<summary><b>1. <code>getSelf</code> — find out which organizations your token can read</b></summary>

**SDK function:** `mistapi.api.v1.self.self.getSelf`

**What it does:** Asks Mist a very simple question: "who am I, and which
organizations does this token have access to?"

**Why the dashboard needs it:** Before the dashboard can list any sites or
gateways, it must know **which** organization to look inside. Some Mist
tokens give access to more than one organization at the same time. This
endpoint returns a list of organizations, and the dashboard picks one of
them.

**What comes back:** Your user information (name, email) and a list called
`privileges`. Each entry in `privileges` contains an `org_id` (the unique
identifier of one organization) and the level of access you have to it
(read, write, admin).

**When it runs:** Exactly one time, right after the dashboard starts up. The
result is not called again during normal use.

**Notes:**
- If your `.env` file has `MIST_ORG_ID=` set to a specific value, the
  dashboard uses that value and this endpoint's answer is only used to
  confirm you have access.
- If `MIST_ORG_ID` is empty, the dashboard picks the **first** `org_id` in
  the list. If your token has access to more than one org, this may not be
  the org you want. In that case, set `MIST_ORG_ID` explicitly.

</details>

<details>
<summary><b>2. <code>getOrg</code> — read the organization's name and creation date</b></summary>

**SDK function:** `mistapi.api.v1.orgs.orgs.getOrg`

**What it does:** Asks for basic information about one specific organization.

**Why the dashboard needs it:** The organization name is displayed at the top
of the page ("You are viewing: **Acme Corporation**"). The creation and last
updated dates are shown in the tooltip.

**What comes back:** The org's display name, when it was created, and when
its settings were last changed.

**When it runs:** Once when the dashboard first opens. Not repeated on
subsequent page loads unless you switch organizations.

**Notes:** No cache is applied. The response is small (a few hundred bytes),
so caching is not necessary.

</details>

<details>
<summary><b>3. <code>listOrgSites</code> — list every site in the organization</b></summary>

**SDK function:** `mistapi.api.v1.orgs.sites.listOrgSites`

**What it does:** Returns every site (office, branch, store, data center)
that belongs to the organization.

**Why the dashboard needs it:** The **site filter** dropdown on the main
page is built from this list. It is also used to convert a `site_id` (a
long string of numbers and letters) into a human-readable site name
whenever a gateway row is drawn.

**What comes back:** For each site: `id`, `name`, `address`, `country_code`,
`timezone`, and some geographic coordinates.

**When it runs:** The first time a page loads, the dashboard reads the full
list. The list is then **cached in memory for 300 seconds (5 minutes)**.
During those 5 minutes, any page reload uses the cached copy and does not
call Mist again. After 5 minutes the cache expires and the next request
reads a fresh list from Mist.

**Notes:**
- Uses `mistapi.get_all(limit=1000)` so that even organizations with more
  than 1,000 sites are fully listed.
- The 5-minute cache is important. Without it, every page load would call
  this endpoint, which for a large org would waste API quota very quickly.

</details>

<details>
<summary><b>4. <code>getOrgInventory</code> — find which template each gateway is using</b></summary>

**SDK function:** `mistapi.api.v1.orgs.inventory.getOrgInventory` (with `type="gateway"`)

**What it does:** Returns the full inventory of gateways in the organization
and, importantly, tells the dashboard **which configuration source** each
gateway uses:
- Some gateways get their config from a **device profile** (typically Hub
  gateways). These have a `deviceprofile_id`.
- Some gateways get their config from a **gateway template** (typically
  Spoke / Branch gateways). These have a `gatewaytemplate_id`.

**Why the dashboard needs it:** To know **what to ask next**. If a gateway
uses a device profile, the dashboard must call endpoint #5 for the config.
If it uses a gateway template, the dashboard must call endpoint #6. This
inventory endpoint is what tells the dashboard which of the two to use.

**What comes back:** For each gateway: `mac`, `serial`, `model`, `site_id`,
and one of `deviceprofile_id` or `gatewaytemplate_id`.

**When it runs:** Once per page render. The result is used only inside that
single page load and then discarded.

**Notes:** Calling this once **per page** is much cheaper than calling it
once per gateway. In an org with 200 gateways this is a 200x saving.

</details>

<details>
<summary><b>5. <code>getOrgDeviceProfile</code> — read the config of a Hub gateway</b></summary>

**SDK function:** `mistapi.api.v1.orgs.deviceprofiles.getOrgDeviceProfile`

**What it does:** Reads one **device profile**. A device profile is the
configuration template that Mist applies to Hub gateways.

**Why the dashboard needs it:** To display the **WAN port names, static IP
addresses, and VLAN IDs** for each Hub gateway. Without this information the
main table would show only "port 0", "port 1" with no meaning.

**What comes back:** The full device profile, including a list of WAN ports.
For each port: name (like `ge-0/0/0`), static IP if any, VLAN ID if any,
and the `port_usage` field.

**When it runs:** Only for gateways that have a `deviceprofile_id`
(see endpoint #4). The response is **cached per profile for 600 seconds
(10 minutes)**. If 50 Hub gateways share the same device profile, the
dashboard only reads that profile once every 10 minutes, not 50 times.

**Notes:**
- Configuration changes rarely, which is why a longer 10-minute cache is
  safe to use here.
- If your device profile changes and you want the dashboard to pick up the
  change immediately, restart the dashboard. Otherwise you will see the new
  values after the cache expires.

</details>

<details>
<summary><b>6. <code>getOrgGatewayTemplate</code> — read the config of a Spoke / Branch gateway</b></summary>

**SDK function:** `mistapi.api.v1.orgs.gatewaytemplates.getOrgGatewayTemplate`

**What it does:** The same idea as endpoint #5, but for the **gateway
template** object type. This is the configuration template Mist applies to
Spoke and Branch gateways.

**Why the dashboard needs it:** To display the WAN port names, static IPs,
and VLANs for Spoke / Branch gateways.

**What comes back:** The same fields as endpoint #5 (port names, static
IPs, VLANs), but read from a different Mist object type.

**When it runs:** Only for gateways that have a `gatewaytemplate_id`
(see endpoint #4). Same 10-minute cache as endpoint #5.

**Notes:** You may wonder **why there are two endpoints (#5 and #6) that do
almost the same thing**. The reason is that Mist stores Hub gateway
templates and Spoke gateway templates in two different places in its
database. The dashboard has to call whichever one applies to each gateway.

</details>

<details>
<summary><b>7. <code>listOrgDevicesStats</code> — read the current status of every gateway</b></summary>

**SDK function:** `mistapi.api.v1.orgs.stats.listOrgDevicesStats` (with `type="gateway"`)

**What it does:** Returns the **live operational status** of every gateway
in the organization at this moment.

**Why the dashboard needs it:** This is where the columns **Status
(connected / disconnected)**, **Model**, **Firmware version**, and
**Uptime** in the main table come from.

**What comes back:** For each gateway: `mac`, `model`, `version`, `status`,
`uptime`, `last_seen`, and CPU / memory statistics.

**When it runs:** Once per main-table page render.

**Notes:**
- This endpoint is also called a second way: with a `mac=<12-char-tail>`
  filter, to look up **one specific gateway**. This is used when you click
  a gateway row and the **Port Details** modal has to load information for
  just that one device.

</details>

<details>
<summary><b>8. <code>searchOrgSwOrGwPorts</code> — read the current stats of every WAN port in the org</b></summary>

**SDK function:** `mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts`

**What it does:** Returns the **port statistics for every switch and every
gateway port in the whole organization**, in one paginated response.

**Why the dashboard needs it:** This is where the **RX and TX bytes**,
**packets**, **speed**, and **link state** for each WAN port on the main
table come from.

**What comes back:** One row per port. Each row includes the parent device's
`mac`, the port `port_id`, the port role (`port_usage`), and the traffic
counters.

**When it runs:** Once per main-table page render.

**Notes:**
- The dashboard asks for **all** ports (switch **and** gateway), then
  keeps only the rows where `port_usage == "wan"`. The filtering happens on
  our side, not on Mist's side.
- Mist offers a similar site-level endpoint. This endpoint is preferred
  because one org-level call replaces many site-level calls. In an org with
  50 sites this endpoint uses one paginated call instead of 50 separate
  calls.

</details>

<details>
<summary><b>9. <code>getSiteDevice</code> — read the per-site device configuration</b></summary>

**SDK function:** `mistapi.api.v1.sites.devices.getSiteDevice`

**What it does:** Reads the site-level device object for one specific
gateway.

**Why the dashboard needs it:** Some gateways have configuration that is
**overridden at the site level** on top of the profile / template. For
example: the device profile might say "use DHCP on WAN0", but the site-level
override might say "use static IP 10.1.1.1 on WAN0". The site-level object
is where those overrides live.

**What comes back:** The full device configuration for one gateway,
including any per-port static IP or VLAN overrides.

**When it runs:** Once per gateway during page assembly. Not cached, because
overrides are small and per-device.

**Notes:** If a port has a static IP configured at the site level, that
value wins over the profile / template value in the UI.

</details>

<details>
<summary><b>10. <code>searchSiteDevices</code> — read the live per-port DHCP information</b></summary>

**SDK function:** `mistapi.api.v1.sites.devices.searchSiteDevices` (with `type="gateway"`, `mac=`, `stats=True`)

**What it does:** Reads the **live runtime state** of one gateway, including
information about IP addresses that were **assigned by DHCP** (rather than
configured statically).

**Why the dashboard needs it:** If a WAN port is set to DHCP, the dashboard
still wants to display the **current** IP address, netmask, and gateway that
DHCP handed to that port. This endpoint provides those live values.

**What comes back:** A field called `if_stat` that includes each WAN port's
current IP address in `<ip>/<cidr>` form (for example `192.168.1.5/24`), the
address mode (`static`, `dhcp`), and the current mask.

**When it runs:** Once per gateway during page assembly.

**Notes:**
- Only rows where `port_usage == "wan"` and where the IPs list is not
  empty are used.
- The IP is stored as CIDR notation (`192.168.1.5/24`). The dashboard
  converts the `/24` part into the dotted-quad form (`255.255.255.0`) that
  most network engineers are used to seeing.

</details>

<details>
<summary><b>11. <code>getSiteDeviceStats</code> — read the deep stats for one gateway</b></summary>

**SDK function:** `mistapi.api.v1.sites.stats.getSiteDeviceStats`

**What it does:** Reads the **detailed port and interface statistics** for
one specific gateway.

**Why the dashboard needs it:** Powers the **Port Details** popup that opens
when you click on a gateway. This is where you see byte counts, packet
counts, error counts, speed, duplex, link state, and the MAC address on the
other side of the link.

**What comes back:** Two large fields:
- `port_stat` — physical port information (speed, duplex, MAC, errors)
- `if_stat` — logical interface information (bytes in / out, packets in /
  out, current bandwidth)

Also included is the gateway's `last_seen` timestamp, which the dashboard
displays as a **freshness label** ("Last seen 3 seconds ago").

**When it runs:** Only when a user clicks on a gateway row to open the Port
Details popup.

**Notes:** This endpoint is heavier than the others (larger response body),
so it is only called on demand.

</details>

<details>
<summary><b>12. <code>searchOrgPeerPathStats</code> — read VPN peer path health for one gateway</b></summary>

**SDK function:** `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats` (`org_id`, `site_id=`, `mac=`)

**What it does:** Reads the health statistics of every VPN peer path that a
gateway is currently using. A **peer path** is one direction of one VPN
tunnel between two gateways.

**Why the dashboard needs it:** Some deployments use VPN overlays (like AWS
Cloud Interconnect, MPLS-over-VPN, or Mist WAN Assurance overlays). Each
WAN port may carry multiple peer paths simultaneously. The dashboard shows
a **peer count** next to each WAN port, so an operator can see at a glance
how many overlays are healthy.

**What comes back:** One entry per peer path. Each entry includes:
- **latency** (in milliseconds)
- **jitter** (in milliseconds)
- **loss** (as a percentage)
- **MOS** (Mean Opinion Score — a voice-quality metric from 1.0 to 5.0)
- **uptime** in seconds
- **MTU** (maximum transmission unit)
- **hop count** to the peer
- the `port_id` this path is using

**When it runs:** Once per gateway during page assembly.

**Notes:** The dashboard **groups results by `port_id`** on the client side.
This is what lets each WAN port row show its own peer count, even though the
raw Mist response is a flat list of all peers.

</details>

<details>
<summary><b>13. <code>getSiteInsightMetricsForGateway</code> — read hourly WAN bandwidth (WAN Insights panel)</b></summary>

**SDK function:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` (`site_id`, `device_id`, `metrics="tx_bps,rx_bps,max_tx_bps,max_rx_bps"`, `port_id=`, `interval=`, `start=`, `end=`)

**What it does:** Reads the historical **bandwidth** of one WAN port over a
period of time. Returns both the **average** and the **peak** bandwidth in
both directions (transmit and receive).

**Why the dashboard needs it:** Powers the four chart lines in the **WAN
Insights** panel:
- RX average (blue)
- RX peak (light blue)
- TX average (green)
- TX peak (light green)

Together these tell you how much data the WAN port is moving and how bursty
that traffic is.

**What comes back:** Four arrays (`tx_bps`, `rx_bps`, `max_tx_bps`,
`max_rx_bps`), each containing one number per time bucket. The numbers are
in **bits per second**.

**When it runs:** Every time a user opens or refreshes the WAN Insights
panel.

**Notes:**
- The parameter `metrics=` must be spelled exactly `"tx_bps,rx_bps,max_tx_bps,max_rx_bps"`.
- The default `interval` is `"1h"` (one hour per bucket). For the **1 hour**
  view, the dashboard uses `interval="10m"` (ten minutes per bucket) which
  gives you six buckets instead of one, so a short spike is still visible.
- The response arrays line up with the time range: element `i` of the array
  is the bandwidth during the bucket that starts at `start + i * interval`.

</details>

<details>
<summary><b>14. <code>getSiteInsightMetricsForDevice</code> — read hourly jitter / latency / loss (WAN Insights panel)</b></summary>

**SDK function:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice` (`site_id`, `metric="wan_link_health"`, `device_mac=`, `port_id=`, `interval=`, `start=`, `end=`)

**What it does:** Reads the historical **link quality** of one WAN port: how
much jitter, latency, and loss it saw, hour by hour.

**Why the dashboard needs it:** Powers the three quality-line charts in the
**WAN Insights** panel:
- Jitter (in milliseconds)
- Latency (in milliseconds)
- Loss (as a percentage)

These are what tell you whether a WAN link is degrading, even when the
bandwidth chart looks normal.

**What comes back:** Three top-level arrays: `avg_latency`, `avg_jitter`,
`avg_loss`, each with one number per time bucket.

**When it runs:** Every time a user opens or refreshes the WAN Insights
panel, at the same time as endpoint #13.

**Notes (very important):**
- **This endpoint is device-scoped, not gateway-scoped.** In other words,
  Mist identifies the target by the device's **MAC address**, not by its
  gateway ID. If you look at similar dashboards you may see the mistake of
  passing a `gateway_id` here — it will not work.
- The dashboard converts the gateway's UUID into a MAC in one step:
  take the last 12 characters of the UUID, and remove any dashes. In Python
  this is `device_id.replace("-", "")[-12:]`. In pseudo-code:
  ```
  device_id  = "00000000-0000-0000-1000-5c5b350a1b2c"
  device_mac = "5c5b350a1b2c"
  ```
- Older Mist responses used a nested format (a dictionary called
  `wan_link_health`). The dashboard also accepts that older shape, so if
  you migrate from an older Mist version everything keeps working.
- If a WAN link is **not** running active probes (this typically means it is
  not an SSR link and does not have SLA probing turned on), the three arrays
  will be empty. That is expected — it is not a bug.

</details>

<details>
<summary><b>15. <code>getSiteSleSummaryTrend</code> — read the Application Health SLE summary and trend</b></summary>

**SDK function:** `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`, `start=`, `end=`)

**What it does:** Reads the **Application Health SLE** for a whole site. This
is a single percentage number ("this site is meeting its application-health
target 97% of the time") plus a **trend** array showing how that number
changed hour by hour.

**Why the dashboard needs it:** Powers the "**Application Health**" tile in
the WAN Insights panel. The tile shows the current summary percentage and a
small trend chart underneath.

**What comes back:** A `sle` object containing three arrays:
- `total` — how many measurements were taken in each hour bucket
- `degraded` — how many of those measurements failed the SLE
- `value` (optional) — Mist's own pre-computed percentage per bucket

The dashboard then calculates the summary itself:
```
summary_percent = 100 * (sum(total) - sum(degraded)) / sum(total)
```
It uses `value[]` for the trend chart if the array is present, otherwise
it computes each bucket's percentage from `total` and `degraded`.

**When it runs:** Every time a user opens or refreshes the WAN Insights
panel.

**Notes (very important):**
- **Do not use `getSiteSleSummary` for this**. That similarly-named
  function returns an HTTP 400 error ("unknown metric") when you ask for
  `application-health`. Only `getSiteSleSummaryTrend` returns 200 OK with
  usable data. This is a Mist API quirk — the dashboard already knows about
  it and always uses the trend variant.
- This SDK function does **not** accept an `interval` argument. Mist uses
  its own default of 3600 seconds (one hour per bucket) and there is no
  way to override that from the client side. This is fine for our use case.
- Sites that do not have the Application Health SLE turned on will return
  `summary_pct: null`. The dashboard displays a "not configured" message in
  that case.

</details>

<details>
<summary><b>16. <code>listSiteSleImpactedInterfaces</code> — read which WAN interfaces are hurting the SLE</b></summary>

**SDK function:** `mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`, `start=`, `end=`)

**What it does:** Returns the list of specific WAN interfaces on specific
gateways that are dragging the site's Application Health SLE down.

**Why the dashboard needs it:** In the WAN Insights panel, if the port you
are looking at is one of the impacted interfaces, a small **"Impacted"**
badge appears next to the port name. This lets a NOC engineer immediately
see whether the port they are looking at is one of the reasons the site's
SLE percentage is low.

**What comes back:** One row per (gateway, interface) pair that is
contributing to SLE degradation. Each row contains `gateway_hostname`
and `interface_name`.

**When it runs:** Every time a user opens or refreshes the WAN Insights
panel, at the same time as endpoint #15.

**Notes:** The dashboard checks each row against the port you are looking
at. If both the gateway hostname and the interface name match, the port is
marked impacted.

</details>

<details>
<summary><b>17. <code>getSiteSleThreshold</code> — read the SLE goal value for the site</b></summary>

**SDK function:** `mistapi.api.v1.sites.sle.getSiteSleThreshold` (`site_id`, `scope="site"`, `scope_id=site_id`, `metric="application-health"`)

**What it does:** Reads the **target percentage** that the site's
Application Health SLE has been configured to aim for, for example `95`
(meaning "we want application health to be good 95% of the time").

**Why the dashboard needs it:** Shown as **"Target: 95%"** next to the
current summary percentage in the WAN Insights panel. This lets an engineer
see whether the current summary is above or below target.

**What comes back:** A single number (the target percentage) or `null` if
the site does not have an SLE configured.

**When it runs:** Every time a user opens or refreshes the WAN Insights
panel.

**Notes:** If the return value is `null`, the dashboard does not display
the "Target" line at all — it hides the field instead of showing "Target:
null".

</details>

<details>
<summary><b>18. <code>getSiteInsightMetricsForGateway</code> (RX/TX only) — the small chart in the main table</b></summary>

**SDK function:** `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway` (`site_id`, `gateway_id`, `metrics="rx_bps,tx_bps"`, `port_id=`, `interval=`, `start=`, `end=`)

**What it does:** The same SDK function as endpoint #13, but called with
only two metrics (`rx_bps,tx_bps`) instead of four. This gives a lighter,
smaller response.

**Why the dashboard needs it:** Powers the **small pop-up chart** that
appears when you click on any RX or TX cell in the main gateway table. This
is a quick "show me what this port looked like recently" chart, separate
from the deeper WAN Insights panel.

**What comes back:** Two arrays: `rx_bps` and `tx_bps`, each with one number
per time bucket, in bits per second.

**When it runs:** Only when a user clicks a specific RX or TX cell in the
main table.

**Notes:**
- The small chart uses **sub-hourly buckets** by default (600 seconds =
  10 minutes) so short traffic bursts are still visible.
- Internally the dashboard reaches this SDK function through a wrapper
  method `MistConnection.get_gateway_port_traffic_series()`. The wrapper
  makes sure this endpoint benefits from the same 429 handling and token
  rotation as every other endpoint — nothing bypasses that.

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
