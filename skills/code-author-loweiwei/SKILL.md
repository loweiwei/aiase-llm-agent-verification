---
name: code-author-loweiwei
description: Generate Python function code for AIASE 2026 Pairwise Code Author and write the result through scripts/run.py using the file-based output contract.
version: 2.0.0
metadata:
  hermes:
    tags: [code, python, pairwise, aiase-2026]
    category: code
    requires_toolsets: [terminal]
required_environment_variables:
  - name: AIASE_RESULT_PATH
    prompt: Runtime result file path
    required_for: file-based AIASE result output
    optional: true
---

# Code Author Skill

## When to Use

Use when invoked with `/code-author-loweiwei {json}` for an AIASE 2026 Pairwise Code Author payload.

The input JSON contains `task_id`, `task_description`, `constraints`, and optional sample test cases. The `constraints` object includes the requested `entry_function`.

## Critical Visible Output Rule

The final assistant response must contain zero characters. The terminal call is the only visible action. After the terminal call returns, end the turn silently.

Mandatory sequence:
- Think privately.
- Call the terminal tool exactly once to run `python3 <skill_dir>/scripts/run.py ...`.
- Immediately stop. Do not produce a final assistant message.

Never print or describe:
- the solution reasoning,
- the generated code,
- the final JSON,
- the result file path,
- a success or validation message,
- Markdown fences.

If the result file was written successfully, do not say so. Stop with an empty final response. Any non-empty final assistant response, including a success sentence, fails this skill.

## Procedure

Use the terminal tool exactly once. Do not use background/process tools. Do not hand-write the final JSON contract.

The only allowed visible action is one terminal call. Do not answer in natural language. Do not summarize the solution. Do not output generated code in chat. Do not say the result was written. Do not write a completion message. After the terminal call completes, stop. Stop with no final message and zero characters.

Privately read the full `task_description`, `constraints`, and public samples. Write one candidate Python solution that directly follows the task semantics. Do not assume that a familiar function name always means the standard LeetCode version; follow the exact task description and public samples first.

Then pass the original JSON payload and the raw candidate code to `scripts/run.py`. The script will validate the candidate, run public samples, check imports/sandbox/SLOC, and choose a safe fallback only when the candidate is invalid or clearly worse.

Use this portable command. `<skill_dir>` is the skill directory path provided by Hermes as `[Skill directory: ...]`. It may be an absolute path, but must not be hardcoded to any machine-specific path.


~~~bash
python3 <skill_dir>/scripts/run.py - <<'AIASERUNINPUT'
<copy the full original input JSON payload verbatim here>
__AIASERUN_CANDIDATE_CODE_V1__
<paste raw candidate Python code here>
AIASERUNINPUT
~~~

The terminal tool must be called exactly once. Do not retry. Do not output the JSON contract in chat or stdout. Do not output generated code in chat or stdout. Do not answer in natural language. Do not say the result was written or validation completed. Do not add explanation before or after the terminal call. Do not write Markdown fences. After the terminal call completes, stop. Stop with no final message and zero characters.

The script writes the final result JSON only to the file specified by `AIASE_RESULT_PATH`. If `AIASE_RESULT_PATH` is not set, it writes to `./aiase_result.json`.

The grader reads the result file, not stdout or chat text.

## Private Solution Method

Before writing candidate code:

1. Extract the exact entry function name from `constraints`.
2. Extract the input/output contract from `task_description`.
3. Treat public samples as binding examples.
4. Do not rely only on the function name. A familiar name may have modified semantics.
5. Check edge cases:
   - empty input,
   - singleton input,
   - duplicates,
   - negative or zero values,
   - equality boundaries,
   - ordering and stability,
   - ties,
   - invalid inputs only if required by the task.
6. For comparison operators, check the equality case explicitly.
7. For loops, dynamic programming, recursion, parsing, or accumulation logic, trace the smallest non-trivial example.
8. Write the simplest correct implementation for the current task, not for a memorized task with a similar name.
9. Do not use `task_id` to decide the algorithm.
10. Do not hardcode public sample outputs. Generalize from the task description.

## Candidate Rules

Candidate code must:
- define the requested entry function exactly,
- avoid file, network, subprocess, multiprocessing, threading, and other external I/O,
- avoid `eval`, `exec`, `open`, `input`, `compile`, and `print`,
- use only allowed imports from the task constraints,
- stay under 500 SLOC,
- handle empty input and edge cases,
- not include Markdown fences.
- implement the general task, not only the public samples,
- not branch on `task_id`,
- not hardcode exact public sample inputs,
- follow samples and task description if they conflict with a familiar standard problem.

## Pitfalls

- Do not use any machine-specific absolute path.
- Do not hand-write the final JSON contract.
- Do not print the result JSON to chat or stdout.
- Do not output a success, completion, or verification message.
- Do not skip `AIASE_RESULT_PATH`; the grader reads the result file.
- Do not use deterministic templates as the official first choice; `scripts/run.py` keeps them only as fallback if candidate code is invalid or clearly worse.
- Do not rely on task id, fixed public scenario strings, or familiar task names to choose an algorithm.
- The raw teacher CLI flags are supported by `run.py` for compatibility, but the official `SKILL.md` flow uses a heredoc marker because candidate Python code may contain quotes and newlines.

## Contract

The result file must contain a JSON object with `task_id`, `code`, `loc`, `self_test_results`, `rationale`, and `confidence`.

## Verification

The terminal command writes the result file. The grader reads the result file from `AIASE_RESULT_PATH`, not stdout or chat text.

A valid result must be a JSON object, have `task_id` equal to the input `task_id`, contain non-empty Python code, define the requested entry function, contain `self_test_results`, keep `loc` within the task limit, and contain `confidence` between 0.0 and 1.0.
