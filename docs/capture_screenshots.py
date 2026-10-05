"""Capture the real Flask UI using synthetic Mist responses and cached CDN assets."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css": "bootstrap.min.css",
    "/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js": "bootstrap.bundle.min.js",
    "/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css": "bootstrap-icons.css",
    "/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2": "bootstrap-icons.woff2",
    "/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff": "bootstrap-icons.woff",
    "/npm/chart.js@4.4.0/dist/chart.umd.js": "chart.umd.js",
}


def demo_samples(start: int, end: int, interval: int) -> list[dict]:
    """Build synthetic bandwidth and link-health buckets for a requested window."""
    return [
        {
            "timestamp": timestamp,
            "hour_iso": datetime.fromtimestamp(timestamp, UTC).isoformat(),
            "rx_bps": 18_000_000 + (index % 6) * 3_000_000,
            "tx_bps": 6_000_000 + (index % 4) * 2_000_000,
            "max_rx_bps": 42_000_000 + (index % 6) * 4_000_000,
            "max_tx_bps": 16_000_000 + (index % 4) * 3_000_000,
            "avg_latency_ms": 22 + index % 5,
            "avg_jitter_ms": 2 + (index % 4) * 0.5,
            "avg_loss_pct": (index % 3) * 0.1,
        }
        for index, timestamp in enumerate(range(start, end, interval))
    ]


def demo_connection() -> Mock:
    """Create a strict fake Mist connection; no SDK session or credentials are used."""
    from mist_connection import MistConnection

    fake = Mock(spec=MistConnection)
    sites = [{"id": "demo-site-1", "name": "Demo Seattle"}, {"id": "demo-site-2", "name": "Demo Austin"}]
    port = {
        "name": "ge-0/0/0",
        "wan_name": "Broadband",
        "description": "Demo primary circuit",
        "enabled": True,
        "up": True,
        "gateway": "192.0.2.1",
        "ip": "192.0.2.10",
        "netmask": 24,
        "type": "dhcp",
        "override": "no",
        "rx_bytes": 94_500_000_000,
        "tx_bytes": 21_200_000_000,
    }
    gateways = [
        {
            "id": f"demo-gateway-{index}",
            "name": name,
            "site_id": site["id"],
            "site_name": site["name"],
            "model": "SSR120",
            "status": "connected",
            "ip": f"198.51.100.{index}",
            "mac": f"02000000000{index}",
            "uptime": 86400 * (index + 2),
            "num_ports": 2,
            "ports": [
                port.copy(),
                {
                    **port,
                    "name": "ge-0/0/1",
                    "wan_name": "LTE backup",
                    "description": "Demo backup circuit",
                    "ip": "203.0.113.10",
                    "gateway": "203.0.113.1",
                    "rx_bytes": 1_200_000_000,
                    "tx_bytes": 450_000_000,
                },
            ],
        }
        for index, (name, site) in enumerate(
            [("demo-seattle-edge", sites[0]), ("demo-austin-edge", sites[1]), ("demo-seattle-lab", sites[0])], 1
        )
    ]
    peers = [
        {
            "vpn_name": "Demo corporate overlay",
            "peer_router_name": "demo-hub",
            "peer_port_id": f"ge-0/0/{index}",
            "type": "overlay",
            "up": True,
            "is_active": index == 0,
            "latency": 24.5 + index * 8,
            "loss": 0.05,
            "jitter": 2.1 + index,
            "mos": 4.4,
            "uptime": 172800,
            "mtu": 1500,
            "hop_count": 3,
        }
        for index in range(2)
    ]
    fake.get_organization_info.return_value = {"org_name": "Offline Demo Organization"}
    fake.get_sites.return_value = sites
    fake.get_gateway_stats.return_value = gateways
    fake.get_gateway_port_stats.return_value = {"gateway_name": gateways[0]["name"]}
    fake.get_vpn_peer_stats.return_value = {
        "success": True,
        "peers_by_port": {"ge-0/0/0": peers, "ge-0/0/1": peers[:1]},
    }
    fake.get_gateway_port_traffic_series.side_effect = lambda _site, _device, _port, start, end, interval: {
        "success": True,
        "data": {key: [sample[key] for sample in demo_samples(start, end, interval)] for key in ("rx_bps", "tx_bps")}
        | {"timestamps": list(range(start, end, interval))},
    }
    fake.get_gateway_hourly_bandwidth.side_effect = lambda _site, _device, _port, start, end, **kwargs: {
        "samples": demo_samples(start, end, kwargs["interval_seconds"]),
    }
    fake.get_gateway_hourly_wan_link_health.side_effect = fake.get_gateway_hourly_bandwidth.side_effect
    fake.get_site_application_health.side_effect = lambda _site, start, end, **kwargs: {
        "success": True,
        "summary_pct": 98.4,
        "threshold_pct": 95.0,
        "impacted_interfaces": [],
        "trend": [
            {"timestamp": ts, "pct": 97 + index % 3}
            for index, ts in enumerate(range(start, end, kwargs["interval_seconds"]))
        ],
    }
    return fake


def capture(asset_dir: Path) -> None:
    """Run a loopback-only app and capture five user screens without live API calls."""
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    sys.path.insert(0, str(ROOT))
    # Patch before importing app so its module-level constructor cannot read .env or contact Mist.
    with (
        patch("mist_connection.MistConnection", return_value=demo_connection()),
        patch("dotenv.load_dotenv", return_value=False),
        patch.dict(os.environ, {"MIST_APITOKEN": "offline-demo", "MIST_ORG_ID": "offline-demo", "LOG_LEVEL": "INFO"}),
    ):
        import app as application

    for filename in ASSETS.values():
        if not (asset_dir / filename).is_file():
            raise FileNotFoundError(f"Missing cached asset: {asset_dir / filename}")

    server = make_server("127.0.0.1", 0, application.app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    failures = []

    def route_request(route) -> None:
        """Serve cached public UI dependencies and reject every non-loopback request."""
        url = urlparse(route.request.url)
        if url.netloc == urlparse(base_url).netloc:
            route.continue_()
        elif url.netloc == "cdn.jsdelivr.net" and url.path in ASSETS:
            route.fulfill(path=str(asset_dir / ASSETS[url.path]))
        else:
            failures.append(f"Blocked external request: {route.request.url}")
            route.abort()

    output = ROOT / "docs" / "screenshots"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            page.route("**/*", route_request)
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.on("console", lambda message: failures.append(message.text) if message.type == "error" else None)
            page.goto(base_url)
            page.locator("#gatewayContainer").wait_for(state="visible")
            page.locator(".peer-paths-badge").first.wait_for(state="attached")
            page.screenshot(path=str(output / "dashboard.png"))
            page.locator("#gateway-row-0").click()
            page.locator("#details-row-0.show").wait_for()
            page.screenshot(path=str(output / "port-details.png"))
            page.locator("#details-row-0 .traffic-cell").first.click()
            page.wait_for_function("currentWanInsightsData !== null && wiAppHealthTrendInstance !== null")
            page.wait_for_timeout(1000)  # Wait for Chart.js animations to finish.
            page.locator("#chartModal").screenshot(path=str(output / "traffic.png"))
            page.set_viewport_size({"width": 1440, "height": 1500})
            page.locator("#chartModal").evaluate("(element) => { element.scrollTop = element.scrollHeight; }")
            page.wait_for_timeout(400)
            page.locator("#chartModal").screenshot(path=str(output / "wan-insights.png"))
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.locator("#chartModal").evaluate("(element) => { element.scrollTop = 0; }")
            page.locator(".chart-modal-close").click()
            page.locator("#details-row-0 .peer-paths-badge").first.click()
            page.locator("#peerPathsModal.show").wait_for()
            page.wait_for_timeout(400)  # Bootstrap modal transition.
            page.screenshot(path=str(output / "peer-paths.png"))
            browser.close()
        if failures:
            raise RuntimeError("\n".join(failures))
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path, help="Directory containing cached public CDN assets")
    capture(parser.parse_args().assets.resolve())
