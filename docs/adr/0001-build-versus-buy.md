# ADR 0001 — Build a small control plane

## Status

Accepted for this reference repository.

## Context

A bought agent platform would hide the integration layer, the policy check, and the release gate behind a product we do not operate. The point of this repository is to show those pieces on one runtime that three workflows share.

## Decision

Build a Python package: FastAPI, a LangGraph order of steps, a SQLite journal, a mock model gateway, and an evaluation gate. Do not depend on a vendor agent service.

Temporal was considered for durable execution. It is not adopted. The workstation has no Temporal server, and the retry story we need is already a journal of finished steps plus a unique effect key. Adding a server we cannot run would be a diagram, not a measurement.

## Consequences

The package is small enough to test in CI without external services. It is not a substitute for a vendor platform in a hospital network. Deployment stays NO-GO.
