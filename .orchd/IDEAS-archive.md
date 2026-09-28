# IDEAS Archive

本文件由 orchd 引擎自动维护：已完结 idea 条目（对应任务全部进入终态）从 IDEAS.md 自动移入此处，保留原文与审计可追溯性。勿手动编辑。
## 2026-09-26 flat 单工作树布局下 claim 的分支切换死锁（id: orchd-flat-claim-deadlock）
- status: pending
- id: orchd-flat-claim-deadlock
- 论证: 本仓采用 flat 布局（无 git worktree 隔离）：claim 把 main 切到 task/<id>，done/review 完成时又切回 main。多轮返工时第 3 次 claim 面对「当前在 main、task/<id> 分支已存在且带未合并提交」的切换前置条件而拒绝，实测死锁一次，最终由用户一次性放行手动 git checkout main 才走出。E030 系列跨 worktree 守卫在该布局下已全部降级为 not_applicable，说明引擎识别了布局特殊性，但 claim 的分支前置条件没跟着降级，两者口径不一致。修复应在引擎侧（claim 时若 task/<id> 已存在且其提交尚未合并，直接 checkout 该分支续作，而不是要求 worktree 不存在）。本仓不改 .orchd/ 引擎本体（conventions §6 发布边界：引擎本体不入库、vendored），故此条登记用于①上游 orchd-core issue 文本 ②本机 flat 布局下的绕行口径记录。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 70-verify require_keys 对非 dict 首元素裸崩冒充 FAIL 与子串假 PASS，需补防御与双向守卫（id: verify-require-keys-non-dict-guard）
- status: pending
- id: verify-require-keys-non-dict-guard
- 论证: 出处 reports/00-REVIEW-2026-09-29.md §2 F-2（沙盒已实锤）。scripts/70-verify.py:197-199 的 require_keys 分支 `key not in data[0]` 未验证 data[0] 是 dict：产物 [1,2,3] 时 TypeError 裸 traceback、rc=1 冒充 FAIL（N-2 家族复发）；产物 ["doi is here",…] 时 in 走 str 子串语义判 rc=0 静默放行（N-3 同族 fail-open）。姊妹分支 require_keys_all（:200-204）有 isinstance 防御，唯独此分支漏了；75 号自测只覆盖顶层标量与 require_keys_all 变体。修法：data[0] 非 dict 时按 N-3 口径判 FAIL（消息点明首元素实际类型）或并入 shape_problems 形态档；75 号补双向守卫（int 首元素不得以 traceback 收场、str 首元素必 FAIL）+ 对照组（对象列表缺键仍 FAIL）。改判据基座后 75/78 全量回归必须绿。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 75 号对 --check 正路的守卫用空目录，引擎 validate 端到端从未进自测（id: selftest-check-engine-e2e）
- status: pending
- id: selftest-check-engine-e2e
- 论证: 出处同报告 §2 F-3。scripts/75-verify-selftest.py:382-383 的「给了 --project 不被新守卫拦下」拿不存在的 base/noparam 当 project（注释自述不要求 rc=0），check() 的正路（生成→引擎 validate）在自测从未执行；引擎 09-25 升 v1.5.0-1 后 master fragment 与引擎 schema 的兼容性无自动回归（最近人工验证停留在 CHANGELOG D-8/D-11）。当日补测 5 档全部 valid:true errors=0（材料 24/wbpu 26/clinical 22/社科 22/cs-ml 24），契约当下成立但回归网有洞。修法：自测内建合成 .orchd 项目（vendor 本仓引擎或最小桩），让 --check 跑通真实 validate 并断言 valid 字段；沙盒用系统临时目录，维持 check() 对目标项目零写入。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

