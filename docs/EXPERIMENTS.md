# Experiments and Result Interpretation

這份文件用作品集讀者比較容易理解的方式，整理本專案做過的實驗、結果代表什麼、以及哪些結論不能過度宣稱。完整分數來源與 claims policy 見 [`EVALUATION.md`](EVALUATION.md)。

## 實驗總覽

| Experiment | Question | Main Takeaway |
|---|---|---|
| External course evaluation | 老師端 private evaluation 上是否有效？ | 原始提交得到 91.38，Basic 30/30，Open Track 93.2/100。這是最重要的外部證據，但 private tasks 無法公開重跑。 |
| Local deterministic tests | Contract、fallback、timeout、edge cases 是否可重現？ | Pytest、self-tests、regressions 與 verifier 都通過，證明工程行為可在本地檢查。 |
| Open Track selection benchmark | Exact/greedy selection 是否比 random 好？ | 三個 public scenarios 中 exact/greedy 都明顯高於 equal-budget random mean。 |
| Component ablation | Deterministic checks 是否真的有作用？ | 移除 schema validation、AST/policy、templates 或 dynamic audit 會造成 invalid acceptance 或 pass rate/recall 下降。 |
| Model-dependent development runs | Hermes + gemma4 端到端是否穩定？ | 結果會受模型與 tool-use 影響；可用於診斷，不可當成 held-out accuracy。 |

## 1. External Course Evaluation

| Metric | Result |
|---|---:|
| Basic Track, Text2SQL | 30.0 / 30 |
| Pairwise Track, Bug Hunter | 8.33 / 10 |
| Open Track | 93.2 / 100 |
| Overall project score | 91.38 |

解讀：

- Basic Track 滿分表示 Text2SQL 在老師端評測流程中表現穩定。
- Open Track 93.2/100 是本專案最有代表性的成果，因為 Open Test Killer 的 correctness 主要由 reference/mutant execution 支撐，不依賴 LLM 自行判斷。
- Pairwise Bug Hunter 8.33/10 顯示 bug detection 有效果，但仍有 precision/recall 改善空間。

限制：

- 老師端 private tasks、逐題 labels 與完整 confusion matrix 不公開。
- 這些分數對應原始課程提交版本，不代表 portfolio branch 後續整理已被老師重新評分。

## 2. Local Deterministic Verification

最近一次本地驗證：

| Check | Result |
|---|---:|
| `python -m pytest` | 192 passed, 1 skipped |
| Code Author self-test | 45 passed, 0 failed |
| Bug Hunter self-test | 31 passed, 0 failed |
| Open Test Killer self-test | 14 passed, 0 failed |
| `verify_repo.py --github-id loweiwei` | 27 / 27 |

解讀：

- 這些測試主要驗證 output contract、SQL validation、AST checks、worker isolation、dynamic probes、Open Track selection 與 repository structure。
- `1 skipped` 是因為 `radon` 不在 PATH，屬於 optional SLOC tooling，不影響核心功能。
- 這組結果說明專案工程流程可重現，但不是模型泛化能力測試。

## 3. Open Track Selection Benchmark

Open Test Killer 的 public development scenarios 比較 exact search、greedy fallback 與 equal-test-count random baseline。

| Scenario | Tests | Exact | Greedy | Random mean | Candidates | Mutants |
|---|---:|---:|---:|---:|---:|---:|
| merge_intervals | 4 | 1.000 | 1.000 | 0.746 | 6 | 5 |
| top_k_frequent | 2 | 1.000 | 1.000 | 0.792 | 6 | 5 |
| valid_parentheses | 3 | 0.800 | 0.800 | 0.436 | 8 | 5 |

解讀：

- `Exact` 是在組合數安全時枚舉所有 candidate combinations，找到最大 mutation coverage。
- `Greedy` 是大規模時的 fallback；在這三個 public scenarios 中，它剛好達到與 exact 相同的 kill rate。
- `Random mean` 使用 deterministic seeds `0-99`，並且測試數量與 exact 選出的數量相同，因此比較的是「同樣 budget 下，策略性選擇是否比隨機選擇好」。
- 三個案例中 exact/greedy 都高於 random mean，表示 execution-derived kill matrix 對測試選擇有實際幫助。

限制：

- 這些是 public development scenarios，不是 hidden benchmark。
- Mutant 品質會影響 mutation score；若 mutants 太簡單或存在 equivalent mutants，分數解讀會受到限制。

## 4. Component Ablation

這組實驗不呼叫模型，只在 development/reference fixtures 上比較 reduced configuration 與 full configuration。

| Component | Reduced | Full | Metric |
|---|---:|---:|---|
| Text2SQL schema validation | 1.000 | 0.000 | invalid acceptance rate, lower is better |
| Code Author validation/fallback | 0.000 | 1.000 | reference-case pass rate |
| Code Author AST/policy | 1.000 | 0.000 | unsafe acceptance rate, lower is better |
| Code Author templates | 0.000 | 1.000 | reference-case pass rate |
| Bug Hunter dynamic audit | 0.000 | 0.500 | line/type overlap recall |

解讀：

- Text2SQL schema validation 把 invalid SQL acceptance 從 `1.000` 降到 `0.000`，代表 schema check 能阻止明顯不可執行 query 進入正式輸出。
- Code Author validation/fallback 與 templates 在 reference cases 中把 pass rate 從 `0.000` 拉到 `1.000`，代表 deterministic fallback 對降低 no-result 或 invalid-code failure 有幫助。
- Code Author AST/policy 把 unsafe acceptance 從 `1.000` 降到 `0.000`，代表 banned imports/calls 與 top-level checks 有實際攔截效果。
- Bug Hunter dynamic audit 把 line/type overlap recall 從 `0.000` 提升到 `0.500`，代表 executable probes 可以補到一部分 LLM report 漏掉或標錯的 bug evidence。

限制：

- 這是 component behavior test，不是 unseen data benchmark。
- Bug Hunter 的 `0.500` recall 代表 probes 有幫助，但也誠實顯示還沒有覆蓋所有 bug pattern。

## 5. Model-Dependent Development Runs

Hermes + `gemma4` 的端到端開發 run 顯示：

| Skill | Repetition pass rates | Mean | Sample SD | Pooled | Mean task sec |
|---|---|---:|---:|---:|---:|
| Text2SQL | 0.857, 0.905, 0.952 | 0.905 | 0.048 | 57/63 | 17.47 |
| Code Author | 0.800, 0.400, 0.600 | 0.600 | 0.200 | 9/15 | 20.05 |
| Bug Hunter | 1.000, 0.800, 0.600 | 0.800 | 0.200 | 12/15 | 55.67 |

失敗分類：

- Text2SQL：5 次 semantic mismatch、1 次 contract/tool-use failure。
- Code Author：6 次 contract/tool-use failure。
- Bug Hunter：3 次 semantic failures。
- Bug Hunter mean recall-like 為 `0.733`，clean false-positive rate 為 `0.067`。

解讀：

- Text2SQL 平均最高，主要錯在語意不匹配，而不是 wrapper 無法產生合法輸出。
- Code Author 變異最大，顯示模型是否正確呼叫工具與是否產生完整 code 仍是風險。
- Bug Hunter 有不錯平均，但 recall 仍可能不足，這也和課程評語中「Pairwise Bug Hunter 仍可改善」一致。

限制：

- 這批 public development tasks 曾用於調整，所以只能作為診斷 evidence。
- 模型 provider、Hermes config、alias 解析與 tool-use 行為都會影響結果。
- Portfolio repo 不保留 raw responses，避免作品集變成模型輸出資料 dump。

## 總結

這些實驗支持的結論是：deterministic verification 能讓 LLM software-engineering agents 的輸出更可控、更容易驗證，尤其在 Open Test Killer 與 contract validation 上效果最清楚。它們不支持宣稱本系統對所有 SQL、Python coding 或 bug hunting 任務都有通用高準確率。
