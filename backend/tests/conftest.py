"""Shared test fixtures.

The API and analytics tests run against the real synthetic warehouse so the
test suite exercises the same read models the product uses.  If the warehouse
is missing, build it once (raw data is generated when absent).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.duck import data_ready
from app.pipeline.process import run_pipeline


@pytest.fixture(scope="session", autouse=True)
def warehouse() -> None:
    ready, _ = data_ready()
    if not ready:
        settings = get_settings()
        run_pipeline(settings, force_generate=not settings.raw_dir.exists())


@pytest.fixture(scope="session")
def client(warehouse: None):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def settings():
    return get_settings()
