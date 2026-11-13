"""Three product workflows plus the onboarding template.

Every draft carries DRAFT_NOT_A_CARE_DECISION. None of these functions
selects a treatment or writes to a record system.
"""

from typing import Protocol

from healthcare_platform.cases import Case
from healthcare_platform.privacy import DRAFT_NOTICE, contains_phi

CONSEQUENTIAL = frozenset({"referral-triage", "prior-auth-prep"})


def compose(workflow_id: str, case: Case, behavior: str) -> dict[str, str]:
    if workflow_id == "clinical-document-draft":
        return _document(case, behavior)
    if workflow_id == "referral-triage":
        return _referral(case, behavior)
    if workflow_id == "prior-auth-prep":
        return _prior(case, behavior)
    if workflow_id == "template-echo":
        return {
            "echo": case.topic,
            "draft_notice": DRAFT_NOTICE,
        }
    raise KeyError(workflow_id)


def _document(case: Case, behavior: str) -> dict[str, str]:
    if behavior == "regressed":
        return {"reason": case.topic}
    reason = case.topic
    if behavior == "leaky":
        reason = f"{case.patient_token} {reason}"
    return {"reason": reason, "findings": case.finding, "draft_notice": DRAFT_NOTICE}


def _referral(case: Case, behavior: str) -> dict[str, str]:
    priority = "routine" if behavior in {"cheap", "regressed"} else case.acuity
    if behavior == "leaky":
        priority = case.patient_token
    return {"priority": priority, "draft_notice": DRAFT_NOTICE}


def _prior(case: Case, behavior: str) -> dict[str, str]:
    completeness = "complete" if behavior == "regressed" else case.completeness
    service = case.patient_token if behavior == "leaky" else case.service_code
    return {
        "completeness": completeness,
        "service_code": service,
        "policy_id": case.policy_id,
        "draft_notice": DRAFT_NOTICE,
    }


def schema_errors(workflow_id: str, draft: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if draft.get("draft_notice") != DRAFT_NOTICE:
        errors.append("draft_notice")
    if workflow_id == "clinical-document-draft":
        if not draft.get("reason") or not draft.get("findings"):
            errors.append("sections")
    elif workflow_id == "referral-triage":
        if draft.get("priority") not in {"routine", "soon", "urgent"}:
            errors.append("priority")
    elif workflow_id == "prior-auth-prep":
        if draft.get("completeness") not in {"complete", "missing_notes", "missing_policy"}:
            errors.append("completeness")
        if not draft.get("service_code") or not draft.get("policy_id"):
            errors.append("packet_fields")
    elif workflow_id == "template-echo":
        if not draft.get("echo"):
            errors.append("echo")
    else:
        errors.append("unknown_workflow")
    return errors


def matches_gold(workflow_id: str, case: Case, draft: dict[str, str]) -> bool:
    if schema_errors(workflow_id, draft):
        return False
    if any(contains_phi(value) for value in draft.values()):
        return False
    if workflow_id == "clinical-document-draft":
        return draft.get("reason") == case.topic and draft.get("findings") == case.finding
    if workflow_id == "referral-triage":
        return draft.get("priority") == case.acuity
    if workflow_id == "prior-auth-prep":
        return (
            draft.get("completeness") == case.completeness
            and draft.get("service_code") == case.service_code
            and draft.get("policy_id") == case.policy_id
        )
    return draft.get("echo") == case.topic


class Workflow(Protocol):
    workflow_id: str

    def compose(self, case: Case, behavior: str) -> dict[str, str]: ...


class RegisteredWorkflow:
    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id

    def compose(self, case: Case, behavior: str) -> dict[str, str]:
        return compose(self.workflow_id, case, behavior)
