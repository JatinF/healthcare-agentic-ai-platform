"""Acceptance checks for the three synthetic workflows and the shared runtime."""

import json
import socket
import zlib

import pytest

from healthcare_platform import __version__
from healthcare_platform.cases import CASES, DATASET_VERSION, WORKFLOWS, Case, disagreements
from healthcare_platform.demo import run_demo
from healthcare_platform.errors import FlowError
from healthcare_platform.evaluation import release_reasons, score_behavior
from healthcare_platform.gates import adapter_report, ensure_local, gate
from healthcare_platform.identity import TENANT
from healthcare_platform.platform import BEHAVIORS, Platform
from healthcare_platform.privacy import DRAFT_NOTICE, contains_phi
from healthcare_platform.registry import CANARY_BUCKETS
from healthcare_platform.workflows import RegisteredWorkflow


def _persisted(platform: Platform) -> str:
    return json.dumps(
        {
            "audit": platform.store.audit(),
            "traces": platform.store.traces(),
            "releases": platform.store.releases(),
        }
    )


def test_sdk_version_and_three_workflows() -> None:
    assert __version__ == "0.1.0"
    assert WORKFLOWS == (
        "clinical-document-draft",
        "referral-triage",
        "prior-auth-prep",
    )
    assert len({item.workflow_id for item in (RegisteredWorkflow(name) for name in WORKFLOWS)}) == 3


def test_catalog_has_at_least_150_cases_and_recorded_disagreements() -> None:
    assert len(CASES) == 180
    assert len(CASES) >= 150
    rows = disagreements()
    assert len(rows) == 12
    assert all(row.judge_label != row.expert_label for row in rows)
    assert {row.workflow_id for row in CASES} == set(WORKFLOWS)


def test_behavior_scores_drive_the_gate() -> None:
    governed, governed_leaks = score_behavior("governed")
    cheap, cheap_leaks = score_behavior("cheap")
    leaky, leaky_leaks = score_behavior("leaky")
    regressed, regressed_leaks = score_behavior("regressed")
    assert (governed, governed_leaks) == (180, 0)
    assert (cheap, cheap_leaks) == (140, 0)
    assert (leaky, leaky_leaks) == (0, 180)
    assert (regressed, regressed_leaks) == (40, 0)


def test_three_workflows_share_one_runtime_and_emit_traces(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    specs = (
        ("clinical-document-draft", "DOC-0001", "DRAFT_READY"),
        ("referral-triage", "REF-0001", "AWAITING_APPROVAL"),
        ("prior-auth-prep", "PA-0001", "AWAITING_APPROVAL"),
    )
    for workflow_id, case_id, status in specs:
        result = platform.run(workflow_id, case_id, rea, run_id=f"trace-{case_id}")
        assert result["status"] == status
        assert result["model_id"] == "mock-governed"
        assert result["failover"] is False
        assert result["output"]["draft_notice"] == DRAFT_NOTICE
        assert result["ehr_calls"] == 0
    traced = {row["workflow_id"] for row in platform.store.traces()}
    assert traced == set(WORKFLOWS)
    for row in platform.store.traces():
        assert row["model_id"] == "mock-governed"
        assert row["tools"] == ["chart.read"]
        assert "approval" in row
    assert "SYN-PHI-" not in _persisted(platform)
    assert platform.stream.topics["healthcare.runs.v1"]
    assert platform.store.effect_count() == 0


def test_default_route_prefers_the_cheaper_quality_model(platform: Platform) -> None:
    decision = platform.gateway.choose()
    assert decision.model_id == "mock-governed"
    assert decision.failover is False
    assert decision.quality == 0.95
    assert decision.cost_units == 8


def test_provider_failover_is_automatic(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    platform.gateway.set_available("mock-governed", False)
    platform.gateway.set_available("mock-alternate", False)
    result = platform.run("clinical-document-draft", "DOC-0003", rea, run_id="fail-over")
    assert result["model_id"] == "mock-cheap"
    assert result["failover"] is True
    assert result["below_quality_floor"] is True
    assert result["status"] == "DRAFT_READY"


def test_no_provider_and_down_provider(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    for model_id in ("mock-governed", "mock-alternate", "mock-cheap"):
        platform.gateway.set_available(model_id, False)
    with pytest.raises(FlowError) as missing:
        platform.run("clinical-document-draft", "DOC-0004", rea, run_id="none")
    assert missing.value.code == "no_provider"
    platform.gateway.set_available("mock-down", True)
    with pytest.raises(FlowError) as down:
        platform.run("clinical-document-draft", "DOC-0004", rea, run_id="down")
    assert down.value.code == "provider_down"


def test_finished_step_is_not_repeated_after_failure(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    platform.graph.fail_remaining["choose_model"] = 1
    with pytest.raises(FlowError) as failed:
        platform.run("clinical-document-draft", "DOC-0005", rea, run_id="retry-1")
    assert failed.value.code == "step_failed"
    assert failed.value.status_code == 503
    assert platform.tools.chart_reads == 1
    assert platform.store.get_run("retry-1")["status"] == "FAILED"
    result = platform.run("clinical-document-draft", "DOC-0005", rea, run_id="retry-1")
    assert result["status"] == "DRAFT_READY"
    assert platform.tools.chart_reads == 1
    replay = platform.run("clinical-document-draft", "DOC-0005", rea, run_id="retry-1")
    assert replay["run_id"] == result["run_id"]
    assert platform.tools.chart_reads == 1


def test_cross_tenant_and_protected_tools_are_denied(
    platform: Platform, rea: object, outsider: object, pam: object
) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    assert isinstance(outsider, Actor)
    assert isinstance(pam, Actor)
    case = CASES[0]
    with pytest.raises(FlowError) as denied:
        platform.run(case.workflow_id, case.case_id, outsider, run_id="cross")
    assert denied.value.code == "forbidden"
    with pytest.raises(FlowError):
        platform.tools.chart_read(pam, case)
    for actor in (rea, outsider, pam):
        with pytest.raises(FlowError) as blocked:
            platform.tools.phi_export(actor, case)
        assert blocked.value.code == "forbidden"
        assert "SYN-PHI-" not in blocked.value.message
    assert platform.tools.accepted_protected == 0
    assert platform.tools.chart_reads == 0
    assert platform.store.effect_count() == 0
    assert "SYN-PHI-" not in _persisted(platform)


def test_approval_is_a_different_person_and_effects_do_not_replay(
    platform: Platform, rea: object, sol: object, rex: object
) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    assert isinstance(sol, Actor)
    assert isinstance(rex, Actor)
    platform.run("prior-auth-prep", "PA-0002", rex, run_id="packet-1")
    with pytest.raises(FlowError) as same:
        platform.approve("packet-1", rex)
    assert same.value.code == "same_actor"
    with pytest.raises(FlowError) as early:
        platform.execute("packet-1", sol)
    assert early.value.code == "not_approved"
    assert platform.store.effect_count() == 0
    approved = platform.approve("packet-1", sol)
    assert approved["status"] == "APPROVED"
    assert approved["approver_id"] != approved["requester_id"]
    assert platform.store.effect_count() == 0
    first = platform.execute("packet-1", sol)
    second = platform.execute("packet-1", sol)
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert first["ehr_calls"] == 0
    assert platform.store.effect_count() == 1
    platform.run("referral-triage", "REF-0002", rea, run_id="ref-1")
    platform.approve("ref-1", sol)
    platform.execute("ref-1", sol)
    platform.execute("ref-1", sol)
    assert platform.store.effect_count() == 2
    platform.run("clinical-document-draft", "DOC-0006", rea, run_id="doc-only")
    with pytest.raises(FlowError) as draft:
        platform.execute("doc-only", sol)
    assert draft.value.code == "not_consequential"


def test_rejected_run_cannot_execute(platform: Platform, rea: object, sol: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    assert isinstance(sol, Actor)
    platform.run("referral-triage", "REF-0004", rea, run_id="rej-1")
    platform.reject("rej-1", sol)
    with pytest.raises(FlowError) as rejected:
        platform.execute("rej-1", sol)
    assert rejected.value.code == "rejected"
    assert platform.store.effect_count() == 0


def test_leaky_output_is_blocked_and_redacted(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    platform.gateway.pinned_behavior = "leaky"
    result = platform.run("referral-triage", "REF-0006", rea, run_id="leak-1")
    assert result["status"] == "BLOCKED"
    assert result["phi_blocked"] is True
    assert result["output"]["priority"] == "[REDACTED]"
    blob = json.dumps(result) + _persisted(platform)
    assert not contains_phi(blob)
    platform.gateway.pinned_behavior = "regressed"
    regressed = platform.run("clinical-document-draft", "DOC-0007", rea, run_id="regress-1")
    assert regressed["status"] == "BLOCKED"
    assert "sections" in regressed["schema_errors"] or "draft_notice" in regressed["schema_errors"]


def test_judge_review_is_required_before_promotion(platform: Platform, nia: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(nia, Actor)
    early = platform.promote("mock-governed", nia, stage="shadow")
    assert early["promoted"] is False
    assert "uncalibrated_judge" in early["reasons"]
    assert platform.registry.active() is None
    review = platform.review_judges(nia)
    assert review["dataset_version"] == DATASET_VERSION
    assert len(review["disagreement_ids"]) == 12
    stored = platform.store.get_review(DATASET_VERSION)
    assert stored is not None
    assert stored["disagreement_ids"] == review["disagreement_ids"]


def test_ineligible_models_are_not_promoted(platform: Platform, nia: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(nia, Actor)
    platform.review_judges(nia)
    for model_id in ("mock-cheap", "mock-leaky", "mock-regressed"):
        result = platform.promote(model_id, nia, stage="active")
        assert result["promoted"] is False
        assert result["reasons"]
    assert platform.registry.active() is None
    assert platform.registry.ineligible_promotions == 0
    released = {row["model_id"] for row in platform.store.releases()}
    assert released.isdisjoint({"mock-cheap", "mock-leaky", "mock-regressed"})
    actions = [row["action"] for row in platform.store.audit()]
    assert actions.count("promotion_rejected") == 3


def test_shadow_canary_rollback_and_regression(platform: Platform, nia: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(nia, Actor)
    platform.review_judges(nia)
    shadow = platform.promote("mock-governed", nia, stage="shadow")
    assert shadow == {"promoted": True, "reasons": [], "stage": "shadow"}
    with pytest.raises(FlowError) as missing:
        platform.serve_model("DOC-0001")
    assert missing.value.code == "no_active_model"
    active = platform.promote("mock-governed", nia, stage="active")
    assert active["promoted"] is True
    canary = platform.promote("mock-alternate", nia, stage="canary")
    assert canary["promoted"] is True
    bucket_zero = next(
        case.case_id
        for case in CASES
        if zlib.crc32(case.case_id.encode("utf-8")) % CANARY_BUCKETS == 0
    )
    other = next(
        case.case_id
        for case in CASES
        if zlib.crc32(case.case_id.encode("utf-8")) % CANARY_BUCKETS != 0
    )
    assert platform.serve_model(bucket_zero) == "mock-alternate"
    assert platform.serve_model(other) == "mock-governed"
    replacement = platform.promote("mock-alternate", nia, stage="active")
    assert replacement["promoted"] is True
    assert platform.registry.active()["model_id"] == "mock-alternate"
    cheap = platform.promote("mock-cheap", nia, stage="active")
    assert cheap["promoted"] is False
    assert "quality" in cheap["reasons"]
    assert "regression" in cheap["reasons"]
    assert platform.registry.active()["model_id"] == "mock-alternate"
    restored = platform.rollback(nia)
    assert restored["active"] == "mock-governed"
    assert platform.registry.ineligible_promotions == 0


def test_release_reasons_name_regression_without_a_live_model() -> None:
    from healthcare_platform.evaluation import Scorecard

    card = Scorecard(
        model_id="mock-sample",
        behavior="governed",
        dataset_version=DATASET_VERSION,
        cases=180,
        exact_matches=170,
        phi_leaks=0,
        disagreements=12,
        disagreements_reviewed=True,
    )
    assert release_reasons(card, active_exact_match=1.0) == ["regression"]
    assert card.exact_match < 1.0


def test_comparison_report_has_quality_latency_and_cost(platform: Platform) -> None:
    report = platform.comparison()
    assert report["cases"] == 180
    assert report["price"] == "none"
    by_id = {row["model_id"]: row for row in report["models"]}
    assert by_id["mock-governed"]["measured_exact_match"] == 1.0
    assert by_id["mock-governed"]["cost_units"] == 8
    assert by_id["mock-governed"]["latency_units"] == 30
    assert by_id["mock-cheap"]["measured_exact_match"] == 140 / 180
    assert by_id["mock-leaky"]["phi_leaks"] == 180
    assert by_id["mock-leaky"]["in_router"] is False
    assert by_id["mock-regressed"]["measured_exact_match"] == 40 / 180
    assert set(BEHAVIORS) == set(by_id)


def test_template_onboarding(platform: Platform, rea: object) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    case = Case(
        case_id="TPL-0001",
        workflow_id="template-echo",
        tenant_id=TENANT,
        encounter_id="SYN-ENC-TPL",
        patient_token="SYN-PHI-NAME-9001",
        mrn="SYN-PHI-MRN-9001",
        topic="SYN-TOPIC-TEMPLATE",
        finding="SYN-FINDING-TEMPLATE",
        acuity="routine",
        completeness="complete",
        service_code="SYN-SVC-1",
        policy_id="SYN-POL-1",
        expert_label="echo",
        judge_label="echo",
    )
    with pytest.raises(FlowError) as missing:
        platform.run("template-echo", "TPL-0001", rea, run_id="tpl-missing")
    assert missing.value.code == "unknown_case"
    platform.register_template(case)
    result = platform.run("template-echo", "TPL-0001", rea, run_id="tpl-1")
    assert result["status"] == "DRAFT_READY"
    assert result["output"]["echo"] == "SYN-TOPIC-TEMPLATE"
    assert "SYN-PHI-" not in json.dumps(result)


def test_remote_url_is_blocked_without_a_dial_or_an_echo() -> None:
    secret = "https://blocked.example/phi-path"
    dialed: list[str] = []

    def refuse(*_args: object, **_kwargs: object) -> None:
        dialed.append("dialed")
        raise AssertionError("socket opened")

    original = socket.create_connection
    socket.create_connection = refuse  # type: ignore[assignment]
    try:
        assert gate(secret) == "blocked"
        assert gate(None) == "not-run"
        assert gate("postgresql://lab:lab@127.0.0.1:5432/labdb") == "local"
        report = adapter_report()
        assert report["ehr"] == "not-run"
        assert report["hosted_model"] == "not-run"
        with pytest.raises(FlowError) as blocked:
            ensure_local(secret)
        assert blocked.value.code == "remote_blocked"
        assert "blocked.example" not in blocked.value.message
        assert secret not in blocked.value.message
    finally:
        socket.create_connection = original
    assert dialed == []


def test_metrics_cover_quality_latency_cost_errors_and_governance(
    platform: Platform, rea: object, sol: object
) -> None:
    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    assert isinstance(sol, Actor)
    platform.run("prior-auth-prep", "PA-0008", rea, run_id="metric-1")
    platform.approve("metric-1", sol)
    text = platform.metrics.render()
    assert "healthcare_runs_total 1" in text
    assert "healthcare_approvals_total 1" in text
    assert "healthcare_cost_units_total 8" in text
    assert "healthcare_quality_ratio 1.0" in text
    assert "healthcare_latency_seconds_sum" in text


def test_spans_record_the_workflow(platform: Platform, rea: object) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from healthcare_platform.identity import Actor

    assert isinstance(rea, Actor)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    platform.run("clinical-document-draft", "DOC-0008", rea, run_id="span-1")
    spans = exporter.get_finished_spans()
    matched = [span for span in spans if span.name == "workflow.run"]
    assert matched
    assert matched[0].attributes is not None
    assert matched[0].attributes["workflow.id"] == "clinical-document-draft"


def test_mlflow_records_the_scorecard(tmp_path: object, nia: object) -> None:
    import mlflow

    from healthcare_platform.identity import Actor

    assert isinstance(nia, Actor)
    assert hasattr(tmp_path, "as_posix")
    uri = f"sqlite:///{tmp_path.as_posix()}/mlflow.db"  # type: ignore[attr-defined]
    platform = Platform(tracking_uri=uri)
    mlflow.set_tracking_uri(uri)
    card = platform.evaluate("mock-governed", nia)
    assert card["exact_matches"] == 180
    assert card["phi_leaks"] == 0
    frame = mlflow.search_runs(max_results=5)
    assert len(frame) == 1
    assert float(frame.iloc[0]["metrics.exact_match"]) == 1.0


def test_benchmark_file_matches_the_scorer() -> None:
    from pathlib import Path

    report = json.loads(Path("benchmarks/latest.json").read_text(encoding="utf-8"))
    assert report["price"] == "none"
    assert report["repeats"] == 30
    for behavior, payload in report["scores"].items():
        matches, leaks = score_behavior(behavior)
        assert payload["exact_matches"] == matches
        assert payload["phi_leaks"] == leaks


def test_demo_stops_before_a_side_effect() -> None:
    text = run_demo()
    assert "Status: AWAITING_APPROVAL" in text
    assert "EHR calls: 0" in text
    assert "SYN-PHI-" not in text
