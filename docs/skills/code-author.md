# Code Author Skill

`code-author-loweiwei` 負責 AIASE Pairwise Code Author 任務：根據題目描述和 constraints 產生 Python function。它不是把 LLM 寫出的 code 直接交給 evaluator，而是採用 candidate-first pipeline：先讓 LLM 產生候選程式，再由 `scripts/run.py` 做 AST、entry point、SLOC、import policy、sample execution 和 fallback selection。

## 設計核心

Code Author 的主要風險是：LLM 寫出的 Python code 可能語法正確，但仍可能違反評分 contract 或在 public samples 以外的基本情境失敗。

常見問題包含：

- 沒有定義題目要求的 entry function。
- 輸出被 Markdown fence 包住。
- import 了 forbidden 或危險模組。
- 使用 `eval`、`exec`、`open`、`input`、process/network I/O。
- 只 hardcode public samples，沒有實作通用邏輯。
- 無限迴圈或資源耗盡。
- 在主 process 直接執行候選 code，讓 evaluator 不穩定。

本 skill 的設計核心是：LLM 負責理解題目並提出 candidate；deterministic runner 負責判斷 candidate 是否能被安全交付。如果 LLM candidate 不可靠，runner 才使用 deterministic template 或低信心 stub。

## 目錄與檔案分工

| File | Purpose |
|---|---|
| `skills/code-author-loweiwei/SKILL.md` | Hermes 看到的 skill 規格，要求模型私下寫候選 code，然後用 marker 傳給 `scripts/run.py` |
| `skills/code-author-loweiwei/scripts/run.py` | 正式 runner，負責 candidate validation、sample execution、template fallback、result JSON |
| `skills/code-author-loweiwei/scripts/selftest.py` | 自我測試 scenarios，驗證 runner 的 contract、fallback 和 sample behavior |
| `skills/code-author-loweiwei/scripts/regression.py` | reference task regression，避免修改後破壞已知行為 |
| `skills/code-author-loweiwei/scripts/reference_training_corpus.py` | 保存 reference/template 相關素材，用於維護 deterministic templates |
| `tests/test_worker_isolation.py` | 測試 worker environment、timeout、resource limit、process group cleanup |
| `tests/test_sloc.py` | 測試 SLOC 與 import policy helper |
| `run_dev.py` | Pairwise evaluator，呼叫 skill、讀 code JSON、執行 reference test cases |

## File-Based Pipeline

```text
dev_set/pairwise/reference_tasks/*.json
  ↓
run_dev.py::grade_pairwise(role="code-author")
  ↓
組成 payload: task_id, task_description, constraints, samples
  ↓
run_dev.py::invoke_skill()
  ↓
設定 AIASE_RESULT_PATH=/tmp/.../<task_id>.json
  ↓
Hermes 執行 /code-author-loweiwei {payload}
  ↓
SKILL.md 要求 Hermes 產生 candidate code 並呼叫 scripts/run.py
  ↓
scripts/run.py 讀 payload + candidate code
  ↓
static checks + worker sample execution + template fallback
  ↓
寫 result JSON 到 AIASE_RESULT_PATH
  ↓
run_dev.py 讀 result JSON
  ↓
run_dev.py exec result["code"]
  ↓
用 reference test_cases 評分
```

正式答案是 result file 中的 `code` 欄位，不是聊天內容或 stdout。

## Input / Output Contract

`run_dev.py` 傳入 payload：

```json
{
  "task_id": "...",
  "task_description": "...",
  "constraints": {
    "entry_function": "solution",
    "max_loc": 500,
    "imports_allowed": []
  },
  "samples": [
    {"input": [[1, 2, 3]], "expected": 6}
  ]
}
```

`SKILL.md` 要求 Hermes 使用 marker protocol：

```text
<original payload JSON>
__AIASERUN_CANDIDATE_CODE_V1__
<raw candidate Python code>
```

正式輸出：

```json
{
  "task_id": "...",
  "code": "def solution(...):\n    ...\n",
  "loc": 12,
  "self_test_results": {
    "passed": 3,
    "failed": 0,
    "errors": [],
    "sloc": 12,
    "loc_violation": false,
    "import_violations": [],
    "sandbox_violations": []
  },
  "rationale": "llm_candidate validated by static checks and samples",
  "confidence": 0.78
}
```

## `scripts/run.py` 內部流程

主線如下：

```text
main()
  ↓
_read_input()
  ↓
_build_contract()
  ↓
_template_result()
  ↓
_llm_candidate_result()
  ↓
_choose_result()
  ↓
_contract_from_result()
  ↓
_emit()
```

### `_read_input()`

`_read_input()` 從 argv 或 stdin 讀取內容，並用 `__AIASERUN_CANDIDATE_CODE_V1__` 分開 payload 和 candidate code。

這個 marker 解決了 Python code 不適合直接放在 CLI argument 的問題。候選 code 可能包含換行、引號、縮排、list/dict literal，heredoc 加 marker 能完整保留內容。

### `_strip_code_fences()`

LLM 常輸出 fenced Python block。這個函式會移除：

~~~text
```python
...
```
~~~

讓 evaluator 收到純 Python source。

### `_safe_entry()`

entry function 來自 `constraints.entry_function`。runner 會確認它是合法 Python identifier，不合法時才退回 `solution`。這避免模型或 payload 中的奇怪 entry name 破壞 AST / exec 流程。

### `_validate_candidate()`

這是 LLM candidate 的第一道閘門。它檢查：

- Python syntax 是否可 parse。
- 是否定義 required entry function。
- SLOC 是否超過限制。
- top-level statement 是否安全。
- import 是否違反 forbidden / allowed policy。
- 是否使用 dangerous calls 或 banned modules。

如果這一步不通過，candidate 會被標成 `llm_invalid`，不會直接交付。

### `_static_checks()` 和 `_allowed_import_violations()`

`_static_checks()` 使用 AST 掃描 import 和 function calls。它會偵測 forbidden imports、banned modules、`eval`、`exec`、`open`、process/network 等不適合 evaluator 的操作。

`_allowed_import_violations()` 則處理 allowlist。如果 task constraints 只允許特定 imports，其他 root module 都會被記錄為 violation。

### `_sample_hardcode_warnings()`

這個檢查用來降低 sample hardcoding 風險。若 code 對 public sample input 做精確 branch，而缺少一般化控制流，runner 會拒絕該 candidate。

這不是形式化保證，但可以擋掉明顯的：

```python
if nums == [1, 2, 3]:
    return 6
```

### `_run_cases()` 和 worker isolation

sample execution 不在主 process 直接執行，而是透過 child worker。相關函式包含：

- `_run_cases()`
- `_run_cases_worker()`
- `_apply_worker_limits()`
- `_kill_worker_group()`

worker 會設定：

- temporary working directory。
- 縮小 environment。
- CPU limit。
- memory limit。
- file size limit。
- file descriptor limit。
- core dump disabled。
- timeout 後 kill process group。

這降低 infinite loop、memory blow-up、stdout/stderr noise、subprocess leak 對 evaluator 的影響。它不是完整 security sandbox，但足以讓 public sample execution 更可控。

### `_template_result()`

runner 內建 deterministic templates，涵蓋常見 coding task family，例如 merge intervals、two sum、valid parentheses、top-k frequent、binary search、max profit、coin change、flood fill 等。

`_template_result()` 會根據：

- entry function name。
- task description keywords。
- sample cases。

選出最可能的 template，然後同樣跑 static checks 和 samples。

template 是 fallback，不是第一選擇。這是為了避免把 LLM 的語意理解完全替換成固定模板。

### `_llm_candidate_result()`

這個函式把 LLM candidate 轉成 `CandidateResult`。流程是：

```text
_validate_candidate()
  ↓
_sample_hardcode_warnings()
  ↓
_run_cases()
  ↓
根據 pass/fail 設定 confidence 和 rationale
```

如果有 sample 且全部通過，candidate 通常會被給較高 confidence。若全部失敗或部分失敗，confidence 會降低。

### `_choose_result()`

這是 candidate-first policy 的核心決策點。

規則摘要：

- 沒有合法 LLM candidate 時，用 template。
- LLM 有 violation 時，用 template。
- 有 samples 且 LLM 全過時，用 LLM。
- template 全過而 LLM 失敗時，用 template。
- 兩者都部分通過時，比較 pass/fail 和 violation 數。
- 沒有 samples 時，若 LLM candidate 合法，保留 LLM。

因此這個 skill 不是只靠 templates，也不是盲目信任 LLM，而是用 deterministic checks 在兩者之間選擇。

### `_build_contract()`

`_build_contract()` 是總控函式：

```text
讀 constraints
  ↓
決定 entry function
  ↓
抽出 task description 和 samples
  ↓
建立 template result
  ↓
如果有 candidate code，建立 llm result
  ↓
_choose_result()
  ↓
_contract_from_result()
```

### `_contract_from_result()` 和 `_emit()`

最後把 `CandidateResult` 轉成正式 JSON，寫到 `AIASE_RESULT_PATH`。若任何 exception 發生，runner 也會產生低信心 fallback contract，而不是讓 evaluator 收不到結果。

## 評分時怎麼接回 `run_dev.py`

`run_dev.py` 讀到 result 後，會檢查：

- JSON 是否存在。
- `task_id` 是否一致。
- 是否有 `code` 欄位。

接著 `_run_code_test_cases()` 會 `exec` 這段 code，找到 `constraints.entry_function`，並用 reference task 的 `test_cases` 評分。

所以 skill runner 的 self-test 不是最終分數，只是本地保護；真正分數取決於 evaluator test cases。

## 如何解決問題

Code Author 把「產生 code」和「驗證 code」拆開：

- LLM 解題，負責生成候選實作。
- AST policy 防止格式、entry、import、危險 call 問題。
- sample execution 防止明顯語意錯誤。
- worker isolation 降低執行候選 code 的風險。
- deterministic template 在 LLM candidate 失敗時救援。
- stub fallback 保證 contract 不會缺失。

這讓失敗從「Hermes 沒有可讀答案」變成「合法 JSON 中附帶低信心、錯誤原因和 fallback code」。

## 測試覆蓋

相關測試與 self-tests 覆蓋：

- fenced code cleaning。
- entry function validation。
- SLOC 計算與 violation。
- forbidden import 和 dangerous call。
- worker 不繼承 secret environment。
- worker 使用 disposable working directory。
- timeout 後清掉 process group。
- memory limit 不影響 parent process。
- deterministic templates 的 reference cases。
- invalid candidate 會 fallback。

## 已知限制

- Public samples 很小，sample pass 不代表 hidden cases 一定正確。
- Template fallback 只涵蓋常見 task family。
- Worker resource limits 不是完整 sandbox。
- Sample hardcoding detection 是 heuristic，不能保證抓到所有 overfit。
- 若題目描述和 familiar problem name 衝突，仍可能依賴 LLM 是否正確理解語意。
