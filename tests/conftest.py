"""Shared pytest fixtures for the attend test suite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture()
def client() -> TestClient:
    """Test client bound to the application (no raised server exceptions)."""
    return TestClient(main.app, raise_server_exceptions=False)
