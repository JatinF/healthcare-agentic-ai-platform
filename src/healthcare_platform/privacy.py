"""Redact synthetic PHI markers. The markers are fixtures, not patient records."""

import re

PHI_PATTERN = re.compile(r"SYN-PHI-[A-Z]+-[A-Za-z0-9]+")
DRAFT_NOTICE = "DRAFT_NOT_A_CARE_DECISION"


def phi_tokens(text: str) -> list[str]:
    return PHI_PATTERN.findall(text)


def contains_phi(text: str) -> bool:
    return PHI_PATTERN.search(text) is not None


def redact(text: str) -> str:
    return PHI_PATTERN.sub("[REDACTED]", text)


def redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value
