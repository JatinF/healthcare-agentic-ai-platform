# Onboard a workflow

The product workflows are `clinical-document-draft`, `referral-triage`, and `prior-auth-prep`. A fourth id, `template-echo`, is the pattern for a new one. It is not registered until a caller adds it.

1. Build a `Case`. Set `workflow_id` to `template-echo` and `tenant_id` to `SYN-TENANT-NORTHBRIDGE`. Put any synthetic patient marker only in `patient_token` or `mrn`. The composer for this template returns `echo` and `draft_notice`. It does not copy those markers.
2. Call `Platform.register_template(case)`. That adds the workflow id to the runtime allow-list and stores the case beside the catalog.
3. Call `run` with an actor who holds `workflow.run` and `tool:chart.read` in the same tenant.
4. Expect status `DRAFT_READY` and an output that contains the topic and `DRAFT_NOT_A_CARE_DECISION`.

`tests/test_acceptance.py` does this with case `TPL-0001`. Catalog cases are not inserted by the template. A run before `register_template` returns `unknown_case` for an id that is not in the catalog.

To add a consequential workflow, extend `compose`, `schema_errors`, and `matches_gold`, and add the id to `CONSEQUENTIAL` only if a later effect must wait for a different person. Do not add a client boolean that skips that wait.
