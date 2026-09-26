#!/usr/bin/env python3
"""30-gen-proposals.py — 域档（profile）→ orchd 原生投喂物。

产出（默认写入 <out>/）：
  proposals/task-<id>.json        单任务提案（字段与 orchd `amend --register` 逐字对齐）
  _master.fragment.json           {project, modules, tasks} 片段，可并入 _master.json
  rules.fragment.md               域口径规则片段（evidence_policy → 可读规则）+ profile
                                  `fragments:` 声明的 static/ 碎片原样注入（未声明则零改动）
  verify_manifest.fragment.json   本域建议的 verify 断言（按任务分组）

用法（三条旗标形态与 argparse 一致，改 CLI 必同步此处，守卫见 75-verify-selftest.py）：
  python -X utf8 30-gen-proposals.py --profile profiles/10-materials-chemistry.yaml --out ./build
  python -X utf8 30-gen-proposals.py --profile ... --check --project <目标项目>    # 生成 master 并跑 orchd validate
  python -X utf8 30-gen-proposals.py --profile ... --regress --project <目标项目>  # 与该项目真实任务结构对比

`--check` 与 `--regress` 都必须同时给 `--project`：二者是"对某个真实项目核对"的动作，缺项目时无从核对。
曾的做法是 `if a.project:` 把整段跳过 → 缺 `--project` 时 rc=0 静默走 emit 写出 `--out`（默认 `./build/`），
门禁现场看起来像"跑过了"（2026-09-26 审查 N-4 实测 M6）。现在缺 `--project` 归 rc=2 且先拒后写，不落生成物。

设计约束（全部来自引擎实测，违反即被拒）：
  1. `source` 必须匹配 ^(idea|roadmap|debug):[a-z0-9-]+$ —— 本脚本用 `debug:<profile>-v<version>`；
     技能名不能直接出现在 source 里（E003）。
  2. 注册期禁目录式/通配符声明：read/edit 必须是具体文件路径，不得以 "/" 结尾。
  3. 单任务 files_to_edit ≤5（超出触发 E029 告警）；确需超出者在 profile 里显式登记 exceptions。
  4. AC 仅 pending 可改，故生成即须可判定：每条 AC 必须提到具体产物路径或可机检口径。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

SCHEMA_SOURCE = re.compile(r"^(idea|roadmap|debug):[a-z0-9-]+$")
AC_ARTIFACT = re.compile(r"(`[^`]+\.(md|json|py|csv|toml|yaml|tex|bib|pdf)`|\d\d-[a-z]+/|"
                         r"70-tools/|\d\d-[a-z]+\.(py|json|md))")
CHECKABLE = re.compile(r"(不得|须|必须|一致|逐条|覆盖|字段|标注|零占位符|可回指|可判定|写明|"
                       r"区间|上限|下限|无重复|一一对应|显式|禁止|至少|不得超出)")
# B6：本 skill 的稿件是英文稿，AC 允许英文表述；CHECKABLE 只含中文词会把
# language: en 轴的合法 AC（must/only/at least…）一律误拒。词表只收**硬约束词**，
# 不收形近虚词（with/within 类由 at most/between 等限定短语覆盖），避免模糊句被误放行；
# 用 \b 定界防止 "must" 命中 "adjust" 之类子串。
CHECKABLE_EN = re.compile(
    r"\b(must|shall|required|only|at least|at most|no more than|no fewer than|"
    r"no less than|no greater than|no later than|no earlier than|between|"
    r"exactly|consisten\w*|identical|match(?:es|ed)?|cover(?:s|ed|age)?|"
    r"explicitly?|forbid(?:den)?|prohibit(?:ed)?|absent|"
    r"unique|continuous|unambiguous|verifiable|reproducib\w+|traceab\w+)\b", re.I)


def die(msg: str) -> None:
    print("ERROR: %s" % msg)
    sys.exit(2)


def deep_merge(base: dict, child: dict) -> dict:
    """child 覆盖 base；tasks 按 id 合并（同 id 覆盖、新增追加）；depends 逐键合并。

    tasks 深度合并规则：子档同名任务的 `inject` 列表**追加合并**（去重），
    其余字段子档整体覆盖。这样子档（如 paper2）可以只写
    `- id: task-write-results-discussion\n  inject: [impedance_rule]`
    来给继承任务追加学科特有口径，而不必重写整个任务。
    """
    out = dict(base)
    for k, v in child.items():
        if k == "tasks":
            by_id = {t["id"]: t for t in out.get("tasks", [])}
            order = [t["id"] for t in out.get("tasks", [])]
            for t in v:
                if t["id"] in by_id:
                    parent_t = dict(by_id[t["id"]])
                    if "inject" in t and "inject" in parent_t:
                        merged_inject = list(parent_t["inject"])
                        for x in t["inject"]:
                            if x not in merged_inject:
                                merged_inject.append(x)
                        parent_t["inject"] = merged_inject
                    for k2, v2 in t.items():
                        if k2 != "inject":
                            parent_t[k2] = v2
                    by_id[t["id"]] = parent_t
                else:
                    by_id[t["id"]] = t
                    order.append(t["id"])
            out["tasks"] = [by_id[i] for i in order]
        elif k == "depends" and isinstance(v, dict):
            out["depends"] = {**out.get("depends", {}), **v}
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load_profile(path: Path, _depth: int = 0) -> dict:
    if _depth > 3:
        die("profile extends chain too deep (or cyclic): %s" % path)
    if not path.exists():
        die("profile not found: %s" % path)
    try:
        p = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        die("profile %s: invalid YAML: %s" % (path, exc))
    if not isinstance(p, dict):
        die("profile %s: top-level must be a mapping" % path)
    parent = p.pop("extends", None)
    if parent:
        p = deep_merge(load_profile(path.parent / parent, _depth + 1), p)
    for key in ("id", "modules", "tasks"):
        if key not in p:
            die("profile missing key: %s" % key)
    p.setdefault("version", "1")
    p.setdefault("tool_dir", "scripts")
    p.setdefault("paths", {})
    p.setdefault("evidence_policy", {})
    p.setdefault("verify_assertions_template", [])
    return p


def fill(value, ctx: dict):
    """占位符替换：{admin} {data} {lit} {ms} {fig} {review} {latex} {nb} {tool_dir} {profile}"""
    if isinstance(value, str):
        return value.format(**ctx)
    if isinstance(value, list):
        return [fill(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, ctx) for k, v in value.items()}
    return value


def policy_lines(profile: dict, inject: list) -> list:
    """把 evidence_policy 的域口径渲染成 AC 行（只取任务声明的 inject 键）。"""
    pol, out = profile["evidence_policy"], []
    for key in inject or []:
        val = pol.get(key)
        if val is None:
            die("task injects unknown evidence_policy key: %s" % key)
        if isinstance(val, list):
            out.append("域口径约束：%s。" % "；".join(str(v) for v in val))
        else:
            out.append("域口径约束：%s。" % val)
    return out


def build(profile: dict, project_override: dict | None = None) -> dict:
    ctx = dict(profile["paths"])
    ctx["tool_dir"] = profile["tool_dir"]
    # verify 脚本名分两制：新项目 70-tools/70-verify.py（编号规范）；paper1 冻结为 scripts/verify.py
    # （22 条历史 verify_command 不可改），由 profile 的 verify_tool 指定。
    ctx["verify_tool"] = profile.get("verify_tool") or ("%s/70-verify.py" % profile["tool_dir"])
    # manifest 名同样分两制：新项目 70-tools/71-verify-manifest.json；paper1 冻结 verify_manifest.json
    ctx["verify_manifest"] = profile.get("verify_manifest") or (
        "%s/71-verify-manifest.json" % profile["tool_dir"])
    ctx["profile"] = profile["id"]
    src = "debug:%s-v%s" % (profile["id"].replace("_", "-"), str(profile["version"]))
    if not SCHEMA_SOURCE.match(src):
        # 设计约束 #1 的机械化：违约的 profile id/version 会经 E003 在注册期才炸，这里前置拒绝。
        die("generated source '%s' violates orchd schema %s" % (src, SCHEMA_SOURCE.pattern))

    deps = profile.get("depends", {})
    tasks, problems = [], []
    seen = set()
    for spec in profile["tasks"]:
        try:
            t = fill(spec, ctx)
        except (KeyError, IndexError, ValueError) as exc:
            # B5：AC/brief 里的字面花括号（JSON/LaTeX 示例）会破坏占位符替换。
            # 报为生成期问题并继续检查其余任务，避免裸 traceback 且不指明任务。
            problems.append("%s: text breaks placeholder fill: %s "
                            "(字面 { } 请双写为 {{ }}，或避免在 AC/brief 中放 JSON/LaTeX 示例)"
                            % (spec.get("id", "?"), exc))
            continue
        tid = t["id"]
        # 依赖图集中在 profile 的 depends: 块（便于逐条审阅），任务条目里可覆盖。
        if "depends_on" not in t:
            t["depends_on"] = deps.get(tid, [])
        if tid in seen:
            problems.append("duplicate task id: %s" % tid)
        seen.add(tid)
        if not re.match(r"^task-[a-z0-9-]+$", tid):
            problems.append("bad task id: %s" % tid)

        ac = list(t.get("ac", [])) + policy_lines(profile, t.get("inject", []))
        if len(ac) < 3:
            problems.append("%s: fewer than 3 acceptance criteria" % tid)
        if len(ac) > 6 and not t.get("ac_exception"):
            problems.append("%s: %d acceptance criteria (>6, needs ac_exception)" % (tid, len(ac)))
        # AC 可判定性口径（对齐 paper1 真实 AC 的形态）：
        #   ① 至少一条 AC 锚定具体产物路径；② 至少一条 AC 给出可判定约束（不得/须/一致/逐条/覆盖…）。
        # 不要求每条 AC 都带路径——真实的 AC 里大量是行为与口径约束。
        if not any(AC_ARTIFACT.search(a) for a in ac):
            problems.append("%s: no AC anchors a concrete artifact path" % tid)
        if not any(CHECKABLE.search(a) or CHECKABLE_EN.search(a) for a in ac):
            problems.append("%s: no AC states a checkable constraint" % tid)

        edit = list(t.get("edit", []))
        if not edit:
            problems.append("%s: empty files_to_edit" % tid)
        if len(edit) > 5 and not t.get("fte_exception"):
            problems.append("%s: %d files_to_edit (>5, needs fte_exception)" % (tid, len(edit)))
        # files_to_edit 必须是具体文件（引擎注册期禁目录式/通配符）；
        # files_to_read 允许目录与通配符（paper1 实际即用 `data/`、`../data/*.csv`）。
        for p in edit:
            if p.endswith("/") or "*" in p:
                problems.append("%s: directory/wildcard declaration not allowed in files_to_edit: %s"
                                % (tid, p))
        try:
            verify_cmd = t["verify"].format(**ctx)
        except (KeyError, IndexError, ValueError) as exc:
            problems.append("%s: format error in verify: %s" % (tid, exc))
            continue
        if not re.match(r"^python \S+ task-%s$" % re.escape(tid[5:]), verify_cmd):
            problems.append("%s: verify_command must be 'python <script> %s'" % (tid, tid))

        tasks.append({
            "id": tid,
            "name": t["name"],
            "brief": t["brief"],
            "module": t["module"],
            "depends_on": sorted(set(t.get("depends_on", []))),
            "estimated_hours": t.get("hours", 2),
            "difficulty": t.get("difficulty", "medium"),
            "requires": t.get("requires", ["python"]),
            "acceptance_criteria": ac,
            "files_to_read": [{"path": r["path"], "priority": r.get("priority", "must_read"),
                               "hint": r.get("hint", "")} for r in t.get("read", [])],
            "files_to_edit": edit,
            "exempt_files": [],
            "verify_command": verify_cmd,
            "source": src,
            "stage": t.get("stage", ""),
        })

    entry_mode = profile.get("entry", {}).get("mode", "data-first")
    # multi-paper 模式才激活 P-1 资产规划任务；其余模式它不进任务图。
    # inherited 模式不额外过滤任务——它的差异在于 audit-data 的 AC 来源
    # （外部路线图已给定故事线），由领域 profile 在任务 AC 里体现，不在这里删任务。
    if entry_mode != "multi-paper":
        tasks = [t for t in tasks if t["id"] != "task-data-asset-mapping"]
    else:
        # N-10：P-1 注入只挂在 task-audit-data 上。该任务被领域档删掉时，注入循环静默零命中，
        # P-1 仍进任务图却无人依赖（生成期 problems 也抓不到——它不依赖任何未知任务），
        # 注册出去就是一个孤儿前置任务。故在注入点显式校验这条假设。
        if not any(t["id"] == "task-audit-data" for t in tasks):
            problems.append("entry.mode=multi-paper 需要 task-audit-data 承载 P-1 注入："
                            "该任务不在任务图里，task-data-asset-mapping 将成为无人依赖的孤儿前置")
        for t in tasks:
            if t["id"] == "task-audit-data" and "task-data-asset-mapping" not in t["depends_on"]:
                t["depends_on"].append("task-data-asset-mapping")
                t["depends_on"] = sorted(set(t["depends_on"]))

    # inherited 模式：P-1 路线图已定故事线，任务按路线图方向执行，不重复探索。
    if entry_mode == "inherited":
        direction = {
            "task-audit-data": "按 `{admin}/07-paper-roadmap.md` 指定的数据子集逐值核对，不盘点全量数据。",
            "task-analyze-data": "按 `{admin}/07-paper-roadmap.md` 指定的故事线定量分析，不探索其他方向。",
            "task-claim-map": "按 `{admin}/07-paper-roadmap.md` 指定的 claim 建需求单，不空泛收敛研究问题。",
        }
        for t in tasks:
            hint = direction.get(t["id"])
            if hint:
                t["acceptance_criteria"].append(hint.format(**ctx))

    ids = {t["id"] for t in tasks}
    for t in tasks:
        for d in t["depends_on"]:
            if d not in ids:
                problems.append("%s: depends_on unknown task %s" % (t["id"], d))

    project = dict(profile.get("project", {}))
    if project_override:
        project.update(project_override)
    master = {
        "schema_version": 1,          # 必须是整数（schema: "1.0" 被拒）
        "project": project,
        "modules": [{"id": m["id"], "name": m["name"], "role": m["role"]}
                    for m in profile["modules"]],
        "tasks": [{k: v for k, v in t.items() if k != "stage"} for t in tasks],
    }
    return {"tasks": tasks, "master": master, "problems": problems, "source": src}


def _render_scalar(v) -> str:
    """把 policy 值渲染成可读文本（dict/list 递归展平，避免 Python repr）。"""
    if isinstance(v, dict):
        return "；".join("%s=%s" % (k, _render_scalar(x)) for k, x in v.items())
    if isinstance(v, list):
        return "；".join(_render_scalar(x) for x in v)
    return str(v)


# ---------- 规则碎片：static/manifest.yaml + static/<轴值>-<主题>.md ----------
# 规格真源 references/60-capability-specs.md §3：声明才注入、未声明零回归（连 manifest 都不读）、
# 未知 id 即 die、注入正文原样不折叠。axes 只做一致性提示，自动匹配不是本能力的激活路径。

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
FRAGMENT_AXES_KEYS = {"paper_type", "evidence_form", "publisher",
                      "citation_style", "language", "reporting"}


def _disp(path: Path) -> str:
    """诊断里的路径只取末两段（`static/manifest.yaml`）：STATIC_DIR 由 __file__ 推出，
    整条回显会把本机绝对路径写进出生输出（40 号脚本同口径，CHANGELOG D-14 同族）。"""
    return "/".join(path.parts[-2:])


def load_fragment_manifest(static_dir: Path) -> dict:
    """读并校验碎片索引，返回 {id: {"path": 碎片文件, "axes": dict}}。

    只在 profile 声明了 `fragments:` 时被调用：未声明的项目不得因这份文件坏掉而新增失败面。
    """
    index = static_dir / "manifest.yaml"
    if not index.exists():
        die("profile 声明了 fragments 但碎片索引不存在: %s" % _disp(index))
    try:
        data = yaml.safe_load(index.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        die("碎片索引 %s 不是合法 YAML: %s" % (_disp(index), exc))
    if not isinstance(data, dict) or not isinstance(data.get("fragments"), list):
        die("碎片索引 %s 须是含顶层列表键 `fragments:` 的映射" % _disp(index))
    if str(data.get("version")) != "1":
        die("碎片索引 %s 的 version 须为 1（实际 %r）" % (_disp(index), data.get("version")))
    out: dict[str, dict] = {}
    for pos, entry in enumerate(data["fragments"], 1):
        if not isinstance(entry, dict):
            die("碎片索引 %s 第 %d 条不是映射（实际类型 %s）"
                % (_disp(index), pos, type(entry).__name__))
        fid, frag = entry.get("id"), entry.get("fragment")
        if not fid or not frag:
            # 不回显条目本体：里面可能有绝对路径，回显等于把本机路径写进出生输出。
            die("碎片索引 %s 第 %d 条须同时有非空 id 与 fragment（该条目键：%s）"
                % (_disp(index), pos,
                   sorted(map(str, entry)) if isinstance(entry, dict) else "?"))
        # 类型先于一切：非字符串会在 `static_dir / frag` 抛 TypeError，非字符串 id 会让
        # 下面"未知 id"消息里的 sorted(index) 崩在报错当场（2026-09-27 code 审查 D1/D2）。
        if not isinstance(fid, str) or not fid.strip():
            die("碎片 id 须是非空字符串（实际类型 %s）" % type(fid).__name__)
        if not isinstance(frag, str):
            die("碎片 %s 的 fragment 须是文件名字符串（实际类型 %s）"
                % (fid, type(frag).__name__))
        if fid in out:
            die("碎片 id 重复: %s" % fid)
        axes = entry.get("axes")
        if not isinstance(axes, dict) or len(axes) < 2:
            die("碎片 %s 的 axes 须是 ≥2 个键的映射（实际类型 %s）"
                % (fid, type(axes).__name__))
        unknown = sorted(set(axes) - FRAGMENT_AXES_KEYS)
        if unknown:
            die("碎片 %s 的 axes 含未知键 %s（允许：%s）"
                % (fid, unknown, sorted(FRAGMENT_AXES_KEYS)))
        # §3.1 的"static/ 下平铺 .md"是加载器强制，不只是文档描述：漏了这层，索引里一个
        # 笔误的 `../` 或绝对路径就会把**别的文件**当规则静默注入（D3）。
        if (not frag.endswith(".md") or frag != Path(frag).name
                or any(sep in frag for sep in ("/", "\\", ":")) or frag.startswith(".")):
            die("碎片 %s 的 fragment 须是 %s 下的裸文件名 .md（不得含路径分隔符、盘符或以 . 开头；"
                "实际文件名为 %s）" % (fid, _disp(static_dir), Path(frag).name or "空"))
        path = static_dir / frag
        if not path.resolve().is_relative_to(static_dir.resolve()):
            die("碎片 %s 的正文解析后越出 %s" % (fid, _disp(static_dir)))
        if not path.exists():
            die("碎片 %s 声明的文件不存在: %s" % (fid, _disp(path)))
        out[fid] = {"path": path, "axes": axes}
    return out


def _axes_mismatch(axes: dict, profile_axes: dict) -> list:
    """碎片 axes 与 profile axes 的不同键（标量按相等、列表按成员关系；profile 未用的轴不参与）。"""
    out = []
    for key, want in axes.items():
        if key not in profile_axes:
            continue                      # 领域档想用该轴才在 `axes:` 补声明，不补即不比较
        have = profile_axes[key]
        have_list = have if isinstance(have, list) else [have]
        if not have_list:
            continue                      # 空列表 = 该轴不适用（如 reporting: []）
        want_list = want if isinstance(want, list) else [want]
        if not ({str(x) for x in want_list} & {str(x) for x in have_list}):
            out.append("%s: profile=%r 碎片=%r" % (key, have, want))
    return out


def fragment_blocks(profile: dict, static_dir: Path) -> str:
    """按 profile 声明顺序把碎片正文拼成注入块；未声明返回空串（且完全不读 manifest）。

    "原样"指语义原样（不折叠空行、不改缩进，换行按 LF 归一）；marker 由本函数独占，
    碎片正文再出现该 marker 即拒，否则下游按 marker 计数的一致性判据不可靠。
    """
    declared = profile.get("fragments") or []
    if not declared:
        return ""
    if not isinstance(declared, list):
        die("profile 的 fragments 须是碎片 id 列表（实际类型 %s）" % type(declared).__name__)
    for fid in declared:
        if not isinstance(fid, str) or not fid.strip():
            die("profile 的 fragments 须全是碎片 id 字符串（有元素是 %s）"
                % type(fid).__name__)
    dup_decl = sorted({f for f in declared if declared.count(f) > 1})
    if dup_decl:
        # 与索引侧「碎片 id 重复」对称：重复声明会把同一片注入两次，marker 计数判据随之失真。
        die("profile 的 fragments 重复声明：%s" % dup_decl)
    index = load_fragment_manifest(static_dir)
    profile_axes = profile.get("axes") or {}
    blocks = []
    for fid in declared:
        if fid not in index:
            die("profile fragments 声明了未知碎片 id: %s（%s 已知：%s）"
                % (fid, _disp(static_dir / "manifest.yaml"), ", ".join(sorted(index)) or "无条目"))
        entry = index[fid]
        mismatch = _axes_mismatch(entry["axes"], profile_axes)
        if mismatch:
            print("   warn  碎片 %s 的 axes 与 profile 不符：%s（仅提示，不改退出码）"
                  % (fid, "；".join(mismatch)))
        try:
            body = entry["path"].read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            # 读不动要明说（conventions §2 读侧口径）：以崩代拒 = rc=1 加 traceback，
            # 硬读下去 = 乱码进规则片段，两条都比不过一次 rc=2 的定位报告。
            die("碎片 %s 的正文 %s 不是合法 UTF-8（%s）"
                % (fid, _disp(entry["path"]), exc.reason or "编码不符"))
        if "<!-- fragment:" in body:
            # 拼接层用该 marker 标块；碎片正文里再出现一次，下游按 marker 计数的一致性判据就不可靠了。
            die("碎片 %s 的正文含注入标记 <!-- fragment: … -->，须改写该正文（marker 由拼接层独占）" % fid)
        blocks.append("<!-- fragment: %s -->\n%s\n" % (fid, body.rstrip("\n")))
    return "\n".join(blocks)


def rules_fragment(profile: dict, static_dir: Path | None = None) -> str:
    pol = profile["evidence_policy"]
    lines = ["# 域口径规则片段（由 profiles/%s 生成，请并入项目 `rules/`）" % profile["id"], ""]
    for k, v in pol.items():
        lines.append("- **%s**：%s" % (k, _render_scalar(v)))
    for key in ("figure_policy", "citation_policy"):
        if key in profile:
            lines += ["", "## %s" % key]
            for k, v in profile[key].items():
                lines.append("- **%s**：%s" % (k, _render_scalar(v)))
    text = "\n".join(lines) + "\n"
    blocks = fragment_blocks(profile, STATIC_DIR if static_dir is None else static_dir)
    return text if not blocks else text + "\n" + blocks


TEXT_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml", ".py", ".bib", ".tex", ".csv",
                 ".ps1", ".sh", ".js", ".html", ".css", ".toml", ".cfg", ".ini"}
_VERIFY_KEYS = ("files", "json_files", "globs", "absent_paths")


def verify_fragment(profile: dict, tasks: list) -> dict:
    """把域档断言模板展开为 70-verify.py 原生形状的 manifest 片段。

    形状必须与 `70-verify.py --schema` 一致（files[].path/forbid、json_files[]…），
    否则任务 done 时基座查不到断言而空转 PASS。

    - 指定 task 的条目：files/json_files/globs/absent_paths/run 原样透传到该任务；
    - task:"*"：同样透传到每个任务；
    - task:"*" + apply_to: edit_files_text：把 forbid[]/min_bytes 挂到本任务 files_to_edit
      里每个文本后缀文件上（.pdf/.png 等二进制跳过）；
    - task:"*" + apply_to: edit_files_binary：把 min_bytes_each 挂到每个**非文本**产物
      （以 files 条目 + min_bytes 表达存在性与体积下限——二进制只验"是真产物、非占位"）。
    展开后任何任务仍为空断言 = 门禁空转，直接 die（2026-09-26 审查：redraw/draw-schematics
    曾因只覆盖文本文件而生成 `{}`，done 时无任何检查）。
    """
    out: dict[str, dict] = {t["id"]: {} for t in tasks}
    for a in profile.get("verify_assertions_template", []):
        target = a.get("task", "*")
        if target == "*":
            targets = [t["id"] for t in tasks]
        else:
            if target not in out:
                die("verify_assertions_template targets unknown task: %s" % target)
            targets = [target]
        for tid in targets:
            entry = out[tid]
            for key in _VERIFY_KEYS:
                if key in a:
                    entry.setdefault(key, []).extend(a[key])
            if "run" in a:
                entry["run"] = a["run"]
        if target == "*" and a.get("apply_to") == "edit_files_text":
            forbid = a.get("forbid", [])
            min_bytes = a.get("min_bytes")
            for t in tasks:
                for path in t.get("files_to_edit", []):
                    if Path(path).suffix.lower() in TEXT_SUFFIXES:
                        item = {"path": path, "forbid": list(forbid)}
                        if min_bytes is not None:
                            item["min_bytes"] = min_bytes
                        out[t["id"]].setdefault("files", []).append(item)
        if target == "*" and a.get("apply_to") == "edit_files_binary":
            min_bytes = a.get("min_bytes_each")
            if min_bytes is None:
                die("apply_to: edit_files_binary template needs min_bytes_each (binary "
                    "artifacts can only be checked for existence + size floor)")
            for t in tasks:
                for path in t.get("files_to_edit", []):
                    if Path(path).suffix.lower() not in TEXT_SUFFIXES:
                        out[t["id"]].setdefault("files", []).append(
                            {"path": path, "min_bytes": min_bytes})
    for tid, entry in out.items():
        if not any(entry.get(k) for k in _VERIFY_KEYS) and not entry.get("run"):
            die("%s: verify assertions expand to EMPTY — gate would idle-PASS at done; "
                "add a task-specific assertion or cover its artifacts via apply_to templates" % tid)
    return out


def emit(built: dict, profile: dict, out: Path) -> None:
    # 先算全部载荷、后写盘：rules_fragment/verify_fragment 都有 die 路径（碎片未知 id、
    # 断言展开为空），曾的顺序是 proposals 与 master 先落盘再 die，现场留下半份生成物 +
    # 上一次的 rules.fragment.md，看起来像"跑过了"（与 N-4 的先拒后写同口径）。
    rules_text = rules_fragment(profile)
    verify_text = json.dumps(verify_fragment(profile, built["tasks"]),
                             ensure_ascii=False, indent=2) + "\n"
    (out / "proposals").mkdir(parents=True, exist_ok=True)
    keep = {"%s.json" % t["id"] for t in built["tasks"]}
    for old in (out / "proposals").glob("task-*.json"):   # 幂等：profile 删任务后不留过期提案
        if old.name not in keep:
            old.unlink()
    for t in built["tasks"]:
        p = {k: v for k, v in t.items()
             if k in ("id", "name", "brief", "module", "depends_on", "estimated_hours",
                      "difficulty", "requires", "acceptance_criteria", "files_to_read",
                      "files_to_edit", "exempt_files", "verify_command", "source")}
        (out / "proposals" / ("%s.json" % t["id"])).write_text(
            json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "_master.fragment.json").write_text(
        json.dumps(built["master"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "rules.fragment.md").write_text(rules_text, encoding="utf-8")
    (out / "verify_manifest.fragment.json").write_text(verify_text, encoding="utf-8")
    print("emitted: %d proposals + master fragment + rules fragment + verify fragment -> %s"
          % (len(built["tasks"]), out))


def check(project: Path, built: dict, tmp: Path) -> int:
    """用 orchd 校验合成的 master（只读；临时文件写在技能工作区，绝不落进项目 .orchd/）。"""
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(built["master"], ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    # -B：引擎是以 import 方式加载目标项目 .orchd/orchd 包的包内模块，默认会在**目标项目**里
    # 落 .pyc（内嵌其绝对路径）。技能对目标项目必须只读，故禁写字节码缓存。
    r = subprocess.run([sys.executable, "-B", ".orchd/__main__.py", "validate", str(tmp)],
                       cwd=str(project), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    # 引擎在"校验失败"时仍返回退出码 0，必须解析 JSON 的 valid 字段（实测：E-13 家族）。
    try:
        rep = json.loads((r.stdout or "").lstrip("\ufeff"))
    except json.JSONDecodeError:
        print("orchd validate -> 无法解析输出（rc=%d）" % r.returncode)
        print((r.stdout or r.stderr).strip()[:1000])
        return 1
    ok = bool(rep.get("valid"))
    print("orchd validate -> %s (rc=%d)" % ("PASS" if ok else "FAIL", r.returncode))
    for e in rep.get("errors", [])[:12]:
        print("   ERROR %s %s: %s" % (e.get("code"), e.get("path"), e.get("message")[:120]))
    for w in rep.get("warnings", [])[:12]:
        print("   warn  %s %s: %s" % (w.get("code"), w.get("path"), w.get("message")[:120]))
    print("   errors=%d warnings=%d" % (len(rep.get("errors", [])), len(rep.get("warnings", []))))
    return 0 if ok else 1


def regress(project: Path, built: dict, expectations: dict | None = None,
            ignore_baseline: set | None = None) -> int:
    """与目标项目的真实任务结构对比。

    A 类（不一致即失败）：任务集合、module、depends_on、verify_command。
    B 类（记录为 INFO，不算失败）：文件声明路径与数量、AC 文本 —— 已完成任务的声明
    是**历史快照**（终态不可改），与规范路径不同属预期。
    """
    exp = expectations or {}
    ignore = set(ignore_baseline or ())   # 一次性基础设施任务须由 profile 的 regress_ignore 显式登记，
                                          # 不内置项目专属默认值（审查：曾硬编码 paper1 的 task-migrate-layout-v2）
    try:
        base = json.loads((project / ".orchd" / "_master.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print("ERROR: %s 无 .orchd/_master.json，无法 regress 比对" % project)
        return 2
    except json.JSONDecodeError as exc:
        print("ERROR: %s 的 _master.json 不是合法 JSON: %s" % (project, exc))
        return 2
    b = {t["id"]: t for t in base["tasks"] if t["id"] not in ignore}
    g = {t["id"]: t for t in built["tasks"]}
    extra, missing = sorted(set(g) - set(b)), sorted(set(b) - set(g))
    print("== A 类：任务集合 ==")
    print("  生成 %d / 基线（去一次性基础设施任务）%d" % (len(g), len(b)))
    print("  生成多出：%s" % (extra or "无"))
    print("  基线多出：%s" % (missing or "无"))
    diffs, infos = [], []
    for tid in sorted(set(g) & set(b)):
        gt, bt = g[tid], b[tid]
        if gt["module"] != bt["module"]:
            diffs.append((tid, "module", gt["module"], bt["module"]))
        bdep = sorted(bt.get("depends_on", []))
        if gt["depends_on"] != bdep:
            if tid in exp and sorted(exp[tid]) == bdep:
                infos.append((tid, "depends_on（规范图有意升级）", gt["depends_on"], bdep))
            else:
                diffs.append((tid, "depends_on", gt["depends_on"], bdep))
        if gt["verify_command"] != bt.get("verify_command"):
            diffs.append((tid, "verify_command", gt["verify_command"], bt.get("verify_command")))
    print("== A 类：结构差异 ==")
    for row in diffs:
        print("  %-34s %-20s gen=%s base=%s" % row)
    if not diffs:
        print("  无——module / depends_on / verify_command 与基线一致")
    print("== B 类：有意差异（不算失败）==")
    for row in infos:
        print("  %-34s %s gen=%s base=%s" % row)
    print("== B 类：规模指标（生成 vs 基线；基线为历史快照）==")
    for tid in sorted(set(g) & set(b)):
        gt, bt = g[tid], b[tid]
        print("  %-34s ac %d/%d  read %d/%d  edit %d/%d" % (
            tid, len(gt["acceptance_criteria"]), len(bt.get("acceptance_criteria", [])),
            len(gt["files_to_read"]), len(bt.get("files_to_read", [])),
            len(gt["files_to_edit"]), len(bt.get("files_to_edit", []))))
    return 0 if not diffs and not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="./build")
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--regress", action="store_true")
    a = ap.parse_args()

    # N-4：先拒后写。曾的写法是 `if a.project:` 包住 check/regress —— 缺 --project 时整段跳过，
    # 前面的 emit 照旧把 26 份生成物写进 --out（默认 ./build/），rc=0。现场看到的是"跑过了"，
    # 实际一步都没核对（实测 M6）。缺参数归用法错 2，且必须早于任何写盘动作。
    if (a.check or a.regress) and not a.project:
        die("--%s 必须同时给 --project <目标项目>（缺失参数 project）："
            "本脚本没有项目可核对，且不落任何生成物"
            % ("check" if a.check else "regress"))

    profile = load_profile(Path(a.profile))
    built = build(profile)
    if built["problems"]:
        print("== 生成期自检未通过（%d）==" % len(built["problems"]))
        for p in built["problems"]:
            print("  -", p)
        return 1
    print("profile=%s tasks=%d source=%s" % (profile["id"], len(built["tasks"]), built["source"]))
    emit(built, profile, Path(a.out))

    rc = 0
    if a.project:
        proj = Path(a.project).resolve()
        if a.check:
            rc |= check(proj, built, Path(a.out).resolve() / "_validate.proposed.json")
        if a.regress:
            rc |= regress(proj, built, profile.get("regress_expectations"),
                          set(profile.get("regress_ignore", [])) or None)
    return rc


if __name__ == "__main__":
    sys.exit(main())
