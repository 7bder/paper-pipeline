# 草稿形态与排版装配：md 单一真源 → 生成式 LaTeX

回答"是不是 md 写文本、最后 LaTeX 拼装"——**是，但要加一条硬规则：单一真源，禁止两头改。**

## 分层职责

| 层 | 承担什么 | 不承担什么 |
|---|---|---|
| `manuscript/*.md`（真源；迁移后布局为 `30-manuscript/`，paper1 冻结旧名，见 layout §6） | 正文、图注、表格、编号制文献表指针、待确认项清单 | 版式、字体、双栏、页边 |
| `latex/**`（迁移后为 `60-latex/`） + 生成器（派生物） | 出版社模板套用、三线表、图注位置、参考文献样式、PDF 构建与回读校验 | 任何文字内容 |

**禁止**：在 `.tex` 里手工改句子。生成器在 `.tex` 头部写入 `% GENERATED — do not edit; change manuscript/*.md and re-run`。

## 为什么不是 docx

docx 的机检性差（难做"引用编号 ↔ 文献表一致""图表覆盖""术语归一""字数预算"这类断言），版本合并也不可审计。md + 生成式 tex 的全部检查都能脚本化，这是本项目一次都没在编号/图表上返工的原因。

## 装配链（本项目已验证）

1. `72-assemble-draft.py`（paper1 位于冻结目录 `scripts/`，新项目按规范放 `70-tools/`）：确定性合稿（标题 → 摘要 → 各节 → 图注 → 表 → 参考文献指针 → 待确认项），**同一输入字节一致**（已验幂等）；
2. 期间自动完成：作者确认项**上收为单一清单**（正文零残留）、术语归一（`wt %`→`wt%`、ASCII 下标统一）、预算判定写进产物（供断言）；
3. 一致性检查（编号↔文献表一一对应、Fig.1..N 与 Table 全被引用、字数区间）：paper1 靠 `verify_manifest` 断言 + `72-latex-build-check.py` 部分覆盖；独立脚本即待建的 `scripts/45-consistency-check.py`（**以 45 为唯一后续命名**，不再另造 consistency_check）；
4. `latex-build` 任务：按锁定期刊模板生成 `.tex` → Tectonic 构建 PDF → `72-latex-build-check.py` 回读校验（页数、图数、引用编号连续性）；
5. 图件由矢量图（PDF）+ 光栅图版（≥600 dpi）分别插入，图注文字来自真源。

## 跨出版社适配

出版社差异（模板、引用制、图注位置、Highlights / Graphical abstract 有无、字数与图数上限）**不进 SKILL.md、不进脚本**，而是：

`static/publisher/<name>.md`（规则碎片）+ `manifest.yaml` 一行映射 → 由 profile 的 `axes.publisher` 命中。
（`static/` 与 `manifest.yaml` 均为**待建**，见 SKILL 待建清单第 3 项；建成前跨出版社适配只能靠 profile 覆盖表达。）
**加一个出版社 = 加一个文件 + 一行 manifest**，不动生成器。

## 迁移时机

只在 `finalize`（内容定稿）之后进入 LaTeX 段。原因：若在排版层继续改文字，md 与 tex 立刻分叉，前面的全部机检失效。若排版阶段发现必改之处，**改 md → 重跑生成器**，不直接改 tex。
