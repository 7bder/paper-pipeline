# IDEAS

> 灵感池：讨论产生的灵感先由 `orchd idea propose` 记入 study（论证中），
> 人工 `orchd idea confirm` 后才进入摄入队列（pending）。

## 2026-09-26 规格补写 suspected 触发面不变量并同步注册表（id: spec-suspected-invariant-sync）
- status: study
- id: spec-suspected-invariant-sync
- 论证: F8 已把不变量落进 scripts/35-refs-gate.py（:485 mismatch_state 分档、:517/:520/:528 三面对照、自测 F8 组四面 + 撤稿例外 + 成文不变量断言），但规格 references/30-literature-pipeline.md §1 只有 :18 那句「只有按 DOI/编号查不到才算 suspected」，未覆盖「查到但对不上」那一面；SKILL.md 注册表那行口径同样落后。不补则下一个实现者会按 acceptance_criteria 的 AC4 字面（任一条件不成立即降为 suspected）把代码改回去，规格与代码分叉。顺带修本轮 code 审查记下的两处漏改注释：scripts/35-refs-gate.py:409（签名注释仍写 by_doi，实参已改 by_id）、:417（hits<need → suspected 与同 docstring :424-425 及实现矛盾）。改动面 3 文件，与 task-root-docs-drift-fix 同类，建议由该任务携带。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。
