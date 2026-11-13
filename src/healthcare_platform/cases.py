"""Deterministic synthetic cases. Sixty of each workflow, 180 total."""

from dataclasses import dataclass

from healthcare_platform.identity import TENANT

DATASET_VERSION = "cases-v1-seed-21"
WORKFLOWS: tuple[str, ...] = (
    "clinical-document-draft",
    "referral-triage",
    "prior-auth-prep",
)
ACUITY = ("routine", "soon", "urgent")
COMPLETENESS = ("complete", "missing_notes", "missing_policy")


@dataclass(frozen=True)
class Case:
    case_id: str
    workflow_id: str
    tenant_id: str
    encounter_id: str
    patient_token: str
    mrn: str
    topic: str
    finding: str
    acuity: str
    completeness: str
    service_code: str
    policy_id: str
    expert_label: str
    judge_label: str

    def facts(self) -> dict[str, str]:
        return {
            "topic": self.topic,
            "finding": self.finding,
            "acuity": self.acuity,
            "completeness": self.completeness,
            "service_code": self.service_code,
            "policy_id": self.policy_id,
        }


def _wrong(workflow_id: str, expert: str) -> str:
    if workflow_id == "clinical-document-draft":
        return "draft_incomplete"
    if workflow_id == "referral-triage":
        return "soon" if expert == "routine" else "routine"
    return "missing_notes" if expert == "complete" else "complete"


def build_cases() -> tuple[Case, ...]:
    rows: list[Case] = []
    prefixes = {
        "clinical-document-draft": "DOC",
        "referral-triage": "REF",
        "prior-auth-prep": "PA",
    }
    index = 0
    for workflow_id in WORKFLOWS:
        prefix = prefixes[workflow_id]
        for offset in range(60):
            acuity = ACUITY[offset % 3]
            completeness = COMPLETENESS[offset % 3]
            if workflow_id == "clinical-document-draft":
                expert = "draft_ok"
            elif workflow_id == "referral-triage":
                expert = acuity
            else:
                expert = completeness
            judge = _wrong(workflow_id, expert) if index % 15 == 0 else expert
            rows.append(
                Case(
                    case_id=f"{prefix}-{offset + 1:04d}",
                    workflow_id=workflow_id,
                    tenant_id=TENANT,
                    encounter_id=f"SYN-ENC-{index + 1:04d}",
                    patient_token=f"SYN-PHI-NAME-{index:04d}",
                    mrn=f"SYN-PHI-MRN-{index:04d}",
                    topic=f"SYN-TOPIC-{(offset % 5) + 1}",
                    finding=f"SYN-FINDING-{(offset % 4) + 1}",
                    acuity=acuity,
                    completeness=completeness,
                    service_code=f"SYN-SVC-{(offset % 6) + 1}",
                    policy_id=f"SYN-POL-{(offset % 3) + 1}",
                    expert_label=expert,
                    judge_label=judge,
                )
            )
            index += 1
    return tuple(rows)


CASES: tuple[Case, ...] = build_cases()
BY_ID: dict[str, Case] = {case.case_id: case for case in CASES}


def disagreements() -> tuple[Case, ...]:
    return tuple(case for case in CASES if case.judge_label != case.expert_label)
