# ADR 0004 — SQLite by default, and a stored judge

## Status

Accepted.

## Context

Postgres is the intended shared database. It is not installed locally. A live LLM judge would be another hosted model, and it would not be calibratable inside a unit test.

## Decision

Default the journal to SQLite. Use Postgres only when `DATABASE_URL` starts with `postgresql` and the host passes the local gate. The Actions integration job is that path.

The judge is a label on the case. Twelve labels disagree with the expert. Promotion requires a recorded review of those ids. MLflow logs the scorecard when the caller passes a SQLite tracking URI. The file store is avoided because MLflow 3 rejects it unless a maintenance flag is set.

## Consequences

Local tests do not need Postgres. The disagreement count is a property of the seed, not a model opinion.
