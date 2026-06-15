# PAIRWISE_ROLE 宣告

role: bug-hunter
skill_path: skills/bug-hunter-loweiwei/

roles:
  - role: code-author
    skill_path: skills/code-author-loweiwei/
  - role: bug-hunter
    skill_path: skills/bug-hunter-loweiwei/

## 說明

上方同時保留舊版 verifier 可解析的頂格 `role` / `skill_path`，以及正式規格要求的 `roles` list。正式評分以 `roles` list 為準，且兩個 Pairwise 角色都已宣告。

## 規則

1. `roles` 同時包含 `code-author` 與 `bug-hunter` 兩筆。
2. 每筆 `skill_path` 指向 repo 中實際存在的 skill 目錄。
3. Pairwise 評分時由課程固定 random seed 隨機抽取其中一個角色。
