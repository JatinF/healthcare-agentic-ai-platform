"""Postgres round trip. Skipped unless DATABASE_URL is a local postgres URL."""

import os

import pytest

from healthcare_platform.gates import gate
from healthcare_platform.store import Store

DATABASE_URL = os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(
    gate(DATABASE_URL) != "local" or not DATABASE_URL.startswith("postgresql"),
    reason="DATABASE_URL is unset or not a local postgres URL",
)


def test_postgres_run_roundtrip() -> None:
    store = Store(DATABASE_URL)
    assert store.kind == "postgres"
    store.save_run("pg-run-1", {"status": "DRAFT_READY", "ehr_calls": 0})
    loaded = store.get_run("pg-run-1")
    assert loaded is not None
    assert loaded["status"] == "DRAFT_READY"
    first = store.apply_effect("pg-effect-1", {"action": "packet.stage"})
    second = store.apply_effect("pg-effect-1", {"action": "packet.stage"})
    assert first["idempotent"] is False
    assert second["idempotent"] is True
