# Matched Raw / Format-Only / Full Validation

Responses collected: 108/108. Complete: True.

| Track | Configuration | Repetition rates | Mean | Sample SD |
|---|---|---|---:|---:|
| text2sql | raw_strict | 0.905, 0.905, 0.905 | 0.905 | 0.000 |
| text2sql | format_only | 0.905, 0.905, 0.905 | 0.905 | 0.000 |
| text2sql | full_validation | 0.905, 0.905, 0.905 | 0.905 | 0.000 |
| code_author | raw_strict | 1.000, 1.000, 1.000 | 1.000 | 0.000 |
| code_author | format_only | 1.000, 1.000, 1.000 | 1.000 | 0.000 |
| code_author | full_validation | 1.000, 1.000, 1.000 | 1.000 | 0.000 |
| bug_hunter | raw_strict | 0.500, 0.500, 0.500 | 0.500 | 0.000 |
| bug_hunter | format_only | 0.500, 0.500, 0.500 | 0.500 | 0.000 |
| bug_hunter | full_validation | 0.800, 0.800, 0.800 | 0.800 | 0.000 |

## Failure Reasons

- `text2sql/raw_strict`: {"execution": 6}
- `text2sql/format_only`: {"execution": 6}
- `text2sql/full_validation`: {"semantic": 6}
- `code_author/raw_strict`: {}
- `code_author/format_only`: {}
- `code_author/full_validation`: {}
- `bug_hunter/raw_strict`: {"false_negative": 12, "false_positive": 3}
- `bug_hunter/format_only`: {"false_negative": 12, "false_positive": 3}
- `bug_hunter/full_validation`: {"false_negative": 3, "false_positive": 3}

The same raw response is replayed through all three configurations. Public development/reference tasks; not held-out.
