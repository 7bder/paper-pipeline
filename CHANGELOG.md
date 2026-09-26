# 设计决策记录（防遗忘）

> 记录已拍板的决策与理由。新决策追加，不改历史条目；被推翻的条目保留并标注"已废止 + 原因"。

## D-1 全文获取路线 = OA 优先 + 一次性批量人工（2026-09-24，用户确认）

- **决策**：① 先自动取 OA（OpenAlex `best_oa_location` / Unpaywall / arXiv）；② 需机构订阅的压缩成**一次性批量动作**（用户按工单给链接集，或 CARSI 登录一次后复用持久化会话）；③ **明令排除盗版源**；④ **全文可得性不是引用前置条件**，缺全文一律降级标注"题录+摘要级 / 未核"。
- **理由（本项目实测）**：25 条标"可自动下载"实际 2 成功 / 23 为 403；脚本直连被出版社拦截；因此留下 8 个 `batch_download_*` 变体 = 无效投入。而验真/归一/审计零返工（42/42 匹配、0 异常）。
- **推论**：把投入倾斜到"验真 + 归一 + 需求单"，不投在通用爬虫上。

## D-2 claim 证据强度门限 = 分层（2026-09-24，用户采纳建议）

- 所有 claim：≥1 条支撑文献 **或** `direct-data`；否则不得进骨架。
- 机制/因果：≥1 条 **A 级全文核对**，否则必须显式标"机制表述引文献，非本稿直证"。
- 背景/现状：允许题录+摘要级，但不得据此推定量结论。
- 分歧类：≥2 条立场相反文献（否则视为伪分歧）。
- 新颖性：≥1 条全文核对 + 1 条对比基线；禁用"首次"除非附检索覆盖声明。
- 领域加严由 `profiles/*.yaml` 注入。

## D-3 立项讨论落 IDEAS（2026-09-24，用户确认）

- P0/P1 走 `orchd idea propose`（status: study）→ 用户 `idea confirm` 才进任务管线；`confirm/drop` 仅用户可执行。
- 条目 **title 必须内嵌 `（id: slug）`**（引擎校验锚点，缺 id 会被 `missing_idea_id` 拒且退出码为 0，须核 JSON）。
- **理由**：防止"讨论了但忘了注册/忘了结论"；同时不污染状态机（讨论期不 claim、不产生空转任务）。

## D-4 多论文 = entry.mode: multi-paper（2026-09-26，替代原"暂缓"）

- **原决策（2026-09-24）**：暂缓 program 级共享文献库，保留为未来能力。
- **新决策（2026-09-26）**：已落地为 `entry.mode: multi-paper`——基类新增 `task-data-asset-mapping`（P-1），做全量数据盘点、候选故事线发现、拆分决策；产出 `00-admin/05-data-inventory.md`、`06-storyline-options.md`、`07-paper-roadmap.md`。用户拍板论文组合后，每篇建独立工作空间、拷贝数据子集、以 `inherited` 模式执行。
- **边界切分**：P-1 做"选择题"（选故事线、拆文章），单篇做"填空题"（逐值核对、分析、写作）；P-1 不做执行性工作（数字核对/分析/写作），inherited 模式不重复故事线发现。

## D-12 三入口模式 = entry.mode（2026-09-26，用户确认）

- **决策**：profile 加 `entry.mode` 字段，四种值：
  - `data-first`（默认）：一组数据，自己发现故事线，走完整单篇流程；
  - `idea-first`：有研究问题，agent 搭框架+数据收集计划，用户去做实验；
  - `multi-paper`：多组数据，先做 P-1 资产盘点与拆分，每篇走 inherited；
  - `inherited`：已有外部路线图（P-1 产出），跳过故事线发现，直接逐值核对。
- **实现**：基类定义 `task-data-asset-mapping`，`build()` 仅在 `multi-paper` 时保留该任务；其余模式静默过滤。P2 之后四种模式完全汇合。
- **理由**：用户场景是 data-first（利用既有数据反推选题），不是正统 idea-first；且有多组数据拆分多篇的需求。三入口避免方向决策与执行工作重复。

## D-11 引擎升级到 v1.5.0-1-g32b4192（2026-09-25）与问题复检结论

- **升级方式**：官方安装器 `python orchd-core/install.py <宿主> --update`（**保留** `shared/`、`_master.json`、IDEAS/ROADMAP/CHANGELOG、台账与锁）。paper1 提交 `764b84f`（引擎）+ `36dbf54`（字节码移出跟踪）；paper2 提交 `ed4b573`。版本从（旧）66 个 .py 升到 **71 个 .py**，新增 `line.py`、`line_ctx.py`、`line_sync.py`、`cli/commands/line.py`、`cli/commands/check.py`，34 个文件内容变更；两项目 `validate` 均 `valid: true, errors: []`。
- **两处需知的部署差异**：① 安装器假定 **flat 宿主不跟踪 `.orchd/orchd/`**，但 **paper1 历史上是把引擎入库的**（为了克隆即可运行）⇒ 我按项目既有意图 `git add -f` 补齐 5 个新引擎文件，**偏离安装器 hint**（否则克隆得到的引擎缺文件）；paper2 不入库（0 个跟踪），遵循契约。② 安装器会在宿主根补 `ROADMAP.md`、`CHANGELOG.md`、`docs/system-design.md`、`AGENTS.md` 指针（paper2 全新创建；paper1 已存在故 `exists`）。另：paper1 曾把引擎 `__pycache__` 一并入库（121 个跟踪路径含 .pyc），已移出跟踪并确认 `.gitignore` 有 `__pycache__/`。
- **问题复检（对新引擎实测，勿凭印象）**：**E-13 已修**（`validate` 非法 master 现返回退出码 1）；**E-15 已修**（`idea propose --help` 明写 id 约定）；**E-21 已修**（`init` 新增越界守卫与 `--root`：`--master` 在项目外时必填，无 `--root` 时推断根必须落在 cwd 的 git 仓库边界内，否则 E007 拒绝——注释原文 "防跨目录静默写入"）。**E-17 部分改善**（`not_applicable` 降级仍在，但新增 `degraded_guards` 聚合、doctor 可按码检索，不再静默）。**E-16 未定**（`exempt_files_path_exists` 类型仍在；rules 文案仍以"连带既有文件"为例，是否仍对既有文件报警需实测 amend）。**E-14 未修**（docs/rules 仍无 verify 断言 schema ⇒ 本 skill 的 `70-verify.py --schema` 继续承担该职责）。
- **对本 skill 的影响**：`.orchd/rules/**`、`.orchd/SKILL.md` 均随升级更新（规则契约变了，执行时以新 rules 为准）；`references/00-project-layout.md` 里关于 `.orchd/.gitignore` 契约的描述需按新版（`orchd/` 不在豁免表）复核。
- **B 案定稿（2026-09-25，用户裁定）**：`.orchd/` 的跟踪面**对齐安装器契约**——只保留豁免表（`_master.json`、`shared/`、`IDEAS.md`、`IDEAS-archive.md`、`SKILL.md`、`__main__.py`、`rules/`、`VERSION`），其余（`orchd/`、`schema/`、`templates/`、`.orchd/docs/`、`.layout.json`）一律随安装器走不入库。paper1 执行 `git rm -r --cached` 共 **79 个条目**，跟踪面 96 → **17**，提交 `4c6661c`；paper2 本就符合（0 跟踪）。**新项目引导一律按契约**：引擎不入库、宿主根 `AGENTS.md` 指针 + `install.py` 承担"克隆即可运行"；回滚方式为 `git add -f .orchd/orchd`（文件始终在盘）。

## D-10 paper2 正式引导（2026-09-24）与引导流程的硬顺序

- **已完成**：paper2 从"裸数据文件夹"变为 orchd 项目——基线提交 `84caa9d`（原样导入 15 个文件）→ vendor 引擎到 `.orchd/`（只带引擎与资产，不带任何状态文件与 paper1 的 `mod-*`）→ 按布局规范归位（`00-admin/00-plan.md`、`01-planning-summary.md`、`02-verification-report.md`；`00-data/` → `10-data/raw/`）→ `orchd init` → **25 个任务全部 pending**、`validate` **`"valid": true, errors: []`**（warning 只剩 E029）→ 提交 `dfcfcec` → `intake`。
- **引导硬顺序（实测，颠倒必失败）**：① 基线提交（先有版本控制，后续搬迁才可归因）→ ② vendor 引擎 → ③ **把 master 落在项目内 `.orchd/_master.json`** → ④ `orchd init`（**不要**用 `--master` 指项目外文件）→ ⑤ 提交（`init` 必产生未提交文件）→ ⑥ `intake`（它要求干净工作区，order_前提是 ⑤）。
- **引擎实测两条（供反馈）**：**E-21** `orchd init --master <项目外路径>` 把**项目根推断为 master 所在目录**，于是 `mod-*/spec.json`、`_ledger.jsonl`、`_checkpoint.json`、`.orchd/snapshots` 全部写到别处，而 cwd 项目**零写入且无告警**（本次污染了我的工作区，已清理）；建议限定 master 必须在项目内，或提供显式 `--root`，否则应报错而非静默跨目录写。**E-22** `bootstrap` 只是**打印机**（输出 schema/prompt/guide，不落文件），其 guidance 文案"先 bootstrap 再 init"容易被读成"bootstrap 会初始化"；且 `intake` 要求干净工作区但未提示"init 后需先 commit"。
- **P0 状态**：paper2 的立项文档本就齐备（`00-admin/00-plan.md` 含标题/目标刊三档/数据来源/创新点/结构），故 P0 不需要重做收敛，直接进 P1；首个候选与人工闸门见 `status`/`request` 回显。**注意** `task-origin-data-separation` 需在 **Origin** 中打开 `.opju` 判含/不含 KWBPU——这是**人工闸门**（agent 读不了专有二进制），也是全链首个外部依赖。

## D-9 判据基座归 skill 发货（2026-09-24）

- **决定**：`verify.py` 与 `verify_manifest.json` 的 schema 由**本 skill 发货**（选 (a)），不采用"每项目自建"。
- **命名两制**：新项目用编号规范 `70-tools/70-verify.py` + `70-tools/71-verify-manifest.json`；**paper1 冻结为 `scripts/verify.py` + `scripts/verify_manifest.json`**（22 条历史 `verify_command` 属执行字段、终态不可改，改名即永久失去历史任务 verify 可重跑这一回归能力）。生成器用 profile 的 `verify_tool` 键切换，勿在任务模板里写死。
- **为什么不选 (b)**：引擎把 `verify_command` 当一等契约（`E014/E022/E024/E027/E037`，其中 E037 标为阻断级）。若不发货，新项目注册后 done 期无门禁、AC 退化为纯文本；且引用门控/文风检查/一致性检查三个脚本都挂在这份基座上，无基座则无处挂。
- **断言类型（不得回退）**：`files{path,min_bytes,contains,forbid,word_count}`、`json_files{path,min_items,max_items,require_keys}`、`globs{pattern,min_count,min_bytes_each}`、`run`——以上为 paper1 在用集合，**逐字保持语义**。
- **新增类型（补 paper1 暴露过的缺口）**：`contains_regex`/`forbid_regex`（编号连续性等正则口径）、`min_matches{pattern,min}`（"逐条列出"类 AC 的条数下限）、`require_keys_all`（原 `require_keys` 只查列表第 1 项，"逐条校验"必须查全部）、`absent_paths`（否定式验收：旧目录无残留 / 正文不得残留标记）。另有 `--root`/`--manifest`/`--all`/`--json`/`--schema`，使审查者能对别的项目一键复跑、且 schema 无需读源码（回应 E-14）。
- **回归方式**：`scripts/75-verify-selftest.py` = ①合成控制套件（每个断言类型一对"应通过/应失败"，只接受两边都触发）②与真实项目历史 verify 的 parity（逐任务 rc 必须一致）。实测：**29/29 用例 + 23/23 任务 parity 一致**（含两个 pending 任务的 FAIL 也一致）。
- **新项目引导补一笔**：`.orchd/.layout.json` 布局标记必须由 init 写入，否则引擎"自动探测为 flat"（LAYOUT 告警）——沙盒试点即因此报出该条。

## D-8 生成器落地 + paper1 回归 + paper2 试点（2026-09-24）

- **生成器** `scripts/30-gen-proposals.py`：profile → `proposals/*.json` + `_master.fragment.json` + `rules.fragment.md` + `verify_manifest.fragment.json`；支持 `extends` 继承（父档 task 列表 + 子档新增/覆盖）、`depends:` 集中声明依赖图、`--check`（用 orchd canonical 校验合成 master）、`--regress`（与真实项目结构对比）。
- **paper1 回归（PASS）**：从 `profiles/10-materials-chemistry.yaml`（当时名 `00-materials-chemistry.yaml`，后按"基类=00、域档=10"改现名）生成 **23 个任务**，`orchd validate` 通过；A 类结构（任务集合/module/depends_on/verify_command）与真实项目**零差异**，仅 6 处"有意升级"（规范图把写作挂到需求单与全文清单之后）+ 1 个新增任务 `task-claim-map`。
- **paper2 试点（PASS）**：`profiles/10-wbpu-kh550.yaml` 继承父档并覆盖四轴（新数据形态 + 有 EIS），生成 **25 个任务**，在**隔离沙盒**（复制一份引擎，不碰 paper2 目录）中 `orchd validate` PASS。
- **多域适配的两个真证据**：① 数据形态不同 → 新增 `task-origin-data-separation`（Origin 工程分离导出 + 缺口登记）与 `task-supplement-decision`（补实验人工闸门）；② 证据形态不同 → paper1 的"禁止阻抗类结论"在 paper2 必须**换成**"阻抗结论须以等效电路拟合为依据"——**同一域档家族，靠 profile 覆盖即可切换，无需改代码**。
- **引擎实测两条（供反馈）**：① `orchd validate` 校验失败时**仍返回退出码 0**，必须解析 JSON 的 `valid` 字段（E-13 家族的又一实例，这次发生在 validate 而非 done/claim）；② E037 的相对路径解析基准是 **master 文件所在目录**，故在项目外合成的 master 会报"路径不存在"假告警——校验沙盒必须把 master 写在项目内或按项目根解析。

## D-7 paper1 迁移落地实证与引擎约束（2026-09-24，迁移任务完成）

- **paper1 已迁到编号布局**（21/23 任务 completed，另外 2 个 pending 的声明路径已同步）：两处例外——`scripts/` 目录名与 `verify.py` / `verify_manifest.json` 两文件名**冻结**（保 22 条历史 verify_command 可跑）；`docs/`（引擎件）不动。
- **批量路径变更的正确姿势**：最小声明 + **单次 `--no-verify`**（用户授权 + 三处披露），因为注册期禁目录式声明、钩子只认带斜杠声明，两者语法互斥。
- **补登声明**：先切回 main 做 amend，再 `git show main:.orchd/_master.json` 写回任务分支提交；任务分支 amend 被 E007 拒、`orchd git merge main` 实机不放行（E-08 未修复）。
- **路径形态**：E010 守卫按 **git 引号+八进制转义**形态比对；取路径一律 `git -z`，禁止 `.split()`。
- **替换幂等**：前缀替换必须带负向后顾；自检必须覆盖**文件内部的值级路径**（本轮 42 条 `local_pdf` 曾被累积前缀 8 层）。
- 细则见 `references/00-project-layout.md §6`。

## D-6 文件组织与命名 = 阶段号前缀 + 产物/临时物/原始件三分（2026-09-24，用户提出）

- **目录**：`NN-<域>`（00-admin / 10-data / 20-lit / 30-manuscript / 40-figures / 50-review / 60-latex / 70-tools / 90-notebooks）。
- **文件**：`<NN><ii>-<kebab-语义>.<ext>`，序号体现阶段位置；工具约定名（`SKILL.md`/`README.md`/`ROADMAP.md`）不加号。
- **三分原则**：产物（编号、进 git）/ 临时物（`scratch/`、`79-archive/`）/ 原始件（`10-data/raw/**` 只增不改 + `MAPPING.md`）。
- **中文名仅存于 `raw/`**，其余一律 ASCII kebab-case。
- **联合约束**：必须同时满足 orchd（相对路径可声明、≤5 files_to_edit、verify_command 可执行、不手改 `.orchd/**`）与本 skill（阶段号、三分、单一真源）——检查表见 `references/00-project-layout.md §4`。
- **paper1 迁移**：**不在飞行中重排**（2 个 pending 任务的声明路径指向现状）。第 1 步仅清理未被引用的死代码/临时物；第 2 步在 `task-latex-build` 完成后，用**专门的 migration 任务**整体迁移（`git mv` 保历史 + 同步 manifest/脚本/链接 + amend 更新声明 + 迁移后全量 verify），且迁移与内容改动**分开提交**。

## D-5 阶段序 = idea → 边界 → **claim 框架 → 定向文献 → 撰写**（2026-09-24，用户指出并确认）

- **决策**：文献检索**后置**为"按需求单采购"，不得先广检再找用途。
- **理由**：本项目真实病历——"库存病"（74 条库、实引 49 条、26 条未引）与"临时凑引病"（写作期临时找文献导致落位失控）。
- **落地**：`lit/claims_map.md` 是 P2 产物、P3 的输入；文献任务 AC 必须写"按需求单逐条覆盖"，禁止"尽可能多检"；引用落位机检 5 条在 P4/P5 复跑（见 `references/20-claim-framework.md`）。

## D-13 审查驱动的修复分档 = 5 档，逐档放行（2026-09-25/26，用户裁决节奏）

- **决策**：两轮全面审查（09-25、09-26）的发现合并为 **5 档**，用户每轮只放行一档，每档末尾必须给实测验证并预告下一档。**此前分档只存在于对话里**（09-25 审查报告原件已从磁盘消失，见"遗留"），本节即其唯一落盘处。
- **各档主题与落点**（行号为本轮 grep 实测，非记忆）：

| 档 | 主题 | 已落盘的关键改动 |
|---|---|---|
| 1 | **门禁不撒谎**：崩溃与 fail-open 家族 | BOM manifest 改 `utf-8-sig` 且坏 JSON 归 rc=2（`scripts/70-verify.py:233-238`）；空 manifest `--all` 不再静默 PASS（`:255-262`）；`_` 前缀非任务键跳过并报告（`:263-271`）；顶层非 dict 归 rc=2（`:239-244`）；两脚本 `subprocess` 显式 `encoding="utf-8", errors="replace"`；含花括号 AC 由裸 KeyError 改为生成期问题记录（`scripts/30-gen-proposals.py:163-171`）。各配守卫（`scripts/75-verify-selftest.py`：manifest guards 2 + rc 语义守卫 5） |
| 2 | **判据不再空转**（深度第一轮） | 断言展开为空即生成期 die（`30-gen-proposals.py:354-357`）；二进制产物走 `apply_to: edit_files_binary` + `min_bytes_each`；`**` 递归 glob；dict 顶层 JSON 键检查不静默跳过；`emit` 清陈旧提案幂等 |
| 3 | **宣称与产物对得上** | 英文 AC 误拒改为独立 `CHECKABLE_EN` 并集判定（`30-gen-proposals.py:42-47`）；文档↔产物编号分裂消除（`references/00-project-layout.md` 改判"以 profile 生成物为准"，实测 24/26 与 SKILL/README 一致）；历史 depends_on 差异改由 `regress_expectations` 登记（`profiles/10-materials-chemistry.yaml:112-119`）；SCHEMA_SOURCE 前置校验、`extends` 以子档目录为基准；建立**能力注册表（可用性以磁盘为准）**与**命名两制**（`70-tools/70-verify.py` vs paper1 冻结 `scripts/verify.py`） |
| 4 | **能发布**：仓库卫生与发布边界 | `_pilot/` 4.1 MB → 55.7 KB 只留证据；`build/`、`build-paper2/` 出仓；含绝对路径的锁文件清除；新建 `.gitignore`；两代 `_validate.proposed.json` 重生成对齐 24/26 且字节级幂等；README 新增 §发布边界（入库集合实测 135.2 KB / 14 文件、机器路径与用户名命中 0）；`.pyc` 结构性根治（跨进程调用 `-B`，见 `30-gen-proposals.py:391` 附近；importlib 前设 `sys.dont_write_bytecode`）；`--check` 对 paper1 全树 1306 文件零写入实证 |
| 5 | **给门禁加牙 + 补新能力**（未启动） | 见下"第 5 档口径" |

- **第 5 档口径（本轮明确）**：**不整体做**。真正的先序是 2 档遗留的 **N-6 断言空心化**（实测 wbpu 26 个任务条目里含实质断言者 = 0，机检 schema 具备能力而 profile 一条没用），它不依赖任何新脚本。之后按"下一篇用得上"只提两项：`45-consistency-check.py`（编号↔文献表、图↔正文提及是**两文件集合比对**，现有五类断言表达不出来）与 `35-refs-gate.py`（唯一必须联网项，假引用不可逆）。`40-style-check.py`（可先靠 profile `forbid_regex` 顶 80%）、`references/50-orchd-runbook.md`（纯文档）、`static/` 碎片命中（只在换刊时要，SKILL.md:106 已声明建成前靠 profile 覆盖）**降级按需领**。
- **规格落点差异**（谁想实现先去读这些，别照注册表那一行自由发挥）：`35-refs-gate` **有完整规格**于 `references/30-literature-pipeline.md:11-19`（四索引、相似度 ≥0.70 且期刊/年份一致且非撤稿、k 语义、三态 `verified/suspected/unresolvable`、**反伪造偏置**、`gate.mode = advisory|strict`），决策依据 D-1；`45-consistency-check` 有范围无算法（`references/40-draft-to-latex.md:22`，并锁定"以 45 为唯一命名"）；`40-style-check` 与 `50-orchd-runbook` **仓库内无规格**（词表与反谄媚条款历来只在外部件里）；`static/` 命中算法**无规格**。→ **2026-09-26 补规格落地**：`40-style-check`（词表 schema + 三条判定 + 自测面）、`50-orchd-runbook`（四节大纲 + 每节最低条目数与真实病历素材出处）、`static/` 碎片命中（manifest schema + 注入算法 + 守卫三条）三项的设计已写入 `references/60-capability-specs.md` §1/§2/§3，并被对应任务的 `files_to_read` 列为 must_read；其中 §3.1 取代 `references/40-draft-to-latex.md` 的 `static/publisher/<name>.md` 旧口径（碎片不止出版社一个轴），该文档更正归 `task-root-docs-drift-fix`。
- **遗留（未修，登记于此）**：① `--regress`/`--check` 缺 `--project` 时静默 rc=0 与位置参数文档写法（N-4）；② cp936 纯环境下 FAIL 打印含非 GBK 字符会 `UnicodeEncodeError` → rc=1 截断诊断（N-1，方向仍 fail-close）；③ `--manifest` 相对路径以 `--root` 为基准二次拼接（N-5）；④ 基类 P-1 注入隐含依赖领域档存在 `task-audit-data`（N-10）；⑤ 入口表 P0/P1 先后表述与 `40-draft-to-latex.md` 的"待建清单第 3 项"悬空序号引用（N-9）。以上均已进 `.orchd/_master.json` 任务池。
- **两处待用户裁决**：① 图件文件名连字符（profile/新立项目标）vs 下划线（paper1 实盘与其终态声明），牵连 13 条路径；② 手工 manifest 条目"四段全空 = 空验收 PASS"旧语义是否收紧。

## D-15 09-26 报告全量复核后的档位修正与补立项（2026-09-26，用户裁决）

- **复核口径**：报告 12 项发现逐条重做实验（沙盒 `C:\tmp\nv\`，脚本现场调用形态），判定 **真 10 / 半真 2 / 不成立 0**。两处半真：
  - **N-5**：现象（相对路径"manifest not found"难诊断）为真，但报告的机理描述有误——实测是 `--root` 覆写 `ROOT` 后 `resolve_manifest` 以 `ROOT` 为基准再拼一次，故 `--root X --manifest X/子路径` 变成 `X/X/…`；错误消息只回显候选名不回显原值与最终绝对路径，这才是难诊断的根因。AC 已按实测重写并拆两条。
  - **N-9**：所谓"入口表 P0/P1 顺序相反"实为**有意倒序**（data-first 先盘点数据再收敛故事线），要加一句说明而不是改序。
- **N-4 实测比报告更糟**：`--regress`/`--check` 缺 `--project` 不是"静默跳过 rc=0"，而是**静默走 emit 写出默认 `--out build/`**（探针已复现并清理）。已把"不落任何生成物"写进 `task-gen-cli-flags-and-p1-guard` 的 AC1，并把该 AC 扩为退出码 2 + 消息含缺失参数名。
- **N-3 档位由 P3 上调为必修**：报告把 N-2/N-3 一并记 P3，但复核确认 **N-3 是全仓唯一真 fail-open**（`check_json:142` 的 `and data` 短路使"空列表 + `require_keys_all`"在无 `min_items` 时 rc=0 静默放行，即"逐条字段齐全"类 AC 空转）。落点：新建 `task-verify-manifest-shape-guards`（`mod-judgment`，importance **critical**，依赖 N-1 任务以避开 `70-verify.py` 单写者冲突），AC 顺序按"先堵 N-3 再收 N-2"排。N-1/N-3/N-6 三项与 N-4 构成发布前必修面。
- **补立项三件**：
  - `task-verify-manifest-shape-guards` —— N-2/N-3 形态守卫，见上。
  - `task-archive-refs-and-register` —— N-7 家族：`references/00-project-layout.md` 指向已消失的 `00-DECISIONS.md`、`.gitignore:9-10` 指向已删除的仓外 vendor 副本、本条 D-13 §遗留 缺 N-2/N-3/N-6/N-7/N-8 编号（现列 ①-⑤，未含全部十条）。
  - `task-profile-social-science` —— SKILL.md 能力注册表 `社科 profile`（`profiles/20-social-science.yaml`）此前**标 planned 而池中无任务**，属"注册表有行、无人认领"的悬空声明；现补一个与 clinical / cs-ml 同构的 pending 任务（extends 基类、只写学科差异、多域适配验证），`mod-domain-profiles` 工时 9 → 13。**本条只登记，不代表放行实现**（红线：claim 需用户点名）。
- **测量教训（本次复核自犯并已回改）**：一度把 `00-REVIEW-2026-09-26.md` 判为"已消失"，据此把 4 个任务的 must_read 改指二手记录 CHANGELOG、并把 N-7 的定义错安成 N-8 内容。实际报告一直在仓根目录（148 行 / 19,585 B）。**判"文件不存在"必须本目录 + 祖先目录都查过**，不能只 `ls` 父目录一层；已全部回指报告并带 §行号。
- **同日续查：池子自身的两处矛盾（报告未覆盖，实测挖出并已补）**：
  - **注册表翻牌无主**：`task-capability-registry-resync` AC1 的守卫要求"标 planned 的行其路径**不存在**"，而 5 个能力实现任务的 `files_to_edit` **无一含 `SKILL.md`**（实测 owner 表），resync 又依赖 `task-style-check-script`/`task-publisher-fragment-hit`——**任一能力落地，守卫必红**。修法：新建 `task-capability-registry-flip`（纯文档，`files_to_edit: [SKILL.md]`，只改状态位不改列结构/行集），并把 resync 的 `depends_on` 接上 flip（先翻牌、后写守卫，中间不出现红窗口）。
  - **机检计数宣称无主**：`README.md:139-140` 写死"31 个合成用例 + 11 个守卫"，而 4 个 pending 任务都往 `75-verify-selftest.py` 加守卫、`task-profile-substantive-assertions` 另建 `78-assertions-selftest.py`；README `L100` 目录树与"必跑"口径只列 75，**78 系测试面会被漏跑**。修法：给 resync 加 AC5（写死数字必须与实测相等，或改为不绑定数字）+ AC6（README 并列 75/78 两条命令，按原文逐条可跑 rc=0），`files_to_edit` 加 `README.md`（与 `task-root-docs-drift-fix` 靠既有依赖串行）。
- **`static/` 两制命名的边界**（写进 `references/60-capability-specs.md` §0 与 §3.2）：`static/` 下并存两类文件——被 `manifest.yaml` 索引的**规则碎片**（`<轴值>-<主题>.md`）与被 `40-style-check.py` 独读的**工具词表**（`40-ai-cavity-wordlist.yaml`）；**词表不进 manifest、生成器读到词表即错**。此前两任务各写一半约定，属悬空。
- **不立项的两项（记此存档）**：① README 自定发布门槛"非材料领域最小项目跑通 validate + 1–2 真任务闭环"需跨目录授权真实项目，不能由本工作空间闭环；② `.orchd/` 内 105 个 `.pyc`（含本日新增 47）由引擎自身落盘、`.gitignore` 已覆盖 `__pycache__/`、发布面不含引擎本体 → 不修。

## D-14 技能本体自托管接入 orchd = 无 git 模式（2026-09-26，用户指定）

> **已废止（2026-09-26 同日，见 D-15）**：本条「不为编排而 `git init`／无 git 模式」的决定已被取代——本仓已 `git init` 并推送远端 `7bder/paper-pipeline`。下方「代价（E030 降级放行）」随之作废（其前提 `not_a_git_repo` 已不成立）；本条的模块划分、任务清单、单写者事实与两条「事实更正」仍然有效。

- **动作**：`git clone 7bder/orchd-core` → `python orchd-core/install.py . --agent --cleanup`（v1.5.0-1-g32b4192），BOOTSTRAP 产 `.orchd/_master.json`（**4 模块 / 12 任务**，`validate` errors=0，2 条 E022 属纯文档任务按拆解指南 §5.5.4 豁免），`init` 建模块 spec 与快照根。
- **决策：不为编排而 `git init`**。宿主无 git 时引擎走 `orchd/nogit.py` 快照后端，claim/done 可用；基线快照在 **claim 时刻**建立（`orchd/onboard/claim.py:252-261`），故 BOOTSTRAP 期改根文档不会污染后续任务的越界判定。
- **代价（实测）**：`request` 的 `degraded_guards` 报 `actual_changes_conflict / E030 = not_applicable (not_a_git_repo)`——在途改动冲突这条门禁降级放行；越界改动仍由 done 期快照差分兜。
- **单写者文件**：`SKILL.md`/`README.md`/`CHANGELOG.md`/`scripts/75-verify-selftest.py` 被多任务共享声明，同一时刻只能有一个在途写者（由 `request` 冲突过滤保证），排期按"一次一个"看。
- **事实更正**：本机 skills 目录现仅剩 `paper-pipeline/`——09-25 审查报告原件、`_paper-pipeline-pilot-vendor-20260926\`（旧引擎出仓副本）、`paper-pipeline - 副本\`（用户备份）、仓内 `_pilot/`、`build*/` 均已不在磁盘。引擎血统可从本机 orchd-core 克隆（git 仓库，tag v1.5.0 = 32b4192）重建，旧引擎副本不再唯一。
- **二次更正（同日复核 N-7 时实测）**：上一条把 **`00-REVIEW-2026-09-26.md` 也一并判为消失，是错的**——它一直在本仓根目录（148 行 / 19,585 B，mtime 09-26 04:10），当时只检索了父目录。真正消失的只有 `00-REVIEW-2026-09-25.md`。教训：**判"文件不存在"必须在本目录与祖先目录都查**，否则会把活的必读件登记成死档（本轮已因此回改 4 个任务的 `files_to_read`）。附带实测：本机 VibeCoding 根目录全盘 `*REVIEW*2026-09-25*` 检索无果 ✓；`.gitignore:9-10` 曾指向已不存在的 vendor 副本路径（悬空引用，属 N-7/N-8 家族；该注释已于同日改述为 orchd-core 血统来源，不再指向该路径）。

## D-15 本仓纳入 git 版本控制（2026-09-26，用户指定；取代 D-14 的「无 git 模式」）

- **动作**：本仓 `git init` → 建远端 **`7bder/paper-pipeline`（public）** → 首推 `main`。基线提交 `35539ec`（39 项跟踪面）；随后 `9a45200` 清理根文档与 `.gitignore` 的本机绝对路径泄漏。跟踪面 = 交付面（`SKILL.md`/`README.md`/`CHANGELOG.md`/`ROADMAP.md`/`AGENTS.md`/`profiles/`/`references/`/`scripts/`/`assets/`/`docs/`）+ `.orchd/` 契约面 18 项（`_master.json`/`shared/`/`rules/`/`SKILL.md`/`IDEAS.md`/`VERSION`/`__main__.py`，按 `.orchd/.gitignore` 豁免表）。
- **引擎随之切模式**：由 `orchd/nogit.py` 快照后端切到 **git 工作树模式**。D-14 记录的「代价」——`request` 的 `actual_changes_conflict / E030 = not_applicable (not_a_git_repo)` 降级放行——**随之作废**（其前提「非 git 仓库」已不成立）；红线 #1/#2 由 `orchd git` 代理强制，唯一豁免 = 任务分支上的 `git commit`（`.orchd/rules/git.md:26`）。
- **被取代范围（仅 D-14 一条）**：「不为编排而 `git init`」及其代价段作废；D-14 的模块划分、任务清单、单写者文件事实、两条「事实更正」仍然有效。
- **本机档案口径（用户裁定「认下本机档案即可」）**：`00-REVIEW-2026-09-25.md` 确已丢失（本机全盘 `*REVIEW*2026-09-25*` 检索无果），**不追补**——本机档案按现状认下，证据链缺口以本 CHANGELOG 记录代替原件。
- **`00-REVIEW-2026-09-26.md` 移入 `reports/`（不入库）**：文件由仓根移至 `reports/00-REVIEW-2026-09-26.md`；`reports/` 已入 `.gitignore`（"本机审计档案"段），**不随技能发货**。文档侧同步登记为不入库项：`README.md` §目录结构 + §发布边界表、`.orchd/shared/conventions.md` §6。
- **6 个任务 `files_to_read` 的路径已修正（用户授权的一次性手改，破例）**：`task-verify-encoding-and-manifest-path`、`task-gen-cli-flags-and-p1-guard`、`task-profile-substantive-assertions`、`task-root-docs-drift-fix`、`task-verify-manifest-shape-guards`、`task-archive-refs-and-register` 的 `files_to_read` 中原 `00-REVIEW-2026-09-26.md` 已改为 `reports/00-REVIEW-2026-09-26.md`（实测 6 处；`priority: must_read` 与 `hint` 原样保留，未动其他字段）。
  - **为何要破例（引擎侧无合法通道）**：唯一合法通道 `amend --files-to-read` 是**整体覆写**，条目一律降为 `priority=reference` 且**丢弃 `hint`**（`orchd/cli/commands/control.py:582-587`；`must_read` 只走 `--register` 提案，而 `--register` 遇已存在 id 即 E007）。即：**路径微调会一次丢掉这 6 个任务全部条目的阅读提示**（含指向 `70-verify.py` 等大文件的行号提示），代价远大于收益；而直接手改 `_master.json` 本属红线（`.orchd/rules/git.md:64`、`.orchd/SKILL.md` MUST NOT 3/9）。经用户明确授权，只替换 6 个 `path` 字符串后落盘。
  - **改后双验（已实测）**：`validate` → `valid: true, errors: []`（余 3 条 E022 属纯文档任务，存量）；`init` 重生成 `mod-*/spec.json` 快照 → 快照内 `reports/00-REVIEW` 引用 4+2 = 6 处，账本/快照对齐。**顺序不可颠倒**：不刷新快照，后续 amend 会因快照落后把这批任务误判为「新增」并按新卡要求 `source`。
  - **留痕**：本 CHANGELOG + `orchd lesson`（`lesson-0001`，type=scene、scene=`amend-files-to-read-overwrite`、severity=warning）记录「`amend --files-to-read` 是破坏性整体覆写、不可用于路径微调」及本次破例的完整处置链（手改 → validate → init → 记录）。
  - **对未来的口径**：勿再移动被任务 `files_to_read` 声明的文件；确需移动时先查该文件是否被声明（`grep '"path": "<相对路径>"' .orchd/_master.json`）。
  - **附带事实（不阻断）**：引擎**不校验 `files_to_read` 的存在性**——`orchd/split.py:1066` 的存在性告警只覆盖 `files_to_edit` / `exempt_files`；claim 只把 `files_to_read` 当阅读指南透传（`orchd/onboard/claim.py:739`）。故即便路径未修正也不会硬阻断，但声明与磁盘事实会不一致。
- **附带修复（引擎快照漂移，已实测）**：`.orchd/mod-*/spec.json` 快照落后账本——账本 16 任务、快照仅 12（缺 `task-capability-registry-flip`、`task-verify-manifest-shape-guards`、`task-archive-refs-and-register`、`task-profile-social-science`），且 4 个存量任务的 `files_to_read` 快照版本早于账本（hint 无行号，如 `task-verify-encoding-and-manifest-path` 快照为「N-1 / N-5 的复现条件…」而账本为「L65 N-1（cp936…）」）。因快照是 amend 的 diff 基线，落后会使这批任务被误判为「新增」而触发「新增任务缺 `source`」阻断。已用 `init` 重生成（ledger 为空，`init` 前置守卫放行），实测快照 4/3/5/4 = **16 任务**，与账本对齐。
- **附带实测（未改）**：`.orchd/_master.json` 中 4 个后加任务无 `source` 字段——`validate` 因「无 source 直接通过（向后兼容存量）」不报错；快照对齐后它们成为存量任务，同样豁免。补 `source` 无 CLI 通道（`amend --task` 不支持 `--source`），暂不处理。

## D-16 根文档漂移修复与 D-13 遗留台账（2026-09-26，task-root-docs-drift-fix）

- **范围**：D-13 §遗留 的**文档面**（N-4 用法块、N-9 两处）与第 4 档留下的发布边界表述。四处改动，行号为改后磁盘态：
  1. `SKILL.md:101-107` §生成器：`--regress <目标项目>` → `--regress --project <目标项目>`，并补一段「缺 `--project` 归 rc=2 且先拒后写」的口径（产品侧在 `scripts/30-gen-proposals.py:490-493`，守卫在 `scripts/75-verify-selftest.py:291` `run_gen_cli_guards()`）。
  2. `SKILL.md:38` 行 + `:45-50` §入口模式：data-first 行的 P1→P0 倒序加「**载体编号** vs **执行序**」说明——N-9 复核结论是倒序有意（先扫数据判可行性再收敛故事线），故改说明不改序。
  3. `references/40-draft-to-latex.md:31`：`见 SKILL 待建清单第 3 项` → 指向 `SKILL.md` §能力注册表 的具体行（悬空序号引用消除）。
  4. `README.md:108-109` §目录结构 + `:143-157` §发布边界：不再声称已消失对象留仓；表头由「为什么留仓」改为「本机现状（实测）」并逐条给字节数。
- **实测台账**（本轮现场重做，非记忆）：`_pilot`、`build-paper2` 在 README/SKILL 命中 0；位置参数形态 `--(regress|check) <` 命中 0；`待建清单第` 在 README/SKILL/`40-draft-to-latex.md` 命中 0（本 CHANGELOG 作为历史引述保留 1 处）。`.gitignore` 10 条声明按磁盘分三类：存在 3（`build/` 28 文件 144,783 B、`reports/` 1 文件 19,585 B、`_tmp-state.txt`）、不存在 7（2 条已出仓的开发期目录 + 5 条编译/引擎噪声面）。
- **测量教训（本轮自犯并已回改）**：`du -sk build` 报 224 KB，字节级实算 141.4 KiB，**虚高 58%**——与既记「Windows 量文件五假信号」同源。凡发布边界一类的数字声明一律改用 `sum(p.stat().st_size)`，不用 `du`。
- **D-13 §遗留 ①–⑤ 处置台账**（逐项给磁盘证据）：① N-4 → 已修（`30-gen-proposals.py:490-493` 先拒后写 + docstring 同步 + 75 的 21 条守卫；文档面即本条 ①）；② N-1 → 已修（`70-verify.py:97-100` 显式 `reconfigure`，75 带「旧行为（无 reconfigure）必崩」反向对照）；③ N-5 → 已修（`70-verify.py:402` 起未命中消息同回原值 + 解析后绝对路径 + 基准，75 守卫「相对 --manifest 按 --root 命中」「未命中消息回显原值+解析后绝对路径+基准」）；④ N-10 → 已修（`build()` multi-paper 分支校验承载任务）；⑤ N-9 → 本条 ②③ 落地。
- **编号冲突登记（刻意不改号）**：仓内现有**两条 `## D-15`**（`:117`「09-26 报告全量复核」与 `:146`「本仓纳入 git」），系既有冲突、非本任务引入。不重编号的理由：git 历史 `468fe3c docs: 记录 D-15（本仓入 git）` 已按该号引用，改号会让提交信息与文档永久脱钩——换号的收益小于制造新脱节的代价。消解归 `task-archive-refs-and-register`（其 AC 已含「D-13 §遗留 缺编号」一条）。本条按 D-16 递增，后续勿复用 15。
- **不扩权项（有主，登记于此）**：① `README.md:139-140` 写死「31 个合成控制用例 + 11 个守卫」——实测前者**仍成立**（`用例 31，期望与实际一致 31`），后者已漂到 **74 条**（六个守卫段 2+5+4+21+10+32，本轮 CLI/P-1 段 +21）；且 §目录结构与「必跑」口径未并列 `78-assertions-selftest.py` → 归 `task-capability-registry-resync`（AC5/AC6，其 `depends_on` 含本任务，串行无红窗口）。② `SKILL.md:151` §能力注册表 的 `:158` 行（文献验真门控）仍 `planned`，而 `scripts/35-refs-gate.py`（82,557 B）已在磁盘 → 归 `task-capability-registry-flip` / `resync`。③ `.gitignore:9-10` 对已出仓试点目录的表述失效 → 归 `task-archive-refs-and-register`。本任务 `files_to_edit` 含 README，但改写死数字正是 resync 的 AC 内容，先改会吞掉它的守卫靶子，故不动。
