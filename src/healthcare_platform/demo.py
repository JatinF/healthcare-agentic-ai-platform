"""Print one prior-authorization draft from a real platform run.

The run stops before approval. No packet is staged.
"""

import json

from healthcare_platform.identity import REA_ID, REA_TOKEN, authenticate
from healthcare_platform.platform import Platform


def run_demo() -> str:
    platform = Platform()
    actor = authenticate(REA_TOKEN)
    if actor is None or actor.user_id != REA_ID:
        raise RuntimeError("requester fixture missing")
    result = platform.run("prior-auth-prep", "PA-0001", actor)
    if result["status"] != "AWAITING_APPROVAL":
        raise RuntimeError("demo did not hold for approval")
    if result["model_id"] != "mock-governed" or result["failover"] is not False:
        raise RuntimeError("demo did not select the governed model")
    if platform.store.effect_count() != 0 or platform.ehr_calls != 0:
        raise RuntimeError("demo staged a packet or called an EHR")
    output = result["output"]
    if not isinstance(output, dict) or output.get("draft_notice") != "DRAFT_NOT_A_CARE_DECISION":
        raise RuntimeError("demo output is not a draft")
    if "SYN-PHI-" in json.dumps(result):
        raise RuntimeError("demo trace contains a PHI marker")
    lines = [
        "Healthcare Agentic Platform Demo",
        "--------------------------------",
        "Tenant: SYN-TENANT-NORTHBRIDGE",
        "Workflow: prior-auth-prep",
        "Case: PA-0001",
        "1. Chart read completed",
        "2. Model mock-governed selected",
        "3. Draft packet prepared",
        "4. PHI markers in the trace: 0",
        "5. Proposed draft awaiting a different person",
        "",
        "Result:",
        f"  Status: {result['status']}",
        f"  Completeness: {output.get('completeness')}",
        f"  Service code: {output.get('service_code')}",
        f"  Notice: {output.get('draft_notice')}",
        f"  Failover: {result['failover']}",
        "",
        "Execution:",
        "  No packet staged before approval",
        "  EHR calls: 0",
        "  Simulated drafts only",
        "",
    ]
    return "\n".join(lines)
