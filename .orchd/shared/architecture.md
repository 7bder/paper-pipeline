# paper-pipeline（技能本体）架构

> 读者：在本工作空间执行 orchd 任务的 agent。本文件描述**技能本体**（研发态），不含任何具体论文项目。
> 消费方式：claim 时由引擎自动附加，勿手工列入 files_to_read。

## 1. 这个仓库是什么

把「已有原始研究数据 → 可投稿英文稿件」的流程封装为 **orchd 引擎原生技能**。三块落地物：

| 板块 | 路径 | 作用 |
|---|---|---|
| 领域知识 | `profiles/*.yaml`、`references/*.md` | 四轴（论文类型 × 证据形态 × 出版社/刊 × 语言与报告规范）+ 阶段方法论 |
| 可机检判据 | `scripts/70-verify.py` + 各 `scripts/3x-7x.py` | 只读验收：manifest 驱动的断言基座与守卫自测 |
| 踩坑约束 | `SKILL.md` 硬约束速查、`CHANGELOG.md` D-1…D-12 | 勿重走老路的判据与决策 |

**不做**：状态机实现（归引擎）、任务注册（归用户 `intake`/`amend --register`）、选题裁决（归用户）。

## 2. 数据流

```
profiles/<domain>.yaml ──┐
                         ├─(30-gen-proposals.py)→ proposals/task-*.json
静态碎片 static/*（规划中）┘                      + _master.fragment.json
                                                 + rules.fragment.md
                                                 + verify_manifest.fragment.json
                                                        │
                                              人工/引擎投喂进**论文项目**
                                                        ↓
                            论文项目内 70-tools/70-verify.py <task-id>  ← done 门禁
```

关键边界：本仓库与任何论文项目**无 git、无路径、无状态耦合**。生成物落 `build*/`（不入库），
`--check` 对目标项目**零写入**（引擎以 `python -B` 起、临时 master 落 `--out`）。

## 3. 脚本职责边界

- `scripts/30-gen-proposals.py`：profile → 投喂物。负责继承（`extends` + `deep_merge`）、依赖图（`depends:`）、
  断言展开（`verify_assertions_template` → 70-verify 原生形状）、AC 可判性检查（`CHECKABLE`/`CHECKABLE_EN`）、
  `--check`（合成 master 跑 orchd validate）、`--regress`（与真实项目任务结构比对）。
- `scripts/70-verify.py`：判据基座。**断言类型集合不得回退**（files/json_files/globs/absent_paths/run）。
  退出码：`0`=PASS、`1`=有未满足断言、`2`=用法或 manifest 问题（含坏 manifest）。
- `scripts/75-verify-selftest.py`：基座 + 生成器守卫（合成控制用例、退出码语义守卫、真实项目 parity）。
- 命名两制：新项目规范路径 `70-tools/70-verify.py`；paper1 冻结为 `scripts/verify.py`（历史 verify_command 不可改）。

## 4. 模块划分（任务池）

| 模块 | 边界 | 不做 |
|---|---|---|
| `mod-judgment` | 判据面：基座脚本正确性、profile 断言实质化、静态碎片命中 | 新增写作方法论内容 |
| `mod-capabilities` | `SKILL.md` 能力注册表 planned 行落地（脚本 + 运行手册） | 改根文档状态位（归 `mod-release-hygiene`） |
| `mod-domain-profiles` | 跨领域档（临床 / CS-ML），验证四轴抽象是否成立 | 改基类语义 |
| `mod-release-hygiene` | 根文档与磁盘事实一致、发布边界、评审记录常驻 | 改脚本行为 |

## 5. 引擎接入事实（2026-09-26）

- 引擎：orchd v1.5.0（vendor 于 `.orchd/`，安装器 `--agent --cleanup`）。
- 本工作空间**已纳入 git 版本控制**（远端 `7bder/paper-pipeline`，`main` 分支）；引擎走 **git 工作树模式**，
  claim/done 直接可用。红线 #1/#2（禁手动 git 写）在 git 模式下由 `orchd git` 代理强制（唯一豁免 =
  任务分支上的 `git commit`，见 `.orchd/rules/git.md`）。D-14 曾按「无 git 模式」接入，该决定已由 D-15 取代。
- `SKILL.md` 是**单写者文件**：同一时刻只允许一个 claimed 任务把它列入 `files_to_edit`，
  冲突由引擎在 `request` 期硬过滤，拆解期不为此额外造依赖边。
