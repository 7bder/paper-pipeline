# IDEAS Archive

本文件由 orchd 引擎自动维护：已完结 idea 条目（对应任务全部进入终态）从 IDEAS.md 自动移入此处，保留原文与审计可追溯性。勿手动编辑。
## 2026-09-26 flat 单工作树布局下 claim 的分支切换死锁（id: orchd-flat-claim-deadlock）
- status: pending
- id: orchd-flat-claim-deadlock
- 论证: 本仓采用 flat 布局（无 git worktree 隔离）：claim 把 main 切到 task/<id>，done/review 完成时又切回 main。多轮返工时第 3 次 claim 面对「当前在 main、task/<id> 分支已存在且带未合并提交」的切换前置条件而拒绝，实测死锁一次，最终由用户一次性放行手动 git checkout main 才走出。E030 系列跨 worktree 守卫在该布局下已全部降级为 not_applicable，说明引擎识别了布局特殊性，但 claim 的分支前置条件没跟着降级，两者口径不一致。修复应在引擎侧（claim 时若 task/<id> 已存在且其提交尚未合并，直接 checkout 该分支续作，而不是要求 worktree 不存在）。本仓不改 .orchd/ 引擎本体（conventions §6 发布边界：引擎本体不入库、vendored），故此条登记用于①上游 orchd-core issue 文本 ②本机 flat 布局下的绕行口径记录。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

