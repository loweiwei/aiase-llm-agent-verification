# Deterministic Verification for LLM Software Engineering Agents

## Abstract

Large language models can generate SQL, Python functions and code-review reports, but a fluent answer may still violate a machine-readable contract, reference nonexistent schema fields, fail tests or identify the wrong defect. This project studies a hybrid workflow in which Hermes/LLM produces a candidate and deterministic code performs the checks that can be executed objectively. Four Skills instantiate the workflow: Text2SQL, Code Author, Bug Hunter and a mutation-testing Open Track. The main technical component, Open Test Killer, executes reference and mutant programs to construct a kill matrix, then selects a bounded test set using exact maximum coverage or deterministic greedy fallback. The AIASE 2026 course private evaluation awarded the original submission 91.38 overall and 93.2/100 for the Open Track. Current offline verification contains 192 passing Pytest checks, one skipped optional check, 90 Skill self-test scenarios and three regression suites. Public matched experiments compare methods reproducibly; teacher private results provide external held-out evidence but cannot be independently rerun.

## 1. Introduction

LLM software-engineering agents combine natural-language understanding with tools that edit or execute code. Their flexibility introduces a verification problem: the model is also the component most likely to produce malformed or semantically incorrect output. Asking the same model to state that its own answer is correct is not an independent check.

This project uses a simple separation of responsibility:

- The model interprets the task and proposes a candidate.
- A deterministic wrapper parses and normalizes the candidate.
- Static or dynamic checks produce objective evidence.
- The wrapper writes an atomic JSON result for the evaluator.

The design does not eliminate model errors. It aims to make failures visible, bounded and machine-checkable.

## 2. Research Questions

The portfolio version is organized around four questions:

1. Does deterministic validation reduce output-contract and execution failures compared with raw LLM output?
2. Which components, including AST checks, dynamic probes and fallback templates, contribute to reliability?
3. What coverage/cost trade-off exists between random, greedy and exact mutation-test selection?
4. How robust is the workflow to renamed identifiers, reordered candidates and rewritten task descriptions?

The portfolio summarizes a public-development matched replay of 108 raw responses through strict, format-only and full validation paths, plus the offline mutation-test comparison. Raw model outputs are intentionally not kept in the GitHub portfolio. The original submission also has teacher-held private evaluation; task-level private generalization details remain unavailable.

## 3. System Design

### 3.1 Output Contract

Each Skill writes a JSON object to the path supplied through `AIASE_RESULT_PATH`. Writes use a temporary file followed by `os.replace`, reducing the chance that the evaluator reads partial JSON. If Hermes fails to propagate the environment path, the development evaluator accepts only a fallback JSON object whose `task_id` matches the active task. It never accepts an unrelated newest file.

The local evaluator retries once only when no matching result exists. It does not retry an incorrect SQL query or select the best semantic answer across attempts. This follows the course no-result retry policy while avoiding best-of-N score inflation.

### 3.2 Text2SQL

Text2SQL receives a natural-language question and SQLite DDL. The model proposes one read-only query. The wrapper removes optional Markdown fences and a trailing semicolon, rejects multiple statements and forbidden DDL/DML, and uses SQLite `EXPLAIN` against an in-memory database built from the supplied schema.

The Skill passes the original payload and candidate SQL through a delimiter-based stdin protocol. This preserves the full schema without unsafe shell quoting. Unknown and ambiguous columns are replaced by a safe read-only fallback and assigned low confidence rather than reaching the evaluator as an executable error.

Execution accuracy is still required for semantic correctness. Schema validation can reject an invalid query but cannot prove that a valid query answers the question.

### 3.3 Code Author

Code Author proposes a Python function and passes it with the original payload to a deterministic wrapper. The wrapper checks:

- Python AST syntax and required entry point.
- Source-line budget.
- Forbidden and allowed imports.
- Unsafe top-level statements and dangerous calls.
- Public sample behavior.
- Task-family fallback templates when a candidate is invalid.

Candidate sample execution runs in a child process on Linux. The child receives wall-clock, CPU, address-space, file-size, file-descriptor and core-dump limits. It executes in a temporary directory with a minimal environment. These controls bound common failures but do not constitute a complete security sandbox.

### 3.4 Bug Hunter

Bug Hunter converts a model-proposed review into a normalized contract containing verdict, bug type, severity, line range, description and suggested fix. The normalizer removes placeholder, speculative and self-negating reports, clamps line ranges and maps invalid enum values.

For recognized task families, deterministic dynamic probes provide stronger evidence. When a model reports a concrete but incorrect bug and the deterministic audit finds a high-confidence execution failure, the audit result takes precedence. High-confidence clean reports are intentionally not overridden, preserving the original precision-oriented policy.

Dynamic audits use the same child-process resource and environment controls as Code Author.

### 3.5 Open Test Killer

Open Test Killer receives reference code, mutants, candidate inputs and a test budget. It executes each valid candidate against the reference and mutants. A candidate kills a mutant when the mutant returns a different value, raises an exception or times out while the reference succeeds.

The resulting binary kill matrix defines a maximum-coverage problem. For candidate combinations at or below 25,000, the selector enumerates combinations and applies deterministic tie-breaking: more killed mutants, fewer tests, then stable input order. Larger instances use greedy marginal coverage. A separate 2,000-call limit bounds matrix construction.

The output records selected inputs, expected values, per-test kills, killed and surviving mutants, mutation score, strategy and truncation status. An independent verifier can rerun the programs and recompute every field.

## 4. Reproducibility

The offline workflow supports Python 3.11 and 3.13 in GitHub Actions. Dependencies are pinned in `requirements.txt`. A single command builds SQLite fixtures and runs root tests, Skill self-tests, regressions and repository verification:

```bash
make test
```

The Open Track selection comparison is generated with:

```bash
make benchmark
```

The lightweight benchmark summaries report scenario-level mutation scores and selected-test counts. Raw machine logs are not kept in the portfolio branch because they quickly become stale and make the repository harder to read.

Model-dependent evaluation is separate because it requires Hermes, provider credentials and a model snapshot that the repository does not control.

## 5. Results

### 5.1 External Course Evaluation

The AIASE 2026 automated evaluation reported:

| Track | Score |
|---|---:|
| Basic Text2SQL | 30.0 / 30 |
| Pairwise Bug Hunter | 8.33 / 10 |
| Open Track | 93.2 / 100 |
| Overall | 91.38 |

The same review reported Bug Hunter buggy F1 around 0.67, showing that defect recall remains an important weakness despite strong local regressions.

### 5.2 Offline Verification

The current portfolio branch passes 192 root Pytest checks with one optional skipped check, 45 Code Author self-tests, 31 Bug Hunter self-tests, 14 Open Track self-tests and all three regression suites. Repository verification passes 27/27 checks.

These counts measure deterministic fixtures and contracts. They should not be interpreted as independent held-out benchmark tasks.

### 5.3 Open Track Development Benchmark

On three public development scenarios, exact and greedy selection reach mutation scores of 1.0, 1.0 and 0.8. At the same selected-test count, a deterministic 100-seed random baseline averages 0.746, 0.792 and 0.436. Exact and greedy choose the same sets on these small scenarios, so the public data does not demonstrate an exact-search advantage. Teacher private Open evaluation reports deterministic behavior and robustness to input reordering, but does not expose enough task-level data to compare exact and greedy privately.

### 5.4 Matched LLM Baseline

The same 108 no-tool model responses were replayed through strict raw, format-only and full deterministic processing. Weighted pass rates were 0.806, 0.806 and 0.889. The improvement was isolated to Bug Hunter, which increased from 0.500 to 0.800 through dynamic audit. Text2SQL remained at 0.905: validation converted six execution errors into safe but semantically incorrect fallbacks. Code Author remained at 1.000 because all raw candidates already passed the small reference suites. These results reject a broad claim that every deterministic wrapper necessarily raises task accuracy; the observed benefit is component- and task-dependent.

## 6. Threats to Validity

### Internal Validity

Implementation and tests may share assumptions. The Open Track verifier reruns programs but imports the same execution helper, so a shared normalization bug remains possible. Some regression tasks are also used during development.

### External Validity

The available Text2SQL and Pairwise sets are small and course-specific. Results cannot be generalized to Spider, HumanEval, SWE-bench or arbitrary production repositories.

### Construct Validity

Mutation score depends on mutant quality and equivalent mutants. Public-test pass rate does not guarantee hidden-case correctness. Confidence fields are heuristic status values, not calibrated probabilities.

### Reproducibility

Offline code is reproducible from pinned dependencies, but model output depends on Hermes, provider behavior and model updates. Formal model experiments must preserve task-level outputs and run metadata.

### Security

Process limits reduce the effect of runaway code but do not provide filesystem, network or kernel-level isolation. Adversarial deployment requires a disposable container or VM with stronger controls.

## 7. Future Work

The strongest next validation step would be re-running this portfolio commit on an independently governed private suite. Additional useful evidence would include private Bug Hunter precision/recall breakdowns and token/cost metrics.

## 8. Conclusion

This project demonstrates a practical architecture for placing deterministic checks around probabilistic software-engineering agents. Its strongest evidence comes from the mutation-testing component, where expected values and mutant kills are execution-derived and independently recomputable. The portfolio does not claim universal accuracy or secure arbitrary-code execution. Public matched replay isolates component effects, while teacher private scores provide external evidence for the original submission without exposing private labels.

## References

This portfolio omits a formal literature review. The implementation uses standard ideas from Text2SQL validation, mutation testing, metamorphic testing and sandboxed code execution.
