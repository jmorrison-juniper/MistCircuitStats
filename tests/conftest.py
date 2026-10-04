"""Shared fixtures for offline application tests."""

import os
from unittest.mock import Mock

import pytest

os.environ["MIST_APITOKEN"] = "offline-test-token"
os.environ["MIST_ORG_ID"] = "offline-test-org"


@pytest.fixture
def app_client(monkeypatch):
    """Create a Flask client with a mocked Mist connection."""
    import mist_connection

    monkeypatch.setattr(mist_connection.mistapi, "APISession", lambda **_: object())
    import app as application

    fake_mist = Mock()
    monkeypatch.setattr(application, "mist", fake_mist)
    return application, application.app.test_client(), fake_mist
