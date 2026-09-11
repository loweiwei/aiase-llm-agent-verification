# Controlled Model Experiment: gemma4_validated_3x_20260829

Three matched repetitions on course public development tasks. These are not held-out results.

| Skill | Repetition rates | Mean | Sample SD | Pooled | Mean task sec |
|---|---|---:|---:|---:|---:|
| bug-hunter-loweiwei | 1.000, 0.800, 0.600 | 0.800 | 0.200 | 0.800 | 55.67 |
| code-author-loweiwei | 0.800, 0.400, 0.600 | 0.600 | 0.200 | 0.600 | 20.05 |
| text2sql-loweiwei | 0.857, 0.905, 0.952 | 0.905 | 0.048 | 0.905 | 17.47 |

## Failure Counts

- `bug-hunter-loweiwei`: {"semantic_model_error": 3}
- `code-author-loweiwei`: {"contract_or_tool_use": 6}
- `text2sql-loweiwei`: {"contract_or_tool_use": 1, "semantic_model_error": 5}

Token usage is unavailable and remains `null`. One invalid model-alias setup run was excluded before analysis and is documented in the manifest.
