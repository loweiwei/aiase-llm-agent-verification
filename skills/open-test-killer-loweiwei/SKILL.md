---
name: open-test-killer-loweiwei
description: Deterministically select compact tests that kill Python mutants by executing reference and mutant implementations for AIASE 2026 Open Track.
version: 2.0.0
metadata:
  hermes:
    tags: [testing, mutation-testing, open-track, aiase-2026]
    category: code
    requires_toolsets: [terminal]
required_environment_variables:
  - name: AIASE_RESULT_PATH
    prompt: Runtime result file path
    required_for: file-based AIASE result output
    optional: true
---

# Test Killer Skill

## When to Use

Use when invoked with `/open-test-killer-loweiwei {json}` for an AIASE 2026 Open Track mutation-test selection payload.

The input JSON contains:
- `task_id`
- `entry_point`
- `reference_code`
- `mutants`
- `candidate_inputs`
- `max_tests`
- optional metadata such as `description`

## Procedure

Use the terminal tool exactly once. Do not use background/process tools. Do not manually analyze the task. Do not invent candidate inputs. Do not hand-write the final JSON contract.

Mandatory sequence:
- Think privately only as needed to prepare the terminal command.
- Call the terminal tool exactly once to run `python3 <skill_dir>/scripts/run.py ...`.
- Immediately stop. Do not produce a final assistant message.

Always pass the full original input JSON payload directly to `scripts/run.py`. The script is responsible for executing the reference implementation and mutants, selecting tests, atomic-writing the final result JSON to `AIASE_RESULT_PATH` when set, and printing the same final fenced JSON block to stdout.

Use this portable command. `<skill_dir>` is the skill directory path provided by Hermes as `[Skill directory: ...]`. It may be an absolute path, but must not be hardcoded to any machine-specific path.

~~~bash
python3 <skill_dir>/scripts/run.py <<'AIASETESTKILLERJSON'
<copy the full original input JSON payload verbatim here>
AIASETESTKILLERJSON
~~~

The terminal tool must be called exactly once.

Do not retry. Do not output the JSON contract in chat yourself; `scripts/run.py` is the only component allowed to print the final fenced JSON block to terminal stdout. Do not add explanation before or after the terminal call. Do not write Markdown fences manually. After the terminal call completes, stop with no final message and zero characters.

The script atomic-writes the final result JSON to the file specified by `AIASE_RESULT_PATH`, or to `./aiase_result.json` when the environment variable is unset. It also prints the same result as the final fenced JSON block on stdout for common-contract compatibility.

## Selection Rules

The deterministic script must:
- use only `candidate_inputs` from the input payload,
- execute the reference implementation to compute expected outputs,
- execute each mutant on each valid candidate input,
- treat mutant output mismatch as a kill,
- treat mutant exception or timeout as a kill,
- treat reference exception, reference timeout, or non-JSON-serializable reference output as making that candidate invalid,
- select at most `max_tests` tests,
- use exact max-coverage search when the combination count is within the safety budget,
- otherwise use a deterministic greedy fallback,
- set `verdict` to `pass` only when `kill_rate >= 0.8` and evaluation was not truncated.

## Pitfalls

- Do not use any machine-specific absolute path.
- Do not invent new candidate inputs.
- Do not manually decide which mutants are killed.
- Do not hand-write the final JSON contract.
- Do not print the result JSON in chat yourself; only `scripts/run.py` may print the terminal stdout fenced JSON block.
- Do not output a success, completion, verification, or result message.
- Do not skip `AIASE_RESULT_PATH`; the grader reads the result file.
- Do not depend on public scenario task IDs or fixed candidate ordering.
- Do not use network access or external APIs.

## Contract

The successful result file must contain a JSON object with:
- `ok`
- `task_id`
- `entry_point`
- `selected_tests`
- `killed_mutants`
- `unkilled_mutants`
- `survived_mutants`
- `kill_rate`
- `num_selected_tests`
- `max_tests`
- `total_mutants`
- `verdict`
- `confidence`
- `rationale`
- `evaluation_stats` for successful runs

Each selected test must contain:
- `id`
- `args`
- `kwargs`
- `expected`
- `kills`

Failure results are also written as JSON by `scripts/run.py`, with `ok` set to `false` and an `error_type` / `message` when applicable.

## Verification

The terminal command writes the result file as the primary output. `scripts/run.py` also prints the same object as the final fenced JSON block on terminal stdout for common-contract compatibility. The assistant must not add any final chat message after the terminal call.

A valid successful result must:
- be a JSON object,
- have `ok` equal to `true`,
- have `task_id` equal to the input `task_id`,
- have `entry_point` equal to the input `entry_point`,
- select tests only from `candidate_inputs`,
- keep `num_selected_tests <= max_tests`,
- report `killed_mutants`, `unkilled_mutants`, and `kill_rate` consistently with the selected tests.
- have `verdict == "pass"` iff `kill_rate >= 0.8` and `evaluation_stats.evaluation_truncated` is false.
