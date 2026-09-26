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
  word_count      [lo, hi]：按空白切分的词数区间

json_files[]（JSON 数据文件）：
  path            必填
  min_items / max_items   顶层长度区间（列表或对象）
  require_keys[]          列表模式下检查第 1 个元素应含的键
  require_keys_all[]      列表模式下检查**每个**元素都应含的键（逐条校验的硬口径）

globs[]（批量产物）：
  pattern         必填，glob 模式（相对项目根，支持 `**` 递归；`[` 等字符按通配语法解析，
                  含字面特殊字符的路径建议改用 files[].path）
  min_count       命中文件数下限
  min_bytes_each  每个命中文件的大小下限

absent_paths[]（不得存在的路径，字符串数组）：
  用于“旧目录无残留”“正文不得残留标记文件”这类否定式验收。

run（字符串，可选）：额外命令；退出码非 0 即失败。用于跑项目内的自检脚本。
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import pathlib
import re
import subprocess
import sys

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
    elif isinstance(data, list) and data:
        for key in j.get("require_keys", []):
            if key not in data[0]:
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
    for rel in spec.get("absent_paths", []):
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


def verify_task(spec: dict, quiet: bool = False) -> tuple[int, list, list]:
    errs: list[str] = []
    oks: list[str] = []
    for f in spec.get("files", []):
        check_file(f, errs, oks)
    for j in spec.get("json_files", []):
        check_json(j, errs, oks)
    for g in spec.get("globs", []):
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
        print("[verify] manifest not found（试过 %s）" % "、".join(MANIFEST_CANDIDATES))
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
        spec = manifest.get(tid)
        if spec is None:
            print(f"[verify] no manifest entry for {tid}")
            results[tid] = {"rc": 2, "errors": [f"no manifest entry for {tid}"], "oks": 0}
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
