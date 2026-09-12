# Bug Hunter Skill

`bug-hunter-loweiwei` 負責 AIASE Pairwise Bug Hunter 任務：審查 Python code，輸出具體、可定位、可修正的 bug report。它不是直接相信 LLM 的 code review，而是把 LLM candidate report 放進 `scripts/run.py`，由 runner 做 JSON extraction、enum normalization、line range 修正、false-positive 過濾，以及必要時的 deterministic dynamic audit。

## 設計核心

Bug Hunter 的主要問題是 LLM 很容易產生「看起來合理但不可驗證」的 bug report。

常見失敗包含：

- 回報格式不是合法 JSON。
- `line_start` 和輸入 code 的實際行號不一致。
- `type` 或 `severity` 不在允許 enum 裡。
- 描述是 placeholder、speculative 或自我否定，例如「可能有 bug 但不確定」。
- clean code 被過度報 bug，造成 false positive。
- 真正可用小測資觸發的 bug 被漏掉。
- LLM 指出一整個函式範圍，而不是具體錯誤行。

本 skill 的設計策略偏 precision-oriented：寧可少報，也避免在 clean code 上亂報。同時，對可用程式執行驗證的 task family，runner 會用 dynamic probes 補強 recall。

## 目錄與檔案分工

| File | Purpose |
|---|---|
| `skills/bug-hunter-loweiwei/SKILL.md` | Hermes 看到的 skill 規格，要求模型私下分析 code，再把 candidate report 傳給 `scripts/run.py` |
| `skills/bug-hunter-loweiwei/scripts/run.py` | 正式 runner，負責 report normalization、dynamic audit、worker isolation、result JSON |
| `skills/bug-hunter-loweiwei/scripts/selftest.py` | 自我測試 scenarios，驗證 normalization、audit、clean/buggy behavior |
| `skills/bug-hunter-loweiwei/scripts/regression.py` | reference clean/buggy/tricky regression |
| `skills/bug-hunter-loweiwei/scripts/analyze.py` | legacy debug helper，不是正式評分 pipeline |
| `tests/test_extract_contract.py` | 測試 JSON extraction、fallback result recovery、invoke retry contract |
| `run_dev.py` | Pairwise evaluator，呼叫 skill 審 buggy code 和 clean code，再比對 line/type |

## File-Based Pipeline

```text
dev_set/pairwise/reference_tasks/*.json
  ↓
run_dev.py::grade_pairwise(role="bug-hunter")
  ↓
取出 buggy_code 組成 payload
  ↓
run_dev.py::invoke_skill()
  ↓
設定 AIASE_RESULT_PATH=/tmp/.../<task_id>_buggy.json
  ↓
Hermes 執行 /bug-hunter-loweiwei {payload}
  ↓
SKILL.md 要求 Hermes 產生 candidate bug report 並呼叫 scripts/run.py
  ↓
scripts/run.py normalize report，必要時執行 dynamic audit
  ↓
寫 result JSON 到 AIASE_RESULT_PATH
  ↓
run_dev.py 讀 result JSON，比對 line_start + type
  ↓
若 task 有 clean_code，再用 clean_code 重跑 skill
  ↓
確認 clean code 不會被報 buggy
```

這條 pipeline 有兩次呼叫的可能：一次審 buggy implementation，一次審 clean implementation。通過條件不是自然語言描述漂不漂亮，而是 buggy code 的 recall-like overlap 夠高，且 clean code 沒有 false positive。

## Input / Output Contract

輸入 payload：

```json
{
  "task_id": "...",
  "task_description": "...",
  "code": "def solution(...):\n    ...\n",
  "constraints": {}
}
```

`SKILL.md` 要求 Hermes 使用 marker protocol：

```text
<original payload JSON>
__AIASE_BUG_REPORT_V1__
<candidate bug report JSON>
```

candidate report 不是正式輸出。正式輸出由 `run.py` 決定：

```json
{
  "task_id": "...",
  "verdict": "buggy",
  "bugs": [
    {
      "line_start": 10,
      "line_end": 10,
      "severity": "high",
      "type": "logic_error",
      "description": "...",
      "suggested_fix": "..."
    }
  ],
  "confidence": 0.82
}
```

clean output：

```json
{
  "task_id": "...",
  "verdict": "clean",
  "bugs": [],
  "confidence": 0.7
}
```

## `scripts/run.py` 內部流程

主線如下：

```text
main()
  ↓
_parse_input()
  ↓
若有 candidate report:
    _normalize_with_audit()
  否則:
    _audit_payload()
  ↓
_emit()
```

### `_read_raw()` 和 `_parse_input()`

runner 可以讀 CLI args、argv payload 或 stdin。正式 Hermes flow 使用 stdin heredoc。

`_parse_input()` 會把原始 payload 和 `__AIASE_BUG_REPORT_V1__` 後面的 candidate report 分開。如果 candidate report 是自然語言包 JSON，runner 會嘗試抽出 JSON object。

### `_extract_json_object()`

LLM 可能輸出：

```text
Here is the report:
{"verdict":"buggy", ...}
```

或 fenced JSON。`_extract_json_object()` 會在文字中尋找可 decode 的第一個 JSON object，讓 runner 有機會修復非純 JSON 的候選回覆。

### `_contract()`

`_contract()` 是統一輸出格式的 helper。如果 bugs 為空，輸出 `verdict="clean"`；如果 bugs 存在，輸出 `verdict="buggy"`。這確保 bugs 和 verdict 一致。

### `_sanitize_bug()`

這是 candidate bug report 的核心清理函式。它會：

- 確認 bug 是 object。
- clamp `line_start` 和 `line_end` 到合理範圍。
- 修正 `line_end < line_start`。
- 把 invalid severity 映射成 `medium`。
- 把 invalid type 映射成 `logic_error`。
- 過濾 placeholder、self-negating、speculative、不可能 control-flow claim。
- 使用 hint 修正 parser delimiter、ordinal index、binary-search boundary、DP recurrence 等常見 line/type 問題。

這個步驟的目標是把「模型可能不穩定的 report」轉成評分器能穩定比較的 report。

### `_normalize_candidate_report()`

這是處理 LLM candidate report 的第一層：

```text
report 不是 dict
  → clean fallback

verdict == clean
  → bugs=[]，回傳 clean contract

verdict == buggy
  → 取 bugs list
  → 每個 bug 做 _sanitize_bug()
  → 最多保留 2 個有效 bugs
  → 沒有效 bug 則 clean fallback
```

這裡選擇最多保留 2 個 bugs，是為了避免 LLM 一次亂列很多 speculative findings，拉高 false positive 風險。

### `_normalize_with_audit()`

這是 Bug Hunter 的主要決策點。它先得到 normalized candidate，再決定是否用 deterministic audit 覆蓋或補強。

策略如下：

- 如果 candidate 已經有 bugs，仍會跑 audit。
- 如果 audit 找到高信心 bug，且 confidence 足夠，使用 audit 結果。
- 如果 candidate 的 line range 太寬，而 audit 能定位到單行 bug，使用 audit 修正後結果。
- 如果 candidate 是 high-confidence clean，保留 clean，避免亂推翻。
- 如果 candidate 是低信心 clean 或沒有有效 report，跑 audit；audit 找到 bug 就回報 bug，否則 clean。

這個設計平衡了 precision 和 recall：不讓 audit 任意推翻高信心 clean，但也不讓低品質 candidate 阻止可執行證據進來。

## Dynamic Audit Pipeline

`_audit_payload()` 和 `_audit_payload_in_process()` 負責 deterministic dynamic audit。

```text
_audit_payload()
  ↓
開 worker process
  ↓
_audit_worker()
  ↓
_audit_payload_in_process()
  ↓
AST parse + restricted exec + probes
  ↓
Finding list
  ↓
_final_contract()
```

### Worker isolation

`_audit_payload()` 在 Linux fork mode 下會開 child process，並透過 pipe 回傳結果。worker 會：

- `os.setsid()` 建立 process group。
- 切到 temporary directory。
- 清空 environment，只保留基本 `PATH` 和 `LANG`。
- 套 CPU、memory、file size、file descriptor、core dump、process count limits。
- timeout 或 pipe error 時 kill process group。

這降低受審 code 無限迴圈、資源耗盡或產生子程序的風險。

### `_audit_payload_in_process()`

這是 audit 核心。它做：

```text
取出 task_id、description、code
  ↓
若 code 空，回報 api_misuse
  ↓
ast.parse(code)
  ↓
推測 entry function
  ↓
restricted exec candidate code
  ↓
找到 function object
  ↓
讀 signature parameters
  ↓
根據 description / entry / params 做 task classification
  ↓
執行 examples、known probes、metamorphic probes、generic probes
  ↓
把 mismatch/crash/timeout 轉成 Finding
  ↓
輸出 final bug contract
```

### Task classification 和 probes

runner 內建一批常見 task family 的 probes 和 oracle，例如：

- merge intervals。
- two sum。
- remove duplicates。
- move zeroes。
- rotate array。
- plus one。
- majority element。
- max subarray。
- max profit。
- search insert。
- kth smallest。
- valid parentheses。
- palindrome。
- valid anagram。
- roman to int。
- CSV parsing。
- binary search。

每個 `TaskSpec` 包含：

- task name。
- 如何產生 probes。
- oracle 如何計算 expected output。
- compare function 如何比較 actual 和 expected。

如果 code 在 probe 上 crash、timeout 或 output mismatch，就會產生 Finding。

### Finding 到 bug report

`_make_finding()` 會把 failure 轉成可評分的 bug：

- 定位 line range。
- 判斷 bug type。
- 設定 severity。
- 產生 description。
- 產生 suggested fix。

line 定位結合 AST、trace line、task kind 和 pattern hints，目標是把 broad report 修到最小可用行號。

## 評分時怎麼接回 `run_dev.py`

`run_dev.py` 會把 result 中的 bugs 轉成：

```python
(line_start, type)
```

然後和 ground truth 的 `(line_start, type)` 做 overlap。對 buggy code，recall-like 必須達到門檻；對 clean code，不能產生 false positive。

因此此 skill 的 report normalization 特別重視行號和 bug type，而不是只重視自然語言描述。

## 如何解決問題

Bug Hunter 把 code review 拆成三層：

- LLM 層：負責語意閱讀和產生候選 bug report。
- Normalization 層：保證 report 符合 machine-readable contract。
- Dynamic audit 層：對可觸發的 bug 用實際執行證據補強。

這讓模型的不穩定輸出被轉成可比較的 JSON，也讓部分 task-family bug 不完全依賴 LLM 自我判斷。

## 測試覆蓋

selftest 和 regression 覆蓋：

- candidate report JSON extraction。
- invalid enum repair。
- line range clamp。
- placeholder/speculative/self-negating report filtering。
- clean fallback。
- known buggy task probes。
- clean code false-positive control。
- worker timeout 和 resource isolation。
- reference clean/buggy/tricky cases。

## 已知限制

- Dynamic audit 不是形式化驗證，無法涵蓋所有 Python bug。
- Task classification 依賴 description、entry name 和 parameter pattern，可能分類錯或分類不到。
- Probes 是有限集合，沒觸發的 bug 仍可能漏掉。
- Precision-oriented policy 可能犧牲 recall。
- Worker limits 降低風險，但不是完整 sandbox。
