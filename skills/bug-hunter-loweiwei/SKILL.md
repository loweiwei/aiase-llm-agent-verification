---
name: bug-hunter-loweiwei
description: Review Python code for AIASE 2026 Pairwise Bug Hunter, then pass a candidate bug report through scripts/run.py for validation and file-based output.
version: 3.0.0
metadata:
  hermes:
    tags: [code, audit, bug-hunter, pairwise, aiase-2026]
    category: code
    requires_toolsets: [terminal]
---

# Bug Hunter Skill

## When to Use

Use when invoked with `/bug-hunter-loweiwei {json}` for an AIASE 2026 Pairwise Bug Hunter payload containing `task_id`, `task_description`, `code`, and optional `constraints`.

## Critical Visible Output Rule

If you output natural language, the skill fails. If you output Markdown fences, the skill fails. If you print the final JSON in chat, the skill fails.

The final assistant response must contain zero characters. The terminal call is the only visible action. After the terminal call returns, end the turn silently.

Never print or describe:

- the audit reasoning,
- the candidate report,
- the final JSON,
- the result file path,
- a success or validation message,
- `# Result`,
- Markdown fences.

If you are tempted to summarize, do not. If the result file was written successfully, do not say so. Stop with an empty final response.

## Procedure

Use the terminal tool exactly once. Do not use background/process tools. Privately analyze the input `task_description` and `code`, then prepare a candidate bug report. Do not output the candidate report in chat. Your visible assistant response after the terminal call must be empty; do not print the result file, do not mention where it was written, and do not provide a final summary.

Prioritize precision over recall. If there is no high-confidence, concrete, triggerable bug, use `verdict="clean"` and `bugs=[]`.

Use this portable command. `<skill_dir>` is the skill directory path provided by Hermes as `[Skill directory: ...]`. It may be an absolute path, but must not be hardcoded to any machine-specific path.

Do not write any analysis outside the heredoc. The private analysis and candidate report are only internal content used to construct the heredoc. The assistant-visible response must contain only the terminal tool call and then no final text.

~~~bash
python3 <skill_dir>/scripts/run.py - <<'AIASEBUGRUN'
<copy the full original input JSON payload verbatim here>
__AIASE_BUG_REPORT_V1__
<paste candidate bug report JSON here>
AIASEBUGRUN
~~~

The terminal tool must be called exactly once. The only allowed visible action is one terminal call. Do not answer in natural language. Do not summarize the audit. Do not say validation completed. Do not say the result is stored anywhere. Do not print the final JSON. Do not write `# Result`. Do not mention output limits. Do not retry. Do not output JSON in chat or stdout. Do not add explanation before or after the terminal call. Do not write Markdown fences. After the terminal call completes, stop immediately with no final message.

The script validates and normalizes the candidate report, then writes the final result JSON only to the file specified by `AIASE_RESULT_PATH`. If `AIASE_RESULT_PATH` is not set, it writes to `./aiase_result.json`.

The grader reads the result file, not stdout or chat text.

## Private Review Method

Before preparing the candidate bug report, privately perform a semantic code review.

1. Extract the task contract:
   - required entry function,
   - valid input domain and preconditions,
   - required output behavior,
   - special requirements such as empty input, singleton input, duplicates, ties, ordering, inclusiveness, touching/overlapping boundaries, or invalid input handling.

2. Search for concrete counterexamples:
   - empty input,
   - singleton input,
   - duplicate values,
   - equality boundary cases,
   - first/last element cases,
   - negative or zero values when relevant,
   - tie cases when the task mentions closest, minimum, maximum, top-k, earliest, latest, or ordering,
   - the smallest non-trivial positive example for loops, dynamic programming, recurrence, counting, parsing, or accumulation logic.

   Always check normal valid-domain behavior before invalid-input behavior. Invalid-input bugs are allowed, but they must not replace a stronger wrong-answer bug on valid inputs.

   For 2D grids, counting paths, tables, matrices, or dynamic programming, privately trace the smallest examples that require an update step, such as a 2-by-2 shape and one slightly larger rectangular shape when applicable. Compare the mathematically expected count/value with the code's recurrence output.

   For quoted, escaped, delimited, tokenized, or parsed text formats, privately trace a valid input where the delimiter appears inside a quoted/grouped context and a valid input where the required escape convention appears. Compare the expected tokens with the code's branch behavior.

   For ranking, kth, nth, top-k, position, index, or ordinal tasks, explicitly determine whether the task uses 1-based or 0-based semantics. Then trace `k=1`, `k=len(collection)`, `k<1`, and `k>len(collection)` when relevant. If the task says 1-based and the code indexes with `[k]`, that is a concrete off-by-one bug: `k=1` returns the second item and `k=len(collection)` is out of range.

3. For comparison operators, explicitly check boundary equality:
   - If the code uses `<`, `<=`, `>`, or `>=`, simulate the case where both sides are equal.
   - Decide from the task description whether equality should be accepted, rejected, merged, split, included, excluded, or treated as a tie.
   - Report a bug only if this produces a concrete mismatch.
   - Before declaring clean, make a private table for every comparison operator: code condition, equality case, expected branch from the task contract, actual branch taken by the code, and whether they differ.
   - For interval, range, boundary, overlap, adjacency, inclusiveness, or touching-boundary tasks, always test an equality-boundary example where one boundary exactly equals the other boundary. If the task says such boundaries should combine, overlap, touch, include, or count as the same group, then a branch that separates or excludes them is a concrete bug.

   For control-flow statements, explicitly account for `continue`, `break`, `return`, and exceptions. If a branch executes `continue`, statements later in the loop body are skipped for that iteration. If a branch executes `return`, no later code in the function runs. Do not report an increment/update bug unless the concrete trace proves the supposedly extra or missing statement actually executes.

4. For each possible bug, require evidence:
   - a concrete trigger input,
   - the expected behavior from the task description,
   - the actual behavior implied by the code,
   - the smallest relevant line range.

   For loops, dynamic programming, recurrence, counting, parsing, or accumulation logic, trace at least one smallest non-trivial valid example step by step. Derive the expected result from the task contract first, then compare it with the value produced by the code branch or recurrence. Do not stop after checking only invalid-input edge cases when the task also has normal valid examples.

   Choose `line_start` and `line_end` as the smallest code line range that directly causes the wrong behavior. For a crash, use the exact line with the failing operation, indexing, attribute access, call, or arithmetic expression. For a wrong branch, use the exact line with the condition or recurrence that sends execution the wrong way. For parser, loop, split, accumulation, or state-machine bugs, use the exact condition/update line that mishandles the concrete character, token, element, or state. Do not point to setup, sorting, initialization, the whole loop, or the whole function unless every line is necessary. Prefer a single exact line when one condition or assignment is responsible.

5. Do not report a bug unless you can explain a concrete failing behavior.
   If you cannot find a concrete counterexample, use:
   `{"verdict":"clean","bugs":[],"confidence":0.6}`

   Never output a candidate bug whose description says there is no bug, no fix is needed, cannot find a concrete bug, or should return clean. If that is your conclusion, the candidate report must be clean.

   If your private reasoning first suspects a bug but then concludes that the code path is actually correct, do not submit the earlier suspected bug. Re-evaluate the candidate report after the final trace; stale or disproven suspicions must be discarded.

6. Report at most 2 bugs.
   Prefer the most concrete and highest-impact bug.

   If you find both an invalid-input/edge-case issue and a valid-domain functional mismatch, prefer the valid-domain functional mismatch first. Bugs that produce a wrong answer for normal valid inputs are usually stronger evidence than bugs that only occur for invalid or boundary inputs. Do not choose an invalid-input bug merely because it is easier to explain. Only prioritize invalid-input handling when it is the only concrete mismatch or the task emphasizes it as the main requirement.

   For recurrence, counting, dynamic programming, or accumulation code, always trace a smallest normal valid input with more than one step. If the recurrence uses the current cell/value instead of a previous neighbor/state, or otherwise reuses an unupdated/incorrect accumulator, report the exact recurrence or assignment line.

   For parsing or tokenization code, if the bug is that a delimiter is handled without checking quote/state/context, report the exact delimiter condition line. If the bug is that quote/state/escape handling is missing, report the exact line where the code appends, splits, or branches incorrectly for the concrete character. Avoid broad ranges covering the whole loop.

   For ordinal indexing bugs, report the exact indexing expression line. Use `off_by_one` when the task's ordinal convention differs from the code's index expression. If required out-of-range cases are not guarded, report that as `unhandled_input` only after the main off-by-one bug.

## Candidate Bug Report JSON

Line number requirements:

- Count line numbers from the original input `code` string only, starting at 1 for the first line of that string.
- Include the `def ...` line when counting.
- Do not count Markdown-rendered snippets, analysis text, or any reformatted code.
- Prefer `line_end` equal to `line_start`.
- Use a multi-line range only when every line in the range is required to demonstrate the bug.
- Before writing the candidate JSON, privately recount the exact line number against the original `code` string.
- If the description quotes a specific bad expression, condition, or assignment, `line_start` must point to that exact source line.

Example candidate report for buggy code, without Markdown fences:
{"verdict":"buggy","bugs":[{"line_start":1,"line_end":1,"severity":"high","type":"logic_error","description":"Concrete reason tied to the code and task. Include a concrete counterexample when possible.","suggested_fix":"Concrete fix."}],"confidence":0.8}

Example candidate report for clean code, without Markdown fences:
{"verdict":"clean","bugs":[],"confidence":0.65}

The candidate report is not the final output. `scripts/run.py` decides the final file-based contract JSON.

## Bug Review Rules

- Report only concrete, triggerable bugs.
- Do not report style issues.
- Do not report speculative issues.
- Do not report a bug only because an input might be invalid unless the task explicitly requires handling it.
- Do not treat parameter names from prose as real inputs, such as `arr`, `target`, `line`, `nums`, `s`.
- For clean code or uncertainty, prefer `clean`.
- `line_start` / `line_end` must refer to the input `code` string only, 1-indexed.
- Report the smallest relevant code region.
- Use only allowed bug types and severities.
- Use `edge_case` for crashes or wrong results that occur only on explicitly required boundary cases such as empty input, singleton input, zero, or negative dimensions.
- Use `off_by_one` for inclusive/exclusive boundary mistakes, missed last/first element, or wrong 1-based vs 0-based indexing.
- Use `logic_error` for wrong formulas, recurrences, state transitions, branch conditions, or algorithms on normal valid inputs.

Allowed bug types:

- `off_by_one`
- `null_deref`
- `type_error`
- `logic_error`
- `edge_case`
- `api_misuse`
- `inefficient`
- `unhandled_input`

Allowed severity values:

- `critical`
- `high`
- `medium`
- `low`

## Pitfalls

- Do not use any machine-specific absolute path.
- Do not call `analyze.py` in the official flow; it is only a legacy debug helper.
- Do not output JSON in chat.
- Do not answer in natural language.
- Do not summarize the audit or say validation completed.
- Do not write `# Result` or any visible audit narrative.
- Do not print the result file, mention where it was written, or provide a final message after the terminal call.
- Do not mention output limits.
- Do not rely on stdout; the grader reads the result file.
- Do not omit the delimiter `__AIASE_BUG_REPORT_V1__`.
- Do not put Markdown fences around the candidate report inside the heredoc.
- Do not hand-write the final result file; call `scripts/run.py` once.
- The raw teacher CLI flags are supported by `run.py` for compatibility, but the official `SKILL.md` flow uses the heredoc delimiter because the original payload and candidate report are easier to pass safely without shell quoting issues.
- After the terminal call completes, stop immediately.

## Contract

The result file must contain a JSON object with:

- `task_id`
- `verdict`
- `bugs`
- `confidence`

Each bug must contain:

- `line_start`
- `line_end`
- `severity`
- `type`
- `description`
- `suggested_fix`

## Verification

The terminal command writes the result file. The grader reads the result file from `AIASE_RESULT_PATH`, not stdout or chat text.

A valid result must:

- be a JSON object,
- have `task_id` equal to the input `task_id`,
- contain `verdict` as `buggy` or `clean`,
- contain `bugs` as an array,
- contain `confidence` between 0.0 and 1.0.
