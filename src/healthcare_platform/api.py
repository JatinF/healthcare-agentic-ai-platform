"""HTTP contracts. State changes require a synthetic bearer."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from healthcare_platform import __version__
from healthcare_platform.errors import FlowError
from healthcare_platform.gates import adapter_report
from healthcare_platform.identity import ORG, require_actor
from healthcare_platform.platform import Platform


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str | None = None


class StageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str


def create_app(platform: Platform | None = None) -> FastAPI:
    app = FastAPI(
        title="Healthcare Agentic AI Platform",
        version=__version__,
        description=(
            "Simulated multi-workflow agent platform. Drafts are not care decisions. "
            "No EHR is contacted."
        ),
    )
    app.state.platform = platform or Platform()

    @app.exception_handler(FlowError)
    def on_flow(_request: Request, exc: FlowError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.code, "message": exc.message}, status_code=exc.status_code
        )

    def current() -> Platform:
        runtime = app.state.platform
        if not isinstance(runtime, Platform):
            raise RuntimeError("platform missing")
        return runtime

    def actor_from(request: Request) -> Any:
        header = request.headers.get("authorization")
        token = None
        if header is not None and header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1]
        return require_actor(token)

    @app.get("/health")
    def health() -> dict[str, Any]:
        runtime = current()
        return {
            "status": "ok",
            "simulation": True,
            "clinically_validated": False,
            "version": __version__,
            "store": runtime.store.kind,
            "adapters": adapter_report(),
            "ehr_calls": runtime.ehr_calls,
            "organization": ORG,
            "workflows": list(runtime.product_workflows()),
        }

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(current().metrics.render(), media_type="text/plain")

    @app.post("/api/v1/workflows/{workflow_id}/runs")
    def start_run(workflow_id: str, body: RunBody, request: Request) -> dict[str, Any]:
        return current().run(workflow_id, body.case_id, actor_from(request), run_id=body.run_id)

    @app.post("/api/v1/runs/{run_id}/approve")
    def approve(run_id: str, request: Request) -> dict[str, Any]:
        return current().approve(run_id, actor_from(request))

    @app.post("/api/v1/runs/{run_id}/reject")
    def reject(run_id: str, request: Request) -> dict[str, Any]:
        return current().reject(run_id, actor_from(request))

    @app.post("/api/v1/runs/{run_id}/execute")
    def execute(run_id: str, request: Request) -> dict[str, Any]:
        return current().execute(run_id, actor_from(request))

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict[str, Any]:
        return current().read_run(run_id, actor_from(request))

    @app.post("/api/v1/evaluations/judge-review")
    def review(request: Request) -> dict[str, Any]:
        return current().review_judges(actor_from(request))

    @app.post("/api/v1/evaluations/{model_id}")
    def evaluate(model_id: str, request: Request) -> dict[str, Any]:
        return current().evaluate(model_id, actor_from(request))

    @app.post("/api/v1/registry/{model_id}/promote")
    def promote(model_id: str, body: StageBody, request: Request) -> dict[str, Any]:
        return current().promote(model_id, actor_from(request), stage=body.stage)

    @app.post("/api/v1/registry/rollback")
    def rollback(request: Request) -> dict[str, Any]:
        return current().rollback(actor_from(request))

    @app.get("/api/v1/reports/models")
    def report() -> dict[str, Any]:
        return current().comparison()

    return app


app = create_app()
