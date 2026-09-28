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

## 2026-09-27 AC 引用路径与 files_to_read 的方向守卫（区分「比对对象」与「交叉引用」）（id: ac-path-declaration-guard）
- status: study
- id: ac-path-declaration-guard
- 论证: 背景：task-profile-clinical 的 code 审查实测出一类会静默失效的声明缺口——AC 规定「与某文件不一致即判 CRITICAL」「按某文件的口径上收」，但该文件不在同任务的 files_to_read 里，agent 按声明读取面工作时根本拿不到比对对象。已修的那两处是 profiles/10-clinical.yaml:573/576（presubmit-review）与 :589/591（finalize-manuscript）。探针实测同类缺口三档共有：clinical 余 7 处、10-materials-chemistry.yaml 3 处（task-analyze-data 引 10-audit.md、task-claim-map 引 02-skeleton.md、task-assemble-draft 引 01-meta.json）、10-wbpu-kh550.yaml 6 处。关键设计点：必须先区分两类引用再上守卫，否则会把正当形态全判红——(a) 比对对象/口径来源（该任务要读它做判断）应要求 ∈ read∪edit；(b) 下游落点（「同一行口径须出现在 32-methods.md」）与交回上游（「数值变更须回到 11-analysis.md」）是指针性交叉引用，不该要求声明。可行的判据口径：按 AC 句子的谓语形态识别（含「与…不一致」「按…的口径」「以…为准」「核对」等判定动词者归 (a)），或退一步只对「同一任务 edit 之外且被 AC 带路径引用、同时该任务 depends_on 里也没有产出该文件的任务」这种无源引用判失败。落点建议放 scripts/78-assertions-selftest.py 新守卫段（与形状守卫同族），反向对照用「把已声明的 read 项删掉必须变红」+「正当交叉引用不得变红」两条。探针脚本可复用 C:/tmp/probe_ac_paths.py 的解析口径。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-27 能力注册表需补 exists→listed 方向（磁盘有的 profile 必须被列出）（id: registry-existence-listed-direction）
- status: study
- id: registry-existence-listed-direction
- 论证: 背景：task-profile-clinical 合并后，profiles/ 下已有 00-base-empirical / 10-clinical / 10-materials-chemistry / 10-wbpu-kh550 四个 yaml，但 SKILL.md:121-122 的领域档表与 README.md:95-96 的目录树只列了材料与 wbpu 两档——新档对使用者不可见。pending 的 task-capability-registry-resync 声明了 SKILL.md/README.md/scripts/75-verify-selftest.py 三个文件，但它的 6 条 AC 全是「列出的路径必须存在」（listed→exists）方向，没有「存在的能力必须被列出」（exists→listed）方向，因此不会自动带上本项。落点建议：resync 的守卫按 PROFILES.glob('*.yaml') 取磁盘真源（与 scripts/78-assertions-selftest.py:71-75 的 domain_profiles() 同口径，注意排除 00- 基类），逐档断言其在 SKILL.md 表行与 README.md 目录树各出现一次，并核对其行内宣称的任务数等于生成器实测 tasks= 值（现 materials 24 / wbpu 26 / clinical 22，全部由 scripts/30-gen-proposals.py 输出首行可取）；反向对照两条——删一行必须变红、把行数写错必须变红。本项可在做 resync 时作为新增 AC 并入，无需另开文件；若并入则同时更新该任务卡的验收口径。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-27 2026-09-27 deep_merge 丢子档-only inject：基类无 inject 占位时域档的「只追加本域口径」整条静默失效（id: deep-merge-child-only-inject-dropped）
- status: study
- id: deep-merge-child-only-inject-dropped
- 论证: 改动点 scripts/30-gen-proposals.py:76-84：追加分支条件从「父子都有 inject」放宽为「子档有 inject 即与父档现有 inject（缺省空列表）合并」，即 parent_inject = list(parent_t.get('inject') or [])，其余字段仍整体覆盖。回归：00-base-empirical.yaml 的 task-back-matter 保持无 inject，域档 30-cs-ml.yaml 只写 inject，断言合并视图该任务含 inject 键、生成卡 AC 多出注入的政策行（现状实测：合并视图无 inject 键、task-back-matter.json 只有基类 3 条 AC，而同批 task-write-implementation.json 有 8 条含「域口径约束」3 处）。影响面：父档已有 inject 时行为不变，父档无 inject 时等价于子档 inject 全量落地；78 号同源守卫不受影响（其比对对象是 files/json_files 断言，不含 inject）。工作量约 3 行 + 1 例自测。临时规避已落档（30-cs-ml.yaml line 775-783 注释注明该覆盖当前不生效），不改生成器则须给基类每个可注入任务补 inject: [] 占位，扩散到四档，不推荐。
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

## 2026-09-29 VERSION 的 git describe 口径不可复现（仓库无 tag 且 HEAD 已领先 10 提交），G7 缺新鲜度校验（id: version-tag-freshness）
- status: pending
- id: version-tag-freshness
- 论证: 出处同报告 §2 F-1。VERSION=v0.1.0-0-g60c0cd0，git describe --tags fatal（无任何 tag），HEAD 793e4d7 领先该提交 10 个提交；D-19 定义 VERSION 为 git describe 口径但当前值无法从仓库状态复现（-0-g 形态要求 HEAD 恰在 tag 上）。76 号 G7 只验形态 vX.Y.Z[-N-g<sha>]，不验与 git 实际状态一致。修法二选一：①在 60c0cd0 打 v0.1.0 tag 并约定发版即打 tag（此后 git describe 可复现；tag 属 git 写操作，执行须用户授权并按引擎纪律走）；②VERSION 改纯语义版本口径并在 CHANGELOG 补记。另可给 G7 加弱校验：git describe 成功时其输出须等于 VERSION 内容。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。

## 2026-09-29 引擎 verify 120s 硬上限与基座 run 断言 300s 超时互不引用，中间预算必撞 E014（id: verify-timeout-budget-crossref）
- status: pending
- id: verify-timeout-budget-crossref
- 论证: 出处同报告 §2 F-7。verify_command 受引擎 _VERIFY_TIMEOUT=120s 硬上限（例外通道 amend --verify-timeout-seconds 上界 600s，见 .orchd/rules/verify.md），而 70-verify.py 的 run 断言超时 RUN_TIMEOUT=300s；任务配 120–300s 的 run 命令时默认预算下引擎先 E014，基座 300s 承诺不可达，两层文档无互相提示。修法：70-verify.py --schema 文案与 SKILL.md 协同契约各补一句「run 断言实际预算受引擎 verify_command 超时约束（默认 120s，例外通道 600s）」，76 号可加互引存在性守卫。
- notes: 由 orchd idea propose 写入（idea-write-gate），待用户 confirm 升 pending 或 drop 丢弃。
