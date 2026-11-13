# ADR 0003 — Mock providers in CI

## Status

Accepted.

## Context

Hosted model calls are not deterministic, they cost money, and they are outside the workstation gate. The routing decision still needs quality, cost, latency, and availability.

## Decision

Route among declared cards. Quality, cost units, and latency units are configuration. Wall-clock time of a platform run is measured separately and stored as `wall_seconds`. A live provider is not called. `price` stays `none`.

Failover is the path where no available card meets the 0.9 quality floor, so the cheapest available card is selected and marked.

## Consequences

CI can assert the selected model. The numbers are not a vendor latency benchmark.
