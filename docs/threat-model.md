# Threat model

This is a lab model for synthetic markers. It is not a clinical safety case and it is not a HIPAA assessment.

## Assets

- Synthetic markers `SYN-PHI-NAME-####` and `SYN-PHI-MRN-####` on each case.
- Draft text, traces, and audit rows.
- The effect journal for packet staging and recommendation release.

## Boundaries

- A bearer maps to one fixture actor. Comparison uses `secrets.compare_digest` after a length check. There is no external issuer.
- `workflow.run` does not include approve, promote, or packet stage.
- Chart read requires `tool:chart.read` and the same tenant as the case. The payload omits the patient token and the MRN.
- `phi.export` denies every fixture and increments the denied counter. The production path does not call the test hook that would count an accepted protected action.
- Consequential execute requires approval by a different person, then the matching tool scope. The effect key is unique. A second call returns the stored payload.
- Audit and trace text pass through the PHI redactor. A remaining marker raises before the row is trusted.
- Remote service URLs are blocked unless `HEALTHCARE_PLATFORM_ALLOW_REMOTE=1`. The blocked error does not contain the URL. Health does not dial.

## Out of scope

Live identity, real PHI, network policies, and clinical harm from a wrong draft. The drafts are labeled so a reader does not treat them as orders.
