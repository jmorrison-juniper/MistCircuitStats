# UI screenshot provenance and reproduction

[Landing README](../README.md) | [Detailed guide](guide.md)

## What was captured

The PNGs in [screenshots/](screenshots/) are genuine browser screenshots of the
repository's Flask application and unchanged `templates/index.html`, captured
on 2026-10-04 using headless Microsoft Edge at 1440 x 1100, device scale 1
(the WAN Insights capture uses a taller 1440 x 1500 viewport to show its full section).
The organization, sites, gateways, peer paths, addresses and metrics are
**synthetic demo fixtures**, not customer data. IPs use documentation-only
ranges. The screenshots are not mockups and no DOM content or application
styles were replaced to stage them.

| File | User action / screen |
| --- | --- |
| `dashboard.png` | Open the organization dashboard |
| `port-details.png` | Expand the first gateway |
| `traffic.png` | Click the first port's RX counter |
| `wan-insights.png` | Scroll the same traffic modal to WAN Insights and Application Health |
| `peer-paths.png` | Close the traffic modal and click the first port's peer count |

The capture harness patches `MistConnection` **before importing `app.py`**,
and disables `.env` loading while substituting dummy environment values,
so no SDK session is constructed and no Mist token, `.env` credentials or live
Mist services are used. The real Flask routes serialize the fixture responses.
Chart buckets are generated relative to each route's requested time window;
capture times and chart labels will change on subsequent runs.

All browser requests outside the temporary loopback server are intercepted:
the exact public Bootstrap, Bootstrap Icons and Chart.js dependencies are served
from a local cache; every other external URL is rejected. Missing cache files,
browser errors and blocked unexpected requests fail capture. The temporary
server is stopped when capture finishes or fails.

## Reproduce

From the repository root, use Python 3.13+ and an installed Microsoft Edge.
Playwright is an optional documentation tool, not a runtime dependency or a
requirement for the offline test suite.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt playwright
mkdir -p .venv/screenshot-assets
```

Prepare the public UI asset cache once while online (these are library downloads,
not calls to Mist). Alternatively copy these exact files into the cache from an
existing trusted installation.

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css -o .venv/screenshot-assets/bootstrap.min.css
curl -fsSL https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js -o .venv/screenshot-assets/bootstrap.bundle.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css -o .venv/screenshot-assets/bootstrap-icons.css
curl -fsSL https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2 -o .venv/screenshot-assets/bootstrap-icons.woff2
curl -fsSL https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff -o .venv/screenshot-assets/bootstrap-icons.woff
curl -fsSL https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js -o .venv/screenshot-assets/chart.umd.js
```

Capture can now run offline without credentials. It updates the five PNGs in
`docs/screenshots/`; it does not change the production application:

```bash
.venv/bin/python docs/capture_screenshots.py --assets .venv/screenshot-assets
```

Review the resulting images before committing. Documentation regression tests
check the landing section names, local Markdown links and fragments, PNG
structure/dimensions, and fixture-backed Flask API contracts:

```bash
.venv/bin/python -m pytest -q tests/test_documentation.py
```
