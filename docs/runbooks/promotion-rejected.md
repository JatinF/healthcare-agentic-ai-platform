# Promotion rejected

## Symptom

`promote` returns `promoted: false` and an audit row `promotion_rejected`.

## Reasons

| Reason | Meaning |
| --- | --- |
| `phi_leak` | The offline run leaked a synthetic marker |
| `quality` | Exact match is below 0.9 |
| `uncalibrated_judge` | The twelve disagreements have no review row |
| `regression` | Exact match is below the active model |

## Action

Review judges with an actor who holds `eval.review` before promoting. Do not lower the floor to make `mock-cheap` or `mock-leaky` active. Rollback only restores a model that was previously active and then retired.
