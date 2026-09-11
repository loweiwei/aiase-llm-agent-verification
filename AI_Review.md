# AIASE 2026 期末專案 — AI 評閱回饋

**GitHub ID:** `loweiwei`

## 成績摘要

| 軌道 | 分數 |
|---|---|
| Basic Track(text2sql) | 30.0 / 30 |
| Pairwise Track(角色:Bug Hunter) | 8.33 / 10 |
| Open Track(設計 40% + 執行 60%) | 93.2 / 100 |
| 基礎加分(nano 第二參考) | 26.0 / 30 |
| Pairwise 加分(nano CA) | 3.75 / 10 |
| **Project 總分** | **91.38** |

- 額外榮譽 / 加分:Open 對抗穩健(輸入重排答案不變)
- 評分重試次數:Basic **0 次**(一次到位);Pairwise 採統一重試政策(no-result 重試 1 次、flaky 受害者重評取最佳),未逐人記錄次數。

## Open Track 計分明細(透明拆解)

Open 總分 = **設計審查 × 40% + 實跑驗證(60 分制)** = **93.2 / 100**

**① 設計審查(占 40 分)= 33.2 分**(LLM 閱讀你的 skill 評分:83.0/100)

- **可驗證性:9/10** — Gold 完全由 run.py 執行 reference 與 mutant 得到，非 LLM 判斷。OPEN_TRACK.md §4 明確定義 kill 規則：輸出不一致、exception、timeout 均視為 kill，且 `expected` 必須等於 reference 輸出，全部可重現。三個 public scenario JSON 存在（merge_intervals、valid_parentheses、top_k_frequent），selftest.py 會自動驗證 stdout fenced JSON 與 result file 一致性，幾乎無主觀成分。
- **完整與清晰:9/10** — OPEN_TRACK.md 涵蓋輸入 schema、成功/失敗輸出 schema、pass metric 所有條件、perturbation robustness 說明、7 個 expected failure modes，SKILL.md 完整描述 Procedure/Contract/Verification；scripts 含 run.py（主 evaluator）、selftest.py（含 perturb_payload、typing、class、greedy_trap 等邊界案例）、regression.py。唯一缺憾是 selftest.py 最後一個函式 verify_truncated_verdict 因素材截斷而不完整，無法確認 truncation 路徑測試是否完整。
- **方法正確性:8/10** — run.py 的 kill 邏輯、normalize/ensure_jsonable、exact search vs greedy fallback 切換、atomic write（tempfile + os.replace）、verdict 條件（kill_rate >= 0.8 且非 truncated）均正確。greedy_trap_payload 可測試 exact search 不被 greedy 次優解取代。ALLOWED_IMPORTS 白名單沙箱設計合理，但 class/typing 案例顯示 _safe_builtins 中已補上 __build_class__ 與 typing import 支援，正確性有所保障。略扣分因 _greedy_select 的 tie-break key 使用 `-ord(ch)` 字元逐一比較而非直接字串比較，可能造成非預期排序，但不影響邏輯正確性。
- **失敗模式/穩健:8/10** — perturb_payload 測試了 task_id 改名、candidate/mutant 順序反轉、加入無關 candidate、縮小 max_tests；renamed_mutant_payload 測試 mutant id 改名；verdict_threshold_payload 測試低 kill_rate 路徑。multiprocessing 隔離執行避免無限迴圈與惡意程式碼影響主程序；GLOBAL_DEADLINE_SEC=110 與 MAX_EVAL_CALLS=2000 提供雙重截斷保護。selftest.py 截斷導致 verify_truncated_verdict 完整性不確定，略扣分。
- **工程嚴謹度:8/10** — exact search 以 _combo_count 預先計算 combinations 數量再決定策略，避免暴力枚舉超限；_better_selection 以 kill 數→選取數→order tuple 三層 deterministic tie-break 確保唯一輸出。selftest.py 的 verify 函式會重新執行 reference 與 mutant 驗證 expected 與 kills 欄位，等同於雙重計算交叉比對。唯一略顯薄弱之處是 MAX_EVAL_CALLS=2000 與 MAX_EXACT_COMBINATIONS=25000 的設定理由未見於文件說明，屬設計選擇但缺乏書面依據。
- **難度與原創:7/10** — 以 mutation testing test selection 作為 Open Track 題目，並自建 deterministic exact search + greedy fallback 雙模式選擇器，架構比典型「呼叫 LLM 輸出答案」的設計更具工程深度。不過 mutation testing 本身是成熟領域，本 skill 的核心貢獻在於將其正確嵌入 AIASE Open Track 框架（atomic write、fenced JSON contract、multiprocessing sandbox），創新性中等。

**② 實跑驗證(占 60 分)= 60.0 分**
- 可實際執行、輸出合法:✓ +20(滿 20)
- **確定性**(同輸入跑兩次結果一致):✓ +25(滿 25)
- 對自宣告 gold:**未宣告 gold** → 此 15 分按比例併入上兩項(重正規化到 60)

> 為何採「設計 + 實跑」雙軌:對齊公告「open in design, strict in verification」——設計分肯定你的構想,實跑分檢驗它**真的可重現、可驗證**(確定性 / 對得上自己的 gold)。

## 評語

**具體優點：**
- **Basic Track 滿分（30/30）**，30 題全數通過，text2sql 能力穩固。
- **Open Track** 設計相當嚴謹：以 multiprocessing 沙箱執行 Python mutants、exact max-coverage search 搭配 greedy fallback、atomic write 結果檔，全程不依賴 LLM 判斷 kill，完全符合可驗證精神；輸入 key 重排後答案不變，對抗穩健加分也已拿到 ✓。
- OPEN_TRACK.md 文件完整，selftest.py 涵蓋 perturbation、邊界案例與 stdout/file 一致性驗證，審查者能清楚理解設計意圖。

**建議改進的方向：**

1. **selftest.py 末段截斷問題**：truncation 路徑的測試目前存在不確定性，建議補齊該段測試案例，確保邊界行為有明確的預期輸出與驗證。
2. **greedy tie-break 邏輯簡化**：`_better_selection` 目前以 kill 數→…多層條件判斷，邏輯略顯迂迴；可考慮將 tie-break 優先順序統一抽象為一個 key function，提升可讀性與維護性。
3. **Pairwise Bug Hunter（83.3/100）**：偵測 buggy F1 平均 0.67 仍有提升空間，可回顧誤判案例，思考 bug pattern 分類策略是否能更細緻。

---
> 本評閱由 AIASE 2026 自動化評分系統產生,供學習回饋參考。
> 方法對齊課程公告精神「**open in design, strict in verification**」:
> Open Track 以 **LLM 設計審查(40%)+ 確定性實跑驗證(60%)** 評分;Basic 對齊權威 `run_dev.py`;Pairwise 以 sandbox 跑題與 bug 偵測 F1 計分。
> 各軌分數與權重以課程最終公告為準;加分項獨立計算。
