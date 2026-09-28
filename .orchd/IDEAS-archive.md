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

## 2026-09-29 README 唯一正确姿势缺判据基座装配步骤，照走首个 done 必撞 E014/E037（id: readme-pipeline-install-step）
- status: pending
- id: readme-pipeline-install-step
- 论证: 出处同报告 §2 F-5。README:126-133「§与 orchd 的接法（唯一正确姿势）」五步第 1 步直接跑生成器、第 4 步说判据脚本经 verify_command 调用，但不含 install.py --mode project（把 70-verify.py/71-verify-manifest.json vendor 进论文项目）；该模式只写在 :157-158「§安装与发布边界」，两节互不引用。2026-09-29 审查对 5 档 profile 跑 --check 时引擎 E037 警告（verify_command 引用路径既未声明也不存在）正是此缺口的引擎侧信号。修法：接法第 1 步后插入 project 模式安装（或生成器 emit 后提示安装命令），两节互加引用；76 号可加「接法节须含 install.py --mode project 字样」守卫。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 README 尾部 7 处状态过时（D 区间/待建注记/已出仓目录），G1 抓不到需状态性守卫（id: readme-drift-state-guards）
- status: pending
- id: readme-drift-state-guards
- 论证: 出处同报告 §2 F-6。README:29/:101/:189 写「D-1…D-17」（CHANGELOG 已到 D-20）、:179「17 条设计决策」、:151「待建：task-release-manifest」与 :152「待建：归 task-installer」（两者均已落地：MANIFEST.in+G6/G7 守卫在盘、install.py 在盘且 --selftest 全绿）、:162「docs/ 待出仓」（D-19 已出仓，仓根无该目录）。76 号 G1 只查死引用，区间过时与状态过时全部漏网。修法：逐处更正外，给 76 号新增状态性守卫——README 提及的 D 区间上界 ≥ CHANGELOG 实际最大 D 编号、「待建：task-xxx」字样要求对应任务不在 _master.json completed 集，各配反向对照。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 基类 profile 单独生成必炸且报错不定位，需显式声明 extends 模板语义（id: base-profile-standalone-diagnosis）
- status: pending
- id: base-profile-standalone-diagnosis
- 论证: 出处同报告 §2 F-4。python 30-gen-proposals.py --profile profiles/00-base-empirical.yaml → rc=1：task-back-matter depends_on unknown task task-finalize-manuscript——该依赖目标只在领域子档定义，基类实为 extends 模板但 build() 不区分模板档/完整档，报错不说明；75 号夹具选取刻意排除 00- 前缀，场景在自测面外，SKILL/README 亦未声明。修法二选一：①build() 检测「depends_on 指向的任务不在本档且档位无 extends 子角色」时报「基类是 extends 模板，请用领域子档生成」（归 rc=2 用法错而非 rc=1 自检未过）；②文档加一行说明。倾向①，配 75 号守卫（对基类单独跑断言消息含「extends 模板」且 rc=2）。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 引擎 verify 120s 硬上限与基座 run 断言 300s 超时互不引用，中间预算必撞 E014（id: verify-timeout-budget-crossref）
- status: pending
- id: verify-timeout-budget-crossref
- 论证: 出处同报告 §2 F-7。verify_command 受引擎 _VERIFY_TIMEOUT=120s 硬上限（例外通道 amend --verify-timeout-seconds 上界 600s，见 .orchd/rules/verify.md），而 70-verify.py 的 run 断言超时 RUN_TIMEOUT=300s；任务配 120–300s 的 run 命令时默认预算下引擎先 E014，基座 300s 承诺不可达，两层文档无互相提示。修法：70-verify.py --schema 文案与 SKILL.md 协同契约各补一句「run 断言实际预算受引擎 verify_command 超时约束（默认 120s，例外通道 600s）」，76 号可加互引存在性守卫。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。
