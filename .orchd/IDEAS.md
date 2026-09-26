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

## 2026-09-26 flat 单工作树布局下 claim 的分支切换死锁（id: orchd-flat-claim-deadlock）
- status: study
- id: orchd-flat-claim-deadlock
- 论证: 本仓采用 flat 布局（无 git worktree 隔离）：claim 把 main 切到 task/<id>，done/review 完成时又切回 main。多轮返工时第 3 次 claim 面对「当前在 main、task/<id> 分支已存在且带未合并提交」的切换前置条件而拒绝，实测死锁一次，最终由用户一次性放行手动 git checkout main 才走出。E030 系列跨 worktree 守卫在该布局下已全部降级为 not_applicable，说明引擎识别了布局特殊性，但 claim 的分支前置条件没跟着降级，两者口径不一致。修复应在引擎侧（claim 时若 task/<id> 已存在且其提交尚未合并，直接 checkout 该分支续作，而不是要求 worktree 不存在）。本仓不改 .orchd/ 引擎本体（conventions §6 发布边界：引擎本体不入库、vendored），故此条登记用于①上游 orchd-core issue 文本 ②本机 flat 布局下的绕行口径记录。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-26 生成器 deep_merge 对 list 是替换：verify_assertions_template 应按任务合并，rules_fragment 与 evidence_policy 应做占位替换（id: deep-merge-list-per-task）
- status: study
- id: deep-merge-list-per-task
- 论证: 落点 scripts/30-gen-proposals.py:deep_merge（list 分支现只对 tasks/depends 例外）与 fill()/rules_fragment()。现状后果：①子档无法给继承任务追加实质断言（一重定义就清掉父档 20 条），故 10-wbpu-kh550 自有任务 origin-data-separation/supplement-decision 至今只有 forbid+min_bytes 通配；②基类 unit_source 改成 {data} 占位后无人替换（fill 只作用于任务规格），只能靠领域档整条覆盖 + scripts/78 两条守卫兜住漏覆盖。改造判据：子档写 - task: X / files: 追加时按 path 归并，同名 path 子档覆盖、父档其余保留；--regress A 类差异保持 0；78 正反控制与反向对照保持全绿并新增一条子档追加断言的用例。风险：合并语义变了会影响既有 paper2+ 档的显式覆盖意图，需在 CHANGELOG 留决策。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-26 通配 forbid(AUTHOR CONFIRM) 与写作分节的人工闸门标记冲突，需裁定豁免面（id: wildcard-forbid-vs-author-marker）
- status: study
- id: wildcard-forbid-vs-author-marker
- 论证: 现网事实：profiles/10-materials-chemistry.yaml 的 task:'*' + apply_to: edit_files_text 通配对所有文本产物禁 AUTHOR CONFIRM，而工作流要求写作分节在合稿前保留 AUTHOR CONFIRM 待作者裁定——paper1 的 31-introduction/32-experimental/33-results-discussion 三个分节均含该标记，脚本 78 --project paper1 已把它显式报成 INFO 3 处。后果：任何新项目的 task-write-* done 门禁在作者未裁定时会 FAIL，而 FAIL 正是它该做的事（逼裁定），除非我们改为豁免分节文件。三条候选：①通配保持不动，把裁定推迟到 task-assemble-draft（现状，代价是写作任务在闸门未开时不可 done）；②apply_to 排除 30-manuscript/sections/*，只禁 36-draft 之后的产物；③给写作任务专用 forbid 集（只禁 TODO）。需作者裁定取哪条，裁定后 78 的回放 INFO 应转为对应口径的断言。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-26 断言词项出处白名单机检：每条 contains/require_keys 须能回指本任务 AC、references 字段表或英文分节名（id: assertion-token-provenance-guard）
- status: study
- id: assertion-token-provenance-guard
- 论证: 本轮 code 审查手工做过一次全量核对（20 任务全部词项），命中 24 处词项不在本任务 AC 字面内，其中 23 处合法（跨档引用 references/30 的 ref_no/two_source_verified、英文分节名 Materials/Introduction、01-meta.json 键名），1 处为真缺陷（task-citation-audit 的「机制承载」是从 task-lit-fulltext-inventory 借来的分层用语，AC 里没有，已在 88ddf2c 删除）。手工核对不可复用，故值得机器化：给 profile 每条断言加 `token_source:` 标注（本档 AC / references/NN:行 / 英文分节名枚举），由 scripts/78 校验 source 指向的文本确实含该词项；无 source 视为违规。风险：白名单机制本身可能变成新的空转装饰，须配一条反向对照（把 source 指向不含该词的位置，78 必须变红）。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-27 78 号同源比对改全对（pairwise），补回第三档挤掉的 5 个任务覆盖（id: selftest-pairwise-shared-assertions）
- status: study
- id: selftest-pairwise-shared-assertions
- 论证: 实测（2026-09-27，task-profile-clinical 合并后）：scripts/78-assertions-selftest.py:300-309 的「共有任务断言逐字一致」是星形比较——base 取 sorted 首档，只与其余档求交集比对。两档时代交集为 20；新增 10-clinical.yaml 后 sorted 首档变成它，三档交集缩到 15，materials↔wbpu 独有的 5 个共有任务（task-analyze-data / task-ingest-sem-tem-figures / task-skeleton-contract / task-sync-figure-specs-sem-tem / task-write-experimental）不再做逐字比较，属新档落地带来的静默覆盖回退。探针量得三对交集 15/15/20、差异均 0（脚本 C:/tmp/probe_pairs.py）。修法：把 300-309 改为对 names 两两组合各自求交集并比对，打印按配对逐行列，标签「两档」随实际配对数改写；反向对照沿用现套路（删某档某共有任务的实质断言，全对版必须变红）。改动只在 scripts/78-assertions-selftest.py 单文件，不动 profile 与生成器。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。
