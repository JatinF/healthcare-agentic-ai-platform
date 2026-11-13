"""Policy-governed tools. Protected exports are denied for every fixture role."""

from healthcare_platform.cases import Case
from healthcare_platform.errors import FlowError
from healthcare_platform.identity import Actor, require_scope


class ToolGate:
    def __init__(self) -> None:
        self.chart_reads = 0
        self.denied = 0
        self.accepted_protected = 0

    def chart_read(self, actor: Actor, case: Case) -> dict[str, str]:
        try:
            require_scope(actor, "tool:chart.read")
        except FlowError:
            self.denied += 1
            raise
        if actor.tenant_id != case.tenant_id:
            self.denied += 1
            raise FlowError("forbidden", "tenant boundary", 403)
        self.chart_reads += 1
        return {
            "encounter_id": case.encounter_id,
            "topic": case.topic,
            "finding": case.finding,
            "acuity": case.acuity,
            "completeness": case.completeness,
            "service_code": case.service_code,
            "policy_id": case.policy_id,
        }

    def phi_export(self, actor: Actor, case: Case) -> dict[str, str]:
        del actor, case
        self.denied += 1
        raise FlowError("forbidden", "phi export is denied", 403)

    def note_protected_accepted(self) -> None:
        """Test hook. Production paths do not call this."""

        self.accepted_protected += 1
