# Contributions and Provenance

本文件區分課程提供內容、個人實作與 AI 工具協助，讓審查者能判斷實際貢獻。

## Course-Provided Material

以下內容源自 AIASE 2026 starter repository 或課程 reference material：

- GitHub Classroom repository structure and assignment workflow.
- `dev_set/` public development tasks and SQLite data builders.
- `skills/reference-*` reference Code Author and Bug Hunter opponents.
- Initial skill skeletons, root tests, `run_dev.py` and `verify_repo.py` foundations.
- Assignment-format documents such as `PAIRWISE_ROLE.md` and the initial Open Track template.

這些內容用於課程相容性、開發測試與比較，不宣稱為個人原創。

## Primary Student Contributions

| Area | Main contribution |
|---|---|
| Text2SQL | Read-only SQL normalization, schema-aware validation, output contract wrapper and SQL-specific guidance |
| Code Author | Candidate-first AST validation, policy checks, sample execution, deterministic fallbacks and self-tests |
| Bug Hunter | Candidate report normalization, AST location logic, dynamic probes, task oracles and regression analysis |
| Open Test Killer | Mutation execution matrix, bounded exact max-coverage, deterministic greedy fallback, result metrics and perturbation tests |
| Reliability | Atomic JSON writes, file-based result contract, fallback result recovery and contract tests |
| Evaluation | Skill self-tests, regression helpers, public Open Track scenarios and failure analysis |

Git history from the classroom starter commit `72c8e42` to submission commit `4708531` records the original course implementation. The original submission is tagged `submission-2026`; portfolio improvements belong in later commits on the `portfolio` branch.

## AI Tool Assistance

Hermes is part of the runtime architecture and generates candidate SQL, code or reports. ChatGPT/OpenCode assisted with specification interpretation, debugging, test execution, prompt review and documentation drafts.

Final claims are based on repository code, deterministic tests or explicitly identified course evaluation. AI-generated suggestions are not treated as evidence without execution or review.

## Publication Status

The repository contains course-provided tasks and reference implementations. Their redistribution license has not been confirmed in this repository. Until the instructor or course owner confirms permission, the portfolio repository should remain private or publish only student-authored components and derived documentation.
