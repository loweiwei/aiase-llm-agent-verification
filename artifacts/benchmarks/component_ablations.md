# Deterministic Component Ablations

Development/reference fixtures only; these are not raw-LLM or held-out results.

| Component | Reduced configuration | Full configuration | Metric |
|---|---:|---:|---|
| Text2SQL schema validation | 1.000 | 0.000 | invalid acceptance rate, lower is better |
| Code Author validation/fallback | 0.000 | 1.000 | reference-case pass rate |
| Code Author AST/policy | 1.000 | 0.000 | unsafe acceptance rate, lower is better |
| Code Author templates | 0.000 | 1.000 | reference-case pass rate |
| Bug Hunter dynamic audit | 0.000 | 0.500 | line/type overlap recall |

Bug Hunter full configuration clean false-positive rate: 0.000.
