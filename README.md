[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/0_h2Gwpe)
# AIASE 2026 期末專案 Starter Repo

> 在 Hermes Agent 上打造可驗證的 Skill。詳細規格請看課程公布的Final Project細節。本檔只說明 starter repo 怎麼開始、怎麼自測、繳交前要檢查什麼。

---

## 快速開始 — 四步驟

### 1. 從課程 starter repo 拉內容,推到你自己的 GitHub Classroom repo

當你接受期末作業的 GitHub Classroom invitation 後,課程會在 `Netdb-NCKU` org 之下幫你開一個 private repo,名為 `final-project-<github_id>`(預設沒有內容)。你需要把本課程的 **starter repo** clone 下來,然後 push 到你自己的那個 classroom repo:

```bash
# (a) 從課程 starter 取得初始內容
git clone https://github.com/Netdb-NCKU/aiase2026-final-project-Final-Project.git final-project-<github_id>
cd final-project-<github_id>

# (b) 把 origin 改成你自己的 classroom repo
git remote set-url origin https://github.com/Netdb-NCKU/final-project-<github_id>.git

# (c) 把 starter 內容推到你的 classroom repo
git push -u origin main

# (d) 安裝本地開發 deps
python -m pip install -r requirements.txt
```

之後所有開發、commit、push 都在你自己的 classroom repo 內進行。**deadline 一過,課程會把全班所有 classroom repo clone 到 local 進行評分**,只認你 default branch 上的最終 commit。

> 若 (c) 失敗、提示 "Updates were rejected because the remote contains work that you do not have locally",代表你的 classroom repo 不是完全空的(可能 GitHub 預設帶了一個 README 之類)。聯繫 TA 確認後再決定要 `git pull --rebase origin main` 合併、或重新初始化。

### 2. 把所有 `<github_id>` / `GITHUBID` 改成你的 GitHub ID

`<github_id>` 以 GitHub Classroom roster mapping 為準。需要改的地方:

- `skills/text2sql-GITHUBID/`、`skills/code-author-GITHUBID/`、`skills/bug-hunter-GITHUBID/` 這三個骨架資料夾的名字
- 每個 `SKILL.md` 的 frontmatter `name:` 欄位
- `PAIRWISE_ROLE.md` 內的 `skill_path:`
- Open Track 沒有骨架,請依 `OPEN_TRACK.md` 模板**自行建立** `skills/open-<short-name>-<github_id>/`(`<short-name>` 自取);完成後在 `OPEN_TRACK.md` 的「## 2. Skill 名稱與目錄」填入該路徑。

方便起見可用:

```bash
GH=<your_github_id>
find skills -depth -type d -name '*GITHUBID*' | while read d; do
  mv "$d" "${d/GITHUBID/$GH}"
done
grep -rl 'GITHUBID' . | xargs sed -i '' "s/GITHUBID/$GH/g"   # macOS
# grep -rl 'GITHUBID' . | xargs sed -i    "s/GITHUBID/$GH/g"  # Linux
```

> 改完請以 `grep -r GITHUBID .` 確認沒有殘留。

### 3. 安裝 Hermes Agent 並把 model provider 指向課程 LiteLLM Gateway

```bash
# 安裝 Hermes（以官方文件 / starter repo pin 的版本為準）
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc   # 或 source ~/.zshrc
hermes doctor
```

把 `docs/hermes-config.example.yaml` 與 `docs/hermes-env.example` 的內容貼進你的 `~/.hermes/config.yaml` 與 `~/.hermes/.env`(或 export 環境變數)。**LiteLLM token 由課程統一提供**,不要自備。

確認:

```bash
hermes model         # 應該看到 aiase/gemma4 或 aiase/gemini-2.5-flash
hermes skills list   # 應看到 hello-aiase 與你的 text2sql-<github_id> 等
```

### 4. 跑煙霧測試與本地 dev set

```bash
# (a) 煙霧測試:hello-aiase 能跑就代表 Hermes ↔ LiteLLM ↔ skill 串得通
hermes chat --toolsets skills -q '/hello-aiase {"name":"world"}'

# (b) 本地 dev set 自測(對你的 Basic skill)
# 第一次自測前,先在本機產生 Basic dev set 的 SQLite 檔(dbs/*.sqlite 不入版控,需自行生成):
python dev_set/basic/build_dbs.py
# 之後就能跑 Basic 自測(run_dev 會在這些 DB 上以 bag equality 比對你的 SQL 與 gold_sql):
python run_dev.py --skill text2sql-<github_id> --track basic

# (c) Pairwise(對 reference 對手自測)
python run_dev.py --skill code-author-<github_id> --track pairwise --role code-author
python run_dev.py --skill bug-hunter-<github_id>  --track pairwise --role bug-hunter
```

`run_dev.py` 會把結果寫進 `dev_run_results/`。

---

## 倉庫結構

```
.
├── README.md                              ← 你正在看
├── requirements.txt                       ← 本地 dev 用,radon/pytest/PyYAML
├── run_dev.py                             ← 本地自測:驅動 hermes chat -q + 比對
├── verify_repo.py                         ← 繳交前自我檢查
├── PAIRWISE_ROLE.md                       ← 必交,宣告 Pairwise 角色
├── OPEN_TRACK.md                          ← 必交,Open Track 七區塊宣告
├── report.md                              ← 必交,設計決策 + 失敗分析
├── docs/                                  ← gateway / env 範例
│   ├── hermes-config.example.yaml
│   └── hermes-env.example
├── skills/                                ← 你的 skill 與 reference 對手
│   ├── hello-aiase/                       ← 煙霧測試,勿改
│   ├── text2sql-GITHUBID/                 ← Basic Track 骨架,改名後填邏輯
│   ├── code-author-GITHUBID/              ← Pairwise Code Author 骨架
│   ├── bug-hunter-GITHUBID/               ← Pairwise Bug Hunter 骨架
│   ├── (Open Track 自建:open-<short-name>-<github_id>/,參考 OPEN_TRACK.md)
│   ├── reference-bug-hunter-conservative/ ← 課程提供,本機自測 Pairwise 對手
│   ├── reference-bug-hunter-aggressive/
│   ├── reference-bug-hunter-noisy/
│   ├── reference-author-clean/
│   ├── reference-author-buggy/
│   └── reference-author-tricky/
├── dev_set/
│   ├── basic/                             ← Basic Track 公開 dev set(含答案)
│   │   ├── task_nl2sql_*.json
│   │   ├── dbs/                           ← 對應 sqlite(用 build_dbs.py 生)
│   │   └── build_dbs.py
│   └── pairwise/
│       ├── task_pairwise_EXAMPLE.json
│       └── reference_tasks/               ← 含 ground-truth bug 標註
└── tests/                                 ← 確定性元件的 pytest
```

---

## 必交檔案清單

繳交 deadline(2026/6/16 23:59 Asia/Taipei)前,確認 default branch 上有:

- [ ] `skills/text2sql-<github_id>/SKILL.md` + scripts(Basic Track)
- [ ] `skills/code-author-<github_id>/` **或** `skills/bug-hunter-<github_id>/`(Pairwise 二擇一)
- [ ] `skills/open-<short-name>-<github_id>/`(Open Track,自取 short-name)
- [ ] `PAIRWISE_ROLE.md`(指向上面選的 Pairwise skill)
- [ ] `OPEN_TRACK.md`(七區塊齊全)
- [ ] `report.md`

---

## 繳交前自我檢查

```bash
python verify_repo.py --github-id <your_github_id>
```

會檢查 folder name 一致性、`SKILL.md` 必填欄位、`OPEN_TRACK.md` 七區塊、無疑似 token、無絕對路徑。輸出 `verify_report.json`。

詳細檢查清單見規格書 §5.7。

---

## 重要規則(摘要,以規格書為準)

1. **不用 MCP**:本地確定性 helper 一律放 `scripts/`,不可以額外起 MCP server。
2. **輸出契約**:每個 skill 的最後一個動作 = 一段 ```` ```json ```` fenced block。多段時評分器只取最後一段。
3. **無外網**:評分環境無外網;只允許課程的 LiteLLM Gateway。
4. **無絕對路徑**:`/Users/...`、`C:\Users\...`、`/home/<name>/...` 全部禁止。
5. **dependency pin 版本**:`scripts/requirements.txt` 必須 pin 版本。
6. **task_id**:輸入有 `task_id`,輸出的 `task_id` 必須完全相同。
7. **model-agnostic**:評分模型為 held-out,別寫死在某顆模型的脾氣上。

---

## 開發策略(建議)

1. **先用 `gemma4` 反覆迭代**(免費,不耗你的 2 美元上限)。
2. 基礎穩了再切 `gemini-2.5-flash` 驗一輪跨模型不退步(計入 2 美元)。
3. `claude-haiku-4-5` 是 held-out,**開發期取不到**(別賭它的脾氣)。
4. 多用 `run_dev.py` —— dev set 含答案,是你唯一可靠的自我檢驗工具。

