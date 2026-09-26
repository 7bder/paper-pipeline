# IDEAS

> 灵感池：讨论产生的灵感先由 `orchd idea propose` 记入 study（论证中），
> 人工 `orchd idea confirm` 后才进入摄入队列（pending）。

## 2026-09-26 规格补写 suspected 触发面不变量并同步注册表（id: spec-suspected-invariant-sync）
- status: study
- id: spec-suspected-invariant-sync
- 论证: F8 已把不变量落进 scripts/35-refs-gate.py（:485 mismatch_state 分档、:517/:520/:528 三面对照、自测 F8 组四面 + 撤稿例外 + 成文不变量断言），但规格 references/30-literature-pipeline.md §1 只有 :18 那句「只有按 DOI/编号查不到才算 suspected」，未覆盖「查到但对不上」那一面；SKILL.md 注册表那行口径同样落后。不补则下一个实现者会按 acceptance_criteria 的 AC4 字面（任一条件不成立即降为 suspected）把代码改回去，规格与代码分叉。顺带修本轮 code 审查记下的两处漏改注释：scripts/35-refs-gate.py:409（签名注释仍写 by_doi，实参已改 by_id）、:417（hits<need → suspected 与同 docstring :424-425 及实现矛盾）。改动面 3 文件，与 task-root-docs-drift-fix 同类，建议由该任务携带。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-26 文献验真门控的真网络冒烟入口（id: refs-gate-live-smoke）
- status: study
- id: refs-gate-live-smoke
- 论证: 本任务两轮返工暴露的共同盲区：离线 fixture 是自写的，测不到端点契约漂移。三处真实缺陷全靠人肉跑真网络才发现——F1（arXiv 正常响应是 Atom XML 且超速以 406 呈现）、F3（Semantic Scholar 免 key 连发两请求即 429、对个别真 DOI 直接 404）、F9（arXiv 的 IP 级速率罚时窗口会累积，静置 240s 未恢复）。缺一个只读冒烟面：按 HOST_INTERVAL_S 的合规间隔、限制请求量（建议 3 条已知真题录、上限 12 个请求），输出四索引 source 状态分布与「较上次漂移」的告警，作为 --selftest 的补面而非替代（后者仍须零联网）。落点候选：scripts/35-refs-gate.py 增 --smoke-live 子面，或独立 scripts/36-refs-smoke.py；须写明不可在 CI 里当硬门禁（外部服务限流非本仓可控）。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。
