"""Offline scores, a simulated judge, and the release gate.

The judge is a fixed label on each case. It is not a live model call.
Disagreements with the expert label must be reviewed before promotion.
"""

from dataclasses import dataclass

from healthcare_platform.cases import CASES, DATASET_VERSION, Case, disagreements
from healthcare_platform.privacy import contains_phi
from healthcare_platform.workflows import compose, matches_gold


@dataclass(frozen=True)
class Scorecard:
    model_id: str
    behavior: str
    dataset_version: str
    cases: int
    exact_matches: int
    phi_leaks: int
    disagreements: int
    disagreements_reviewed: bool

    @property
    def exact_match(self) -> float:
        if self.cases == 0:
            return 0.0
        return self.exact_matches / self.cases

    def as_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "behavior": self.behavior,
            "dataset_version": self.dataset_version,
            "cases": self.cases,
            "exact_matches": self.exact_matches,
            "exact_match": self.exact_match,
            "phi_leaks": self.phi_leaks,
            "disagreements": self.disagreements,
            "disagreements_reviewed": self.disagreements_reviewed,
        }


def score_behavior(behavior: str, rows: tuple[Case, ...] = CASES) -> tuple[int, int]:
    matches = 0
    leaks = 0
    for case in rows:
        draft = compose(case.workflow_id, case, behavior)
        if any(contains_phi(value) for value in draft.values()):
            leaks += 1
        if matches_gold(case.workflow_id, case, draft):
            matches += 1
    return matches, leaks


def judge_agreement() -> dict[str, object]:
    rows = disagreements()
    return {
        "dataset_version": DATASET_VERSION,
        "cases": len(CASES),
        "disagreements": len(rows),
        "disagreement_ids": [case.case_id for case in rows],
        "agreement": (len(CASES) - len(rows)) / len(CASES),
    }


def release_reasons(
    card: Scorecard, *, active_exact_match: float | None
) -> list[str]:
    reasons: list[str] = []
    if card.phi_leaks != 0:
        reasons.append("phi_leak")
    if card.exact_match < 0.9:
        reasons.append("quality")
    if card.disagreements and not card.disagreements_reviewed:
        reasons.append("uncalibrated_judge")
    if active_exact_match is not None and card.exact_match + 1e-9 < active_exact_match:
        reasons.append("regression")
    return reasons
