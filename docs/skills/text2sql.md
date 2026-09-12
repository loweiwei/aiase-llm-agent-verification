# Text2SQL Skill

`text2sql-loweiwei` 負責 AIASE Basic Track 的自然語言轉 SQL 任務。它的核心不是只寫 prompt 讓 LLM 直接回答 SQL，而是把 LLM 產生的候選 SQL 放進一個 file-based deterministic wrapper。wrapper 會清理格式、檢查 read-only policy、用題目提供的 SQLite schema 做驗證，最後才把可被評分器讀取的 JSON 寫到 `AIASE_RESULT_PATH`。

## 設計核心

這個 skill 解決的主要問題是：LLM 產生的 SQL 看起來可能合理，但在評分環境中可能因為格式、schema、權限或多 statement 直接失敗。

常見失敗包含：

- 回答包在 Markdown code fence 裡，評分器不能直接執行。
- SQL 引用不存在的 table 或 column。
- JOIN 後使用 `id`、`name` 這類 ambiguous column。
- 輸出多個 statement 或混入 DDL/DML。
- trailing semicolon、註解或字串內容讓簡單 keyword scanner 誤判。
- LLM 用自然語言說明，而不是產生機器可讀 JSON。

本 skill 的設計原則是：LLM 只負責根據 `question` 和 `db_schema` 產生候選查詢；`scripts/run.py` 負責所有能用程式客觀檢查的部分。

## 目錄與檔案分工

| File | Purpose |
|---|---|
| `skills/text2sql-loweiwei/SKILL.md` | Hermes 看到的 skill 規格，要求模型私下推理 SQL，然後只呼叫 `scripts/run.py` 一次 |
| `skills/text2sql-loweiwei/scripts/run.py` | 正式 runner，負責讀 payload、接收候選 SQL、驗證、fallback、寫 result JSON |
| `skills/text2sql-loweiwei/scripts/validate_sql.py` | schema-aware SQL validation helper，供 `run.py` 和 tests 使用 |
| `tests/test_validate_sql.py` | SQL validation、delimiter protocol、fallback 行為測試 |
| `tests/test_bag_equality.py` | SQL result comparison helper 的 multiset 行為測試 |
| `aiase_contract.py` | evaluator 共用 contract，包含 `validate_basic_schema()`、`run_sql()`、`bag_equal()` |
| `run_dev.py` | 本地 Basic Track evaluator，呼叫 skill、讀 result file、執行 SQL、比對 gold SQL |

## File-Based Pipeline

整體串接如下：

```text
dev_set/basic/task_nl2sql_xxx.json
  ↓
run_dev.py::grade_basic()
  ↓
組成 payload: task_id, question, db_schema, dialect
  ↓
run_dev.py::invoke_skill()
  ↓
設定 AIASE_RESULT_PATH=/tmp/.../<task_id>.json
  ↓
Hermes 執行 /text2sql-loweiwei {payload}
  ↓
SKILL.md 要求 Hermes 呼叫 scripts/run.py
  ↓
scripts/run.py 讀完整 payload + candidate SQL
  ↓
清理 SQL、驗證 policy、驗證 schema
  ↓
寫 result JSON 到 AIASE_RESULT_PATH
  ↓
run_dev.py 讀 result JSON
  ↓
aiase_contract.run_sql() 執行 student SQL 和 gold SQL
  ↓
aiase_contract.bag_equal() 比對結果集
```

正式結果不是聊天文字，也不是 stdout，而是 `AIASE_RESULT_PATH` 指定的 JSON 檔。這使 evaluator 可以穩定讀取結果，也避免 Hermes 回覆中的自然語言雜訊污染評分。

## Input / Output Contract

輸入 payload 由 `run_dev.py` 交給 Hermes：

```json
{
  "task_id": "task_nl2sql_001",
  "question": "...",
  "db_schema": "CREATE TABLE ...",
  "dialect": "sqlite"
}
```

`SKILL.md` 要求 Hermes 把原始 payload 和候選 SQL 用 delimiter 傳給 `run.py`：

```text
<original payload JSON>
__AIASE_SQL_V1__
<candidate SQLite SELECT query>
```

正式輸出 JSON 只包含：

```json
{
  "task_id": "task_nl2sql_001",
  "sql": "SELECT ...",
  "rationale": "Candidate SQL validated against the supplied schema.",
  "confidence": 0.8
}
```

`db_schema` 不會出現在正式結果裡。schema 只用於 local validation。

## `scripts/run.py` 內部流程

`run.py` 的主線可以用這個順序理解：

```text
main()
  ↓
parse_payload()
  ↓
emit_contract()
  ↓
write_result()
```

### `main()`

`main()` 支援三種呼叫方式：CLI flags、`argv[1]` payload、stdin payload。正式 Hermes flow 使用 stdin heredoc，因為 SQL 和 schema 可能包含換行、引號或特殊字元。

若輸入是空的或不是合法 JSON，`run.py` 仍會輸出合法 JSON，而不是讓程式直接 crash。這符合課程 evaluator 的 file-based contract：失敗也要有機器可讀結果。

### `parse_payload()`

`parse_payload()` 先讀 JSON object，再檢查後面是否有 `__AIASE_SQL_V1__` marker。如果有 marker，marker 後面的文字會被視為 candidate SQL。

這個設計解決 shell quoting 問題。比起把 SQL 塞進 CLI argument，delimiter protocol 更能保留多行 SQL、引號、schema 內容和特殊字元。

### `_extract_sql_body()`

LLM 可能產生：

~~~text
```sql
SELECT name FROM students;
```
~~~

`_extract_sql_body()` 會拿掉 Markdown fence，只留下 SQL 本體。這避免 evaluator 收到 fenced text。

### `_mask_sql()`

`_mask_sql()` 會遮蔽 SQL 字串和註解內容，再做 keyword 或 semicolon 掃描。

這是為了避免把字串中的危險字誤判成 SQL 指令，例如：

```sql
SELECT 'DROP TABLE users' AS text
```

這裡 `DROP` 是字串內容，不應該被當成 DDL。

### `_strip_optional_trailing_semicolon()` 和 `_has_multiple_statements()`

runner 允許一個 optional trailing semicolon：

```sql
SELECT * FROM students;
```

但拒絕多 statement：

```sql
SELECT * FROM students; DROP TABLE students;
```

這個檢查同樣建立在 `_mask_sql()` 上，避免誤判字串裡的分號。

### `_validate_schema()`

`_validate_schema()` 是 schema-aware validation 的核心。它優先呼叫 `validate_sql.validate()`，若 helper import 失敗，則退回 in-memory SQLite：

```text
sqlite3.connect(":memory:")
  ↓
executescript(db_schema)
  ↓
EXPLAIN <candidate sql>
```

這可以抓到：

- SQL syntax error。
- nonexistent table。
- nonexistent column。
- ambiguous column。
- schema 不相容查詢。

### `emit_contract()`

`emit_contract()` 是正式決策點。它會：

- 清理 code fence 和 trailing semicolon。
- 檢查 SQL 非空。
- 檢查第一個 statement 是否為 `SELECT`。
- 拒絕 multiple statements。
- 拒絕 DDL/DML/PRAGMA/transaction keywords。
- 拒絕超出 project envelope 的 `WITH`、recursive、window constructs。
- 用 schema validation 檢查可執行性。
- 根據結果調整 `confidence`。
- 寫出最後 JSON。

如果任何 contract 或 schema 檢查失敗，SQL 會被替換成：

```sql
SELECT NULL WHERE 0
```

這個 fallback 不是為了答對，而是為了保證輸出安全、read-only、可執行。語意錯誤會在 evaluator 的 gold SQL 比對中 fail，但不會因為非法 SQL 造成 evaluator 崩潰或 side effect。

### `write_result()`

`write_result()` 使用 temporary file 加 `os.replace()` 寫入正式 result path。這確保 evaluator 不會讀到寫一半的 JSON。

## `validate_sql.py` 的角色

`validate_sql.py` 提供獨立的 SQL validation helper。它和 `run.py` 有部分相似邏輯，但定位不同：

- `run.py` 是正式 runner，負責 file-based output 和 fallback。
- `validate_sql.py` 是 reusable helper，負責 schema-aware validation。

主要函式是：

```python
validate(schema_ddl: str, sql: str) -> tuple[bool, str]
```

它會回傳 `(True, "")` 或 `(False, reason)`，讓 `run.py` 可以把錯誤原因寫進 `rationale`。

## 評分時怎麼接回 `run_dev.py`

`run_dev.py::grade_basic()` 讀到 result JSON 後，會先用 `aiase_contract.validate_basic_schema()` 檢查：

- result 是 JSON object。
- `task_id` 和題目一致。
- `sql` 是非空字串。
- `confidence` 在 `0.0..1.0`。

接著它會執行：

```text
student_rows = run_sql(db_path, student_sql)
gold_rows = run_sql(db_path, gold_sql)
passed = bag_equal(student_rows, gold_rows)
```

`bag_equal()` 是 multiset comparison：忽略 row order，但保留 duplicates 和 column order。

## 如何解決問題

這個 skill 把 Text2SQL 的風險拆成兩類：

- 語意正確性：交給 LLM 產生候選 SQL，再由 evaluator 和 gold SQL 結果比較。
- 可執行性與安全性：交給 deterministic wrapper 檢查。

因此，即使 LLM 語意答錯，輸出仍會是合法 JSON 和安全 SQL。這讓失敗可重現、可定位，也避免格式或 schema 錯誤污染整體評測。

## 測試覆蓋

相關測試檢查：

- valid SELECT 會通過。
- nonexistent table/column 會被拒絕。
- syntax error 會被拒絕。
- DDL/DML/multiple statements 會被拒絕。
- optional trailing semicolon 可以被清理。
- JOIN query 可通過。
- marker protocol 能保留完整 schema 和 SQL。
- marker 出現在 question 文字時不會誤切 payload。
- unknown/ambiguous column 會被 safe fallback 取代。

## 已知限制

- Schema validation 只能證明 SQL 可執行，不能證明 SQL 語意答對。
- `SELECT NULL WHERE 0` 是安全 fallback，不是答案修復。
- Private evaluation 的 schema 和 question 未公開，repository 只能重跑 public/dev-set 行為。
- SQL envelope 刻意限制 `WITH`、recursive、window functions，以換取 predictable validation 行為。
