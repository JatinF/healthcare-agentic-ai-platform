"""Shared fixtures for the simulated platform."""

import pytest

from healthcare_platform.identity import (
    NIA_TOKEN,
    OUT_TOKEN,
    PAM_TOKEN,
    REA_TOKEN,
    REX_TOKEN,
    SOL_TOKEN,
    Actor,
    authenticate,
)
from healthcare_platform.platform import Platform


def _actor(token: str) -> Actor:
    actor = authenticate(token)
    if actor is None:
        raise RuntimeError("fixture token missing")
    return actor


@pytest.fixture
def platform() -> Platform:
    return Platform()


@pytest.fixture
def rea() -> Actor:
    return _actor(REA_TOKEN)


@pytest.fixture
def sol() -> Actor:
    return _actor(SOL_TOKEN)


@pytest.fixture
def nia() -> Actor:
    return _actor(NIA_TOKEN)


@pytest.fixture
def outsider() -> Actor:
    return _actor(OUT_TOKEN)


@pytest.fixture
def pam() -> Actor:
    return _actor(PAM_TOKEN)


@pytest.fixture
def rex() -> Actor:
    return _actor(REX_TOKEN)
