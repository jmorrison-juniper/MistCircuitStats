"""Offline tests for the typed helpers that the mypy gate added to the Mist connection."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import mist_connection
from mist_connection import MistConnection, _as_dict, _as_query


def _connection(org_id: str | None = "org-1") -> MistConnection:
    """Build a connection object without the constructor, so no SDK session starts."""
    connection = MistConnection.__new__(MistConnection)
    connection.org_id = org_id
    connection.apisession = Mock(spec=mist_connection.mistapi.APISession)
    connection.api_token = "offline-test-token"
    return connection


@pytest.mark.parametrize(
    ("data", "expected"),
    [({"a": 1}, {"a": 1}), ([{"a": 1}], {}), (None, {}), ("text", {})],
)
def test_as_dict_keeps_only_json_objects(data: object, expected: dict) -> None:
    """Return the object for a dict payload and an empty dict for each other payload."""
    assert _as_dict(data) == expected


@pytest.mark.parametrize(("value", "expected"), [(1000, "1000"), (0, None), (None, None)])
def test_as_query_keeps_sdk_truthiness(value: int | None, expected: str | None) -> None:
    """Send a value only when it is truthy, as the SDK did with the previous int value."""
    assert _as_query(value) == expected


def test_require_org_id_returns_value() -> None:
    """Return the organization ID when it has a value."""
    assert _connection()._require_org_id() == "org-1"


def test_require_org_id_rejects_missing_value() -> None:
    """Raise ValueError before an org-scoped SDK call when the organization ID has no value."""
    with pytest.raises(ValueError, match="Organization ID is required"):
        _connection(org_id=None)._require_org_id()


def test_extract_sle_samples_accepts_missing_start() -> None:
    """Return a zero start when neither the payload nor the SLE block holds a start value."""
    payload = {"start": None, "sle": {"start": None, "samples": {"total": [1]}}}

    totals, _degradeds, _values, env_start, _interval = MistConnection._extract_sle_samples(payload)

    assert totals == [1]
    assert env_start == 0


def test_extract_sle_samples_falls_back_to_sle_start() -> None:
    """Use the SLE start when the payload start has no value."""
    payload = {"sle": {"start": 1234, "samples": {}}}

    assert MistConnection._extract_sle_samples(payload)[3] == 1234


def test_gateway_insights_send_string_query_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass start and end to the SDK as strings, because the SDK declares them as strings."""
    sdk_call = Mock(return_value=SimpleNamespace(status_code=200, data={"rx_bps": []}))
    monkeypatch.setattr(mist_connection.mistapi.api.v1.sites.insights, "getSiteInsightMetricsForGateway", sdk_call)
    monkeypatch.setattr(MistConnection, "_rate_limited_tokens", {})

    result = _connection()._insights_gateway_stats("site-1", "device-1", "wan0", 100, 200, "rx_bps")

    assert result["success"] is True
    assert sdk_call.call_args.kwargs["start"] == "100"
    assert sdk_call.call_args.kwargs["end"] == "200"


def test_device_profile_ignores_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache and return an empty dict when the SDK returns a list for a device profile."""
    sdk_call = Mock(return_value=SimpleNamespace(status_code=200, data=[]))
    monkeypatch.setattr(mist_connection.mistapi.api.v1.orgs.deviceprofiles, "getOrgDeviceProfile", sdk_call)
    monkeypatch.setattr(MistConnection, "_device_profile_cache", {})

    assert _connection()._get_device_profile("profile-1") == {}
    assert sdk_call.call_args.args[1] == "org-1"
