"""LangGraph step order with a journal so a retry does not repeat a finished step."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from healthcare_platform.cases import WORKFLOWS, Case
from healthcare_platform.errors import FlowError
from healthcare_platform.gateway import ModelGateway
from healthcare_platform.identity import Actor, actor_by_id
from healthcare_platform.privacy import redact_value
from healthcare_platform.store import Store
from healthcare_platform.tools import ToolGate
from healthcare_platform.workflows import CONSEQUENTIAL, compose, schema_errors


class FlowState(TypedDict, total=False):
    run_id: str
    case_id: str
    actor_id: str
    retrieval: dict[str, str]
    tools: list[str]
    model_id: str
    behavior: str
    quality: float
    cost_units: int
    latency_units: int
    failover: bool
    below_quality_floor: bool
    draft_raw_redacted: object
    schema_errors: list[str]
    status: str
    output: object
    phi_blocked: bool
    consequential: bool


class GraphRuntime:
    def __init__(self, store: Store, gateway: ModelGateway, tools: ToolGate) -> None:
        self.store = store
        self.gateway = gateway
        self.tools = tools
        self.fail_remaining: dict[str, int] = {}
        self.allowed: set[str] = set(WORKFLOWS)
        self.extra_cases: dict[str, Case] = {}
        builder: StateGraph[FlowState] = StateGraph(FlowState)
        builder.add_node("retrieve_chart", self._retrieve)
        builder.add_node("choose_model", self._choose)
        builder.add_node("compose_draft", self._compose)
        builder.add_node("check_schema", self._check)
        builder.add_node("apply_policy", self._policy)
        builder.add_edge(START, "retrieve_chart")
        builder.add_edge("retrieve_chart", "choose_model")
        builder.add_edge("choose_model", "compose_draft")
        builder.add_edge("compose_draft", "check_schema")
        builder.add_edge("check_schema", "apply_policy")
        builder.add_edge("apply_policy", END)
        self.graph = builder.compile()

    def invoke(self, run_id: str, case: Case, actor: Actor) -> dict[str, Any]:
        if case.workflow_id not in self.allowed:
            raise FlowError("unknown_workflow", "workflow is not registered", 404)
        initial: FlowState = {
            "run_id": run_id,
            "case_id": case.case_id,
            "actor_id": actor.user_id,
        }
        self.graph.invoke(initial)
        merged: dict[str, Any] = {}
        for name in (
            "retrieve_chart",
            "choose_model",
            "compose_draft",
            "check_schema",
            "apply_policy",
        ):
            step = self.store.get_step(run_id, name)
            if step is None:
                raise RuntimeError(f"step {name} missing after the graph returned")
            merged.update(step)
        return merged

    def _lookup_case(self, state: FlowState) -> Case:
        return _case_from_state(state, self.extra_cases)

    def _cached(self, state: FlowState, name: str) -> dict[str, Any] | None:
        run_id = state.get("run_id")
        if not isinstance(run_id, str):
            raise RuntimeError("run id missing")
        return self.store.get_step(run_id, name)

    def _save(self, state: FlowState, name: str, payload: dict[str, Any]) -> None:
        run_id = state.get("run_id")
        if not isinstance(run_id, str):
            raise RuntimeError("run id missing")
        self.store.save_step(run_id, name, payload)

    def _maybe_fail(self, name: str) -> None:
        left = self.fail_remaining.get(name, 0)
        if left > 0:
            self.fail_remaining[name] = left - 1
            raise RuntimeError(f"injected failure at {name}")

    def _carry(self, state: FlowState, payload: dict[str, Any]) -> FlowState:
        # LangGraph 1.2 replaces the dict state with the node return.
        carried: dict[str, Any] = dict(state)
        carried.update(payload)
        return carried  # type: ignore[return-value]

    def _retrieve(self, state: FlowState) -> FlowState:
        cached = self._cached(state, "retrieve_chart")
        if cached is not None:
            return self._carry(state, cached)
        self._maybe_fail("retrieve_chart")
        case = self._lookup_case(state)
        actor = _actor_from_state(state)
        chart = self.tools.chart_read(actor, case)
        payload = {"retrieval": chart, "tools": ["chart.read"]}
        self._save(state, "retrieve_chart", payload)
        return self._carry(state, payload)

    def _choose(self, state: FlowState) -> FlowState:
        cached = self._cached(state, "choose_model")
        if cached is not None:
            return self._carry(state, cached)
        self._maybe_fail("choose_model")
        route = self.gateway.choose()
        payload = {
            "model_id": route.model_id,
            "behavior": route.behavior,
            "quality": route.quality,
            "cost_units": route.cost_units,
            "latency_units": route.latency_units,
            "failover": route.failover,
            "below_quality_floor": route.below_quality_floor,
        }
        self._save(state, "choose_model", payload)
        return self._carry(state, payload)

    def _compose(self, state: FlowState) -> FlowState:
        cached = self._cached(state, "compose_draft")
        if cached is not None:
            return self._carry(state, cached)
        self._maybe_fail("compose_draft")
        case = self._lookup_case(state)
        behavior = state.get("behavior")
        if not isinstance(behavior, str):
            raise RuntimeError("model behavior missing")
        draft = compose(case.workflow_id, case, behavior)
        payload = {"draft_raw_redacted": redact_value(draft), "behavior": behavior}
        self._save(state, "compose_draft", payload)
        return self._carry(state, payload)

    def _check(self, state: FlowState) -> FlowState:
        cached = self._cached(state, "check_schema")
        if cached is not None:
            return self._carry(state, cached)
        case = self._lookup_case(state)
        behavior = state.get("behavior")
        if not isinstance(behavior, str):
            raise RuntimeError("model behavior missing")
        draft = compose(case.workflow_id, case, behavior)
        payload = {"schema_errors": schema_errors(case.workflow_id, draft)}
        self._save(state, "check_schema", payload)
        return self._carry(state, payload)

    def _policy(self, state: FlowState) -> FlowState:
        cached = self._cached(state, "apply_policy")
        if cached is not None:
            return self._carry(state, cached)
        case = self._lookup_case(state)
        behavior = state.get("behavior")
        if not isinstance(behavior, str):
            raise RuntimeError("model behavior missing")
        draft = compose(case.workflow_id, case, behavior)
        leaked = any(isinstance(value, str) and "SYN-PHI-" in value for value in draft.values())
        errors = state.get("schema_errors")
        invalid = isinstance(errors, list) and len(errors) > 0
        if leaked or invalid:
            status = "BLOCKED"
        elif case.workflow_id in CONSEQUENTIAL:
            status = "AWAITING_APPROVAL"
        else:
            status = "DRAFT_READY"
        payload = {
            "status": status,
            "output": redact_value(draft),
            "phi_blocked": leaked,
            "consequential": case.workflow_id in CONSEQUENTIAL,
        }
        self._save(state, "apply_policy", payload)
        return self._carry(state, payload)


def _case_from_state(state: FlowState, extra: dict[str, Case]) -> Case:
    from healthcare_platform.cases import BY_ID

    case_id = state.get("case_id")
    if not isinstance(case_id, str):
        raise RuntimeError("case id missing")
    case = BY_ID.get(case_id) or extra.get(case_id)
    if case is None:
        raise FlowError("unknown_case", "case is not in the synthetic catalog", 404)
    return case


def _actor_from_state(state: FlowState) -> Actor:
    actor_id = state.get("actor_id")
    if not isinstance(actor_id, str):
        raise FlowError("unauthorized", "actor missing from the run", 401)
    actor = actor_by_id(actor_id)
    if actor is None:
        raise FlowError("unauthorized", "actor missing from the run", 401)
    return actor
