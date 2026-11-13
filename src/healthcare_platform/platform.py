"""One runtime for every registered workflow."""

import json
import time
import uuid
from typing import Any

from healthcare_platform.cases import BY_ID, CASES, DATASET_VERSION, WORKFLOWS, Case, disagreements
from healthcare_platform.errors import FlowError
from healthcare_platform.evaluation import Scorecard, judge_agreement, score_behavior
from healthcare_platform.gateway import ModelGateway
from healthcare_platform.graph_runtime import GraphRuntime
from healthcare_platform.identity import Actor, require_scope
from healthcare_platform.privacy import contains_phi, redact
from healthcare_platform.registry import Registry
from healthcare_platform.store import Store
from healthcare_platform.telemetry import TRACER, Metrics, public_trace
from healthcare_platform.tools import ToolGate
from healthcare_platform.workflows import CONSEQUENTIAL

BEHAVIORS = {
    "mock-governed": "governed",
    "mock-alternate": "governed",
    "mock-cheap": "cheap",
    "mock-leaky": "leaky",
    "mock-regressed": "regressed",
}


class InProcessStream:
    def __init__(self) -> None:
        self.topics: dict[str, list[dict[str, Any]]] = {}

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.topics.setdefault(topic, []).append(payload)


class Platform:
    def __init__(self, database_url: str = "sqlite://", tracking_uri: str | None = None) -> None:
        self.store = Store(database_url)
        self.gateway = ModelGateway()
        self.tools = ToolGate()
        self.graph = GraphRuntime(self.store, self.gateway, self.tools)
        self.registry = Registry(self.store)
        self.metrics = Metrics()
        self.stream = InProcessStream()
        self.tracking_uri = tracking_uri
        self.ehr_calls = 0

    def register_template(self, case: Case) -> None:
        self.graph.allowed.add(case.workflow_id)
        self.graph.extra_cases[case.case_id] = case

    def _case(self, case_id: str) -> Case:
        case = BY_ID.get(case_id) or self.graph.extra_cases.get(case_id)
        if case is None:
            raise FlowError("unknown_case", "case is not in the synthetic catalog", 404)
        return case

    def run(
        self, workflow_id: str, case_id: str, actor: Actor, *, run_id: str | None = None
    ) -> dict[str, Any]:
        require_scope(actor, "workflow.run")
        case = self._case(case_id)
        if case.workflow_id != workflow_id:
            raise FlowError("workflow_mismatch", "case belongs to another workflow", 404)
        if actor.tenant_id != case.tenant_id:
            self.metrics.denials += 1
            self._audit(actor, "tenant_denied", case_id, "")
            raise FlowError("forbidden", "tenant boundary", 403)
        if workflow_id not in self.graph.allowed:
            raise FlowError("unknown_workflow", "workflow is not registered", 404)
        chosen = run_id or f"run-{uuid.uuid4().hex[:12]}"
        existing = self.store.get_run(chosen)
        if existing is not None and existing.get("status") not in {None, "FAILED"}:
            return existing
        started = time.perf_counter()
        try:
            with TRACER.start_as_current_span("workflow.run") as span:
                span.set_attribute("workflow.id", workflow_id)
                state = self.graph.invoke(chosen, case, actor)
        except RuntimeError as exc:
            if "injected" not in str(exc):
                raise
            self.metrics.errors += 1
            failed = {
                "run_id": chosen,
                "workflow_id": workflow_id,
                "case_id": case_id,
                "requester_id": actor.user_id,
                "status": "FAILED",
            }
            self.store.save_run(chosen, failed)
            raise FlowError("step_failed", "step failed before completion", 503) from exc
        elapsed = time.perf_counter() - started
        output = state.get("output")
        output_text = json.dumps(output, sort_keys=True)
        if contains_phi(output_text):
            raise RuntimeError("redaction failed")
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        retrieval = state.get("retrieval")
        encounter = ""
        if isinstance(retrieval, dict):
            raw_encounter = retrieval.get("encounter_id")
            encounter = raw_encounter if isinstance(raw_encounter, str) else ""
        status = state.get("status")
        if not isinstance(status, str):
            raise RuntimeError("status missing")
        trace = public_trace(
            {
                "trace_id": trace_id,
                "run_id": chosen,
                "workflow_id": workflow_id,
                "model_id": state.get("model_id"),
                "failover": bool(state.get("failover")),
                "below_quality_floor": bool(state.get("below_quality_floor")),
                "cost_units": state.get("cost_units"),
                "latency_units": state.get("latency_units"),
                "tools": state.get("tools"),
                "retrieval_encounter": encounter,
                "approval": None,
                "status": status,
                "phi_blocked": bool(state.get("phi_blocked")),
                "requester_id": actor.user_id,
                "approver_id": None,
            }
        )
        record = {
            "run_id": chosen,
            "workflow_id": workflow_id,
            "case_id": case_id,
            "requester_id": actor.user_id,
            "approver_id": None,
            "status": status,
            "output": output,
            "model_id": state.get("model_id"),
            "failover": bool(state.get("failover")),
            "below_quality_floor": bool(state.get("below_quality_floor")),
            "cost_units": state.get("cost_units"),
            "latency_units": state.get("latency_units"),
            "phi_blocked": bool(state.get("phi_blocked")),
            "schema_errors": state.get("schema_errors"),
            "trace_id": trace_id,
            "trace": trace,
            "wall_seconds": elapsed,
            "ehr_calls": self.ehr_calls,
        }
        self.store.save_run(chosen, record)
        self.store.add_trace(trace_id, workflow_id, trace)
        self.stream.publish("healthcare.runs.v1", {"run_id": chosen, "status": status})
        self.metrics.runs += 1
        self.metrics.latency_seconds_sum += elapsed
        cost = state.get("cost_units")
        if isinstance(cost, int):
            self.metrics.cost_units += cost
        if status == "BLOCKED" and state.get("phi_blocked"):
            self.metrics.phi_blocks += 1
        if status in {"DRAFT_READY", "AWAITING_APPROVAL"}:
            self.metrics.quality_sum += 1
            self.metrics.quality_count += 1
        elif status == "BLOCKED":
            self.metrics.quality_count += 1
        self._audit(actor, "run_completed", chosen, status)
        return record

    def approve(self, run_id: str, actor: Actor) -> dict[str, Any]:
        require_scope(actor, "workflow.approve")
        run = self._require_run(run_id)
        if run.get("requester_id") == actor.user_id:
            raise FlowError("same_actor", "requester cannot approve the run", 403)
        if run.get("status") == "APPROVED":
            return run
        if run.get("status") != "AWAITING_APPROVAL":
            raise FlowError("not_approvable", "run is not waiting for approval", 409)
        run["status"] = "APPROVED"
        run["approver_id"] = actor.user_id
        trace = run.get("trace")
        if isinstance(trace, dict):
            trace["approval"] = "approved"
            trace["approver_id"] = actor.user_id
            trace["status"] = "APPROVED"
            trace_id = run.get("trace_id")
            workflow_id = run.get("workflow_id")
            if isinstance(trace_id, str) and isinstance(workflow_id, str):
                self.store.add_trace(trace_id, workflow_id, trace)
        self.store.save_run(run_id, run)
        self.metrics.approvals += 1
        self._audit(actor, "approved", run_id, "no side effect")
        return run

    def reject(self, run_id: str, actor: Actor) -> dict[str, Any]:
        require_scope(actor, "workflow.approve")
        run = self._require_run(run_id)
        if run.get("status") == "EXECUTED":
            raise FlowError("already_executed", "executed run cannot be rejected", 409)
        run["status"] = "REJECTED"
        run["approver_id"] = actor.user_id
        self.store.save_run(run_id, run)
        self._audit(actor, "rejected", run_id, "no side effect")
        return run

    def execute(self, run_id: str, actor: Actor) -> dict[str, Any]:
        run = self._require_run(run_id)
        workflow_id = run.get("workflow_id")
        if workflow_id not in CONSEQUENTIAL:
            raise FlowError("not_consequential", "this draft has no side effect", 409)
        if run.get("status") == "REJECTED":
            raise FlowError("rejected", "rejected run cannot execute", 409)
        if run.get("status") not in {"APPROVED", "EXECUTED"}:
            raise FlowError("not_approved", "approval is required before execute", 409)
        if workflow_id == "prior-auth-prep":
            require_scope(actor, "tool:packet.stage")
            effect_key = f"packet:{run.get('case_id')}"
            action = "packet.stage"
        else:
            require_scope(actor, "tool:recommendation.release")
            effect_key = f"recommendation:{run.get('case_id')}"
            action = "recommendation.release"
        effect = self.store.apply_effect(
            effect_key,
            {
                "run_id": run_id,
                "case_id": run.get("case_id"),
                "action": action,
                "notice": "DRAFT_NOT_A_CARE_DECISION",
                "ehr_calls": self.ehr_calls,
            },
        )
        run["status"] = "EXECUTED"
        self.store.save_run(run_id, run)
        self._audit(actor, "executed", run_id, action)
        return effect

    def review_judges(self, actor: Actor) -> dict[str, Any]:
        require_scope(actor, "eval.review")
        payload = {
            "dataset_version": DATASET_VERSION,
            "reviewer_id": actor.user_id,
            "disagreement_ids": [case.case_id for case in disagreements()],
        }
        self.store.save_review(DATASET_VERSION, payload)
        self._audit(actor, "judge_review", DATASET_VERSION, str(len(payload["disagreement_ids"])))
        return payload

    def evaluate(self, model_id: str, actor: Actor) -> dict[str, Any]:
        require_scope(actor, "eval.run")
        behavior = BEHAVIORS.get(model_id)
        if behavior is None:
            raise FlowError("unknown_model", "model is not in the eval catalog", 404)
        matches, leaks = score_behavior(behavior)
        reviewed = self.store.get_review(DATASET_VERSION) is not None
        card = Scorecard(
            model_id=model_id,
            behavior=behavior,
            dataset_version=DATASET_VERSION,
            cases=len(CASES),
            exact_matches=matches,
            phi_leaks=leaks,
            disagreements=len(disagreements()),
            disagreements_reviewed=reviewed,
        )
        self._log_mlflow(card)
        return card.as_dict()

    def promote(self, model_id: str, actor: Actor, *, stage: str) -> dict[str, Any]:
        card_body = self.evaluate(model_id, actor)
        card = Scorecard(
            model_id=model_id,
            behavior=str(card_body["behavior"]),
            dataset_version=DATASET_VERSION,
            cases=int(card_body["cases"]),
            exact_matches=int(card_body["exact_matches"]),
            phi_leaks=int(card_body["phi_leaks"]),
            disagreements=int(card_body["disagreements"]),
            disagreements_reviewed=bool(card_body["disagreements_reviewed"]),
        )
        return self.registry.promote(model_id, card, actor, stage=stage)

    def rollback(self, actor: Actor) -> dict[str, Any]:
        return self.registry.rollback(actor)

    def serve_model(self, case_id: str) -> str:
        return self.registry.serve(case_id)

    def comparison(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for model_id, behavior in BEHAVIORS.items():
            matches, leaks = score_behavior(behavior)
            card = next((item for item in self.gateway.cards() if item.model_id == model_id), None)
            rows.append(
                {
                    "model_id": model_id,
                    "measured_exact_match": matches / len(CASES),
                    "phi_leaks": leaks,
                    "cost_units": None if card is None else card.cost_units,
                    "latency_units": None if card is None else card.latency_units,
                    "routing_quality": None if card is None else card.quality,
                    "in_router": card is not None,
                }
            )
        return {
            "dataset_version": DATASET_VERSION,
            "cases": len(CASES),
            "judge": judge_agreement(),
            "models": rows,
            "price": "none",
        }

    def _log_mlflow(self, card: Scorecard) -> None:
        if self.tracking_uri is None:
            return
        import mlflow

        # MLflow 3 rejects the filesystem store unless a maintenance flag is set.
        # The supported local store is SQLite. Callers pass that URI explicitly.
        mlflow.set_tracking_uri(self.tracking_uri)
        with mlflow.start_run(run_name=card.model_id):
            mlflow.log_param("dataset_version", card.dataset_version)
            mlflow.log_param("behavior", card.behavior)
            mlflow.log_metric("exact_match", card.exact_match)
            mlflow.log_metric("phi_leaks", float(card.phi_leaks))

    def read_run(self, run_id: str, actor: Actor) -> dict[str, Any]:
        run = self._require_run(run_id)
        case_id = run.get("case_id")
        if not isinstance(case_id, str):
            raise FlowError("unknown_run", "run was not found", 404)
        case = self._case(case_id)
        if actor.tenant_id != case.tenant_id:
            self.metrics.denials += 1
            self._audit(actor, "tenant_denied", run_id, "")
            raise FlowError("forbidden", "tenant boundary", 403)
        return run

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise FlowError("unknown_run", "run was not found", 404)
        return run

    def _audit(self, actor: Actor, action: str, subject: str, detail: str) -> None:
        message = redact(detail)
        if contains_phi(message):
            raise RuntimeError("audit redaction failed")
        self.store.add_audit(
            {
                "actor_id": actor.user_id,
                "action": action,
                "subject": subject,
                "message": message,
            }
        )

    def product_workflows(self) -> tuple[str, ...]:
        return WORKFLOWS
