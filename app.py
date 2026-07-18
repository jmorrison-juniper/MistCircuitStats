"""
MistCircuitStats - Flask application for displaying Gateway WAN port statistics
"""

import csv
import io
import logging
import os
import time
from datetime import UTC, datetime
from urllib.parse import unquote

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

from mist_connection import (
    HOUR_INTERVAL,
    MistConnection,
    clip_to_retention_window,
    duration_to_seconds,
)

# Load environment variables from .env file
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)

# Initialize Mist connection
mist = MistConnection(
    api_token=os.getenv("MIST_APITOKEN", ""),
    org_id=os.getenv("MIST_ORG_ID"),
    host=os.getenv("MIST_HOST", "api.mist.com"),
)


@app.route("/")
def index():
    """Render the main dashboard page"""
    return render_template("index.html")


@app.route("/health")
def health():
    """Health check endpoint for container orchestration"""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()}), 200


@app.route("/api/organization")
def get_organization():
    """Get current organization information"""
    try:
        org_info = mist.get_organization_info()
        return jsonify({"success": True, "data": org_info})
    except Exception as e:
        logger.error(f"Error fetching organization info: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/organizations")
def get_organizations():
    """Get list of organizations (if org_id not specified)"""
    try:
        orgs = mist.get_organizations()
        return jsonify({"success": True, "data": orgs})
    except Exception as e:
        logger.error(f"Error fetching organizations: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sites")
def get_sites():
    """Get list of sites in the organization"""
    try:
        sites = mist.get_sites()
        return jsonify({"success": True, "data": sites})
    except Exception as e:
        logger.error(f"Error fetching sites: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gateways")
def get_gateways():
    """Get all gateways with their WAN port statistics"""
    try:
        import time

        site_id = request.args.get("site_id")
        duration = request.args.get("duration", "7d")  # Default to 7 days

        # Calculate epoch timestamps based on duration
        end = int(time.time())
        duration_map = {"15m": 15 * 60, "1h": 60 * 60, "1d": 24 * 60 * 60, "7d": 7 * 24 * 60 * 60}
        seconds = duration_map.get(duration, 24 * 60 * 60)  # Default to 1 day
        start = end - seconds

        logger.info(f"Fetching gateway stats with timeframe: {duration} (start={start}, end={end})")
        gateways = mist.get_gateway_stats(site_id=site_id, start=start, end=end)
        return jsonify({"success": True, "data": gateways})
    except Exception as e:
        logger.error(f"Error fetching gateway stats: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gateway/<gateway_id>/ports")
def get_gateway_ports(gateway_id):
    """Get detailed WAN port statistics for a specific gateway"""
    try:
        port_stats = mist.get_gateway_port_stats(gateway_id)
        return jsonify({"success": True, "data": port_stats})
    except Exception as e:
        logger.error(f"Error fetching gateway port stats: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gateway/<gateway_id>/port/<path:port_id>/traffic")
def get_port_traffic(gateway_id, port_id):
    """Get time-series traffic data for a specific port"""
    try:
        from urllib.parse import unquote

        import requests

        # Decode the port_id in case it's URL encoded
        port_id = unquote(port_id)

        site_id = request.args.get("site_id")
        start = int(request.args.get("start", 0))
        end = int(request.args.get("end", 0))
        interval = int(request.args.get("interval", 600))

        if not site_id or start == 0 or end == 0:
            return jsonify({"success": False, "error": "site_id, start, and end are required"}), 400

        logger.info(f"Fetching traffic for gateway {gateway_id}, port {port_id}, interval {interval}")

        # Fetch from Mist insights API
        headers = {"Authorization": f"Token {mist.api_token}", "Content-Type": "application/json"}

        url = f"https://{mist.host}/api/v1/sites/{site_id}/insights/gateway/{gateway_id}/stats"
        params = {"interval": interval, "start": start, "end": end, "port_id": port_id, "metrics": "rx_bps,tx_bps"}

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()

            # Format response for frontend
            result = {
                "timestamps": [start + (i * interval) for i in range(len(data.get("rx_bps", [])))],
                "rx_bps": data.get("rx_bps", []),
                "tx_bps": data.get("tx_bps", []),
            }

            return jsonify({"success": True, "data": result})
        else:
            logger.error(f"Insights API error: {response.status_code}")
            return jsonify({"success": False, "error": f"API error: {response.status_code}"}), 500

    except Exception as e:
        logger.error(f"Error fetching port traffic: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gateway/<gateway_id>/vpn_peers")
def get_vpn_peers(gateway_id):
    """Get VPN peer path statistics for a gateway"""
    try:
        site_id = request.args.get("site_id")
        device_mac = request.args.get("mac")

        if not site_id or not device_mac:
            return jsonify({"success": False, "error": "site_id and mac are required"}), 400

        logger.info(f"Fetching VPN peers for gateway {gateway_id} (MAC: {device_mac})")

        peer_stats = mist.get_vpn_peer_stats(site_id, device_mac)

        return jsonify(peer_stats)

    except Exception as e:
        logger.error(f"Error fetching VPN peers: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# WAN Insights feature routes (spec 001-wan-insights-metrics)
# ---------------------------------------------------------------------------


def _resolve_site_and_device(site_id, device_id):
    """Look up site_name and gateway_hostname for CSV export / envelope. Returns (site_name, gw_hostname)."""
    site_name = ""
    gw_hostname = ""
    try:
        for s in mist.get_sites() or []:
            if s.get("id") == site_id:
                site_name = s.get("name", "") or ""
                break
    except Exception as e:
        logger.debug(f"Could not resolve site name: {e}")
    try:
        port_stats = mist.get_gateway_port_stats(device_id)
        gw_hostname = port_stats.get("gateway_name", "") or ""
    except Exception as e:
        logger.debug(f"Could not resolve gateway hostname: {e}")
    return site_name, gw_hostname


def _compute_window(duration):
    """Return (start, end, clipped, retention_notice) or raise ValueError."""
    end = int(time.time())
    seconds = duration_to_seconds(duration)
    raw_start = end - seconds
    start, clipped, notice = clip_to_retention_window(raw_start, end)
    return start, end, clipped, notice


def _build_hourly_response(site_id, device_id, port_id, duration):
    """Shared assembler: returns the PortHourlyResponse dict (no jsonify wrap).

    Raises ValueError on bad duration.
    """
    start, end, clipped, retention_notice = _compute_window(duration)

    bw = mist.get_gateway_hourly_bandwidth(site_id, device_id, port_id, start, end)
    wlh = mist.get_gateway_hourly_wan_link_health(site_id, device_id, port_id, start, end)
    app_health = mist.get_site_application_health(site_id, start, end)

    # Merge bandwidth + wan_link_health by hour bucket
    wlh_by_ts = {s["timestamp"]: s for s in wlh.get("samples", [])}
    hourly = []
    for bw_sample in bw.get("samples", []):
        ts = bw_sample["timestamp"]
        wlh_sample = wlh_by_ts.get(ts, {})
        hourly.append(
            {
                "timestamp": ts,
                "hour_iso": bw_sample["hour_iso"],
                "tx_bps": bw_sample.get("tx_bps"),
                "rx_bps": bw_sample.get("rx_bps"),
                "max_tx_bps": bw_sample.get("max_tx_bps"),
                "max_rx_bps": bw_sample.get("max_rx_bps"),
                "avg_latency_ms": wlh_sample.get("avg_latency_ms"),
                "avg_jitter_ms": wlh_sample.get("avg_jitter_ms"),
                "avg_loss_pct": wlh_sample.get("avg_loss_pct"),
            }
        )

    # If bandwidth had no samples but wan_link_health did, fill from wlh
    if not hourly and wlh.get("samples"):
        for wlh_sample in wlh["samples"]:
            hourly.append(
                {
                    "timestamp": wlh_sample["timestamp"],
                    "hour_iso": wlh_sample["hour_iso"],
                    "tx_bps": None,
                    "rx_bps": None,
                    "max_tx_bps": None,
                    "max_rx_bps": None,
                    "avg_latency_ms": wlh_sample.get("avg_latency_ms"),
                    "avg_jitter_ms": wlh_sample.get("avg_jitter_ms"),
                    "avg_loss_pct": wlh_sample.get("avg_loss_pct"),
                }
            )

    site_name, gw_hostname = _resolve_site_and_device(site_id, device_id)

    # Per-port slice of App Health SLE
    port_app_health = None
    if app_health.get("success") and app_health.get("summary_pct") is not None:
        matched = any(
            r.get("interface_name") == port_id and (not gw_hostname or r.get("gateway_hostname") == gw_hostname)
            for r in app_health.get("impacted_interfaces", [])
        )
        port_app_health = {
            "summary_pct": app_health.get("summary_pct"),
            "threshold_pct": app_health.get("threshold_pct"),
            "impacted": matched,
        }

    hourly_app_health = [{"timestamp": t.get("timestamp"), "pct": t.get("pct")} for t in app_health.get("trend", [])]

    return {
        "success": True,
        "port_id": port_id,
        "device_id": device_id,
        "gateway_hostname": gw_hostname,
        "site_id": site_id,
        "site_name": site_name,
        "start": start,
        "end": end,
        "interval": HOUR_INTERVAL,
        "clipped": clipped,
        "retention_notice": retention_notice,
        "hourly": hourly,
        "port_app_health": port_app_health,
        "hourly_app_health": hourly_app_health,
        "rate_limited": {
            "bandwidth": bool(bw.get("rate_limited")),
            "wan_link_health": bool(wlh.get("rate_limited")),
            "app_health": bool(app_health.get("rate_limited")),
        },
    }


@app.route("/api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly")
def get_gateway_port_hourly(site_id, device_id, port_id):
    """Per-port hourly Rx/Tx + jitter/latency/loss + App Health slice."""
    try:
        port_id = unquote(port_id)
        duration = request.args.get("duration", "24h")
        try:
            body = _build_hourly_response(site_id, device_id, port_id, duration)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
        return jsonify(body)
    except Exception as e:
        logger.error(f"Error building hourly response: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/v1/sites/<site_id>/gateways/<device_id>/ports/<path:port_id>/hourly/export")
def export_gateway_port_hourly_csv(site_id, device_id, port_id):
    """CSV export — canonical 12-column layout (see contract + data-model.md)."""
    try:
        port_id = unquote(port_id)
        duration = request.args.get("duration", "24h")
        try:
            body = _build_hourly_response(site_id, device_id, port_id, duration)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400

        site_name = body["site_name"]
        gw_hostname = body["gateway_hostname"]

        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "site_name",
                "gateway_name",
                "port_id",
                "hour_epoch",
                "hour_iso",
                "rx_avg_bps",
                "rx_peak_bps",
                "tx_avg_bps",
                "tx_peak_bps",
                "jitter_avg_ms",
                "latency_avg_ms",
                "loss_avg_pct",
            ]
        )

        rows = sorted(body["hourly"], key=lambda r: (site_name, gw_hostname, port_id, r["timestamp"]))
        for r in rows:

            def cell(v):
                return "" if v is None else v

            writer.writerow(
                [
                    site_name,
                    gw_hostname,
                    port_id,
                    r["timestamp"],
                    r["hour_iso"],
                    cell(r.get("rx_bps")),
                    cell(r.get("max_rx_bps")),
                    cell(r.get("tx_bps")),
                    cell(r.get("max_tx_bps")),
                    cell(r.get("avg_jitter_ms")),
                    cell(r.get("avg_latency_ms")),
                    cell(r.get("avg_loss_pct")),
                ]
            )

        iso_now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_port = port_id.replace("/", "_")
        safe_host = gw_hostname or device_id
        filename = f"hourly_metrics_{safe_host}_{safe_port}_{iso_now}.csv"

        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/v1/sites/<site_id>/application-health-summary")
def get_site_app_health_summary(site_id):
    """Native Application Health SLE for a site (summary + trend + impacted interfaces + threshold)."""
    try:
        duration = request.args.get("duration", "24h")
        try:
            start, end, clipped, _notice = _compute_window(duration)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400

        result = mist.get_site_application_health(site_id, start, end)
        body = {
            "site_id": site_id,
            "summary_pct": result.get("summary_pct"),
            "threshold_pct": result.get("threshold_pct"),
            "trend": result.get("trend", []),
            "impacted_interfaces": result.get("impacted_interfaces", []),
            "clipped": clipped,
            "rate_limited": bool(result.get("rate_limited")),
        }
        return jsonify(body)
    except Exception as e:
        logger.error(f"Error fetching site application health: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=(LOG_LEVEL == "DEBUG"))  # nosec B104  # noqa: E501  # fmt: skip
