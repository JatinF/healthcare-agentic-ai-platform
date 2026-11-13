"""Decide whether a configured service URL may be contacted.

Unset means not-run. A localhost URL may be contacted. Any other host is
blocked unless HEALTHCARE_PLATFORM_ALLOW_REMOTE=1. Blocked calls do not open
a socket and do not include the URL in the error text.
"""

import os

from healthcare_platform.errors import FlowError

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def endpoint_host(value: str) -> str:
    rest = value.split("://", 1)[-1]
    rest = rest.split("/", 1)[0]
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    return rest.split(":", 1)[0].strip("[]")


def gate(value: str | None, *, allow_remote: bool | None = None) -> str:
    if value is None or value.strip() == "":
        return "not-run"
    if allow_remote is None:
        allow_remote = os.environ.get("HEALTHCARE_PLATFORM_ALLOW_REMOTE") == "1"
    host = endpoint_host(value)
    if host in LOCAL_HOSTS:
        return "local"
    if allow_remote:
        return "remote"
    return "blocked"


def ensure_local(value: str | None) -> str:
    """Return the gate decision. A blocked host raises without the URL in the text."""

    decision = gate(value)
    if decision == "blocked":
        raise FlowError("remote_blocked", "remote endpoint is blocked", 403)
    return decision


def adapter_report() -> dict[str, str]:
    database = os.environ.get("DATABASE_URL")
    redis_url = os.environ.get("REDIS_URL")
    otlp = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    return {
        "postgres": "sqlite-default" if not database else gate(database),
        "redis": gate(redis_url),
        "otlp": gate(otlp),
        "ehr": "not-run",
        "hosted_model": "not-run",
    }
