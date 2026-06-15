## 1. Skill 簡介

`open-test-killer-loweiwei` 是一個 deterministic mutation-testing Test Killer。它會執行 reference implementation 與 mutants，從候選輸入中選出能殺死最多 mutants 的精簡測試集合，將結果 JSON 寫入 `AIASE_RESULT_PATH` 指定的結果檔；若未設定則寫入 `./aiase_result.json`，不依賴網路或 LLM 判斷 kill 結果。

## 2. Skill 名稱與目錄

Skill name: `open-test-killer-loweiwei`

Skill path: `skills/open-test-killer-loweiwei/`

Slash command: `/open-test-killer-loweiwei`

主要 deterministic evaluator: `skills/open-test-killer-loweiwei/scripts/run.py`

## 3. 呼叫方式

Hermes 呼叫方式。Hermes chat 只負責觸發 skill；正式結果以 `AIASE_RESULT_PATH` 指向的 JSON 檔為準，chat stdout 不作為評分依據。

In grading, the evaluator is expected to set `AIASE_RESULT_PATH`; the skill writes the result JSON there. If unset, `run.py` falls back to `./aiase_result.json`.

Hermes 載入 skill 後，skill 內部正式 Procedure 使用 Hermes 提供的 `[Skill directory: ...]` 路徑呼叫 `run.py`，並以 stdin/heredoc 傳完整 payload，不依賴 repo root 或目前工作目錄：

```bash
python3 <skill_dir>/scripts/run.py <<'AIASETESTKILLERJSON'
<full original input JSON>
AIASETESTKILLERJSON
```

因為 Open Track payload 可能包含大量 Python 原始碼、換行與引號，stdin/heredoc 是正式入口；`run.py --payload '<json>'` 僅作為本地 smoke test 相容模式。

```bash
rm -f /tmp/open_killer_result.json
AIASE_RESULT_PATH=/tmp/open_killer_result.json hermes chat --toolsets skills,terminal --yolo -Q -q "$(cat <<'AIASEQUERY'
/open-test-killer-loweiwei {"task_id":"smoke","entry_point":"f","max_tests":1,"description":"optional string metadata","reference_code":"def f(x):\n    return x\n","mutants":[{"id":"m1","code":"def f(x):\n    return x+1\n"}],"candidate_inputs":[{"id":"t1","args":[1],"kwargs":{}}]}
AIASEQUERY
)"
cat /tmp/open_killer_result.json
```

本地可直接執行三個 public scenarios。`run.py` 不使用 stdout 作為正式輸出，請讀取結果檔：

```bash
rm -f /tmp/open_killer_result.json
AIASE_RESULT_PATH=/tmp/open_killer_result.json python skills/open-test-killer-loweiwei/scripts/run.py < skills/open-test-killer-loweiwei/scripts/public_scenarios/merge_intervals.json
cat /tmp/open_killer_result.json

rm -f /tmp/open_killer_result.json
AIASE_RESULT_PATH=/tmp/open_killer_result.json python skills/open-test-killer-loweiwei/scripts/run.py < skills/open-test-killer-loweiwei/scripts/public_scenarios/valid_parentheses.json
cat /tmp/open_killer_result.json

rm -f /tmp/open_killer_result.json
AIASE_RESULT_PATH=/tmp/open_killer_result.json python skills/open-test-killer-loweiwei/scripts/run.py < skills/open-test-killer-loweiwei/scripts/public_scenarios/top_k_frequent.json
cat /tmp/open_killer_result.json
```

輸入 schema：

```json
{
  "task_id": "non-empty string",
  "entry_point": "non-empty string",
  "max_tests": "integer >= 0",
  "description": "optional string metadata",
  "reference_code": "non-empty Python source string",
  "mutants": [{"id": "unique string", "code": "Python source string"}],
  "candidate_inputs": [{"id": "unique string", "args": [], "kwargs": {}}]
}
```

`mutants` must be a non-empty array. `candidate_inputs` must be a non-empty array. `description` is optional metadata and is not required by `run.py`.

成功結果檔 JSON schema：

```json
{
  "ok": true,
  "task_id": "...",
  "entry_point": "...",
  "selected_tests": [
    {
      "id": "TEST_ID",
      "args": [],
      "kwargs": {},
      "expected": "reference output",
      "kills": ["MUTANT_ID"]
    }
  ],
  "killed_mutants": ["..."],
  "unkilled_mutants": ["..."],
  "kill_rate": 1.0,
  "num_selected_tests": 1
}
```

失敗結果檔 JSON schema：

```json
{
  "ok": false,
  "error_type": "invalid_input_schema",
  "message": "..."
}
```

`error_type` may also be `invalid_json`, `no_mutants`, `no_candidates`, `reference_execution_error`, or `internal_error`.

## 4. 自定 Verifiable Scenario

此 Open Track 的 verifiable scenario 是 mutation testing test selection。輸入包含一個 Python coding task package：`task_id`、`entry_point`、optional `description`、`reference_code`、多個 mutant implementations、`candidate_inputs` 與 `max_tests`。Ground truth 不是由 LLM 判斷，而是由 evaluator 實際執行每個 candidate input 在 reference 與 mutant 上的結果。

一個 selected test 殺死 mutant 的定義如下：

- `expected` 必須等於 reference implementation 在該 candidate input 上的輸出。
- mutant 在同一 input 上的輸出若不同於 reference output，該 test 殺死此 mutant。
- mutant 若 raise exception 或 timeout，也視為被該 test 殺死。
- reference 若 raise exception、timeout，或輸出無法 JSON serialize，該 candidate input 無效，不可被選取。

Metric：`scenario_pass` 為 true iff：

- output 是合法 JSON。
- required fields 都存在。
- `ok` 必須為 `true`。
- 每個 selected test 都來自 `candidate_inputs`。
- 每個 selected test 的 `expected` 都等於 reference output。
- 每個 selected test 的 `kills` 都與 evaluator 實際執行 mutants 得到的 kill set 完全一致。
- `killed_mutants` 必須等於所有 selected tests 的 kills 聯集。
- `unkilled_mutants` 必須等於輸入 mutants 扣除 `killed_mutants`。
- `kill_rate == len(killed_mutants) / len(mutants)`。
- `kill_rate >= 0.8`。
- `num_selected_tests == len(selected_tests)`。
- `num_selected_tests <= max_tests`。

Overall score = `passed_scenarios / total_scenarios`。

Staff perturbations 仍應視為同一能力：

- candidate order changes。
- mutant order changes。
- task_id changes。
- mutant id changes。
- comments and whitespace changes。
- variable name changes。
- added irrelevant candidates。
- adjusted max_tests。

Staff may add distractor or equivalent-looking mutants only when the private scenario remains solvable to `kill_rate >= 0.8`.

Anti-hardcoding：fixed `task_id`、fixed candidate index、fixed mutant id、fixed string matching、以及 public-scenario hardcoding 都會失敗，因為 evaluator 會用 execution 重新計算 expected outputs 與 kill sets。

## 5. 預期失敗模式

- invalid JSON：觸發條件是 stdin 為空或不是合法 JSON。處理方式是輸出 `ok=false`、`error_type=invalid_json` 與可讀訊息。
- invalid input schema：觸發條件是缺少 `task_id`、`entry_point`、`reference_code`、`mutants`、`candidate_inputs` 或 `max_tests`，或型別錯誤。處理方式是輸出 `ok=false`、`error_type=invalid_input_schema` 與可讀訊息。
- empty mutants：觸發條件是 `mutants` 為空陣列。處理方式是輸出 `ok=false`、`error_type=no_mutants`。
- empty candidates：觸發條件是 `candidate_inputs` 為空陣列。處理方式是輸出 `ok=false`、`error_type=no_candidates`。
- reference timeout：觸發條件是 reference implementation 在某 candidate input 上無限迴圈或超過 timeout。處理方式是該 candidate input 無效，不列入 selected tests；若所有 candidates 都無效，輸出 `reference_execution_error`。
- mutant timeout：觸發條件是 mutant implementation 在某 candidate input 上超時。處理方式是該 candidate 殺死該 mutant，因為 mutant 未能在限制內產生正確輸出。
- no candidate can kill enough mutants：觸發條件是 candidate set 太弱或 mutants 與 reference 等價，導致 greedy selection 的 `kill_rate < 0.8`。處理方式是仍輸出最好的 deterministic selection，metric 會判定該 scenario 未通過。
- non-JSON-serializable reference output：觸發條件是 reference 回傳 set、object 或其他無法穩定 JSON serialize 的值。處理方式是該 candidate input 無效，不可被選取。

## 6. 互動對象

此 skill 不需要另一位同學的 skill，也不依賴外部 API 或網路。互動對象只有 Hermes 與 `skills/open-test-killer-loweiwei/scripts/run.py`。Open Track scoring 是獨立的，由本 skill 的 deterministic evaluator 直接執行 reference 與 mutants。

## 7. Token Budget 估算

單一 scenario 的輸入預估約 3k 到 8k tokens，包含 reference code、mutant code 與候選 inputs。輸出預估約 1k 到 3k tokens，包含 selected tests、expected outputs 與 kill lists。總計約 5k 到 13k tokens per scenario，低於 50k tokens/scenario。
