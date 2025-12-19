# MistCircuitStats

A Flask web application that displays Gateway WAN port statistics from all gateways in a Juniper Mist organization.

![License](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)

## Features

- 📊 Real-time gateway WAN port statistics with 7-day history
- 📈 Interactive time-series charts (click any RX/TX cell to view)
- ⏱️ In-chart timeframe filtering: 1 hour, 6 hours, 24 hours, 7 days
- 📐 Dynamic resolution: optimal data granularity per view (5min → 1hr intervals)
- 🌐 Organization-wide gateway overview
- 📱 Responsive dark theme UI with T-Mobile magenta accents
- 🔍 Search and filter by site or gateway name
- 🎯 Per-port detailed statistics and configuration
- 📥 CSV export with peer path counts
- 🐳 Multi-architecture Docker support (amd64/arm64)

## Quick Start

### Prerequisites

- Python 3.9+
- Juniper Mist API Token with appropriate permissions
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
| `MIST_APITOKEN` | Yes | - | Mist API token(s) - comma-separated for multiple tokens |
| `MIST_ORG_ID` | No | Auto-detect | Organization ID |
| `MIST_HOST` | No | `api.mist.com` | Mist API host |
| `PORT` | No | `5000` | Web server port |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Multiple API Tokens (Rate Limit Protection)

To avoid API rate limiting (429 errors), you can configure multiple API tokens. When one token is rate limited, the application automatically switches to the next available token.

```bash
# Single token
MIST_APITOKEN=your_token_here

# Multiple tokens (comma-separated)
MIST_APITOKEN=token1,token2,token3
```

**Note:** All tokens must have access to the same organization.

### Mist API Hosts
| Region | Host |
|--------|------|
| Global | `api.mist.com` |
| EU | `api.eu.mist.com` |
| GovCloud | `api.gc1.mist.com` |

### Required API Permissions

Your Mist API token needs the following permissions:
- **Read** access to Organization and Sites
- **Read** access to Device Statistics

## Architecture

```
MistCircuitStats/
├── app.py                 # Flask application entry point
├── mist_connection.py     # Mist API connection module
├── templates/
│   └── index.html         # Main web UI
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container build file
├── docker-compose.yml     # Docker compose configuration
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
└── README.md              # This file
```

## Troubleshooting

### Connection Issues

1. Verify your API token is correct and has not expired
2. Check the `MIST_HOST` matches your Mist cloud region
3. Ensure network connectivity to the Mist API

### No Gateways Showing

- Verify your organization has gateways deployed
- Check the browser console for JavaScript errors
- Review application logs with `LOG_LEVEL=DEBUG`

### Chart Issues

- Ensure the gateway is actively reporting statistics
- Check that WAN ports have recent traffic data
- Verify the selected timeframe has available metrics

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0)**.

See the [LICENSE](LICENSE) file for full details.

## Mist API Endpoints Used

This application uses the following Juniper Mist API endpoints via the `mistapi` Python SDK:

| API Endpoint | Method | Description |
|--------------|--------|-------------|
| `mistapi.api.v1.self.self.getSelf` | GET | Get current API token info and privileges |
| `mistapi.api.v1.orgs.orgs.getOrg` | GET | Get organization details |
| `mistapi.api.v1.orgs.sites.listOrgSites` | GET | List all sites in organization |
| `mistapi.api.v1.sites.sites.getSiteInfo` | GET | Get individual site details |
| `mistapi.api.v1.orgs.stats.listOrgDevicesStats` | GET | List gateway device statistics |
| `mistapi.api.v1.sites.stats.searchSiteSwOrGwPorts` | GET | Search WAN port statistics |
| `mistapi.api.v1.sites.devices.getSiteDevice` | GET | Get gateway configuration (static IPs) |
| `mistapi.api.v1.sites.devices.searchSiteDevices` | GET | Get runtime interface stats (DHCP IPs) |
| `mistapi.api.v1.orgs.devices.searchOrgDevices` | GET | Search devices by criteria |
| `/api/v1/sites/{site_id}/insights/gateway/{device_id}/stats` | GET | Port-specific time-series traffic data |

> **Note**: Time-series charts use the Mist Insights API directly for windowed bandwidth metrics with parameters: `port_id`, `start`, `end`, `interval`, `metrics=rx_bps,tx_bps`

## Author

Joseph Morrison <jmorrison@juniper.net>

## Related Projects

- [MistGuestAuthorizations](https://github.com/jmorrison-juniper/MistGuestAuthorizations) - Mist Guest WiFi Pre-Authorization Portal
- [MistSiteDashboard](https://github.com/jmorrison-juniper/MistSiteDashboard) - Mist Site Health Dashboard
- [MistHelper](https://github.com/jmorrison-juniper/MistHelper) - Mist API Helper Tools

---

Made with ❤️ for the Juniper Mist community
