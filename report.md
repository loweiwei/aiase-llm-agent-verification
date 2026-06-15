# AIASE 2026 Final Project Report

學生 / GitHub ID：`loweiwei`

## 1. 專案概述

本 repo `final-project-loweiwei` 完成四個必交 skill：`text2sql-loweiwei`、`code-author-loweiwei`、`bug-hunter-loweiwei` 與 Open Track 的 `open-test-killer-loweiwei`。整體策略是讓 Hermes Agent 只負責必要的私下推理與觸發 terminal call，正式輸出一律交給各 skill 的 deterministic `scripts/run.py` 寫入 `AIASE_RESULT_PATH` 指定結果檔；若環境變數不存在，fallback 到目前工作目錄的 `./aiase_result.json`。

file-based update 後，chat/stdout 不再是正式評分來源，因此四個 wrapper 都避免輸出 fenced JSON 到 stdout，並使用 `tempfile.mkstemp` 搭配 `os.replace` 做 atomic write，降低 partial JSON、格式漂移與 Hermes final response 干擾評分的風險。

## 2. 整體設計決策

### 2.1 為什麼採用 deterministic wrapper

LLM 直接輸出 JSON、SQL 或 Python code 時，常見風險包含 Markdown fence、自然語言夾雜、欄位缺漏、語法錯誤、unsafe imports、timeout、行號錯誤與 stdout 被評分器誤讀。因此本專案把每個 skill 拆成兩層：`SKILL.md` 負責規範 Hermes 的角色與單次 terminal call；`scripts/run.py` 負責 schema normalization、validation、fallback、timeout/sandbox/self-test 與 file-based result output。

這樣的設計讓 hidden scenario 泛化比較穩定。模型可以換、Hermes final response 可能仍有文字，但 result file 由 deterministic wrapper 寫出，contract 欄位與錯誤處理邏輯不依賴模型語氣。

### 2.2 SKILL.md 設計原則

四個 `SKILL.md` 都要求使用 terminal tool exactly once，不使用 process/background tool，不在 chat/stdout 輸出正式 JSON，不 hardcode repo root 或本機路徑。Text2SQL 使用老師 raw-template style CLI flags；Code Author 與 Bug Hunter 因 payload/code/report 可能含換行與引號，正式流程保留 heredoc marker；Open Track payload 最大，正式入口也保留 stdin/heredoc。

## 3. 各 Skill 設計

### 3.1 Text2SQL Skill

`skills/text2sql-loweiwei/SKILL.md` 限制 Hermes 只做自然語言到 SQLite read-only SQL 的推理，要求 SQL 使用現有 schema 的 table/column、JOIN 欄位要 qualify、必要時使用 `DISTINCT`，並禁止 DDL/DML、PRAGMA、transaction、WITH/CTE/window function 與多 statement。正式呼叫方式已改成 `python3 <skill_dir>/scripts/run.py --task_id ... --sql ...`，不依賴 repo root。

`scripts/run.py` 支援老師 CLI flags、argv JSON 與 stdin JSON 三種模式。它會清理 SQL fence、移除一個 optional trailing semicolon、偵測 multiple statements、forbidden keywords、WITH/window function，並在提供 schema 時用 SQLite in-memory `EXPLAIN` 做語法與欄位檢查。若 SQL invalid，結果會降成安全 fallback `SELECT NULL WHERE 0`，且 final result 只保留 `task_id`、`sql`、`rationale`、`confidence` 四欄。`scripts/validate_sql.py` 是 SQL 驗證輔助工具，保留 public `validate(schema_ddl, sql)` 介面；`run.py` 會優先共用該 helper，若 import 失敗再 fallback 到內建 SQLite `EXPLAIN` 驗證，避免正式流程因 helper import 問題中斷。

本次改善沒有加入 task_id、完整 question string 或 public case hardcoding，而是在 `SKILL.md` 補強通用 SQL reasoning：遇到 `every`、`all`、`each`、`for every`、`in every` 或「at least one ... in every ...」這類 universal quantification 時，優先使用 nested `NOT EXISTS` 的 anti-division pattern，而不是用 scalar subquery 放在 `COUNT(DISTINCT ...)` 中比較數量。這是泛化規則，可套用到 team/game/goal、customer/order、department/appointment 等不同 schema。

### 3.2 Code Author Skill

`skills/code-author-loweiwei/SKILL.md` 要求 Hermes 依 `task_description`、`constraints` 與 public samples 產生 candidate Python code，然後用 heredoc marker `__AIASERUN_CANDIDATE_CODE_V1__` 把原始 payload 與 candidate code 交給 `scripts/run.py`。這避免把多行 Python code 塞進 shell `--code` 造成 quoting 問題；同時 `run.py` 也支援老師 CLI flags 作相容入口。

`scripts/run.py` 會做 candidate-first validation：strip code fence、AST parse、entry function 檢查、SLOC、forbidden imports、allowed imports、unsafe top-level statement、`print/eval/exec/open/input/subprocess/threading/network` 等 sandbox checks，並執行 public sample self-test。candidate 通過 static checks 與 samples 時優先採用；否則使用 deterministic templates 或 fallback code。result contract 包含 `task_id`、`code`、`loc`、`self_test_results`、`rationale`、`confidence`，能降低 malformed JSON、syntax error、違規 imports 與超過 LOC 的風險。

### 3.3 Bug Hunter Skill

`skills/bug-hunter-loweiwei/SKILL.md` 要求 Hermes 分析 Code Author 輸出或待審 code，提出候選 bug report，再用 delimiter `__AIASE_BUG_REPORT_V1__` 交給 `scripts/run.py` normalize。官方流程不呼叫 `analyze.py`；`analyze.py` 僅保留為 legacy debug helper。

`scripts/run.py` 規範 final contract 為 `task_id`、`verdict`、`bugs`、`confidence`。每個 bug object 必須包含 `line_start`、`line_end`、`severity`、`type`、`description`、`suggested_fix`。line number 以 Code Author JSON 內的 `code` 字串為準，1-indexed，空行與註解都計入，不使用 harness wrapper 行號。normalizer 會 clamp line number、修正 invalid enum、過濾 placeholder report、self-negating report、speculative report 與不可能的 control-flow claim。這個設計偏 conservative：抓明顯、可觸發 bug，同時降低 clean code 誤報。

### 3.4 Open Track：open-test-killer-loweiwei

Open Track skill name、資料夾、slash command 與文件一致：`open-test-killer-loweiwei`、`skills/open-test-killer-loweiwei/`、`/open-test-killer-loweiwei`。`SKILL.md` 要求 terminal tool exactly once，並把完整原始 input JSON 經由 stdin/heredoc 傳給 `scripts/run.py`。payload 可能含大量 `reference_code`、`mutants.code` 與 candidate inputs，因此 stdin 是正式入口；`--payload` 只作 local smoke 相容模式。

`scripts/run.py` 是 deterministic mutation-testing Test Killer。它檢查 required fields，執行 reference implementation 取得 expected output，再用同一 candidate input 執行每個 mutant。reference exception、timeout 或 non-JSON-serializable output 使該 candidate invalid；mutant output mismatch、exception 或 timeout 都視為被該 candidate kill。selection 使用 deterministic greedy：每次選擇帶來最多 new kills 的 candidate，最多選 `max_tests`。結果檔包含 `selected_tests`、每個 selected test 的 `expected` 與 `kills`、`killed_mutants`、`unkilled_mutants`、`kill_rate`、`num_selected_tests`。

這個 scenario 是 verifiable，因為 kill set 由實際執行 reference/mutant 得到，不靠 LLM 自稱。演算法不 hardcode task_id、mutant id 或 candidate index，因此能應對 candidate order、mutant order、id rename、whitespace/comment 與 max_tests perturbation。

## 4. OPEN_TRACK.md 完整性

`OPEN_TRACK.md` 已檢查並包含七個必要標題：Skill 簡介、Skill 名稱與目錄、呼叫方式、自定 Verifiable Scenario、預期失敗模式、互動對象、Token Budget 估算。內容描述了 skill 名稱、目錄、slash command、stdin/heredoc 正式 procedure、input schema、successful/failure output contract、metric/pass condition、hidden perturbation/anti-hardcoding、本地測試方式與 token budget。文件不要求 repo root 當前工作目錄，也不依賴 `REPO_ROOT` 或 `git rev-parse`。

## 5. 測試與執行 Log 證據

| 測試 | 指令 | 結果 | 重點 log |
|---|---|---|---|
| repo verification | `python verify_repo.py --github-id loweiwei` | PASS | `passed: 28/28` |
| Text2SQL baseline | `python run_dev.py --skill text2sql-loweiwei --track basic` | PARTIAL | baseline `total: 21 passed: 20 rate: 95.2%`; only failure `task_nl2sql_016 result set differs`, student rowcount 5 vs gold rowcount 4 |
| Text2SQL final | `python run_dev.py --skill text2sql-loweiwei --track basic` | PASS | final `total: 21 passed: 21 rate: 100.0%`; `task_nl2sql_016` used nested `NOT EXISTS` and matched gold |
| Code Author dev | `python run_dev.py --skill code-author-loweiwei --track pairwise --role code-author` | PASS | `total: 5 passed: 5 rate: 100.0%` |
| Bug Hunter known dev log | `python run_dev.py --skill bug-hunter-loweiwei --track pairwise --role bug-hunter` | PARTIAL | 已知舊 log：`total: 5 passed: 2 rate: 40.0%`; failures show `recall=0.00, clean_fp=0` |
| Bug Hunter baseline 本次實測 | `python run_dev.py --skill bug-hunter-loweiwei --track pairwise --role bug-hunter` | PARTIAL | 修改前完整 baseline：`total: 5 passed: 3 rate: 60.0%`; failed `task_pair_002 recall=0.00, clean_fp=0`, `task_pair_004 recall=0.00, clean_fp=0`; stdout 只有 summary 與 report path，stderr 空白 |
| Bug Hunter post-fix | `python run_dev.py --skill bug-hunter-loweiwei --track pairwise --role bug-hunter` | PASS | `total: 5 passed: 5 rate: 100.0%`; all pairwise Bug Hunter cases pass |
| Code Author selftest | `python3 skills/code-author-loweiwei/scripts/selftest.py` | PASS | `ok:true passed:45 failed:0` |
| Bug Hunter selftest | `python3 skills/bug-hunter-loweiwei/scripts/selftest.py` | PASS | `ok:true passed:30 failed:0` |
| Open Track selftest | `python3 skills/open-test-killer-loweiwei/scripts/selftest.py` | PASS | `ok:true passed:5 failed:0`; public scenarios kill rates include `merge_intervals=1.0`, `valid_parentheses=0.8`, `top_k_frequent=1.0` |
| Open Track direct smoke | `AIASE_RESULT_PATH=/tmp/open_killer_result.json python3 skills/open-test-killer-loweiwei/scripts/run.py < .../merge_intervals.json` | PASS | result `ok:true`, `task_id:open_test_killer_merge_intervals`, `kill_rate:1.0`, `num_selected_tests:4` |
| Open Track Hermes smoke | `AIASE_RESULT_PATH=/tmp/open_killer_result.json hermes chat --toolsets skills,terminal --yolo -Q -q '/open-test-killer-loweiwei {...}'` | PASS | result file `ok:true`, `task_id:smoke`, selected `t1`, killed `m1`, `kill_rate:1.0` |
| Open Track via run_dev | `python run_dev.py --help` | N/A | current `run_dev.py` choices only `{basic,pairwise}`; Open Track 用 selftest/direct smoke 驗證 |

補充：Hermes smoke 測試中 chat 仍會顯示 JSON 或自然語言，但正式 result file 正確。file-based grader 讀 `AIASE_RESULT_PATH`，不是 chat/stdout；`run.py` 本身 stdout 保持空白。

## 6. 實際遭遇的失敗與分析

### 6.1 repo verification 初次掃描失敗

現象：初次執行 `python verify_repo.py --github-id loweiwei` 得到 `passed: 26/28`。log 顯示 `no-absolute-paths` 掃到 Text2SQL 文件中的 Windows path 範例字串，`no-tokens` 掃到舊 `verify_report.json` 或歷史 log 的 token-like 字串。

根本原因：這不是 skill 行為錯誤，而是文件中的「禁止範例」也會被 verifier 視為 hardcoded path；舊測試 log 也會被 token scanner 掃描。

修正方式：做非行為性清理，將具體 path literal 改為「machine-specific path」描述，並清理歷史 log 中 token-like 摘要。重跑 verifier 後得到 `passed: 28/28`。

與 verifiability 的關係：正式評分環境會掃描 repo，文件與產物也必須避免 path/token-like 字串，否則 deterministic skill 即使正確也可能被結構檢查擋下。

### 6.2 Text2SQL universal quantification 問題

現象：Text2SQL baseline dev run 為 `20/21`。唯一失敗是 `task_nl2sql_016`，log 顯示 `result set differs`，student rowcount 5、gold rowcount 4。baseline SQL 用 `GROUP BY` 搭配 `COUNT(DISTINCT (SELECT ...))` 比較數量，問題是「players who scored at least one goal in every home game played by their team」。

根本原因：這是 universal quantification，而不是一般 aggregation。用 count 比較容易因 scalar subquery、grouping scope 或 duplicate path 產生語意偏差；正確通用 pattern 是「不存在任何 team home game，使得該 player 在那場 game 沒有 goal」，也就是 nested `NOT EXISTS` anti-division。

修正方式：在 `SKILL.md` 補強通用 reasoning 規則：`every/all/each/for every/in every` 優先考慮 nested `NOT EXISTS`，`at least one ... in every ...` 不應用 scalar subquery 放在 `COUNT(DISTINCT ...)` 裡比較。單題回歸 `task_nl2sql_016` 後為 1/1 pass，完整 basic dev set 重跑為 21/21 pass。

與 verifiability 的關係：SQL 正確性必須由實際 DB 執行與 bag equality 驗證；格式與安全檢查只能保證 contract，不足以保證語意正確。這次修正是語意泛化規則，而不是背 public SQL。

### 6.3 Bug Hunter conservative normalizer 漏報

現象：已知舊 Bug Hunter pairwise dev log 為 `2/5`、`rate: 40.0%`，失敗重點是 `recall=0.00, clean_fp=0`。本次修改前依規定先跑完整 baseline，實測為 `total: 5 passed: 3 rate: 60.0%`，失敗案例是 `task_pair_002 recall=0.00, clean_fp=0` 與 `task_pair_004 recall=0.00, clean_fp=0`。兩份 log 的共同訊號一致：clean code 沒有誤報，但 buggy/tricky code 沒被抓到或 line/type 沒對齊，問題核心是 recall，不是 precision 或 clean false positive。

根本原因：`scripts/run.py` 已有 task-description / entry-function based deterministic analyzer、AST line locator、dynamic probes 與 common oracle，但正式 Hermes heredoc 路徑只執行 `_normalize_candidate_report()`，也就是只驗證 Hermes candidate report。當 Hermes 對 buggy code 回 clean 或回了錯誤 bug type 時，已有的 deterministic evidence 不會補上。因此 failure 類型不是 contract 或 output format 問題，而是正式決策路徑太保守、sample/probe evidence 沒被用來補強 candidate clean，另有 binary-search equality boundary 的 `logic_error` vs `off_by_one` type normalization 問題。

修正方式：保留 conservative default 與既有 sanitizer，不改成「不確定就報 bug」。正式修正分三步：第一，新增 `_normalize_with_audit()`，只有在 Hermes candidate 沒有有效 bug、原 candidate 明確是 clean、且 clean confidence 低於 0.70 時，才呼叫 deterministic `_audit_payload()` 補強；高信心 clean、被 placeholder/speculative sanitizer 過濾的 report、或已有有效 candidate bug 都不覆寫。第二，調整 finding ranking，讓 normal valid-domain oracle mismatch 優先於 boundary crash；這讓 `unique_paths` 先報 DP recurrence line，而不是只報 `m <= 0` crash。第三，加入泛化 binary-search boundary normalization：binary-search 類任務若報告描述 `lo == hi`、final candidate、single-element 或 skip boundary，且 code 有 `while lo < hi`，將 line 指向該 loop condition 並把 type 正規化為 `off_by_one`。

修改過程中的觀察：第一次 post-fix 從 `3/5` 提升到 `4/5`，`task_pair_004` 已 pass 且 `clean_fp=0`；剩餘 `task_pair_002` debug result 顯示 Hermes 已抓到 line 3，但 type 是 `logic_error`，grader ground truth 需要 `off_by_one`。加入 binary-search boundary type normalization 後，單題 debug `task_pair_002` 為 `passed=True recall=1.00 clean_fp=0`，完整 dev run 為 `total: 5 passed: 5 rate: 100.0%`。

為什麼不是背答案：修正沒有使用 `task_id`、固定 dev case 名稱、固定 task 順序、完整 `task_description` 字串、完整 code 字串或 line number table。觸發條件來自泛化訊號：candidate confidence、task_description/constraints 中的 binary search 語意、code 中的 `while lo < hi` 邊界型態、dynamic probe 與 deterministic oracle mismatch、AST line locator。這些規則可應對 hidden perturbations，例如 task_id 改名、case order 改變、同題型不同函式名稱或等價 code layout。

與 verifiability 的關係：Pairwise Bug Hunter 需要在 recall 與 false positive 間平衡。本次修正只在有具體 oracle/probe evidence 時補強，且保留 high-confidence clean 不覆寫，避免為了 recall 犧牲 clean code precision。最終 `Bug Hunter selftest` 仍為 `ok:true passed:30 failed:0`，`verify_repo.py --github-id loweiwei` 仍為 `passed: 28/28`。

### 6.4 stdout/chat output 與 file-based output 混淆

現象：Hermes smoke 測試中，chat 畫面仍顯示 result JSON 或成功訊息；但 `/tmp/open_killer_result.json` 正確寫入 `ok:true`、`kill_rate:1.0`。

根本原因：Hermes final response 行為不完全受 skill prompt 控制。若舊版評分器依賴 stdout/chat，這會造成 contract 風險。

修正方式：四個 `SKILL.md` 都加強 terminal exactly once 與不要在 chat 輸出 JSON；更重要的是 `run.py` 全部採 file-based output，stdout 保持空白。

與 verifiability 的關係：file-based output 將可驗證 contract 與 Agent 對話文字分離，避免 Markdown/natural-language 影響評分。

### 6.5 Open Track hardcoding 風險

現象：public scenarios 容易用固定 candidate id 或 mutant id 寫死通過，但 hidden perturbation 會改 candidate order、mutant order、task_id、id 與 whitespace。

根本原因：若 Open Track 只做字串比對或 public scenario hardcode，無法證明真正的 mutation-testing 能力。

修正方式：`run.py` 建立 reference/mutant execution matrix，直接計算每個 candidate 的 kill set，再用 deterministic greedy selection 選測資，不讀 fixed public id。

與 verifiability 的關係：kill set 由執行結果得出，因此 staff 可以重跑 evaluator 驗證 selected tests、expected output、kills 與 kill_rate。

## 7. 改進方向

- Text2SQL：持續維持 `validate_sql.py` 與 `run.py` 共用驗證介面，並增加 ambiguous column static check。
- Text2SQL：建立更多 hidden-like SQL dev set，特別是 universal quantification、UNION、nested aggregation、ambiguous names、join path 變形。
- Code Author：增加更多 deterministic templates 與 AST-based checks，並讓 self-test error 更細緻標示 syntax、runtime、sample mismatch、sandbox violation。
- Bug Hunter：建立更多 clean/buggy/tricky/noisy regression set，加入 line-number 自動校驗、更多題型 oracle、confidence calibration、dynamic probe timeout/安全隔離與 hidden-like perturbation 測試，持續提升 recall 同時維持 clean_fp 低。
- Open Track：改善 greedy tie-breaker，加入 pairwise/coverage-aware selection，對等價 mutants 與 invalid candidates 提供更完整 diagnostics。
- 測試流程：整合 `verify_repo.py`、`run_dev.py`、各 skill selftest、Open Track public scenarios 成一鍵 regression script，並固定輸出 logs 到 `logs/` 以便 report 引用。

## 8. 分工說明

本專案由本人完成，無兩人組分工。所有 skill 設計、wrapper 整合、本地測試與報告整理皆由本人負責；AI 工具僅作為輔助設計、除錯與文字整理工具。

## 9. 引用與 AI 工具使用說明

本專案以課程 starter repo、public dev set、reference skills、老師提供的 file-based raw templates 作為格式與測試參考。與 starter/reference 的差異包含：加入 file-based output、atomic write、CLI/stdin/heredoc 相容入口、SQL validator、Code Author candidate validation、Bug Hunter normalizer、Open Track deterministic mutation-testing evaluator、skill selftests 與 public scenarios。

Hermes 作為正式 skill 執行 agent；ChatGPT / OpenCode 協助理解規格、整理 prompt、檢查合規風險、產生報告草稿與定位測試失敗。最終 deterministic logic、contract、測試執行與整合驗證以 repo 內檔案與本地執行結果為準，AI 工具不取代實際驗證。
