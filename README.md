# Verifiable LLM Software Engineering Agents

這個專案在做一件事：LLM 可以先產生答案，但最後交給評分器的內容不能只靠模型自己說了算。所以我在 SQL、Python code、bug report 和 mutation testing 外面都加了一層可重跑的檢查程式，確認格式、限制、執行結果和 fallback 行為。

## 30 秒摘要

- 主題：LLM agent reliability、程式驗證、mutation testing、Text2SQL。
- 核心成果：四個可執行 Skill，包含 Text2SQL、Code Author、Bug Hunter、Open Test Killer。
- 主要貢獻：Open Test Killer 實際執行 reference implementation 與 mutants，建立 kill matrix，再用 exact search 或 deterministic greedy fallback 選出測試。
- 外部評分：原始 AIASE 2026 課程提交總分 **91.38**，Basic Track **30/30**，Open Track **93.2/100**；private tasks 沒有公開，portfolio branch 沒有重新送老師評分。
- 本地驗證：`192 passed, 1 skipped` 的 Pytest，加上 Skill self-tests、regression tests 與 repository verifier。

推薦履歷寫法：

> Built a verifiable LLM software-engineering agent framework with SQL validation, AST checks, dynamic probes, and mutation-test selection. The original AIASE 2026 course submission scored 93.2/100 on the Open Track and 91.38 overall.

## 為什麼做這個

LLM 可以產生看起來合理的答案，但在軟體工程任務中常見問題包含：

- JSON contract 格式錯誤，evaluator 無法讀取。
- SQL 查詢引用不存在或 ambiguous 的 table/column。
- Python 程式語法正確但 sample test 或邊界案例失敗。
- Bug report 的行號、錯誤類型或修正建議與實際行為不一致。
- 模型用自然語言宣稱正確，但缺少可重跑的驗證證據。

本專案的設計原則是：模型負責語意理解，程式負責可以客觀檢查的部分。

## 核心想法

LLM 的優勢是理解自然語言任務；弱點是格式、邊界條件、執行正確性與自我驗證不穩定。我的做法是把責任拆開：

- `SKILL.md` 規範 Hermes/LLM 怎麼產生候選答案與呼叫工具。
- `scripts/run.py` 是每個 Skill 的 deterministic wrapper，負責解析、驗證、fallback 與 atomic result-file write。
- `run_dev.py` 是本地端到端 evaluator，用來測試 Hermes/model 實際是否能完成任務。
- `tests/`、self-tests、regression scripts 用來證明 contract 與關鍵邊界行為可以重現。

## 系統架構

```mermaid
flowchart LR
    A[Task payload] --> B[Hermes / LLM]
    B --> C[Candidate answer]
    C --> D[Deterministic wrapper]
    D --> E{Verification}
    E -->|Text2SQL| F[SQLite schema and execution checks]
    E -->|Code Author| G[AST, policy and sample tests]
    E -->|Bug Hunter| H[Normalization and dynamic probes]
    E -->|Open Test Killer| I[Reference and mutant execution]
    F --> J[Atomic JSON result]
    G --> J
    H --> J
    I --> J
    J --> K[Evaluator]
```

## 四個 Skill

| Skill | 做什麼 | 主要驗證策略 | 詳細說明 |
|---|---|---|---|
| Text2SQL | 將自然語言問題轉成 SQLite query | read-only policy、schema validation、SQLite `EXPLAIN`、safe fallback | [`docs/skills/text2sql.md`](docs/skills/text2sql.md) |
| Code Author | 產生符合限制的 Python function | AST、entry point、SLOC/import policy、sample execution、template fallback | [`docs/skills/code-author.md`](docs/skills/code-author.md) |
| Bug Hunter | 找出 Python 程式中的具體錯誤 | report normalization、line/type repair、dynamic probes、task-family oracles | [`docs/skills/bug-hunter.md`](docs/skills/bug-hunter.md) |
| Open Test Killer | 選出能 kill mutants 的測試輸入 | reference/mutant execution、kill matrix、exact/greedy selection | [`docs/skills/open-test-killer.md`](docs/skills/open-test-killer.md) |

每份 Skill 文件都包含流程架構圖、input/output contract、方法策略、fallback、安全限制與重要檔案。

## Open Test Killer

Open Test Killer 接收 reference code、mutants、candidate inputs 與 test budget，先執行 reference 得到 expected output，再執行每個 mutant 判斷 candidate 是否 kill 該 mutant。

Kill 條件：

- mutant 輸出與 reference 不同。
- mutant 丟出 exception，但 reference 成功。
- mutant timeout，但 reference 成功。

選取策略：

- candidate combinations 不超過 `25,000` 時使用 exact maximum-coverage search。
- 超出預算時使用 deterministic greedy fallback。
- matrix construction 受 `2,000` 次 evaluation call 與 global deadline 限制。
- `kill_rate >= 0.8` 且 evaluation 未被截斷時才輸出 pass verdict。

完整規格見 [`OPEN_TRACK.md`](OPEN_TRACK.md)。

## 我實作的重點

本 repository 同時包含課程 starter/reference material 與個人實作。個人主要貢獻整理如下：

| Area | Contribution |
|---|---|
| Output contract | 設計並落實 `AIASE_RESULT_PATH` file-based JSON output，使用 temporary file + `os.replace` 做 atomic write |
| Text2SQL | SQL fence cleaning、read-only policy、schema-aware validation、SQLite `EXPLAIN`、safe fallback |
| Code Author | Candidate-first AST validation、SLOC/import policy、sample execution、deterministic templates |
| Bug Hunter | Candidate report normalization、line/type sanitization、placeholder/speculative report filtering、dynamic probes |
| Open Test Killer | Reference/mutant execution、kill matrix construction、bounded exact maximum coverage、greedy fallback |
| Reliability | Worker isolation、timeouts、resource limits、self-tests、regressions、contract tests |

更完整的來源與貢獻說明見 [`docs/CONTRIBUTIONS.md`](docs/CONTRIBUTIONS.md)。

## 成果證據

### 外部課程評測

| Track | Result |
|---|---:|
| Basic Track, Text2SQL | 30.0 / 30 |
| Pairwise Track, Bug Hunter | 8.33 / 10 |
| Open Track | 93.2 / 100 |
| Overall project score | 91.38 |

課程評語與分數來源見 [`AI_Review.md`](AI_Review.md)。老師端 private tasks 與 labels 未公開，因此 repository 無法重跑 private evaluation。

### 本地 deterministic verification

| Check | Result |
|---|---:|
| Root Pytest | 192 passed, 1 skipped |
| Code Author self-test | 45 passed, 0 failed |
| Bug Hunter self-test | 31 passed, 0 failed |
| Open Track self-test | 14 passed, 0 failed |
| Repository verifier | 27 / 27 |

### Public benchmark 摘要

| Scenario | Exact | Greedy | Random mean |
|---|---:|---:|---:|
| merge_intervals | 1.000 | 1.000 | 0.746 |
| top_k_frequent | 1.000 | 1.000 | 0.792 |
| valid_parentheses | 0.800 | 0.800 | 0.436 |

完整成果數字與限制見 [`docs/EVALUATION.md`](docs/EVALUATION.md)。

實驗結果整理在 [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md)，包含 external course evaluation、local tests、Open Track benchmark、component ablation 與 model-dependent runs。

## 快速開始

需求：Python 3.11 以上。Hermes 只有在執行模型端到端評測時需要。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python dev_set/basic/build_dbs.py
```

執行完整離線測試：

```bash
make test
```

使用 Docker 重現：

```bash
docker build -t verifiable-llm-se-agents .
docker run --rm verifiable-llm-se-agents
```

常用指令：

```bash
make selftest
make verify
```

執行 Hermes/model 端到端開發評測：

```bash
python run_dev.py --skill text2sql-loweiwei --track basic
python run_dev.py --skill code-author-loweiwei --track pairwise --role code-author
python run_dev.py --skill bug-hunter-loweiwei --track pairwise --role bug-hunter
```

Hermes 設定範例位於 [`docs/hermes-config.example.yaml`](docs/hermes-config.example.yaml) 與 [`docs/hermes-env.example`](docs/hermes-env.example)。不要提交真實 token。

## Repository Layout

```text
skills/                  四個個人 Skill 與課程 reference fixtures
dev_set/                 課程提供的 public development tasks
tests/                   deterministic test suite
scripts/                 reproducible benchmark / evidence helpers
artifacts/               benchmark 摘要
docs/skills/             每個 Skill 的流程、方法與策略說明
docs/                    技術報告、評測說明、環境與貢獻來源
run_dev.py               Hermes end-to-end development evaluator
verify_repo.py           repository contract verifier
OPEN_TRACK.md            Open Test Killer 完整規格
AI_Review.md             AIASE 2026 課程評閱回饋
```

## Documentation

| Document | Purpose |
|---|---|
| [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) | 完整技術報告 |
| [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) | 實驗結果解讀：分數代表什麼、不能代表什麼 |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | 成果數字來源、限制與 claims policy |
| [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) | Python、Hermes、Docker 環境說明 |
| [`docs/CONTRIBUTIONS.md`](docs/CONTRIBUTIONS.md) | 個人實作、課程素材與 AI 工具使用說明 |
| [`docs/skills/text2sql.md`](docs/skills/text2sql.md) | Text2SQL 流程、驗證與 fallback |
| [`docs/skills/code-author.md`](docs/skills/code-author.md) | Code Author 流程、AST/sample checks 與 worker controls |
| [`docs/skills/bug-hunter.md`](docs/skills/bug-hunter.md) | Bug Hunter normalization、dynamic probes 與限制 |
| [`docs/skills/open-test-killer.md`](docs/skills/open-test-killer.md) | Open Test Killer kill matrix 與 exact/greedy 策略 |
| [`SECURITY.md`](SECURITY.md) | 安全限制與 responsible use |

## 限制

- Public development tasks 曾用於開發與調整，不能視為 held-out benchmark。
- 老師 private evaluation 只提供 aggregate evidence，private tasks 與逐題 labels 無法公開重跑。
- Portfolio branch 的後續整理尚未接受同一套 private re-evaluation。
- Child-process limits 可降低 runaway code 風險，但不是完整 security sandbox。
- 端到端模型結果可能受 provider、模型版本與 Hermes 設定影響。
