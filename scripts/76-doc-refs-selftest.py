#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""76-doc-refs-selftest.py — 档案悬空引用与遗留台账的门禁自测（N-7 家族的守卫面）。

用法：
    python -X utf8 scripts/76-doc-refs-selftest.py            # 五条守卫（verify_command 形态）
    python -X utf8 scripts/76-doc-refs-selftest.py --selftest # 合成控制用例（红绿双向 + 反向对照）

五条守卫（G1/G3 对 AC1、AC2，G4 对 AC3，G2/G5 是同类悬空引用的横向补齐）：
  G1 死档案引用：发布面文档引用 `00-DECISIONS.md` / `00-REVIEW-2026-09-25.md` / 仓外 vendor 目录时，
     同一行必须带失效标记（"已消失 / 不在磁盘 / 重命名 / 悬空 / 丢失 …"），否则按悬空引用判 FAIL；
     `references/00-project-layout.md` 对 `00-DECISIONS.md` 是**硬零**（AC1 逐字要求）。
  G2 小节约束：文中以 `D-n` / `§小节` 形式指向 `CHANGELOG.md`、`references/*.md` 的锚点必须真在磁盘与标题里。
  G3 发布边界：发布面不得出现本机绝对路径与用户名；`.gitignore` 对已出仓目录必须给**可重建来源**（引擎血统串）。
  G4 台账完整：`CHANGELOG.md` D-13 §遗留 必须覆盖 N-1…N-10 全部十条，每条有级别·状态 + 落点（任务 id 或"不修"）。
  G5 编号唯一：`## D-n` 二级标题编号不得重复。

只读承诺：本脚本不写任何文件（`--selftest` 的控制用例全在内存）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent

# G1：指向已消失对象的引用名 + 同一行必须出现的失效标记
DEAD_REFS = ("00-DECISIONS.md", "00-REVIEW-2026-09-25.md", "_paper-pipeline-pilot-vendor")
DEAD_MARKS = ("已消失", "不在磁盘", "不在本盘", "重命名", "未在本工作空间留档", "未留档",
              "悬空", "丢失", "已删除", "已出仓", "出仓", "曾指向", "指向已", "改指", "改写",
              "原记", "已废止", "取代", "复发", "改为指", "不再引用", "未落盘", "指向过")
# AC1 逐字要求：该文件对 00-DECISIONS.md 命中数必须为 0（连"失效标记豁免"都不给）
HARD_ZERO = {"references/00-project-layout.md": ("00-DECISIONS.md",)}

# G3：本机绝对路径 / 家目录（不写死用户名——写死它本身就成了发布面泄漏）
MACHINE_PATH = re.compile(r"[A-Za-z]:[\\/]{1,2}[Uu]sers[\\/]"
                          r"|/home/[A-Za-z0-9_.-]+"
                          r"|[A-Za-z]:[\\/](?!tmp\b|TMP\b)[A-Za-z0-9_. -]+[\\/]")
# G3：引擎血统的可重建来源（三条同时缺任何一条即"只说没了、不说怎么重建"）
BLOOD = ("orchd-core", "v1.5.0", "32b4192")

SCOPE_REL = ("SKILL.md", "README.md", "CHANGELOG.md", ".gitignore",
             ".orchd/shared/conventions.md", ".orchd/shared/architecture.md")
N_IDS = tuple(range(1, 11))          # 09-26 审查报告的 N-1…N-10
TASK_ID = re.compile(r"`?(task-[a-z0-9-]+)`?")
H2_D = re.compile(r"^## (D-\d+)\b", re.M)
H3_D = re.compile(r"^### (D-\d+) 续\b", re.M)
REL_PATH = re.compile(r"(?<![\w/.-])((?:references|scripts|profiles)/[\w./*-]+\.md|"
                      r"(?:references|scripts|profiles)/[\w./*-]+\.(?:py|yaml|json))")
# 引了不在盘的路径，但语境已声明它属"另一套命名 / 尚未建 / 按需再生"——不算悬空引用：
# paper1 冻结命名两制（`scripts/verify.py`）、注册表 planned 行、模板占位符（`3x-7x.py`）。
ABSENT_OK_MARKS = ("冻结", "planned", "待建", "按需", "需要时", "重建", "假设", "尚未", "两制", "归 `task-")
PLACEHOLDER = re.compile(r"\dx\b|NN|\*|<|>|\{")


def read_text(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def scope_files(texts: dict) -> list:
    """发布面清单：固定件 + references/ 全量（以磁盘为准，不假设文件名）。"""
    out = [r for r in SCOPE_REL if r in texts]
    out += [k for k in sorted(texts) if k.startswith("references/") and k.endswith(".md")]
    return out


def split_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def n_table_lines(text: str) -> dict:
    """从 CHANGELOG 的 §遗留 表里抽 N-x 行（按首格匹配，不依赖列序）。"""
    rows = {}
    for line in text.split("\n"):
        if not line.strip().startswith("|"):
            continue
        cells = split_row(line)
        if not cells:
            continue
        head = cells[0].replace("**", "").strip()
        m = re.fullmatch(r"N-?(\d{1,2})", head)
        if m:
            rows[int(m.group(1))] = cells
    return rows


def section_tokens(raw: str) -> list:
    """`§1/§2/§3`、`§1.3`/`§1.5`、`§4 表`、`§反向控制` → ['1','2','3'] / ['1.3','1.5'] / ['4'] / ['反向控制']。"""
    out = []
    for piece in re.split(r"[/、]", raw):
        tok = piece.strip().strip("`").strip()
        tok = re.sub(r"^§+", "", tok).strip()
        m = re.match(r"^(\d+(?:\.\d+)*)", tok)
        out.append(m.group(1) if m else tok.strip(" .,，。"))
    return [t for t in out if t]


def heading_has(titles: set, token: str) -> bool:
    """数字锚点按**层级编号相等**判（`§1` 命中 `## 1. xxx`，不误命中 `### 1.1`）；文字锚点按包含。"""
    if re.match(r"^\d+(\.\d+)*$", token):
        for t in titles:
            m = re.match(r"^\s*(\d+(?:\.\d+)*)", t)
            if m and m.group(1) == token:
                return True
        return False
    return any(token in t for t in titles)


def check(texts: dict) -> list:
    """返回 [(guard, detail), ...]；空列表 = 五条守卫全绿。"""
    fails = []

    def fail(guard: str, detail: str):
        fails.append((guard, detail))

    # ---- G1 死档案引用 ----------------------------------------------------
    for rel in scope_files(texts):
        for i, line in enumerate(texts[rel].split("\n"), 1):
            for dead in DEAD_REFS:
                if dead not in line:
                    continue
                for hard_file, hard_names in HARD_ZERO.items():
                    if rel == hard_file and dead in hard_names:
                        fail("G1", "%s:%d 硬零引用「%s」（AC1：该文件命中数必须为 0）" % (rel, i, dead))
                        break
                else:
                    if not any(mk in line for mk in DEAD_MARKS):
                        fail("G1", "%s:%d 引用死档案「%s」同行无失效标记 → 读者会去开一个不存在的文件"
                             % (rel, i, dead))

    # ---- G2 小节约束：锚点必须真存在 --------------------------------------
    changelog = texts.get("CHANGELOG.md", "")
    d_heads = set(H2_D.findall(changelog)) | set(H3_D.findall(changelog))
    ref_titles = {}
    for rel in [k for k in texts if k.startswith("references/") and k.endswith(".md")]:
        ref_titles[rel] = {t.strip(" #").strip() for t in re.findall(r"^#{2,3} (.+)$", texts[rel], re.M)}
    for rel in scope_files(texts):
        own_titles = ref_titles.get(rel)
        for i, line in enumerate(texts[rel].split("\n"), 1):
            for dn in re.findall(r"\bD-(\d{1,3})\b", line):
                if ("D-%s" % dn) not in d_heads:
                    fail("G2", "%s:%d 引 CHANGELOG 小节 D-%s，但本文件无该编号标题（现有 %s）"
                         % (rel, i, dn, "、".join(sorted(d_heads)) or "无"))
            # 自引用（"本表 §5"、"本节 …"）同样要落得下——它是读者最先查的那一处
            if own_titles is not None:
                for m in re.finditer(r"(?:本表|本节|本文|本文件)\s*§\s*(\d+(?:\.\d+)*)", line):
                    if not heading_has(own_titles, m.group(1)):
                        fail("G2", "%s:%d 自引 §%s，本文件无该小节（现有：%s）"
                             % (rel, i, m.group(1), "、".join(sorted(t for t in own_titles if t)[:6]) or "无标题"))
            for m in re.finditer(r"`?(references/[\w.-]+\.md)[`]?\s*§\s*([^\s，。；)）]+)", line):
                target, raw = m.group(1), m.group(2)
                titles = ref_titles.get(target)
                for tok in section_tokens(raw):
                    if titles is None:
                        fail("G2", "%s:%d 引 %s §%s，但该文件不在盘" % (rel, i, target, tok))
                    elif not any(heading_has([t], tok) for t in titles):
                        fail("G2", "%s:%d 引 %s §%s，该文件无此小节（现有：%s）"
                             % (rel, i, target, tok,
                                "、".join(sorted(t for t in titles if t)[:6]) or "无标题"))

    # ---- G3 发布边界与血统来源 --------------------------------------------
    for rel in scope_files(texts):
        for i, line in enumerate(texts[rel].split("\n"), 1):
            m = MACHINE_PATH.search(line)
            if m:
                fail("G3", "%s:%d 本机绝对路径/家目录泄漏：%s" % (rel, i, m.group(0)[:60]))
    gi = texts.get(".gitignore", "")
    if "_paper-pipeline-pilot-vendor" in gi:
        fail("G3", ".gitignore 仍指向已删除的仓外 vendor 目录（AC2）")
    for name in BLOOD:
        if name not in gi:
            fail("G3", ".gitignore 缺引擎血统来源「%s」——只说副本没了、不说可从哪重建（AC2）" % name)

    # ---- G4 十条台账 + G5 编号唯一 ----------------------------------------
    rows = n_table_lines(changelog)
    body = changelog.split("### D-13 续")[0]
    head = re.search(r"\*\*遗留台账 = ([^*]+)\*\*", body)
    if head is None:
        fail("G4", "CHANGELOG 的 D-13 §遗留 台账无「N-1…N-10」声明头（模板被改名即 FAIL）")
    else:
        if re.search(r"仍缺|现缺|尚未覆盖|未覆盖", head.group(1)):
            fail("G4", "§遗留 台账声明头自称仍缺号（%s）——十条齐备是本任务的 AC3" % head.group(1)[:60])
        if not re.search(r"N-1[.…-]+N-10", head.group(1)):
            fail("G4", "§遗留 台账声明头没写覆盖范围 N-1…N-10（%s）" % head.group(1)[:60])
    for n in N_IDS:
        key = "N-%d" % n
        cells = rows.get(n)
        if cells is None:
            hit = [l for l in body.split("\n") if key in l and l.strip().startswith("|")]
            if not hit:
                fail("G4", "§遗留 台账缺 %s 行（AC3：十条必须无缺号）" % key)
                continue
            cells = split_row(hit[0])
        joined = " | ".join(cells)
        if "已修" not in joined and "不修" not in joined and "本任务" not in joined:
            fail("G4", "%s 行无状态（已修 / 不修+理由 / 本任务修）：读者无法判断是否还需动" % key)
        if not TASK_ID.search(joined) and "不修" not in joined:
            fail("G4", "%s 行既无落点任务 id 也未写「不修 + 理由」" % key)
        # 证据只看**末列**（实测证据）：整行拼起来判会让落点列里的文件名替证据列顶包
        evidence = cells[-1] if len(cells) >= 3 else ""
        if not re.search(r"[\w.-]+\.(py|md|yaml|json)", evidence):
            fail("G4", "%s 行「实测证据」列没有 file 级指向（AC3 + conventions §4：证据要到具体文件，"
                       "且不能靠其他列的文件名顶包）：%s" % (key, evidence[:60]))
        if len(cells) < 5:
            fail("G4", "%s 行列数 %d < 5（主题/级别·状态/落点/实测证据 缺一即无法机检）" % (key, len(cells)))
    pending = [l for l in changelog.split("\n") if "待用户裁决" in l and l.strip().startswith("-")]
    if not pending:
        fail("G4", "CHANGELOG 无「两处待用户裁决」条（裁决项必须可见且各带不修 + 理由）")
    else:
        items = re.split(r"[①②③④⑤]", pending[0])[1:]
        if len(items) < 2:
            fail("G4", "「待用户裁决」条未用 ①② 分列（分不开就判不了每项有没有理由）：%s" % pending[0][:60])
        for item in items:
            if "不修 + 理由" not in item:
                fail("G4", "待用户裁决的某项缺「不修 + 理由」（读者无法区分漏做与刻意）：%s" % item[:50])
    seen = {}
    for d in H2_D.findall(changelog):
        seen[d] = seen.get(d, 0) + 1
    dup = sorted([d for d, c in seen.items() if c > 1])
    if dup:
        fail("G5", "CHANGELOG 有重复的二级编号：%s（引用者无法确定指向哪一条）" % "、".join(dup))

    # ---- G2 补：引用路径必须在盘 ------------------------------------------
    for rel in scope_files(texts):
        for i, line in enumerate(texts[rel].split("\n"), 1):
            for m in REL_PATH.finditer(line):
                target = m.group(1)
                if PLACEHOLDER.search(target):
                    continue          # 模板占位符（`profiles/<x>.yaml`、`scripts/3x-7x.py`）不验存在性
                if not (ROOT / target).exists():
                    if any(k in line for k in ABSENT_OK_MARKS):
                        continue      # 语境已声明"另一套命名 / 尚未建 / 按需再生"，不是悬空引用
                    fail("G2", "%s:%d 引 %s，但该路径不在盘（同行亦无 planned/冻结/按需等声明词）"
                         % (rel, i, target))
    return fails


def load_snapshot() -> dict:
    texts = {}
    for rel in SCOPE_REL:
        texts[rel] = read_text(rel)
    for p in sorted((ROOT / "references").glob("*.md")):
        texts["references/" + p.name] = p.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    return texts


def run() -> int:
    texts = load_snapshot()
    missing = [r for r in ("CHANGELOG.md", ".gitignore", "SKILL.md") if not texts.get(r)]
    if missing:
        print('[76] FAIL  发布面文件读不到（%s）——守卫不接受"读不到"当通过' % "、".join(missing))
        return 1
    fails = check(texts)
    if fails:
        print("[76] FAIL  %d 条" % len(fails))
        for guard, detail in fails:
            print("  - %s  %s" % (guard, detail))
        return 1
    print("[76] PASS  G1 死档案引用 / G2 小节约束 / G3 发布边界 / G4 十条台账 / G5 编号唯一 全绿（发布面 %d 文件）"
          % len(scope_files(texts)))
    return 0


# --------------------------------------------------------------------------
# --selftest：全部在内存，不落盘。正控制 = 干净快照必须 0 失败；
# 反控制 = 逐条把判据的输入改坏，必须由**该当守卫**变红（否则判据是摆设）。
# --------------------------------------------------------------------------

def _base_snapshot() -> dict:
    """合成基线：结构照真实发布面（含十条表、血统串、锚点），与磁盘内容无关，
    这样即使 CHANGELOG 后续演进，自测面也不会漂移成假绿。"""
    rows = []
    for n in N_IDS:
        rows.append("| N-%d | 主题 %d | P2·已修 | `task-demo-%d` | `scripts/70-verify.py:%d` |" % (n, n, n, 40 + n))
    changelog = "\n".join([
        "# 决策记录",
        "## D-1 基类",
        "",
        "## D-13 审查驱动的修复分档",
        "",
        "- **遗留台账 = 09-26 审查 N-1…N-10 全十条**（守卫在 `scripts/76-doc-refs-selftest.py`）。",
        "",
        "| N | 主题 | 级别·状态 | 落点 | 实测证据 |",
        "|---|---|---|---|---|",
        "\n".join(rows),
        "",
        "- **两处待用户裁决（不修 + 理由）**：① 图件命名 不修 + 理由：跨盘迁移；② 空验收 不修 + 理由：通用门禁。",
        "",
        "## D-14 接入",
        "",
        "## D-15 本仓纳入 git 版本控制",
        "",
        "### D-13 续 · 09-26 报告全量复核",
        "",
    ])
    layout = ("# 项目文件组织\n\n> 原件未在本工作空间留档，结论落 `CHANGELOG.md` 的 D-13。\n"
              "> 编号规则见 `CHANGELOG.md` D-13 与 `references/20-claim-framework.md §3`。\n"
              "> 本表 §5 是迁移方案。\n\n## 5. paper1 迁移方案\n")
    gitignore = ("# 开发期产物\n__pycache__/\n\n# 生成物沙盒\nbuild/\nbuild-paper2/\n\n"
                 "# paper2 试点沙盒：当前不在盘，需要时重跑 `scripts/30-gen-proposals.py`。\n"
                 "# 引擎血统可从 orchd-core（git 仓库，tag v1.5.0 = 32b4192）重建。\n_pilot/\n"
                 "reports/\n")
    refs = {"references/00-project-layout.md": layout,
            "references/20-claim-framework.md": "## 1. 范围\n\n### 2. 术语\n\n## 3. 证据强度门限\n\n## 4. 引用落位\n"}
    return dict({
        "SKILL.md": "# 技能本体\n\n见 `scripts/70-verify.py` 与 `CHANGELOG.md` D-13。\n",
        "README.md": "# README\n\n发布边界见 `CHANGELOG.md` D-13；测试面 `scripts/75-verify-selftest.py`。\n",
        "CHANGELOG.md": changelog,
        ".gitignore": gitignore,
        ".orchd/shared/conventions.md": "# 规范\n\n见 `CHANGELOG.md` D-13。\n",
        ".orchd/shared/architecture.md": "# 架构\n\nD-14 曾按无 git 模式接入，已由 D-15 取代。\n",
    }, **refs)


def _lines_containing(text: str, needle: str) -> list:
    return [l for l in text.split("\n") if needle in l]


def selftest() -> int:
    base = _base_snapshot()
    bad = []
    counters = {"control": 0}

    def expect(label: str, mutate, guard: str):
        """反向对照：改坏输入后必须由指定守卫变红；不红 = 判据是摆设。"""
        counters["control"] += 1
        snap = {k: v for k, v in base.items()}
        mutate(snap)
        if snap == {k: v for k, v in base.items()}:
            bad.append("%s：变异没有改动任何输入（用例自身失效，不算验过）" % label)
            return
        fails = check(snap)
        hits = [d for g, d in fails if g == guard]
        if not fails:
            bad.append("%s：改坏后 rc 仍为绿（无任何 FAIL）→ 该判据是摆设" % label)
        elif not hits:
            bad.append("%s：变红的不是 %s 而是 %s → 判据没有咬住靶子"
                       % (label, guard, "、".join(sorted({g for g, _ in fails}))))

    # 正控制：干净基线必须 0 失败（否则守卫恒红，同样不可用）
    clean = check(base)
    if clean:
        for g, d in clean:
            bad.append("正控制失败（干净基线本应全绿）：%s %s" % (g, d))

    expect("G1-复发：硬零文件引回 00-DECISIONS.md", lambda s: s.update({
        "references/00-project-layout.md": s["references/00-project-layout.md"]
        + "> 结论已回灌 `00-DECISIONS.md`。\n"}), "G1")
    expect("G1-裸引：引用死档案而同行无失效标记", lambda s: s.update({
        "SKILL.md": s["SKILL.md"] + "详见 `00-REVIEW-2026-09-25.md`。\n"}), "G1")
    expect("G2-幽灵小节：引一个不存在的 D-99", lambda s: s.update({
        "README.md": s["README.md"] + "口径见 `CHANGELOG.md` D-99。\n"}), "G2")
    expect("G2-小节名漂移：§真源不存在", lambda s: s.update({
        "README.md": s["README.md"]
        + "门限见 `references/20-claim-framework.md §9.9`。\n"}), "G2")
    expect("G2-路径不在盘：引未建的 profiles 文件", lambda s: s.update({
        "README.md": s["README.md"] + "见 `profiles/70-ghost.yaml`。\n"}), "G2")
    expect("G3-本机路径泄漏", lambda s: s.update({
        "README.md": s["README.md"] + "复现目录 `C:/Users/someone/work/x.md`。\n"}), "G3")
    expect("G3-血统串缺失", lambda s: s.update({
        ".gitignore": s[".gitignore"].replace(
            "# 引擎血统可从 orchd-core（git 仓库，tag v1.5.0 = 32b4192）重建。\n",
            "# 引擎副本已出仓。\n")}), "G3")
    expect("G3-vendor 目录名复发", lambda s: s.update({
        ".gitignore": s[".gitignore"].replace("_pilot/", "_pilot/\n_paper-pipeline-pilot-vendor-20260926/\n")}), "G3")

    def drop_n7(s):
        s["CHANGELOG.md"] = "\n".join(l for l in s["CHANGELOG.md"].split("\n") if not l.startswith("| N-7 "))

    expect("G4-台账缺号（删 N-7 行）", drop_n7, "G4")

    def strip_taskid(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace(
            "| N-7 | 主题 7 | P2·已修 | `task-demo-7` |", "| N-7 | 主题 7 | P2·已修 | — |")

    expect("G4-落点为空（无任务 id、无「不修」）", strip_taskid, "G4")

    def strip_status(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace("| N-3 | 主题 3 | P2·已修 |", "| N-3 | 主题 3 |  |")

    expect("G4-状态列消失", strip_status, "G4")

    def strip_evidence(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace(
            "| N-4 | 主题 4 | P2·已修 | `task-demo-4` | `scripts/70-verify.py:44` |",
            "| N-4 | 主题 4 | P2·已修 | `task-demo-4` | 已处理 |")

    expect("G4-证据列无 file 级指向", strip_evidence, "G4")

    def evidence_piggyback(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace(
            "| N-5 | 主题 5 | P2·已修 | `task-demo-5` | `scripts/70-verify.py:45` |",
            "| N-5 | 主题 5 | P2·已修 | `scripts/70-verify.py` 的 `resolve_manifest()` | 已处理 |")

    expect("G4-顶包：落点列有文件名、证据列空话", evidence_piggyback, "G4")

    def pending_reason(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace(
            "② 空验收 不修 + 理由：通用门禁。", "② 空验收是否收紧。")

    expect("G4-待裁决某项丢掉「不修 + 理由」", pending_reason, "G4")

    def pending_no_marks(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace(
            "：① 图件命名 不修 + 理由：跨盘迁移；② 空验收 不修 + 理由：通用门禁。",
            "：图件命名与空验收两项待定。")

    expect("G4-待裁决不分 ①② 列项（每项判据会空转）", pending_no_marks, "G4")

    def self_section_drift(s):
        s["references/00-project-layout.md"] = s["references/00-project-layout.md"].replace(
            "本表 §5 是迁移方案", "本表 §99 是迁移方案")

    expect("G2-自引小节号漂走（本表 §99）", self_section_drift, "G2")

    def dup_d15(s):
        s["CHANGELOG.md"] = s["CHANGELOG.md"].replace("## D-14 接入", "## D-14 接入\n\n## D-15 重复编号条目\n")

    expect("G5-二级编号重复", dup_d15, "G5")

    if not counters["control"]:
        print("  FAIL  反向对照用例数为 0 → 自测面退化成空转")
        return 1
    for msg in bad:
        print("  FAIL  %s" % msg)
    if bad:
        print("SELFTEST FAIL（%d）" % len(bad))
        return 1
    print("SELFTEST PASS  正控制 1（干净基线全绿）+ 反向对照 %d（逐条改坏均由该当守卫变红）"
          % counters["control"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="档案悬空引用与遗留台账门禁")
    ap.add_argument("--selftest", action="store_true", help="合成控制用例（红绿双向）")
    a = ap.parse_args()
    return selftest() if a.selftest else run()


if __name__ == "__main__":
    sys.exit(main())
