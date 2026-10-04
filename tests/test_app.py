"""Offline tests for Flask routes and WAN Insights responses."""

import csv
import io

import pytest


def test_health_and_dashboard_routes(app_client):
    """Serve the health check and dashboard without contacting Mist."""
    _, client, fake_mist = app_client

    health = client.get("/health")
    dashboard = client.get("/")

    assert health.status_code == 200
    assert health.json["status"] == "healthy"
    assert health.json["timestamp"].endswith("+00:00")
    assert dashboard.status_code == 200
    fake_mist.assert_not_called()


def test_traffic_route_validates_required_query_values(app_client):
    """Reject incomplete traffic queries before calling the API wrapper."""
    _, client, fake_mist = app_client

    response = client.get("/api/gateway/gateway-1/port/wan0/traffic?site_id=site-1&start=0&end=20")

    assert response.status_code == 400
    assert response.json == {"success": False, "error": "site_id, start, and end are required"}
    fake_mist.get_gateway_port_traffic_series.assert_not_called()


def test_traffic_route_returns_mocked_series(app_client):
    """Keep the established traffic response envelope for a successful query."""
    _, client, fake_mist = app_client
    fake_mist.get_gateway_port_traffic_series.return_value = {
        "success": True,
        "data": {"timestamps": [10], "rx_bps": [120], "tx_bps": [45]},
    }

    response = client.get("/api/gateway/gateway-1/port/wan0/traffic?site_id=site-1&start=10&end=20&interval=600")

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "data": {"timestamps": [10], "rx_bps": [120], "tx_bps": [45]},
    }
    fake_mist.get_gateway_port_traffic_series.assert_called_once_with("site-1", "gateway-1", "wan0", 10, 20, 600)


def test_hourly_route_merges_metrics_and_app_health(app_client, monkeypatch):
    """Merge bandwidth, link health, and impacted-interface data by timestamp."""
    application, client, fake_mist = app_client
    monkeypatch.setattr(application.time, "time", lambda: 2_000_000_000)
    timestamp = 1_999_998_200
    fake_mist.get_gateway_hourly_bandwidth.return_value = {
        "samples": [
            {
                "timestamp": timestamp,
                "hour_iso": "2033-05-18T03:00:00Z",
                "rx_bps": 100,
                "tx_bps": 200,
                "max_rx_bps": 150,
                "max_tx_bps": 250,
            }
        ]
    }
    fake_mist.get_gateway_hourly_wan_link_health.return_value = {
        "samples": [{"timestamp": timestamp, "avg_latency_ms": 12, "avg_jitter_ms": 2, "avg_loss_pct": 0.5}]
    }
    fake_mist.get_site_application_health.return_value = {
        "success": True,
        "summary_pct": 99.5,
        "threshold_pct": 95,
        "trend": [{"timestamp": timestamp, "pct": 99.5}],
        "impacted_interfaces": [{"interface_name": "wan0", "gateway_hostname": "gw-1"}],
    }
    fake_mist.get_sites.return_value = [{"id": "site-1", "name": "Test Site"}]
    fake_mist.get_gateway_port_stats.return_value = {"gateway_name": "gw-1"}

    response = client.get("/api/v1/sites/site-1/gateways/gateway-1/ports/wan0/hourly?duration=6h")

    assert response.status_code == 200
    body = response.json
    assert body["success"] is True
    assert body["site_name"] == "Test Site"
    assert body["gateway_hostname"] == "gw-1"
    assert body["interval"] == 3600
    assert body["hourly"] == [
        {
            "timestamp": timestamp,
            "hour_iso": "2033-05-18T03:00:00Z",
            "tx_bps": 200,
            "rx_bps": 100,
            "max_tx_bps": 250,
            "max_rx_bps": 150,
            "avg_latency_ms": 12,
            "avg_jitter_ms": 2,
            "avg_loss_pct": 0.5,
        }
    ]
    assert body["port_app_health"] == {"summary_pct": 99.5, "threshold_pct": 95, "impacted": True}
    assert body["hourly_app_health"] == [{"timestamp": timestamp, "pct": 99.5}]
    assert body["rate_limited"] == {"bandwidth": False, "wan_link_health": False, "app_health": False}


def test_hourly_route_rejects_unknown_duration(app_client):
    """Return a client error for durations outside the supported allow-list."""
    _, client, fake_mist = app_client

    response = client.get("/api/v1/sites/site-1/gateways/gateway-1/ports/wan0/hourly?duration=30d")

    assert response.status_code == 400
    assert "duration must be one of" in response.json["error"]
    fake_mist.get_gateway_hourly_bandwidth.assert_not_called()


def test_hourly_csv_has_canonical_columns_and_blank_missing_values(app_client, monkeypatch):
    """Export the canonical twelve columns and render absent metrics as blanks."""
    application, client, fake_mist = app_client
    monkeypatch.setattr(application.time, "time", lambda: 2_000_000_000)
    fake_mist.get_gateway_hourly_bandwidth.return_value = {
        "samples": [
            {
                "timestamp": 1_999_998_200,
                "hour_iso": "2033-05-18T03:00:00Z",
                "rx_bps": None,
                "tx_bps": 200,
            }
        ]
    }
    fake_mist.get_gateway_hourly_wan_link_health.return_value = {"samples": []}
    fake_mist.get_site_application_health.return_value = {"success": False}
    fake_mist.get_sites.return_value = [{"id": "site-1", "name": "Test Site"}]
    fake_mist.get_gateway_port_stats.return_value = {"gateway_name": "gw-1"}

    response = client.get("/api/v1/sites/site-1/gateways/gateway-1/ports/wan0/hourly/export?duration=6h")

    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert len(rows[0]) == 12
    assert rows[0] == [
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
    assert rows[1][5] == ""
    assert rows[1][7] == "200"


def test_sites_route_reports_upstream_failure(app_client):
    """Convert an exception from the mocked Mist API into the route error response."""
    _, client, fake_mist = app_client
    fake_mist.get_sites.side_effect = RuntimeError("offline simulated error")

    response = client.get("/api/sites")

    assert response.status_code == 500
    assert response.json == {"success": False, "error": "offline simulated error"}


@pytest.mark.parametrize(
    ("duration", "seconds"),
    [("1h", 3600), ("6h", 21600), ("24h", 86400), ("3d", 259200), ("7d", 604800)],
)
def test_duration_conversion_supported_windows(duration, seconds):
    """Convert every supported duration to its number of seconds."""
    from mist_connection import duration_to_seconds

    assert duration_to_seconds(duration) == seconds
