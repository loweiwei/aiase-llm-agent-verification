# Evaluation and Evidence

本文件記錄成果數字的來源，避免混合課程評分、離線測試與模型端到端結果。

最新完整離線檢查的機器可讀輸出位於 [`artifacts/verification.json`](../artifacts/verification.json)。若該檔標示 `dirty_worktree=true`，應在正式 portfolio commit 後重新產生。

Python 3.11 clean-container build、完整測試與 `make demo` 結果記錄於 [`artifacts/docker_verification.md`](../artifacts/docker_verification.md)。

歷史 Hermes 開發 runs 的聚合與逐份摘要位於 [`artifacts/benchmarks/model_runs_summary.md`](../artifacts/benchmarks/model_runs_summary.md)。這 100 份 reports 橫跨多次開發版本與 targeted reruns，只適合分析不穩定性與失敗類型，不是受控 baseline，也不能當成 held-out accuracy。

## Experiment Status

| Comparison | Status | Evidence |
|---|---|---|
| Open Track exact vs greedy vs equal-budget random | Complete on public development scenarios | `artifacts/benchmarks/open_selection.*` |
| Raw LLM vs format normalization vs full validation | Complete on public development/reference tasks | `artifacts/model_experiments/matched_raw_format_full_gemma4_3x.*` |
| AST, dynamic-probe, template and fallback ablations | Complete on development/reference fixtures | `artifacts/benchmarks/component_ablations.*` |
| External course evaluation | Complete | `AI_Review.md` |

### Matched Raw / Format-Only / Full Comparison

同一批 108 個 no-tool raw responses（36 cases × 3 repetitions）分別重播到 strict raw、format-only 與 full deterministic paths。完整逐題結果位於 [`artifacts/model_experiments/matched_raw_format_full_gemma4_3x.md`](../artifacts/model_experiments/matched_raw_format_full_gemma4_3x.md) 及同名 JSON。

| Track | Raw strict | Format-only | Full validation |
|---|---:|---:|---:|
| Text2SQL | 0.905 | 0.905 | 0.905 |
| Code Author | 1.000 | 1.000 | 1.000 |
| Bug Hunter | 0.500 | 0.500 | 0.800 |
| Overall weighted | 0.806 | 0.806 | 0.889 |

所有 raw responses 都已是合法 JSON，因此 format-only 沒有帶來改善。Text2SQL full validation 將 6 次 SQL execution errors 轉為合法 safe fallback，但 fallback 仍無法回答問題，所以 pass rate 不變。Code Author raw candidates 在 reference cases 已全部通過。Full configuration 的 8.3 percentage-point overall gain 完全來自 Bug Hunter dynamic audit；false negatives 從 12 降到 3，false positives 維持 3。三次 pass rates 相同，sample SD 為 0；這表示此 provider/model/prompt 組合在本資料上高度 deterministic，不代表其他模型沒有變異。

這仍是曾用於開發的 public/reference tasks。結果支持「deterministic audit 可改善這批 Bug Hunter cases」，不支持所有 Skill 或 unseen data 都必然改善。

### Deterministic Component Ablation

[`artifacts/benchmarks/component_ablations.md`](../artifacts/benchmarks/component_ablations.md) records a development/reference-fixture ablation that does not require model API calls:

| Component | Reduced | Full | Metric |
|---|---:|---:|---|
| Text2SQL schema validation | 1.000 | 0.000 | invalid acceptance rate, lower is better |
| Code Author validation/fallback | 0.000 | 1.000 | reference-case pass rate |
| Bug Hunter dynamic audit | 0.000 | 0.500 | line/type overlap recall |

Bug Hunter full-configuration clean false-positive rate is 0.000 on these five reference tasks. These fixtures were used during development, so the table demonstrates component behavior rather than generalization.

## External Evaluation

課程自動化評分結果來源為 [`AI_Review.md`](../AI_Review.md)：

| Metric | Result |
|---|---:|
| Basic Track | 30.0 / 30 |
| Pairwise Bug Hunter | 8.33 / 10 |
| Open Track | 93.2 / 100 |
| Overall project | 91.38 |

外部回饋另記錄 Bug Hunter buggy F1 約 0.67，顯示 precision/recall 仍有改善空間。

這是老師使用未公開資料與私有評測流程對原始提交 `4708531` 進行的 external held-out evaluation。Basic 30/30、Pairwise Bug Hunter 8.33/10、Open Track 93.2/100 是目前最重要的未見資料證據。因 private tasks、逐題 labels 與完整 confusion counts 未公開，repository 無法獨立重跑，也不能從 F1 反推出 precision/recall。Portfolio branch 的後續修改尚未接受同一套 private re-evaluation。

## Local Deterministic Tests

Portfolio branch 最近一次完整執行：

| Command | Result |
|---|---:|
| `pytest` | 192 passed, 1 skipped |
| Code Author self-test | 45 passed, 0 failed |
| Bug Hunter self-test | 31 passed, 0 failed |
| Open Track self-test | 14 passed, 0 failed |
| Repository verifier | 27 / 27 |

這些測試主要驗證 contract、normalization、公開案例與 deterministic behavior，不代表未見資料上的一般化能力。

## Model-Dependent Development Runs

Hermes 端到端結果會受到模型回覆、工具呼叫與 provider 狀態影響。最近一次修正 result-path contract 後：

- Text2SQL 完整 run：19/21；兩個失敗為模型產生無效或 ambiguous SQL。
- Code Author 完整 run：4/5；no-result 題依一次重試政策後通過。
- Bug Hunter 完整 run：4/5；剩餘失敗為 bug recall 不足。

以上是開發診斷，不作為最終研究結論。正式比較需要固定模型版本、重複執行、保存逐題輸出並報告變異。

Portfolio 修正後的 targeted rerun 顯示 Text2SQL ambiguous-column case 與 Bug Hunter merge-interval case 通過。另一個 Text2SQL case 連續兩次直接回覆聊天文字而未呼叫 Skill，保留為 model/tool-use instability，不以 stdout recovery 偷算成正式通過。

### Controlled Three-Repetition Run

在 Hermes v0.16.0、Python 3.13.9、config `default_model: gemma4` 下，完整 validated configuration 連續執行三次。指定 reports、排除規則、逐題清理後結果與統計位於 [`artifacts/model_experiments/gemma4_validated_3x_20260829.md`](../artifacts/model_experiments/gemma4_validated_3x_20260829.md) 及同名 JSON。

| Skill | Repetition pass rates | Mean | Sample SD | Pooled | Mean task sec |
|---|---|---:|---:|---:|---:|
| Text2SQL | 0.857, 0.905, 0.952 | 0.905 | 0.048 | 57/63 | 17.47 |
| Code Author | 0.800, 0.400, 0.600 | 0.600 | 0.200 | 9/15 | 20.05 |
| Bug Hunter | 1.000, 0.800, 0.600 | 0.800 | 0.200 | 12/15 | 55.67 |

失敗分類：Text2SQL 有 5 次 semantic mismatch 與 1 次 contract/tool-use failure；Code Author 有 6 次 contract/tool-use failure；Bug Hunter 有 3 次 semantic failures。Bug Hunter mean recall-like 為 0.733，clean false-positive rate 為 0.067。這批 public development tasks 曾用於調整，因此只能呈現目前版本的不穩定性，不能作為 held-out generalization 結論。

一次使用 `--model gemma4` 的設定測試因 alias 被當成 provider model ID 而全部收到 HTTP 400；該 run 在分析前排除，並記錄於 experiment manifest。有效三次實驗都不傳 `--model`，由 Hermes config 解析 default model。Token usage 未由 Hermes/run_dev 提供，維持 `null`。

## Claims Policy

可以支持的敘述：

- The project implements deterministic validation around LLM-generated candidates.
- Open Track kill sets are derived from actual reference/mutant execution.
- The repository has substantial deterministic self-tests and course external evaluation.

目前不應宣稱：

- 100% general Text2SQL or Bug Hunter accuracy.
- Safe execution of arbitrary untrusted Python.
- Fully reproducible model results without a pinned provider and model snapshot.
- Novel mutation-testing theory beyond the engineering integration demonstrated here.
