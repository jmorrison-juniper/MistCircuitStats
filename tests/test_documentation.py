"""Regression checks for landing documentation and offline screenshot fixtures."""

import re
import struct
import zlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from docs.capture_screenshots import demo_connection

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = {"dashboard", "port-details", "traffic", "wan-insights", "peer-paths"}


def markdown_headings(text: str) -> list[str]:
    """Extract headings without treating fenced shell comments as headings."""
    unfenced = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.findall(r"^#{1,6} (.+)$", unfenced, flags=re.MULTILINE)


def test_landing_readme_sections() -> None:
    """Keep substantive landing content within the six required sections."""
    text = (ROOT / "README.md").read_text()
    assert markdown_headings(text) == ["MistCircuitStats", "What", "How", "Where", "When", "Why", "Who"]
    assert "synthetic offline demo" in text
    images = re.findall(r"!\[[^\]]+\]\(docs/screenshots/([a-z-]+)\.png\)", text)
    assert set(images) == SCREENSHOTS


def test_local_documentation_links() -> None:
    """Require local Markdown links and fragments to resolve after documentation moves."""
    documents = [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]
    for document in documents:
        for link in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", document.read_text()):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            assert target.exists(), f"{document.name}: missing {link}"
            if parsed.fragment:
                anchors = {
                    re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                    for heading in markdown_headings(target.read_text())
                }
                assert unquote(parsed.fragment) in anchors, f"{document.name}: missing fragment {link}"


def test_screenshots_are_valid_pngs() -> None:
    """Validate complete PNG chunks, checksums, image data and useful UI dimensions."""
    for name in SCREENSHOTS:
        image = (ROOT / "docs" / "screenshots" / f"{name}.png").read_bytes()
        assert image[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", image[16:24])
        assert width >= 1000 and height >= 600
        position = 8
        compressed = bytearray()
        last_type = None
        while position < len(image):
            length = struct.unpack(">I", image[position : position + 4])[0]
            chunk_type = image[position + 4 : position + 8]
            chunk_data = image[position + 8 : position + 8 + length]
            checksum = struct.unpack(">I", image[position + 8 + length : position + 12 + length])[0]
            assert zlib.crc32(chunk_type + chunk_data) == checksum
            if chunk_type == b"IDAT":
                compressed.extend(chunk_data)
            last_type = chunk_type
            position += 12 + length
        assert position == len(image) and last_type == b"IEND"
        assert len(zlib.decompress(compressed)) > width * height


def test_screenshot_demo_routes(app_client, monkeypatch) -> None:
    """Exercise the actual Flask routes used for capture with strict offline fixtures."""
    application, client, _ = app_client
    monkeypatch.setattr(application, "mist", demo_connection())
    assert client.get("/").status_code == 200
    org = client.get("/api/organization").get_json()
    assert org["data"]["org_name"] == "Offline Demo Organization"
    gateways = client.get("/api/gateways").get_json()["data"]
    assert len(gateways) == 3 and sum(gateway["num_ports"] for gateway in gateways) == 6
    peers = client.get("/api/gateway/demo-gateway-1/vpn_peers?site_id=demo-site-1&mac=020000000001").get_json()
    assert len(peers["peers_by_port"]["ge-0/0/0"]) == 2
    traffic = client.get(
        "/api/gateway/demo-gateway-1/port/ge-0%2F0%2F0/traffic" "?site_id=demo-site-1&start=1000&end=8200&interval=600"
    ).get_json()
    assert traffic["success"]
    assert len(traffic["data"]["timestamps"]) == len(traffic["data"]["rx_bps"]) == 12
    hourly = client.get(
        "/api/v1/sites/demo-site-1/gateways/demo-gateway-1/ports/ge-0%2F0%2F0/hourly?duration=24h"
    ).get_json()
    assert hourly["success"] and len(hourly["hourly"]) == 24
    assert all(sample["rx_bps"] > 0 and sample["avg_latency_ms"] > 0 for sample in hourly["hourly"])
    assert hourly["port_app_health"]["summary_pct"] == 98.4
    assert len(hourly["hourly_app_health"]) == 24
