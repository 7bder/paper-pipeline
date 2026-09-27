# paper-pipeline

> 把"**手上已有一堆研究数据**"变成"**一篇可以直接投出去的英文 SCI 稿件**"的全套工作方法，
> 封装成任务编排引擎 [orchd] 的一个原生技能。

这是一个**开发工作空间**，与本机任何论文项目（paper1…paperN 等）
**无 git、无路径、无状态耦合**：论文项目里的 orchd 引擎不读本目录；本目录也不向论文项目写任何东西，
除非某个脚本被显式以路径参数指过去。生成物由你（或引擎命令）手动投喂进论文项目。

---

## 它解决什么问题

orchd 这类任务引擎只给你一套状态机（claim → done → review）和 git 纪律，但它**不知道写论文这件事**：
不知道论文该分几步、每步该产出什么、什么算"写完了"、文献怎么找才不浪费、数据口径怎么才不漂移。

而真实写一篇论文（从学位论文/项目数据改写成 SCI）会反复踩同一批坑：

| 坑 | 真实症状 |
|---|---|
| **库存病** | 文献库攒了 74 条，正文实际只引 49 条，26 条白攒——因为检索时没有"到底需要什么证据"的清单 |
| **临时凑引病** | 写到 Discussion 才发现某句没人支撑，临时搜一篇往上贴，结果 over-claim、引用落位失控 |
| **口径漂移** | n=1 的数据敢写 significantly，没测 EIS 敢给阻抗结论，纵轴截断夸大差异 |
| **返工地狱** | md 改一遍、tex 改一遍，两边分叉；投稿前才发现编号和文献表对不上 |

paper-pipeline 就是把这篇论文（paper1，材料涂层方向）一路踩坑沉淀下来的打法，反过来做成可复用的技能。
它只做三件引擎不做的事：**领域知识**（profiles/）、**可机检的验收判据**（scripts/）、**踩过的坑**（references/ + 决策记录）。

## 核心亮点

1. **顺序铁律：先需求单，后采购，再落位。**
   先用 claim 框架（P2）把"这篇文章每个论点需要什么证据"列成一张需求单，
   再按单子去定向检索（P3），最后写作时把引用钉进句子（P4）。
   禁止"先广搜一圈再找用途"——这是库存病和临时凑引病的根。

2. **四种入口，适配你的真实处境。**
   不是只有"有 idea 做实验"这一种正统路径——大多数人是数据已经有了、不知道讲什么故事。
   `data-first`（有数据找故事）、`idea-first`（有问题补实验）、`multi-paper`（多组数据拆多篇）、
   `inherited`（故事线已定直接干），P2 之后四条路汇合成同一条管线。

3. **profile 驱动，加一个领域 = 加一个 YAML。**
   所有学科差异（证据形态、禁止的论断、必检清单、图件要求、引用策略）都写在 profile 里，
   用 `extends` 继承基类。paper2 只是把 evidence_form 从"普通实验"换成"Origin 工程 + 有 EIS"，
   就自动多出"Origin 数据分离导出""补实验裁定"两个任务，并把"禁止阻抗结论"改成
   "阻抗结论必须有等效电路拟合依据"——**不改一行代码**。

4. **每个任务都有机器可判的验收。**
   不是"写完了就行"，而是每个 done 之前由 `70-verify.py` 跑断言：
   产物存在且非空、不含 TODO/AUTHOR CONFIRM 残留、字数在预算内、引用编号连续、
   JSON 必填字段齐全……判据即契约。

5. **md 单一真源，LaTeX 只是派生物。**
   正文只在 `30-manuscript/*.md` 里改，`.tex` 由脚本生成（头部标 `GENERATED — do not edit`）。
   这样"编号↔文献表一致""图表全覆盖""术语归一"这些检查才能全部脚本化——paper1 因此一次都没在编号上返工。

6. **严守边界：只生成，不替你做主。**
   它生成 proposals 给引擎校验，但**注册任务永远由你执行**；选题、拆几篇、选哪个刊、
   做不做补实验、投稿——这些策略判断全部是人工闸门，agent 不替你拍板。

## 一次完整使用长什么样

```
你："我手上有 KH-550 改性水性聚氨酯的防腐数据，想写一篇 SCI"
 │
 ├─ 1. agent 判断 entry.mode（你有几组数据？有没有 idea？）→ 通常 data-first
 │
 ├─ 2. 选/写 profile（profiles/10-wbpu-kh550.yaml），跑生成器：
 │      python scripts/30-gen-proposals.py --profile profiles/10-wbpu-kh550.yaml --out <论文项目>/
 │      python scripts/30-gen-proposals.py --profile ... --check --project <论文项目>   # orchd validate 必须通过
 │
 ├─ 3. 你在论文项目里执行注册： orchd intake / amend --register   ← 人工闸门，agent 不代劳
 │
 ├─ 4. orchd 引擎接管，逐任务 request → claim → done → review
 │      每个 done 前自动跑 70-verify.py 机检；agent 负责数据核对、文献验真、逐节写作、合稿
 │
 ├─ 5. 你在人工闸门处介入：选故事线 / 选刊 / 开 Origin .opju / 裁定补不做实验
 │
 └─ 6. P6：六层评审 → 定稿 → 按期刊模板生成 LaTeX → Tectonic 构建 PDF
        ↓
      可投稿 PDF
```

产物目录按阶段编号（`00-admin/` `10-data/` `20-lit/` `30-manuscript/` `40-figures/`
`50-review/` `60-latex/` `70-tools/` `90-notebooks/`），看文件名就知道在第几阶段。

## 目录结构

```
paper-pipeline/
├── SKILL.md                  技能入口（机器读：何时触发、阶段序、协同契约、硬约束）
├── README.md                 本文件（人读）
├── CHANGELOG.md              设计决策记录 D-1…D-12（为什么这么定，含引擎实测坑）
├── profiles/                 领域档（四轴：论文类型×证据形态×出版社×语言/报告规范）
│   ├── 00-base-empirical.yaml    通用基类：证据口径 + back-matter + P-1 资产规划
│   ├── 10-materials-chemistry.yaml   材料/化工/涂层（paper1 反推，24 任务）
│   └── 10-wbpu-kh550.yaml       paper2 试点（Origin 工程 + EIS，26 任务）
├── scripts/                  判据与生成脚本（全部离线、秒级）
│   ├── 30-gen-proposals.py    profile → proposals/master/rules/断言片段
│   ├── 70-verify.py           判据基座（manifest 驱动的结构化验收）
│   └── 75-verify-selftest.py  基座自测（合成用例 + 真实项目 parity）
├── assets/                   投喂模板（proposal 模板、verify manifest 模板）
├── references/                运行手册（按阶段号命名）
│   ├── 00-project-layout.md   目录/命名规范 + orchd 联合约束检查表
│   ├── 10-idea-to-skeleton.md   立项交互（idea → 骨架契约）
│   ├── 20-claim-framework.md    claim 需求单 + 证据门限 + 引用落位机检
│   ├── 30-literature-pipeline.md 定向文献流水线
│   └── 40-draft-to-latex.md      md 真源 → LaTeX 装配
├── build/                    本机开发期生成物沙盒（`.gitignore` 内，不入库；随时可重生成）
└── reports/                  本机审计档案（审查报告等，不入库，见 §发布边界）
```

## 与 orchd 的接法（唯一正确姿势）

1. 跑生成器：`python scripts/30-gen-proposals.py --profile profiles/<x>.yaml --out <输出目录>`
   （输出目录直接放目标论文项目内，或生成后拷入）
2. 在**目标论文项目**内：`python .orchd/__main__.py validate`（必须通过）
3. **由你**执行注册：`intake` / `amend --register`（本技能永不代注册）
4. 之后全程走引擎：`request → claim → done → review → merge`，判据脚本经 `verify_command` 调用
5. 踩坑用 `python .orchd/__main__.py lesson ...` 回灌，不另建自由文档

## 哪些事必须你亲自做（人工闸门）

| 时机 | 你做什么 | agent 做不了什么 |
|---|---|---|
| 判断入口模式 | 告诉它你有几组数据、有没有 idea | 不知道你的实验进展 |
| multi-paper 拆分 | 拍板发几篇、先后顺序、共享数据边界 | 发表策略是你的决定 |
| 注册 proposals | 你跑 `orchd intake` | agent 不替你注册 |
| idea-first 做实验 | 你去实验室 | agent 不能跑实验 |
| 专有二进制 | Origin `.opju`、仪器软件导出由你打开确认 | agent 读不了专有格式 |
| 选刊 | agent 给三档建议，你定投哪个 | 期刊匹配是策略判断 |
| 投稿 | 你提交、回复审稿意见 | agent 不替你投稿 |

其余（数据核对、文献检索验真、逐节写作、合稿、引用审计、LaTeX 排版、机检）都由 agent + orchd 自动推进。

## 开发与回归

- **回归基线**：paper1 的 21 个真实 proposal 与 verify manifest 是"标准答案"。
  任何生成器改动都必须能重生成等价集合且 `validate` 通过（`--regress` 对比）。
- **自测**（改基座或换 profile 后必跑，两条命令按原文逐条复制执行均应退出码 0；守卫条目随能力演进增删，不在此绑定具体数字）：
  - `python scripts/75-verify-selftest.py`——合成控制用例（每个断言类型一对"应过/应失败"）+ 生成器/碎片/编码/注册表守卫面
  - `python scripts/78-assertions-selftest.py`——profile 实质断言棘轮（下限 + 形状 + 正反控制 + 反向对照）
- **多领域验收（唯一可信证明）**：用一个**非材料领域**的最小真实项目跑通 `validate` + 1–2 个真任务闭环；不通过不发布。

## 发布边界

技能发货只需 `SKILL.md` + `profiles/` + `scripts/` + `assets/` + `references/`。
以下为开发期产物，打包时排除（已在 `.gitignore`）：

| 排除项 | 本机现状（实测） | 重建方式 |
|---|---|---|
| `build/` | 存在，28 文件 / 144,783 B（141.4 KiB），未被 git 跟踪 | 重跑 `30-gen-proposals.py --profile profiles/<x>.yaml --out build` |
| `reports/` | 存在，1 文件 / 19,585 B（09-26 审查报告），未被 git 跟踪 | 不重建：审计档案只在执行机留存，按需重跑审查 |

`.gitignore` 共 10 条声明，按磁盘实测分三类：上表 2 条在本机存在；`_tmp-state.txt`（会话临时态）
亦存在但未跟踪；其余 7 条在**仓库根目录**当前无此类目——其中 2 条是曾留仓、已随仓库卫生出仓的开发期目录
（沿革见 `CHANGELOG.md` D-13/D-14/D-16，本节不重复维护），另 5 条为编译与引擎噪声面
（`__pycache__/`、`*.py[cod]`、`.intake.lock`、`.layout.json`、`.lock`）。

`.pyc` 的口径要划清两处：**发货面**（`SKILL.md` + `profiles/` + `scripts/` + `assets/` + `references/`）实测
`*.pyc` = 0、`__pycache__/` = 0，机制是跨进程的 Python 调用带 `-B`、`importlib` 前置 `sys.dont_write_bytecode`
（两处例外不需要它：manifest 的 `run` 断言按外部命令执行，`-c` 内联探针不落文件）；而 `.orchd/` 里的引擎副本
另有 128 个 `.pyc`（引擎自身 import 产物，由 `.orchd/.gitignore` 整目录排除，不属发货面）。git 跟踪集内
`*.pyc`/`__pycache__` 命中 0，故"不再生成"只对发货面与入库集合成立，不要按字面理解成全盘洁净。

两条已实测的边界纪律：
1. `--check` 对目标论文项目**零写入**（跑前跑后比对全树 mtime+size 为 0 变化；以 `python -B` 起引擎避免落 `.pyc`）。
2. 不得在无 `.orchd` 的目录里以 cwd 调引擎——曾因此落下含本机绝对路径的锁文件。

## 当前状态与 Roadmap

**已完成**：生成器 + 判据基座 + 自测；paper1 回归 PASS（23 任务结构零差异）、paper2 试点 PASS；
四种入口模式落地；12 条设计决策沉淀（见 `CHANGELOG.md`）。

**待建能力**：统一登记在 [`SKILL.md`](SKILL.md) 的「能力注册表」中，带落地路径与状态（planned/available）；
可用性以磁盘文件是否存在为准，建好即把状态改为 available，不在此重复维护。

**待人工推进事项**：正式引导 paper2（当前仅沙盒验证，需你指定论文项目目录）。

## 设计决策

所有"为什么这么做"的来龙去脉（含 orchd 引擎实测出的 bug、迁移血的教训、全文获取路线取舍）
都记录在 [`CHANGELOG.md`](CHANGELOG.md) 的 D-1…D-12 条目里——有疑问先查那里，不要凭印象重走老路。
