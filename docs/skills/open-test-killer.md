# Open Test Killer Skill

`open-test-killer-loweiwei` 是本專題的 Open Track skill。它做的是 mutation-testing test selection：給定 reference implementation、mutants、candidate inputs 和 `max_tests`，runner 實際執行 reference 與 mutants，建立 kill matrix，再在測試數量預算內選出能 kill 最多 mutants 的測試集合。

## 設計核心

Open Test Killer 的核心設計是：測試是否有效不能由 LLM 用自然語言宣稱，而要由 execution-derived evidence 決定。

它解決的問題包含：

- LLM 可能猜哪些 input 會殺死 mutant，但猜測不可驗證。
- Candidate inputs 可能讓 reference crash，不能被選為合法測試。
- Mutant 可能輸出不同值、raise exception 或 timeout，這些都需要一致的 kill 定義。
- 測試選擇是 maximum coverage 問題，不能只貪心選第一個看起來好的 input。
- 大型候選集合不能無限制枚舉所有組合，需要 bounded exact search 和 deterministic fallback。
- 評分器需要能重跑 selected tests，驗證 expected output、kills 和 kill_rate。

因此，這個 skill 幾乎不依賴 LLM 語意推理。Hermes 主要只是把完整 payload 交給 `scripts/run.py`，真正的選擇邏輯全由 deterministic code 完成。

## 目錄與檔案分工

| File | Purpose |
|---|---|
| `skills/open-test-killer-loweiwei/SKILL.md` | Hermes 看到的 skill 規格，要求把完整 Open Track payload 原封不動傳給 `scripts/run.py` |
| `skills/open-test-killer-loweiwei/scripts/run.py` | 正式 deterministic evaluator，負責 schema validation、reference/mutant execution、kill matrix、exact/greedy selection、result JSON |
| `skills/open-test-killer-loweiwei/scripts/selftest.py` | 自我驗證器，重跑 scenarios 並檢查 result file、stdout JSON、kills、kill_rate、perturbation behavior |
| `skills/open-test-killer-loweiwei/scripts/regression.py` | Open Track regression entry，防止選擇策略或 contract 退化 |
| `skills/open-test-killer-loweiwei/scripts/public_scenarios/*.json` | Public development scenarios，例如 merge intervals、top-k frequent、valid parentheses |
| `OPEN_TRACK.md` | Open Track 完整規格、input/output schema、pass criteria、failure modes |
| `artifacts/benchmarks/open_selection.md` | Public scenarios 上 exact/greedy/random comparison 摘要 |

## File-Based Pipeline

```text
Open Track payload JSON
  ↓
Hermes 執行 /open-test-killer-loweiwei {payload}
  ↓
SKILL.md 要求 Hermes 呼叫 scripts/run.py 並用 stdin 傳完整 payload
  ↓
scripts/run.py::main()
  ↓
json.loads(stdin)
  ↓
run(payload)
  ↓
validate_payload()
  ↓
build_matrix()
  ↓
select_tests()
  ↓
emit()
  ↓
write result JSON 到 AIASE_RESULT_PATH
  ↓
同一份 JSON 也印成最後一個 fenced stdout block
```

和其他 Basic/Pairwise skill 不同，Open Test Killer 的 `run.py` 本身就包含主要 evaluator logic。它不需要 `run_dev.py` 去執行 SQL 或 code test cases；`run.py` 已經在內部執行 reference 和 mutants。

## Input / Output Contract

輸入 payload：

```json
{
  "task_id": "scenario_1",
  "entry_point": "solution",
  "max_tests": 3,
  "description": "optional metadata",
  "reference_code": "def solution(...): ...",
  "mutants": [
    {"id": "m1", "code": "def solution(...): ..."},
    {"id": "m2", "code": "def solution(...): ..."}
  ],
  "candidate_inputs": [
    {"id": "t1", "args": [[1, 2, 3]], "kwargs": {}},
    {"id": "t2", "args": [[0]], "kwargs": {}}
  ]
}
```

成功輸出：

```json
{
  "ok": true,
  "task_id": "scenario_1",
  "entry_point": "solution",
  "selected_tests": [
    {
      "id": "t1",
      "args": [[1, 2, 3]],
      "kwargs": {},
      "expected": 6,
      "kills": ["m1"]
    }
  ],
  "killed_mutants": ["m1"],
  "unkilled_mutants": ["m2"],
  "survived_mutants": ["m2"],
  "kill_rate": 0.5,
  "num_selected_tests": 1,
  "max_tests": 3,
  "total_mutants": 2,
  "verdict": "fail",
  "confidence": 1.0,
  "rationale": "Deterministic exact max-coverage over execution-derived kill sets.",
  "evaluation_stats": {
    "evaluation_truncated": false,
    "evaluated_candidates": 2,
    "evaluated_calls": 6,
    "selection_strategy": "exact",
    "exact_combinations_considered": 3,
    "exact_combination_budget": 25000
  }
}
```

失敗時也會輸出合法 JSON，`ok=false`，並包含 `error_type` 和 `message`。

## `scripts/run.py` 內部流程

主線如下：

```text
main()
  ↓
run()
  ↓
validate_payload()
  ↓
build_matrix()
  ↓
select_tests()
  ↓
emit()
```

### `main()`

`main()` 從 `--payload` 或 stdin 讀 JSON。正式 flow 使用 stdin，因為 Open Track payload 可能包含大量 Python source code、換行、引號和 nested data。

如果 JSON decode 失敗，runner 仍會輸出合法 failure JSON，而不是讓 process 直接 crash。

### `validate_payload()`

`validate_payload()` 檢查 input schema：

- top-level 必須是 object。
- required fields 必須存在。
- `task_id`、`entry_point`、`reference_code` 必須是 non-empty string。
- `mutants` 必須是 non-empty list。
- `candidate_inputs` 必須是 non-empty list。
- `max_tests` 必須是 integer 且 `>= 0`。
- mutant ids 不能重複。
- candidate ids 不能重複。
- candidate `args` 必須是 list。
- candidate `kwargs` 必須是 object。

這一步把不合法 payload 轉成 structured failure，例如 `invalid_input_schema`、`no_mutants`、`no_candidates`。

### `_worker()` 和 `call_function()`

`call_function()` 是執行 reference/mutant 的統一入口。它會開 multiprocessing child process，讓 `_worker()` 執行 source code 中的 entry function。

`_worker()` 使用 restricted builtins 和 import allowlist。允許的 imports 包含 `math`、`collections`、`itertools`、`functools`、`heapq`、`bisect`、`re`、`string`、`typing`、`operator`。

執行結果會標準化為：

```json
{"status": "ok", "value": ...}
```

或：

```json
{"status": "exception", "error": "..."}
```

timeout 會回傳：

```json
{"status": "timeout", "error": "timeout"}
```

### `normalize()` 和 `ensure_jsonable()`

Reference output 必須可以穩定 JSON serialize。`normalize()` 會把 tuple 轉 list，dict key 轉 string 並排序。若輸出含不可 JSON 化物件，該 candidate input 會被視為 invalid。

這讓 `expected` 可以被寫進 result JSON，也讓 verifier 能重新比較。

### `build_matrix()`

這是 Open Test Killer 的核心。

對每個 candidate input：

```text
1. 用 args/kwargs 執行 reference_code。
2. 若 reference timeout、exception 或 output 不可 JSON 化，該 candidate 無效。
3. 若 reference 成功，記錄 expected output。
4. 對每個 mutant 執行同一組 input。
5. mutant exception、timeout 或 output != expected，都算被 kill。
6. 產生此 candidate 的 kills_set。
```

每個有效 candidate 會被轉成：

```python
{
    "id": cand["id"],
    "args": args,
    "kwargs": kwargs,
    "expected": expected,
    "kills_set": kills,
    "order": cand_index,
}
```

這就是 kill matrix 的一列。

### Kill 定義

在 reference 成功的前提下，candidate input kill mutant 的條件是：

- mutant 回傳值和 reference output 不同。
- mutant raise exception。
- mutant timeout。
- mutant output 無法 normalize 成 JSON。

Reference 失敗時，candidate input 不合法，不能被選入 `selected_tests`。

### `_guard_exceeded()`

matrix construction 受兩個 budget 控制：

```python
GLOBAL_DEADLINE_SEC = 110.0
MAX_EVAL_CALLS = 2000
```

如果超過 budget，`evaluation_truncated` 會設為 true。即使 runner 仍輸出 best-effort result，`verdict` 也必須是 `fail`。

### `_exact_select()`

如果候選組合數不超過：

```python
MAX_EXACT_COMBINATIONS = 25000
```

runner 會枚舉所有大小 `1..max_tests` 的組合，選出 kill mutants 最多的組合。

Tie-break 順序：

- kill 數多。
- 使用測試數少。
- candidate 原始順序穩定。
- candidate id 穩定。

這讓同一 payload 重跑會得到相同 selected tests。

### `_greedy_select()`

如果組合數超過 exact budget，runner 改用 deterministic greedy fallback。

每一步選擇能新增 kill 最多 mutants 的 candidate。如果平手，使用原始順序和 id 做 deterministic tie-break。

Greedy 不保證全域最優，但能在大型輸入下提供 bounded best-effort。

### `select_tests()`

`select_tests()` 把 selected candidates 轉成正式 output：

- `selected_tests`
- `killed_mutants`
- `unkilled_mutants`
- `survived_mutants`
- `kill_rate`
- `num_selected_tests`
- `verdict`
- `evaluation_stats`

verdict 規則：

```text
pass iff kill_rate >= 0.8 and evaluation_truncated is false
```

這避免把 truncated best-effort 結果包裝成完整通過。

### `emit()` 和 `write_result()`

`emit()` 會先把 JSON 寫到 `AIASE_RESULT_PATH`，再把同一個 object 以 fenced JSON block 印到 stdout。stdout 是相容輸出，正式 primary output 仍是 result file。

`write_result()` 使用 temporary file 加 `os.replace()`，避免 evaluator 讀到 partial JSON。

## `selftest.py` 的角色

Open Test Killer 的 `selftest.py` 比一般 smoke test 更像 verifier。它會：

- 呼叫 `run.py`。
- 檢查 result file 和 stdout 最後 fenced JSON 是否一致。
- 重跑 reference，確認 `expected` 正確。
- 重跑 mutants，確認每個 selected test 的 `kills` 正確。
- 檢查 `killed_mutants` 是 selected tests 的 kills union。
- 檢查 `unkilled_mutants` 和 `survived_mutants` 一致。
- 檢查 `kill_rate`、`num_selected_tests`、`verdict`。
- 測試 candidate order / mutant id perturbation。
- 測試 exact-search greedy trap。
- 測試 truncated verdict。

這確保 result 中的 evidence 可以被獨立重算，而不只是信任 runner 輸出。

## 如何解決問題

Open Test Killer 把 mutation-test selection 拆成三個 deterministic 問題：

- Execution：reference 和 mutants 實際跑出 expected / actual。
- Matrix：每個 candidate 對每個 mutant 是否 kill 形成 binary coverage set。
- Selection：在 `max_tests` budget 下做 exact max coverage 或 greedy fallback。

這讓最終結果具備可驗證性：每個 expected output、每個 kill、整體 kill_rate 都可以重跑確認。

## Public Scenarios 和 Benchmark

目前 public scenarios 包含：

- `merge_intervals`
- `top_k_frequent`
- `valid_parentheses`

benchmark 比較 exact、greedy 和 random baseline。public data 上 exact 和 greedy 達到相同 score，但 exact-search greedy trap 測試證明在特定構造下 exact search 可以避免 greedy 的局部選擇問題。

## 已知限制

- Mutation score 取決於 mutants 品質，等價 mutant 可能無法被 kill。
- `MAX_EVAL_CALLS` 和 global deadline 會讓大型 payload 被 truncated。
- Greedy fallback 不保證全域最優。
- Worker import allowlist 和 restricted builtins 降低風險，但不是完整 sandbox。
- Public scenarios 曾用於開發，不能視為獨立 held-out benchmark。
