"""Synthetic bearer identities. This is not an external identity provider."""

import secrets
from dataclasses import dataclass

from healthcare_platform.errors import FlowError

TENANT = "SYN-TENANT-NORTHBRIDGE"
ORG = "SYN-ORG-NORTHBRIDGE"
OTHER_TENANT = "SYN-TENANT-SOUTHLINE"

REA_ID = "SYN-USER-REA"
SOL_ID = "SYN-USER-SOL"
NIA_ID = "SYN-USER-NIA"
OUT_ID = "SYN-USER-OUT"
PAM_ID = "SYN-USER-PAM"
REX_ID = "SYN-USER-REX"

REA_TOKEN = "lab-rea"
SOL_TOKEN = "lab-sol"
NIA_TOKEN = "lab-nia"
OUT_TOKEN = "lab-out"
PAM_TOKEN = "lab-pam"
REX_TOKEN = "lab-rex"


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str
    tenant_id: str
    scopes: frozenset[str]


_FIXTURES: tuple[tuple[str, Actor], ...] = (
    (
        REA_TOKEN,
        Actor(REA_ID, "requester", TENANT, frozenset({"workflow.run", "tool:chart.read"})),
    ),
    (
        SOL_TOKEN,
        Actor(
            SOL_ID,
            "approver",
            TENANT,
            frozenset({"workflow.approve", "tool:packet.stage", "tool:recommendation.release"}),
        ),
    ),
    (
        NIA_TOKEN,
        Actor(
            NIA_ID,
            "evaluator",
            TENANT,
            frozenset({"eval.run", "eval.review", "registry.promote"}),
        ),
    ),
    (
        OUT_TOKEN,
        Actor(OUT_ID, "outsider", OTHER_TENANT, frozenset({"workflow.run", "tool:chart.read"})),
    ),
    (
        PAM_TOKEN,
        Actor(PAM_ID, "other-tenant", OTHER_TENANT, frozenset({"tool:chart.read", "workflow.run"})),
    ),
    (
        REX_TOKEN,
        Actor(
            REX_ID,
            "requester-approver",
            TENANT,
            frozenset({"workflow.run", "workflow.approve", "tool:chart.read"}),
        ),
    ),
)


def _matches(presented: str, expected: str) -> bool:
    if len(presented) != len(expected):
        return False
    return secrets.compare_digest(presented, expected)


def authenticate(token: str) -> Actor | None:
    for expected, actor in _FIXTURES:
        if _matches(token, expected):
            return actor
    return None


def require_actor(token: str | None) -> Actor:
    if token is None or token.strip() == "":
        raise FlowError("unauthorized", "bearer token required", 401)
    actor = authenticate(token.strip())
    if actor is None:
        raise FlowError("unauthorized", "unknown token", 401)
    return actor


def require_scope(actor: Actor, scope: str) -> None:
    if scope not in actor.scopes:
        raise FlowError("forbidden", "scope not permitted", 403)


def actor_by_id(user_id: str) -> Actor | None:
    for _token, actor in _FIXTURES:
        if actor.user_id == user_id:
            return actor
    return None
