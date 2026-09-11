# Experiment Protocol

本目錄定義作品集版本的實驗方式。課程 public dev set 與 reference tasks 曾用於開發，只能作 development evaluation。老師已用未公開資料評估原始提交，該 external held-out result 記錄於 `AI_Review.md`；private tasks 無法在本地 matched replay。

## Questions

1. Deterministic wrappers 是否降低格式、contract 與執行失敗？
2. AST validation、dynamic probes 與 fallback templates 的個別貢獻為何？
3. Exact、greedy 與 random test selection 的 coverage/cost trade-off 為何？

## LLM Baselines

模型比較必須固定 provider、model identifier、prompt version 與 task set，並保存逐題輸出。

| Configuration | Description |
|---|---|
| raw-llm | 直接使用模型最後回答，不經 deterministic wrapper |
| normalized | 只做 JSON/Markdown normalization，不做語意驗證 |
| validated | 完整 wrapper，包含 static checks、dynamic tests 與 fallback |

`scripts/collect_matched_baseline.py` 使用 no-tool prompt 收集 raw responses；每個回答只呼叫模型一次。`scripts/evaluate_matched_baseline.py` 將同一回答重播到 strict raw、format-only 與 full validation，避免三種配置比較到不同模型樣本。2026-08-29 實驗已收集 108/108 responses。

每個 configuration 至少重複三次。報告 task success rate、format failure rate、execution failure rate、latency 與 token usage。不得挑選單次最佳結果作為主要結論。Matched public-development 實驗已完成三次；token usage 因 provider/run_dev 未提供而維持 `null`。

## Ablations

- Code Author：關閉 AST/policy validation、sample execution、fallback templates。
- Bug Hunter：關閉 dynamic probes、task-specific oracle、candidate normalization。
- Open Track：random、greedy、exact selection，在相同 selected-test count 下比較 mutation score。
- Text2SQL：關閉 schema validation、SQL normalization。

## Data Split

- Development：現有課程 public tasks，只用於除錯與回歸。
- External held-out：老師 private evaluation，僅能引用已提供的 aggregate scores/F1。
- Perturbation：改 task ID、函式名稱、候選順序、mutant 順序與題目文字，不改核心語意。

## Reproduction

```bash
make benchmark
```

離線 Open Track benchmark 會輸出到 `artifacts/benchmarks/`。模型實驗應另外記錄 commit、Python/Hermes/model 版本、執行時間與逐題結果。

若本機已有 `dev_run_results/*.json`，`make benchmark` 也會產生歷史開發 run 摘要，將失敗區分為 contract/tool-use、format/schema、execution 與 semantic model error。這些歷史資料不是受控 baseline，token usage 缺失時會明確記為 `null`。

`component_ablations.*` 是不需模型 API 的 deterministic component ablation：使用 curated SQL validation fixtures 與課程 Pairwise reference variants，比較 schema validation、Code Author validation/fallback、Bug Hunter dynamic audit 的 reduced/full configuration。它不能替代 raw LLM 或 held-out 實驗。

`gemma4_validated_3x.json` 明確列出完整 validated configuration 的三次 matched reports。`scripts/summarize_controlled_experiment.py` 只讀 manifest 指定 reports，輸出平均值、樣本標準差、失敗率與移除本機路徑/session 內容後的逐題結果。
