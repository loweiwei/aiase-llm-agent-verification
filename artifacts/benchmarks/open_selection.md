# Open Track Selection Benchmark

Public development scenarios; these are not held-out results.

| Scenario | Tests | Exact | Greedy | Random mean | Candidates | Mutants |
|---|---:|---:|---:|---:|---:|---:|
| merge_intervals | 4 | 1.000 | 1.000 | 0.746 | 6 | 5 |
| top_k_frequent | 2 | 1.000 | 1.000 | 0.792 | 6 | 5 |
| valid_parentheses | 3 | 0.800 | 0.800 | 0.436 | 8 | 5 |

Random reports the mean over deterministic seeds 0-99 at the same test count selected by exact search.
Execution times are environment-dependent and intentionally not emphasized in this portfolio summary.

## Interpretation

- Exact search enumerates candidate combinations when the search space is under the safety budget.
- Greedy is the deterministic fallback for larger instances; in these public scenarios it matches exact search.
- Random uses the same number of selected tests as exact search, so the comparison isolates the value of using the execution-derived kill matrix.
- These results show the selector is useful on the public development scenarios, but they are not hidden benchmark results.
