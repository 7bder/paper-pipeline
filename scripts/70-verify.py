# -*- coding: utf-8 -*-
"""70-verify.py — 论文任务的判据基座（manifest 驱动的结构化验收）。

用法：
    python 70-tools/70-verify.py <task-id>            # 单个任务（verify_command 的标准形态）
    python 70-tools/70-verify.py --all                # 全量（迁移/回归自检用）
    python 70-tools/70-verify.py <task-id> --json      # 机器可读判定（供审查脚本解析）
    python 70-tools/70-verify.py --schema             # 打印断言 schema（无需读源码）
    python 70-tools/70-verify.py --list               # 列出 manifest 里的任务

退出码：0 = PASS，1 = FAIL（有未满足断言），2 = 用法/manifest 问题（无该任务条目等）。
安全：只读文件与执行 manifest 中显式声明的 `run`（超时 300 s），不写任何文件。
`run` 经 **shell 解释执行**（Windows 为 cmd.exe）——manifest 属受信输入（由本 skill 生成器
或项目作者维护，done 前经审查），任何不可信来源的 manifest 一律不得直接喂给本基座。

manifest 位置（按序取第一个存在的）：`--manifest` 参数 → `70-tools/71-verify-manifest.json`
→ `scripts/verify_manifest.json` → `scripts/71-verify-manifest.json`。
`{ROOT}` = 本脚本的上级目录（即项目根）。

# 断言 schema

任务条目 = {"files": [...], "json_files": [...], "globs": [...], "absent_paths": [...], "run": "..."}
（各段均可省略；四段全空即空验收，直接 PASS。）

files[]（文本/产物文件）：
  path            必填，相对项目根
  min_bytes       文件至少这么大
  contains[]      必须出现的子串（逐条）
  forbid[]        必须不出现的子串（逐条）
  contains_regex[]  必须匹配的正则（条数不限）
  forbid_regex[]    必须不匹配的正则（条数不限）
  min_matches     {"pattern": 正则, "min": n}：匹配次数下限（用于“逐条列出”类 AC）
                  两键都必填，pattern 须能编译为正则
  word_count      [lo, hi]：按空白切分的词数区间（两元数组、两端为整数）

json_files[]（JSON 数据文件）：
  path            必填
  min_items / max_items   顶层长度区间（列表或对象）
  require_keys[]          列表模式下检查第 1 个元素应含的键
  require_keys_all[]      列表模式下检查**每个**元素都应含的键（逐条校验的硬口径）

  与 min_items 的组合语义（N-3，"逐条字段齐全"类 AC 的 fail-open 修正）：
    逐条键检查是对**已有元素**求"每条都含此键"，空列表下 0 条恒真。所以
    **空列表 + 任一 require_keys* 且未配有效 min_items（缺省或 0）判为 FAIL(1)**，不再静默 PASS。
    两种正确写法：配 `min_items: n`（n≥1）声明"至少 n 条"；或不写键要求（只验文件是合法 JSON）。
    判 1 而非 2 的理由：门禁现场看到的通常是"产物交了空清单"，属验收未达；若确系 manifest
    漏配，错误消息会同时点出两种补救，不必再猜。

globs[]（批量产物）：
  pattern         必填，glob 模式（相对项目根，支持 `**` 递归；`[` 等字符按通配语法解析，
                  含字面特殊字符的路径建议改用 files[].path）
  min_count       命中文件数下限
  min_bytes_each  每个命中文件的大小下限

absent_paths[]（不得存在的路径，字符串数组）：
  用于“旧目录无残留”“正文不得残留标记文件”这类否定式验收。

run（字符串，可选）：额外命令；退出码非 0 即失败。用于跑项目内的自检脚本。

条目形态自检（N-2：形态不合一律归用法错，不许裸 traceback 冒充 FAIL）：
  条目值必须是对象；files / json_files / globs 必须是**数组 of 对象**，且每项含该段的定位键
  （前两段 `path`、globs `pattern`）；absent_paths 必须是字符串数组；run 必须是字符串。
  段内可选项的类型也有口径，写错类型同样拦在形态档：`min_bytes / min_items / max_items /
  min_count / min_bytes_each` 为整数，`min_matches` 为对象，`word_count / contains / forbid /
  contains_regex / forbid_regex / require_keys / require_keys_all` 为数组；再往里一层也管：
  定位键须是字符串、`word_count` 须是两元整数、`min_matches` 两键齐备、regex 类数组的每项
  须能编译（坏正则会以 re.error 崩，而不是"没匹配上"）。
  **null 的两种待遇是刻意的**：整段写 null（YAML `files:` 空值）等同省略该段；段内某个键写
  null（`min_bytes:` 空值）判形态错——省略整段是有意的，写半个键是笔误。
  不合时退出码 2，逐条回显「任务 id + 段名[下标] + 缺的键名或实际类型」；
  历史上这些形态都是 `AttributeError: 'str' object has no attribute 'get'` /
  `KeyError: 'path'` / `TypeError: string indices must be integers` 裸崩，rc=1 混进 FAIL 语义。

路径解析基准（2026-09-26 审查 N-5：曾把 `--root X --manifest X/子路径` 解析成 X/X/子路径，
只报 "manifest not found" 不给解析轨迹，难诊断）：

  ROOT          = `--root` 指定值；未指定时 = 本脚本上级目录（项目根）。
  断言里的 path   = 相对 **ROOT** 解析。
  `--manifest`   = 绝对路径原样使用；**相对路径也以 ROOT 为基准，不以当前工作目录为基准**。
                  因此从别处调用时应写 `--manifest 70-tools/71-verify-manifest.json`
                  （相对目标项目根），或干脆给绝对路径；给了带根名前缀的相对路径不会自动剥离，
                  未命中时错误消息会同时回显 `--manifest` 原值与最终解析出的绝对路径。
                  未带 `--manifest` 时按上面的候选顺序在 ROOT 下查找。
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import pathlib
import re
import subprocess
import sys

# 引擎强制的调用形态是 `python 70-verify.py <task-id>`（生成器锁死该形态，不可能带 -X utf8）。
# cp936 主机上 FAIL 明细含非 GBK 字符（✅、生僻符号）时 print 会 UnicodeEncodeError →
# traceback 截断 FAIL 与 --json 输出，rc=1 由崩溃而非断言失败给出（2026-09-26 审查 N-1）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_CANDIDATES = ("70-tools/71-verify-manifest.json", "scripts/verify_manifest.json",
                       "scripts/71-verify-manifest.json")
RUN_TIMEOUT = 300


def resolve_manifest(explicit: str | None) -> pathlib.Path | None:
    if explicit:
        p = pathlib.Path(explicit)
        return p if p.is_absolute() else (ROOT / p)
    for rel in MANIFEST_CANDIDATES:
        p = ROOT / rel
        if p.exists():
            return p
    return None


def read_text(p: pathlib.Path) -> str:
    # utf-8-sig：产物带 BOM 时剥掉之（否则 \ufeff 残留会影响首行 marker 与 word_count）；
    # 非 UTF-8 正文用替换字符兜底（审查已登记：GBK 正文的中文标记可能误判，产物口径为 UTF-8）。
    return p.read_text(encoding="utf-8-sig", errors="replace")


def check_file(f: dict, errs: list, oks: list) -> None:
    rel = f["path"]
    p = ROOT / rel
    if not p.exists():
        errs.append(f"missing file: {rel}")
        return
    size = p.stat().st_size
    if "min_bytes" in f and size < f["min_bytes"]:
        errs.append(f"{rel}: {size}B < min {f['min_bytes']}B")
    needs_text = any(k in f for k in ("contains", "forbid", "contains_regex", "forbid_regex",
                                      "min_matches", "word_count"))
    text = read_text(p) if needs_text else ""
    for needle in f.get("contains", []):
        if needle not in text:
            errs.append(f"{rel}: missing marker {needle!r}")
    for needle in f.get("forbid", []):
        if needle in text:
            errs.append(f"{rel}: forbidden marker {needle!r} present")
    for pat in f.get("contains_regex", []):
        if not re.search(pat, text, flags=re.M):
            errs.append(f"{rel}: regex not matched {pat!r}")
    for pat in f.get("forbid_regex", []):
        if re.search(pat, text, flags=re.M):
            errs.append(f"{rel}: forbidden regex matched {pat!r}")
    if "min_matches" in f:
        mm = f["min_matches"]
        n = len(re.findall(mm["pattern"], text, flags=re.M))
        if n < mm["min"]:
            errs.append(f"{rel}: {n} matches of {mm['pattern']!r} < min {mm['min']}")
    if f.get("word_count"):
        lo, hi = f["word_count"]
        n = len(text.split())
        if not (lo <= n <= hi):
            errs.append(f"{rel}: word count {n} outside [{lo},{hi}]")
    oks.append(f"file ok: {rel} ({size}B)")


def check_json(j: dict, errs: list, oks: list) -> None:
    rel = j["path"]
    p = ROOT / rel
    if not p.exists():
        errs.append(f"missing json: {rel}")
        return
    try:
        data = json.loads(read_text(p))
    except Exception as exc:                                  # noqa: BLE001 — 报告原始错误
        errs.append(f"{rel}: invalid JSON: {exc}")
        return
    if not isinstance(data, (dict, list)):
        # 顶层是标量（JSON `5` / "str" / null）：长度与逐条键检查都没有意义，
        # 曾在 len(data) 处 TypeError 裸崩（N-2 同族：形态尾巴不许 traceback 冒充 FAIL）。
        errs.append(f"{rel}: JSON 顶层必须是数组或对象，实为 {type(data).__name__}"
                    "（产物形态问题，非 manifest 写法问题）")
        return
    if "min_items" in j and len(data) < j["min_items"]:
        errs.append(f"{rel}: {len(data)} items < min {j['min_items']}")
    if "max_items" in j and len(data) > j["max_items"]:
        errs.append(f"{rel}: {len(data)} items > max {j['max_items']}")
    if isinstance(data, dict):
        # dict 顶层：require_keys / require_keys_all 都按"该 dict 是否含此键"检查，
        # 不再静默跳过（曾因静默跳过导致 manifest 配错也 PASS）。
        for key in j.get("require_keys", []) + j.get("require_keys_all", []):
            if key not in data:
                errs.append(f"{rel}: dict missing key {key!r}")
    else:
        # N-3：曾写作 `elif isinstance(data, list) and data`，空列表整段跳过，
        # "每条都含 doi"这类 AC 在 0 条产物上恒真 → rc=0 静默放行（全仓唯一真 fail-open）。
        want = list(j.get("require_keys") or []) + list(j.get("require_keys_all") or [])
        if not data and want and not j.get("min_items"):
            errs.append(f"{rel}: 空列表但配了 require_keys*"
                        f"（{'、'.join(repr(k) for k in want)}）— 逐条键检查 0 条恒真（空转），"
                        "请补 min_items≥1 或删去键要求")
        for key in j.get("require_keys", []):
            if data and key not in data[0]:
                errs.append(f"{rel}: first item missing key {key!r}")
        for key in j.get("require_keys_all", []):
            bad = [i for i, it in enumerate(data) if not isinstance(it, dict) or key not in it]
            if bad:
                errs.append(f"{rel}: {len(bad)} item(s) missing key {key!r} "
                            f"(first at index {bad[0]})")
    oks.append(f"json ok: {rel}")


def check_glob(g: dict, errs: list, oks: list) -> None:
    hits = [x for x in _glob.glob(str(ROOT / g["pattern"]), recursive=True)
            if pathlib.Path(x).is_file()]
    if "min_count" in g and len(hits) < g["min_count"]:
        errs.append(f"glob {g['pattern']}: {len(hits)} < min {g['min_count']}")
    if "min_bytes_each" in g:
        for h in hits:
            if pathlib.Path(h).stat().st_size < g["min_bytes_each"]:
                errs.append(f"glob {g['pattern']}: {h} smaller than {g['min_bytes_each']}B")
    oks.append(f"glob ok: {g['pattern']} ({len(hits)} files)")


def run_spec(spec: dict, errs: list, oks: list) -> None:
    for rel in spec.get("absent_paths") or []:
        if (ROOT / rel).exists():
            errs.append(f"path must not exist: {rel}")
        else:
            oks.append(f"absent ok: {rel}")
    if spec.get("run"):
        try:
            r = subprocess.run(spec["run"], shell=True, cwd=str(ROOT),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            errs.append(f"run timed out after {RUN_TIMEOUT}s: {spec['run']}")
            return
        if r.stdout:
            print(r.stdout.rstrip())
        if r.returncode != 0:
            errs.append(f"run failed ({r.returncode}): {spec['run']}\n{r.stderr}")
        else:
            oks.append(f"run ok: {spec['run']}")


SEGMENT_REQUIRED = (("files", "path"), ("json_files", "path"), ("globs", "pattern"))
# 段内可选项的类型口径：写错类型会在比较处 TypeError 裸崩（`len(data) < "20"`），
# 与 N-2 同族，故一并纳入形态自检。
SEGMENT_TYPED = {
    "files": {"min_bytes": int, "min_matches": dict, "word_count": list,
              "contains": list, "forbid": list, "contains_regex": list, "forbid_regex": list},
    "json_files": {"min_items": int, "max_items": int,
                   "require_keys": list, "require_keys_all": list},
    "globs": {"min_count": int, "min_bytes_each": int},
}


def _type_bad(val: object, want: type) -> bool:
    if want is int:
        return not isinstance(val, int) or isinstance(val, bool)   # True 不是计数下限
    return not isinstance(val, want)


# 内容必须是字符串的数组型可选项（正则类还要能编译）。
SEGMENT_STR_LISTS = {"files": ("contains", "forbid", "contains_regex", "forbid_regex"),
                     "json_files": ("require_keys", "require_keys_all")}


def _knob_problems(task_id: str, seg: str, i: int, it: dict) -> list:
    """段内可选项的**内部**形态（外层类型由 SEGMENT_TYPED 把关，这里管键齐不齐、元素类型）。

    这里每一条都是历史上会以 KeyError / TypeError / re.error 收场的地方：`min_matches` 少
    `min`、`word_count` 不是两元整数、定位键写成数字、字符串数组里混进数字、正则写坏。
    """
    where = f"任务 {task_id}: {seg}[{i}]"
    probs: list[str] = []
    req = dict(SEGMENT_REQUIRED)[seg]
    if req in it and not isinstance(it[req], str):
        probs.append(f"{where} 的定位键 {req!r} 必须是字符串，实为 {type(it[req]).__name__}")
    mm = it.get("min_matches")
    if isinstance(mm, dict):
        if "pattern" not in mm or "min" not in mm:
            probs.append(f"{where} 的 min_matches 须同时含 pattern 与 min"
                         f"（已有键：{sorted(mm) or '无'}）")
        else:
            if _type_bad(mm["pattern"], str):
                probs.append(f"{where} 的 min_matches['pattern'] 必须是 str，"
                             f"实为 {type(mm['pattern']).__name__}")
            else:
                try:
                    re.compile(mm["pattern"])
                except re.error as exc:
                    probs.append(f"{where} 的 min_matches['pattern'] 不是合法正则"
                                 f"（{exc}）：{mm['pattern']!r}")
            if _type_bad(mm["min"], int):
                probs.append(f"{where} 的 min_matches['min'] 必须是 int，"
                             f"实为 {type(mm['min']).__name__}")
    wc = it.get("word_count")
    if isinstance(wc, list):
        if len(wc) != 2 or any(_type_bad(x, int) for x in wc):
            probs.append(f"{where} 的 word_count 必须是 [lo, hi] 两个整数，实为 "
                         f"{[type(x).__name__ for x in wc]}（{len(wc)} 元）")
    for key in SEGMENT_STR_LISTS.get(seg, ()):
        val = it.get(key)
        if not isinstance(val, list):
            continue
        for n, x in enumerate(val):
            if not isinstance(x, str):
                probs.append(f"{where} 的 {key}[{n}] 必须是字符串，实为 {type(x).__name__}")
            elif key.endswith("regex"):
                try:
                    re.compile(x)
                except re.error as exc:
                    probs.append(f"{where} 的 {key}[{n}] 不是合法正则（{exc}）：{x!r}")
    return probs


def shape_problems(task_id: str, spec: object) -> list:
    """manifest 条目形态自检（N-2）。返回人可读的问题列表（空 = 形态合）。

    只判形态（值类型与该段定位键），不判断言内容：内容未达是 FAIL(1)，形态不合是用法错(2)。
    段值写 null 等同省略该段（与"四段全空 = 空验收"的既有口径一致，不额外收紧）。
    """
    if not isinstance(spec, dict):
        return [f"任务 {task_id}: 条目值必须是对象，实为 {type(spec).__name__}"]
    probs: list[str] = []
    for seg, req in SEGMENT_REQUIRED:
        items = spec.get(seg)
        if items is None:
            continue                                   # 显式写 null 等同省略该段
        if not isinstance(items, list):
            probs.append(f"任务 {task_id}: 段 {seg} 必须是数组，实为 {type(items).__name__}")
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                probs.append(f"任务 {task_id}: {seg}[{i}] 必须是对象，实为 {type(it).__name__}")
                continue
            if req not in it:
                probs.append(f"任务 {task_id}: {seg}[{i}] 缺定位键 {req!r}"
                             f"（已有键：{sorted(it) or '无'}）")
            for k, want in SEGMENT_TYPED[seg].items():
                if k in it and _type_bad(it[k], want):
                    # 值为 null 也算形态错（YAML 里 `min_bytes:` 空值 = None → 比较处会 TypeError），
                    # 与"段值 null 等同省略"刻意不同：省略整段是有意的，写半个键是笔误。
                    probs.append(f"任务 {task_id}: {seg}[{i}] 的 {k!r} 必须是 "
                                 f"{want.__name__}，实为 {type(it[k]).__name__}")
            probs += _knob_problems(task_id, seg, i, it)
    absent = spec.get("absent_paths")
    if absent is not None:
        if not isinstance(absent, list):
            probs.append(f"任务 {task_id}: 段 absent_paths 必须是字符串数组，"
                         f"实为 {type(absent).__name__}")
        else:
            for i, rel in enumerate(absent):
                if not isinstance(rel, str):
                    probs.append(f"任务 {task_id}: absent_paths[{i}] 必须是字符串路径，"
                                 f"实为 {type(rel).__name__}")
    run = spec.get("run")
    if run is not None and not isinstance(run, str):
        probs.append(f"任务 {task_id}: run 必须是字符串命令，实为 {type(run).__name__}")
    return probs


def verify_task(spec: dict, quiet: bool = False) -> tuple[int, list, list]:
    errs: list[str] = []
    oks: list[str] = []
    for f in spec.get("files") or []:
        check_file(f, errs, oks)
    for j in spec.get("json_files") or []:
        check_json(j, errs, oks)
    for g in spec.get("globs") or []:
        check_glob(g, errs, oks)
    run_spec(spec, errs, oks)
    if not quiet:
        for o in oks:
            print("[ok]", o)
    return (1 if errs else 0), errs, oks


SCHEMA_HELP = __doc__.split("# 断言 schema", 1)[1].strip() if "# 断言 schema" in __doc__ else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="论文任务判据基座（manifest 驱动）")
    ap.add_argument("task_id", nargs="?", default="")
    ap.add_argument("--manifest", help="manifest 路径（默认按约定自动查找）")
    ap.add_argument("--root", help="项目根（默认=本脚本上级目录；供审查/回归对别的项目运行）")
    ap.add_argument("--all", action="store_true", help="校验 manifest 中全部任务")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出判定（供脚本解析）")
    ap.add_argument("--quiet", action="store_true", help="不打印 [ok] 明细")
    ap.add_argument("--schema", action="store_true", help="打印断言 schema")
    ap.add_argument("--list", action="store_true", help="列出 manifest 中的任务")
    a = ap.parse_args()

    if a.schema:
        print(SCHEMA_HELP)
        return 0

    if a.root:
        global ROOT
        ROOT = pathlib.Path(a.root).resolve()

    mp = resolve_manifest(a.manifest)
    if mp is None or not mp.exists():
        if a.manifest:
            # N-5：只报 "not found" 无法区分「相对谁解析」，故同回原值与解析结果。
            print("[verify] manifest not found: --manifest %r → %s（相对路径以 --root 为基准；"
                  "当前 --root=%s；不带 --manifest 时才试候选 %s）"
                  % (a.manifest, mp, ROOT, "、".join(MANIFEST_CANDIDATES)))
        else:
            print("[verify] manifest not found（试过 %s；--root=%s）"
                  % ("、".join("%s" % (ROOT / c) for c in MANIFEST_CANDIDATES), ROOT))
        return 2
    try:
        # utf-8-sig 同时兼容无 BOM 与带 BOM 两种形态；带 BOM 曾裸 traceback 且 rc=1
        # 混入 FAIL 语义（审查 B1），现归入 rc=2（manifest 问题）。
        manifest = json.loads(mp.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print("[verify] manifest invalid JSON: %s (%s)" % (mp, exc))
        return 2
    if not isinstance(manifest, dict):
        # 标量/列表顶层不是任务映射，属 manifest 结构问题（审查 B4：曾在 --all 处
        # TypeError 裸崩、rc=1 混入 FAIL 语义），显式归入 rc=2。
        print("[verify] manifest must be a JSON object of task entries, got %s"
              % type(manifest).__name__)
        return 2
    try:
        print("[verify] manifest:", mp.relative_to(ROOT))
    except ValueError:
        print("[verify] manifest:", mp)

    if a.list:
        for tid in manifest:
            print("  -", tid)
        return 0

    if a.all:
        targets = list(manifest)
        if not targets:
            # 空 manifest 下 --all 会 0 任务静默 PASS（门禁空转，审查 B2），
            # 显式报为 manifest 问题而非放行。
            print("[verify] manifest is empty（无任何任务条目）— 门禁空转 PASS，请先补断言"
                  "（参考 assets/10-verify-manifest.template.json 或 --schema）")
            return 2
        # `_` 前缀键为模板/注释专用（如 assets 模板的 _note），不是任务条目；
        # --all 若枚举它们会 AttributeError 崩溃（审查 B7）。--list 仍如实列出。
        skipped = [tid for tid in targets if tid.startswith("_")]
        if skipped:
            targets = [tid for tid in targets if not tid.startswith("_")]
            print("[verify] 跳过非任务键（_ 前缀）：%s" % "、".join(skipped))
            if not targets:
                print("[verify] manifest 仅含非任务键 — 同属空门禁，请补任务条目断言")
                return 2
    else:
        targets = [a.task_id]
    results = {}
    for tid in targets:
        if tid not in manifest:
            print(f"[verify] no manifest entry for {tid}")
            results[tid] = {"rc": 2, "errors": [f"no manifest entry for {tid}"], "oks": 0}
            continue
        spec = manifest[tid]
        probs = shape_problems(tid, spec)
        if probs:
            # N-2：以前这些形态会在这里以下三种裸崩之一结束（AttributeError / KeyError /
            # TypeError），rc=1 被当成 FAIL，且诊断只剩一行 traceback；现在归 2 并逐条定位。
            print(f"[verify] manifest 形态不合: {tid}")
            for p in probs:
                print("  -", p)
            results[tid] = {"rc": 2, "errors": probs, "oks": 0}
            continue
        rc, errs, oks = verify_task(spec, quiet=a.quiet)
        results[tid] = {"rc": rc, "errors": errs, "oks": len(oks)}
        if rc:
            print(f"\n[verify] FAIL: {tid}")
            for e in errs:
                print("  -", e)
        else:
            print(f"\n[verify] PASS: {tid}")

    if a.json:
        print(json.dumps({"manifest": str(mp), "results": results,
                          "pass": sum(1 for r in results.values() if r["rc"] == 0),
                          "fail": sum(1 for r in results.values() if r["rc"] == 1),
                          "usage_error": sum(1 for r in results.values() if r["rc"] == 2)},
                         ensure_ascii=False, indent=2))
    elif a.all:
        ok = sum(1 for r in results.values() if r["rc"] == 0)
        print(f"\n[verify] {ok}/{len(results)} PASS（其余见上）")
    # rc 语义不因批量模式而糊：有真 FAIL → 1（验收未达是首要信号）；
    # 无 FAIL 但有 manifest/用法问题 → 2；全过 → 0。（曾用 max() 合并，
    # FAIL 会被 usage-error 掩盖成 2，2026-09-26 审查修复。）
    if any(r["rc"] == 1 for r in results.values()):
        return 1
    if any(r["rc"] == 2 for r in results.values()):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
