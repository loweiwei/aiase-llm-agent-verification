---
name: text2sql-loweiwei
description: Convert a natural-language question + SQLite schema into verified read-only SQL, then write the result via scripts/run.py using the file-based AIASE output contract.
version: 2.0.0
metadata:
  hermes:
    tags: [sql, text2sql, data, aiase-2026]
    category: data
    requires_toolsets: [terminal]
---

# Text2SQL Skill

## When to Use

Use when invoked with `/text2sql-loweiwei {json}` for an AIASE 2026 Basic Track Text2SQL payload.

The input JSON contains:
- `task_id`
- `question`
- `db_schema`
- `dialect`, usually `sqlite`

## Critical Visible Output Rule

If you output natural language, the skill fails. If you output any Markdown heading, the skill fails. If you say the task is complete or the result was written, the skill fails. If you output Markdown fences, the skill fails.

The final assistant response must contain zero characters. The terminal call is the only visible action. After the terminal call returns, end the turn silently.

Mandatory sequence:
- Think privately.
- Call the terminal tool exactly once to run `python3 <skill_dir>/scripts/run.py ...`.
- Immediately stop. Do not produce a final assistant message.

Never print or describe:
- the SQL reasoning,
- the candidate SQL,
- the final JSON,
- the result file path,
- a success or validation message,
- any Markdown heading,
- Markdown fences.

If the result file was written successfully, do not say so. Stop with an empty final response. Any non-empty final assistant response, including a success sentence, fails this skill.

## Procedure

Use the terminal tool exactly once. Do not use background/process tools.

The only allowed visible action is one terminal call. Do not answer in natural language. Do not summarize the SQL. Do not print the result file path. Do not say the result was written. Do not write any Markdown heading. Do not write a completion message. After the terminal call completes, stop with no final message and zero characters.

1. Read the input `question` and `db_schema`.
2. Privately derive one SQLite read-only `SELECT` query that answers the question using only tables and columns present in `db_schema`.
3. Execute `scripts/run.py` exactly once using CLI flags. The script will normalize and write the final result JSON to `AIASE_RESULT_PATH`.

Use this portable command. `<skill_dir>` is the skill directory path provided by Hermes as `[Skill directory: ...]`. It may be an absolute path, but must not be hardcoded to any machine-specific path.

~~~bash
python3 <skill_dir>/scripts/run.py \
  --task_id "<same task_id as input>" \
  --sql "<single read-only SQLite SELECT query>" \
  --rationale "<brief reason>" \
  --confidence 0.8
~~~

Do not include `db_schema` in the formal result. Use the input schema only for reasoning, then pass only `task_id`, `sql`, `rationale`, and `confidence` to `run.py`.

The script writes the final result JSON to the file specified by `AIASE_RESULT_PATH`.
If `AIASE_RESULT_PATH` is not set, it writes to `./aiase_result.json`.

Do not output the JSON contract in chat or stdout. Do not output SQL in chat or stdout. Do not add explanation before or after the terminal call. Do not retry. Do not make more than one terminal call. Do not use process/background tools. Do not write Markdown fences. After the terminal call completes, stop with no final message and zero characters.

## Private SQL Reasoning Method

Before writing SQL, privately reason from the current `question` and `db_schema`.

1. Identify the target output columns requested by the question.
2. Identify the required tables and join path from key-like columns.
3. Decide whether duplicates are possible; use DISTINCT when the question asks for entities and joins may duplicate them.
4. Identify filters from the question, including names, years, statuses, thresholds, negations, and date constraints.
5. Identify whether aggregation is required: COUNT, SUM, AVG, MAX, MIN, GROUP BY, HAVING.
6. Identify ordering and limit requirements such as top N, oldest, youngest, highest, lowest, latest, earliest, ascending, or descending.
7. Identify universal quantification: words such as `every`, `all`, `each`, `for every`, `in every`, or `at least one ... in every ...` usually require nested `NOT EXISTS`, not a scalar subquery inside `COUNT(DISTINCT ...)`.
8. For JOIN queries, qualify ambiguous column names using table aliases.
9. Use only tables and columns present in `db_schema`.
10. Do not rely on task_id, dev-set memory, or fixed question strings. Derive the SQL from the current question and schema only.
11. If a familiar question pattern appears with changed table or column names, adapt to the current schema instead of using a memorized SQL template.

## SQL Rules

- Use only SQLite syntax.
- Produce exactly one read-only `SELECT` query.
- Allowed constructs include `SELECT`, `INNER JOIN`, `LEFT JOIN`, subqueries up to depth 2, correlated subqueries, `GROUP BY`, `HAVING`, `COUNT`, `SUM`, `AVG`, `MAX`, `MIN`, `ORDER BY`, `LIMIT`, `UNION`, and `UNION ALL`.
- Do not use `WITH`, CTEs, `WITH RECURSIVE`, recursive queries, or window functions such as `OVER(...)`.
- Do not use DDL, DML, `PRAGMA`, transaction statements, or multiple SQL statements.
- Do not include SQL comments.
- Use table and column names that actually appear in `db_schema`.
- In JOIN queries, prefer table aliases and qualify column references with table names or aliases.
- When multiple joined tables contain the same column name, never use a bare ambiguous column such as `name`, `id`, `title`, `date`, or `status`; use qualified references such as `Doctors.name`, `Patients.name`, or aliases such as `d.name`.
- Choose JOIN conditions from plausible schema key columns.
- If JOINs may duplicate requested entities, consider `DISTINCT`.
- For each group / per group questions, use `GROUP BY` and aggregate functions when appropriate.
- For none / no / never / not questions, consider `LEFT JOIN ... IS NULL`, `NOT EXISTS`, or `NOT IN`.
- For every / all / each questions, prefer anti-division with nested `NOT EXISTS`: select an entity `e` where there does not exist a required related row `r` for which there does not exist evidence row `x` linking `e` and `r`.
- For `at least one <event> in every <required row>` questions, use nested `NOT EXISTS` with an inner `EXISTS` / `NOT EXISTS` over the event table. Do not compare counts using scalar subqueries such as `COUNT(DISTINCT (SELECT ...))`.
- For universal conditions scoped by ownership, correlate the required rows to the entity's group first, for example required rows belonging to the entity's team, department, customer, or parent record.
- For most / least / top N / highest / lowest / latest / earliest questions, use `ORDER BY` with `LIMIT` or aggregation when appropriate.
- For oldest / oldest age / highest age / age descending questions, use `ORDER BY <age column> DESC`.
- For youngest / youngest age / lowest age / age ascending questions, use `ORDER BY <age column> ASC`.
- For top N oldest entities, use `ORDER BY age DESC LIMIT N`.
- For top N youngest entities, use `ORDER BY age ASC LIMIT N`.
- If the question explicitly says `descending`, do not use `ASC` for that sort key.
- If the question explicitly says `ascending`, do not use `DESC` for that sort key.
- Avoid a trailing semicolon; `run.py` will remove one optional trailing semicolon if present.
- Output column aliases usually do not matter; grading compares row tuple values unless the question explicitly requires names. This does not mean table qualification can be omitted in JOIN queries.
- Keep `rationale` brief.
- Set `confidence` from 0.0 to 1.0 based on certainty.
- When selecting non-aggregated columns with aggregates, include all selected non-aggregated columns in `GROUP BY`, for example `GROUP BY c.cid, c.title`.

## CLI Argument Rules

- `task_id` must exactly match the input `task_id`.
- Quote CLI argument values so the shell passes each value as a single argument.
- Prefer single quotes for SQL string literals, for example `WHERE name = 'Alice'`.
- Keep the SQL in one argument. Do not paste raw multi-line text into CLI argument values.

## Pitfalls

- Do not use any machine-specific absolute path.
- Do not output JSON in chat.
- Do not output SQL in chat.
- Do not answer in natural language.
- Do not summarize the SQL or say the result was written.
- Do not output a success, completion, or verification message.
- Do not rely on stdout; the grader reads the result file.
- Do not include `db_schema` in the formal result.
- Do not return fallback SQL unless the SQL is truly invalid.
- In JOIN queries, avoid bare column names when common names appear in more than one table.

## Contract

The result file must contain exactly the Text2SQL contract fields:
- `task_id`
- `sql`
- `rationale`
- `confidence`

## Verification

The terminal command writes the result file. The grader reads the result file from `AIASE_RESULT_PATH`, not stdout or chat text.

A valid result must:
- be a JSON object,
- have `task_id` equal to the input `task_id`,
- contain a non-empty read-only SQLite `SELECT` query,
- contain `confidence` between 0.0 and 1.0.
