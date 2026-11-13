# Deployment

![What ran on this workstation](diagrams/deployment.svg)

## Decision

NO-GO. The API can serve drafts on localhost. It is not cleared for a shared environment, a hospital network, or an unsupervised workflow.

## Workstation path

This path produced `benchmarks/latest.json` and the local pytest run.

- OS: Windows. Processor: 11th Gen Intel(R) Core(TM) i7-1185G7 @ 3.00GHz. 4 cores. 8 logical processors.
- At the benchmark CIM read, free physical memory was 9432996 KB and total visible memory was 32916868 KB.
- Python 3.12.10 in `.venv`.
- Store: SQLite, `sqlite://`, `StaticPool`, `check_same_thread=False`.
- Stream: in-process topic `healthcare.runs.v1`. `REDIS_URL` unset, so the gate reports `not-run`. The runtime does not open a Redis client in either case.
- Models: mock adapters only. `hosted_model` is `not-run`.
- Commands that ran: `python -m pytest`, `ruff check`, `mypy`, `scripts/benchmark.py`, `scripts/export_openapi.py`, `python -m healthcare_platform demo`.

Docker and kubectl were not on this workstation's PATH when the repository was assembled. A local image build was not run. `deploy/k8s/platform.yaml` is marked `applied: false`. `deploy/grafana/dashboard.json` was not imported.

## Compose sketch

`docker-compose.yml` names an API image, postgres:16, and redis:7. The API service sets `HEALTHCARE_PLATFORM_ALLOW_REMOTE=1` so a future compose network could pass the gate. That file was not started here. The application still journals in SQLite unless `DATABASE_URL` is a postgres URL, and it still publishes on the in-process stream.

The Dockerfile uses `python:3.12-slim`, creates user id 10001, and starts `python -m healthcare_platform serve`.

## GitHub Actions

`.github/workflows/ci.yml` on `ubuntu-24.04`:

| Job | What it runs |
| --- | --- |
| `test` | `pip install -e ".[dev]"`, ruff, mypy, pytest. Adapter URLs are not set. |
| `integration` | Postgres 16. `pip install -e ".[dev,postgres]"`. `tests/integration/test_postgres.py` with `postgresql+psycopg://lab:lab@127.0.0.1:5432/labdb`. |
| `docker-build` | `docker build` and `docker compose config`. The stack is not started. |

`.github/workflows/security.yml` runs `scripts/reject_private_keys.py`. The private-key markers in that file are split so the scanner does not match itself.

The first commit does not list Actions run ids. Those ids belong in a later commit after the jobs finish.

## Gates

| Variable | Unset | Local host | Other host |
| --- | --- | --- | --- |
| `DATABASE_URL` | SQLite default | engine may connect | blocked |
| `REDIS_URL` | not-run | gate says local; this build still does not open a client | blocked |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | not-run | gate says local; no exporter is configured by the app | blocked |

`ehr` and `hosted_model` are fixed at `not-run`. `GET /health` reads the gate table and does not dial.
