"""In-process traces and Prometheus text. No collector is exported."""

from typing import Any

from opentelemetry import trace

from healthcare_platform import __version__

TRACER = trace.get_tracer("healthcare_platform", __version__)


class Metrics:
    def __init__(self) -> None:
        self.runs = 0
        self.errors = 0
        self.denials = 0
        self.phi_blocks = 0
        self.approvals = 0
        self.quality_sum = 0.0
        self.quality_count = 0
        self.cost_units = 0
        self.latency_seconds_sum = 0.0

    def render(self) -> str:
        quality = 0.0 if self.quality_count == 0 else self.quality_sum / self.quality_count
        lines = [
            "# TYPE healthcare_runs_total counter",
            f"healthcare_runs_total {self.runs}",
            "# TYPE healthcare_errors_total counter",
            f"healthcare_errors_total {self.errors}",
            "# TYPE healthcare_denials_total counter",
            f"healthcare_denials_total {self.denials}",
            "# TYPE healthcare_phi_blocks_total counter",
            f"healthcare_phi_blocks_total {self.phi_blocks}",
            "# TYPE healthcare_approvals_total counter",
            f"healthcare_approvals_total {self.approvals}",
            "# TYPE healthcare_quality_ratio gauge",
            f"healthcare_quality_ratio {quality}",
            "# TYPE healthcare_cost_units_total counter",
            f"healthcare_cost_units_total {self.cost_units}",
            "# TYPE healthcare_latency_seconds_sum counter",
            f"healthcare_latency_seconds_sum {self.latency_seconds_sum}",
            "",
        ]
        return "\n".join(lines)


def public_trace(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the trace fields a reviewer can check. PHI is already redacted."""

    keys = (
        "trace_id",
        "run_id",
        "workflow_id",
        "model_id",
        "failover",
        "below_quality_floor",
        "cost_units",
        "latency_units",
        "tools",
        "retrieval_encounter",
        "approval",
        "status",
        "phi_blocked",
        "requester_id",
        "approver_id",
    )
    return {key: payload[key] for key in keys if key in payload}
