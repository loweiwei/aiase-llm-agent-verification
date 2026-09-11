# Open Track Selection Benchmark

Public development scenarios; these are not held-out results.

| Scenario | Tests | Exact | Greedy | Random mean | Candidates | Mutants |
|---|---:|---:|---:|---:|---:|---:|
| merge_intervals | 4 | 1.000 | 1.000 | 0.746 | 6 | 5 |
| top_k_frequent | 2 | 1.000 | 1.000 | 0.792 | 6 | 5 |
| valid_parentheses | 3 | 0.800 | 0.800 | 0.436 | 8 | 5 |

Random reports the mean over deterministic seeds 0-99 at the same test count selected by exact search.
Execution times are available in the JSON artifact and are environment-dependent.
