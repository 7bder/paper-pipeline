#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""78-assertions-selftest.py — profile 实质断言的门禁自测（棘轮下限 + 形状守卫 + 正反控制 + 反向对照）。

用法：
    python -X utf8 78-assertions-selftest.py                     # 全量守卫（verify_command 形态）
    python -X utf8 78-assertions-selftest.py --project <项目根>  # 追加真实产物回放（假阳控制，只读）

背景（2026-09-26 审查 N-6）：profiles/*.yaml 的 verify_assertions_template 曾只有
`forbid + min_bytes` 通配，展开后没有任何一条内容判据——done 门禁形同空转。本脚本把
"含实质断言的任务条目数"做成**棘轮下限**（FLOOR，只准升不准降），并逐任务做正反控制：
  · 正控制：按断言反推满足的产物 → 70-verify.py 必须 rc=0（证明断言可满足、阈值没定死）；
  · 反控制：空项目 → 必须 rc=1（rc=2 说明 manifest 形状本身有问题；全过则断言是摆设）；
  · 反向对照：内存中把任一实质断言删空 → 下限门禁必须判失败（证明棘轮真咬得住）；
  · --project 回放：真实已完工项目的产物必须满足断言，否则阈值是假的（假阳控制）。
只读承诺：只写 tempfile 沙箱，绝不写技能目录与目标项目。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "70-verify.py"
SKILL_ROOT = HERE.parent
PROFILES = SKILL_ROOT / "profiles"
REFS_DOC = SKILL_ROOT / "references" / "30-literature-pipeline.md"

sys.dont_write_bytecode = True                     # .pyc 内嵌本机绝对路径，是发布面污染
import importlib.util                              # noqa: E402
_spec = importlib.util.spec_from_file_location("gen30", HERE / "30-gen-proposals.py")
gen30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen30)                    # noqa: E402

# AC1 口径：实质 = 这六类之一（forbid/min_bytes/min_bytes_each 的通配不算，只拦空文件与残留标记）
SUBSTANTIVE = ("contains", "contains_regex", "min_matches", "word_count", "json_files", "run")
FILE_SUBSTANTIVE = ("contains", "contains_regex", "min_matches", "word_count")
FLOOR = 20                                         # 2026-09-26 实测两档各 20 条；棘轮：只准升
WRITING_TASKS = ("task-write-introduction", "task-write-results-discussion",
                 "task-write-conclusion-abstract")
PLACEHOLDER = re.compile(r"\{(admin|data|lit|ms|fig|review|latex|nb|tool_dir|verify_tool|verify_manifest)\}")

# 正则可满足性探针：正则必须至少命中一条，否则断言永不可满足（写死在探测里，随断言演进补样本）
PROBES = ["1", "12", "123", "| 1", "| 12", "keep", "drop", "C-1", "G1", "100kx",
          "Fig. 1", "Fig 1", "**Fig. 1.**", "[1]", "@article{", "CRITICAL", "DOI"]


def probe_for(pattern: str):
    for p in PROBES:
        try:
            if re.search(pattern, p, flags=re.M):
                return p
        except re.error:
            return None
    return None


def domain_profiles() -> list:
    """可独立生成的领域档：编号规范里 `00-` 是抽象基类（无 verify 模板、unit_source 仍是占位），
    其余（`10-` 起）都要独立生成投喂物——注意：10-materials-chemistry 既被 wbpu 继承又被单独生成，
    故不能按"被 extends 引用"排除（那是 75 的口径，会漏掉整档覆盖）。"""
    return sorted(p for p in PROFILES.glob("*.yaml") if not p.name.startswith("00-"))


def gen(profile_path: pathlib.Path):
    """生成（内存中，不落盘）：返回 (manifest 片段, 生成任务表, 生成器 problems)。"""
    with contextlib.redirect_stdout(io.StringIO()):
        prof = gen30.load_profile(profile_path)
        built = gen30.build(prof)
        frag = gen30.verify_fragment(prof, built["tasks"])
        rules = gen30.rules_fragment(prof)
    return frag, {t["id"]: t for t in built["tasks"]}, built["problems"], prof, rules


def substantive_ids(frag: dict) -> list:
    out = []
    for tid, e in frag.items():
        kinds = [k for k in SUBSTANTIVE if k in e]
        for f in e.get("files", []):
            kinds += [k for k in FILE_SUBSTANTIVE if k in f]
        if kinds:
            out.append(tid)
    return sorted(out)


def substantive_entries(frag: dict) -> int:
    """实质断言**条目**数（一个任务可有多条）；下限门禁比的是任务数，两者都要报，
    否则读者会把 20 个任务误读成 20 条断言（实测条目 27）。"""
    n = 0
    for tid in substantive_ids(frag):
        e = frag[tid]
        n += sum(1 for f in e.get("files", []) if any(k in f for k in FILE_SUBSTANTIVE))
        n += len(e.get("json_files", []) or [])
        n += 1 if e.get("run") else 0
    return n


def floor_ok(frag: dict, floor: int = FLOOR) -> bool:
    return len(substantive_ids(frag)) >= floor


def substantive_view(frag: dict) -> dict:
    """只看实质断言部分。两档的 tool_dir 分制（scripts/ vs 70-tools/）会让通配 files 条目
    天然不同，逐字比对会误报；实质判据必须一致才算"同一套断言在两档都成立"。"""
    out = {}
    for tid in substantive_ids(frag):
        e = frag[tid]
        out[tid] = {"files": [f for f in e.get("files", [])
                              if any(k in f for k in FILE_SUBSTANTIVE)],
                    "json_files": e.get("json_files", [])}
    return out


def strip_substantive(frag: dict, tid: str) -> dict:
    """把某任务的实质断言删空，保留通配（forbid/min_bytes）——模拟"删掉一条实质断言"。"""
    f = copy.deepcopy(frag)
    e = f[tid]
    for k in list(e):
        if k in SUBSTANTIVE and k != "files":
            e.pop(k)
    e["files"] = [{k: v for k, v in item.items() if k not in FILE_SUBSTANTIVE}
                  for item in e.get("files", [])]
    return f


# ── 守卫 1：下限 + 逐任务非空 + 生成器干净 ────────────────────────────────────────
def run_floor_guards() -> int:
    print("== 实质断言下限（棘轮 %d）==" % FLOOR)
    bad = 0
    for prof in domain_profiles():
        try:
            frag, tasks, problems, _, _ = gen(prof)
        except SystemExit as exc:                     # 生成器 die 本身就是失败信号
            print("  %-28s 生成器拒绝展开（rc=%s）" % (prof.name, exc))
            bad += 1
            continue
        n = len(substantive_ids(frag))
        empty = [tid for tid, e in frag.items()
                 if not any(e.get(k) for k in ("files", "json_files", "globs", "absent_paths"))
                 and not e.get("run")]
        ok = n >= FLOOR and not empty and not problems
        print("  %-28s 任务=%-3d 实质任务=%-3d(≥%d) 实质条目=%-3d 空断言任务=%d 生成 problems=%d  %s"
              % (prof.name, len(frag), n, FLOOR, substantive_entries(frag), len(empty),
                 len(problems), "OK" if ok else "MISMATCH"))
        for p in problems[:4]:
            print("      problem: %s" % p)
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 2：形状（路径字面量 / 归属 / 正则可编译 / json 必带 min_items）────────────
def run_shape_guards() -> int:
    print("== 断言形状守卫 ==")
    bad = 0
    cases = []
    for prof in domain_profiles():
        try:
            frag, tasks, _, _, _ = gen(prof)
        except SystemExit:
            cases.append((("%s: 生成" % prof.name), "生成器 die"))
            continue
        raw = yaml_template(prof)
        for a in raw:
            tid = a.get("task", "*")
            if tid == "*":
                continue
            if tid not in tasks:
                cases.append(("%s %s: 点名了本档不存在的任务" % (prof.name, tid), "unknown task"))
                continue
            allowed = set(tasks[tid]["files_to_edit"]) | {r["path"] for r in tasks[tid]["files_to_read"]}
            for key in ("files", "json_files"):
                for item in a.get(key, []):
                    p = item.get("path", "")
                    if PLACEHOLDER.search(p) or "{" in p:
                        cases.append(("%s %s: path 含占位符" % (tid, p), "本块不做占位替换，须写字面量"))
                    elif p not in allowed:
                        cases.append(("%s %s: 不在 files_to_edit∪files_to_read" % (tid, p), "幽灵断言"))
                    if key == "json_files" and (item.get("require_keys") or item.get("require_keys_all")) \
                            and "min_items" not in item:
                        cases.append(("%s %s: require_keys* 缺 min_items" % (tid, p), "N-3 fail-open"))
                    if key == "files":
                        cases += _regex_cases(tid, item)
                        wc = item.get("word_count")
                        if wc and not (isinstance(wc, list) and len(wc) == 2
                                       and all(isinstance(x, int) and x > 0 for x in wc)
                                       and wc[0] < wc[1]):
                            cases.append(("%s %s: word_count 区间" % (tid, p), str(wc)))
                        for t in (item.get("contains") or []) + (item.get("forbid") or []):
                            if not isinstance(t, str) or not t.strip():
                                cases.append(("%s %s: contains/forbid 有空或非字符串项" % (tid, p), repr(t)))
            if "run" in a:
                cases.append(("%s: 含 run 断言" % tid, "run 与 profile 的 tool_dir 绑定，两档不通用"))
        # 通配覆盖必须在子档存活（deep_merge 对 list 是替换：子档重定义本键会清掉通配项）。
        # 同一 path 可能有多条 files 断言（通配一条 + 点名一条），按 path 归并后判"至少一条带 forbid"。
        for tid, entry in frag.items():
            by_path: dict = {}
            for f in entry.get("files", []):
                d = by_path.setdefault(f["path"], {"forbid": set(), "bytes": 0})
                d["forbid"] |= set(f.get("forbid", []))
                d["bytes"] = max(d["bytes"], f.get("min_bytes", 0) or 0)
            for p, d in by_path.items():
                is_text = pathlib.Path(p).suffix.lower() in gen30.TEXT_SUFFIXES
                if is_text and "TODO" not in d["forbid"]:
                    cases.append(("%s %s: 文本产物无 forbid 通配" % (tid, p),
                                  "子档重定义了 verify_assertions_template"))
                if not is_text and d["bytes"] < 5000:
                    cases.append(("%s %s: 二进制产物无体积下限" % (tid, p), "同上"))
    for name, why in cases:
        print("  MISMATCH %-56s %s" % (name, why))
        bad += 1
    print("  形状问题 %d 条" % len(cases))
    return 1 if bad else 0


def yaml_template(prof: pathlib.Path) -> list:
    """读本档**自己**声明的 verify_assertions_template（未合并），用于形状审查。"""
    raw = yaml.safe_load(prof.read_text(encoding="utf-8-sig"))
    return raw.get("verify_assertions_template", []) or []


def _regex_cases(tid: str, item: dict) -> list:
    out = []
    for key in ("contains_regex", "forbid_regex"):
        for pat in item.get(key, []):
            try:
                re.compile(pat)
            except re.error as exc:
                out.append(("%s %s: %s 无法编译" % (tid, item.get("path"), key), str(exc)))
    mm = item.get("min_matches")
    if mm is not None:
        if not isinstance(mm, dict) or "pattern" not in mm or not isinstance(mm.get("min"), int) \
                or mm["min"] < 1:
            out.append(("%s %s: min_matches" % (tid, item.get("path")), "需 {pattern, min≥1}"))
        elif probe_for(mm["pattern"]) is None:
            out.append(("%s %s: min_matches 正则无任何探针命中"
                        % (tid, item.get("path")), repr(mm["pattern"])))
    for pat in item.get("contains_regex", []):
        if probe_for(pat) is None:
            out.append(("%s %s: contains_regex 无任何探针命中" % (tid, item.get("path")), repr(pat)))
    return out


# ── 守卫 3：规格一致性（AC2 必填字段 / AC3 三写作任务 word_count / 两档同源）─────────
def refs_required_keys() -> set:
    """22-refs.json 的必填字段集合，从两处规范文本取出（不抄常量，规范改了这里就得改）。"""
    row = next(l for l in REFS_DOC.read_text(encoding="utf-8-sig").splitlines()
               if "22-refs.json" in l and "验真" in l)
    cell = next(c for c in row.split("|") if "22-refs.json" in c)
    keys = {k for k in re.findall(r"`([a-z_]+)`", cell)}
    prof = gen30.load_profile(PROFILES / "10-materials-chemistry.yaml")
    ac = next(a for t in prof["tasks"] if t["id"] == "task-search-verify-refs"
              for a in t["ac"] if "字段" in a)
    m = re.search(r"字段（([^）]+)）", ac)
    keys |= {x.strip() for x in m.group(1).split("、")} if m else set()
    return keys


def run_spec_guards() -> int:
    print("== 规格一致性（AC2/AC3/两档同源）==")
    cases = []
    required = refs_required_keys()
    frags = {}
    for prof in domain_profiles():
        try:
            frags[prof.name], _, _, _, _ = gen(prof)
        except SystemExit:
            cases.append(("生成 %s" % prof.name, "die"))
    # AC2：task-citation-audit 的 json_files 必须逐条覆盖必填字段集合
    cit = (frags.get("10-wbpu-kh550.yaml") or {}).get("task-citation-audit", {})
    refs = [j for j in cit.get("json_files", []) if j["path"].endswith("22-refs.json")]
    have = set(refs[0].get("require_keys_all", [])) if refs else set()
    cases.append(("citation-audit json_files 覆盖必填字段集合 %s" % sorted(required),
                  "" if refs and required <= have else "缺 %s" % sorted(required - have)))
    cases.append(("citation-audit json_files 带 min_items（N-3）",
                  "" if refs and "min_items" in refs[0] else "无 min_items"))
    # AC3：三个写作任务各含 word_count 正整数区间
    for tid in WRITING_TASKS:
        bands = [f["word_count"] for e in frags.values() for f in e.get(tid, {}).get("files", [])
                 if "word_count" in f]
        ok = bool(bands) and all(isinstance(b, list) and len(b) == 2
                                 and all(isinstance(x, int) and x > 0 for x in b) and b[0] < b[1]
                                 for b in bands)
        cases.append(("%s word_count 区间" % tid, "" if ok else str(bands[:2])))
    # 两档同源：共有任务的**实质**断言必须逐字一致（子档若重定义本键，deep_merge 的 list 替换
    # 会静默清掉父档实质断言，展开后形同无断言）
    names = sorted(frags)
    views = {n: substantive_view(f) for n, f in frags.items()}
    base_frag = views[names[0]] if names else {}
    shared = set(base_frag)
    for n in names[1:]:
        shared &= set(views[n])
    diffs = ["%s:%s" % (n, t) for n in names[1:] for t in sorted(shared)
             if base_frag[t] != views[n][t]]
    cases.append(("两档共有任务（%d 个）断言逐字一致" % len(shared),
                  "" if not diffs else "差异 " + "、".join(diffs[:3])))
    bad = 0
    for name, why in cases:
        ok = not why
        print("  %-56s %s" % (name, "OK" if ok else "MISMATCH " + why))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 4：正反控制（合成沙箱跑真实 70-verify.py）─────────────────────────────
def plan_artifacts(frag: dict):
    """按断言反推一份"全部满足"的产物计划。返回 (files, jsons, globs, 不可满足问题)。"""
    texts, jsons, globs, issues = {}, {}, [], []
    for tid, e in frag.items():
        for f in e.get("files", []):
            d = texts.setdefault(f["path"], {"tokens": set(), "probes": [], "bytes": 0,
                                              "lo": 0, "hi": None, "pads": []})
            d["tokens"] |= set(f.get("contains") or [])
            d["bytes"] = max(d["bytes"], f.get("min_bytes", 0) or 0)
            if "min_matches" in f:
                d["probes"].append((f["min_matches"]["pattern"], f["min_matches"]["min"]))
            for pat in f.get("contains_regex", []):
                d["pads"].append(pat)
            if "word_count" in f:
                lo, hi = f["word_count"]
                d["lo"] = max(d["lo"], lo)
                d["hi"] = hi if d["hi"] is None else min(d["hi"], hi)
        for j in e.get("json_files", []):
            d = jsons.setdefault(j["path"], {"keys": set(), "min": 1, "max": None})
            d["keys"] |= set(j.get("require_keys", []) + j.get("require_keys_all", []))
            d["min"] = max(d["min"], j.get("min_items", 1))
            if "max_items" in j:
                d["max"] = j["max_items"] if d["max"] is None else min(d["max"], j["max_items"])
        for g in e.get("globs", []):
            globs.append((g["pattern"], g.get("min_count", 1), g.get("min_bytes_each", 0)))
    for path, d in sorted(texts.items()):
        lines = sorted(d["tokens"])
        for pat, n in d["probes"]:
            p = probe_for(pat)
            if p is None:
                issues.append("%s: min_matches %r 不可满足" % (path, pat))
                continue
            lines += [p] * n
        for pat in d["pads"]:
            p = probe_for(pat)
            if p is None:
                issues.append("%s: contains_regex %r 不可满足" % (path, pat))
            else:
                lines.append(p)
        text = "".join(l + "\n" for l in lines)
        need = d["lo"] - len(text.split())
        if need > 0:
            text += " ".join(["w"] * need) + "\n"
        if d["hi"] is not None and len(text.split()) > d["hi"]:
            issues.append("%s: 满足下限后词数 %d 超上限 %d（区间与其他断言冲突）"
                          % (path, len(text.split()), d["hi"]))
        if len(text.encode("utf-8")) < d["bytes"]:
            text += "z" * (d["bytes"] - len(text.encode("utf-8")) + 8) + "\n"
        d["content"] = text
    for path, d in sorted(jsons.items()):
        n = d["min"] if d["max"] is None else min(d["min"], d["max"])
        d["content"] = json.dumps([{k: 1 for k in sorted(d["keys"])}] * max(n, 1),
                                  ensure_ascii=False)
    return texts, jsons, globs, issues


def write_sandbox(root: pathlib.Path, texts: dict, jsons: dict, globs: list) -> None:
    for path, d in texts.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d["content"], encoding="utf-8")
    for path, d in jsons.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d["content"], encoding="utf-8")
    for pattern, min_count, min_bytes in globs:
        if "**" in pattern:
            continue                                   # 本 skill 的 profile 未用递归 glob
        d, base = pattern.rsplit("/", 1)
        target = root / d
        target.mkdir(parents=True, exist_ok=True)
        if "*" not in base:
            (target / base).write_bytes(b"y" * max(min_bytes, 1))
            continue
        stem, suf = base.split("*", 1)
        for i in range(max(min_count, 1)):
            (target / ("%s%d%s" % (stem, i, suf))).write_bytes(b"y" * max(min_bytes, 1))


def run_verify(root: pathlib.Path, manifest: pathlib.Path, tid: str):
    # -B：conventions §2 要求跨进程调用不落 .pyc
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), tid, "--quiet",
                        "--root", str(root), "--manifest", str(manifest)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_synth_guards() -> int:
    print("== 正反控制（合成沙箱，逐任务跑真实 70-verify.py）==")
    frags, biggest = {}, None
    for prof in domain_profiles():
        try:
            frag, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        frags[prof.name] = frag
        if biggest is None or len(frag) > len(frags[biggest]):
            biggest = prof.name
    if not frags:
        print("  MISMATCH 无可用 profile")
        return 1
    views = {n: substantive_view(f) for n, f in frags.items()}
    identical = len({json.dumps(v, ensure_ascii=False, sort_keys=True)
                     for v in views.values()}) == 1
    covers_all = all(set(frags[biggest]) >= set(f) for f in frags.values())
    targets = [biggest] if identical and covers_all else sorted(frags)
    print("  实质断言集合%s、任务集%s ⊇ 其余档 → 沙箱覆盖：%s"
          % ("一致" if identical else "不一致", "覆盖" if covers_all else "不覆盖",
             "、".join(targets)))
    bad = 0
    for name in targets:
        frag = {tid: {k: v for k, v in e.items() if k != "run"}
                for tid, e in frags[name].items()}
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            texts, jsons, globs, issues = plan_artifacts(frag)
            if issues:
                bad += 1
            for msg in issues:
                print("  MISMATCH 不可满足：%s" % msg)
            mf = tmp / "manifest.json"
            mf.write_text(json.dumps(frag, ensure_ascii=False), encoding="utf-8")
            pos, neg = tmp / "pos", tmp / "neg"
            pos.mkdir(); neg.mkdir()
            write_sandbox(pos, texts, jsons, globs)
            npass = nfail = 0
            for tid in sorted(frag):
                rc_pos, out_p = run_verify(pos, mf, tid)
                rc_neg, out_n = run_verify(neg, mf, tid)
                ok = rc_pos == 0 and rc_neg == 1
                npass += 1 if ok else 0
                nfail += 0 if ok else 1
                if not ok:
                    bad += 1
                    print("  MISMATCH %-14s %s: pos=%d(应0) neg=%d(应1)" % (name, tid, rc_pos, rc_neg))
                    print("      pos 输出：%s" % (out_p.strip().replace("\n", " | ")[:300]))
                    print("      neg 输出：%s" % (out_n.strip().replace("\n", " | ")[:300]))
            print("  %-28s 正反控制 %d/%d 通过" % (name, npass, len(frag)))
    return 1 if bad else 0


# ── 守卫 5：反向对照（删空任一实质断言 → 下限门禁必须失败）────────────────────────
def run_reverse_guards() -> int:
    print("== 反向对照（逐条删空实质断言，门禁必须判失败）==")
    frag = None
    for prof in domain_profiles():
        try:
            f, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        if frag is None or len(substantive_ids(f)) > len(substantive_ids(frag)):
            frag = f
    if frag is None or not floor_ok(frag):
        print("  MISMATCH 基线本身未过下限，反向对照无从判定")
        return 1
    bad = 0
    for tid in substantive_ids(frag):
        stripped = strip_substantive(frag, tid)
        bites = not floor_ok(stripped)
        still_gated = bool(stripped[tid].get("files") or stripped[tid].get("json_files"))
        ok = bites and still_gated
        print("  %-34s 删后实质任务=%d 门禁失败=%s 通配仍覆盖=%s  %s"
              % (tid, len(substantive_ids(stripped)), bites, still_gated, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 6：AC6 基类不写死字面 data/、领域档解析成规范目录 ────────────────────────
def run_unit_source_guards() -> int:
    print("== unit_source 占位与解析（AC6）==")
    base = gen30.load_profile(PROFILES / "00-base-empirical.yaml")
    cases = []
    us = base["evidence_policy"].get("unit_source", "")
    cases.append(("基类 unit_source 不含字面 data/", " data/" not in us and "项目 data/" not in us))
    cases.append(("基类 unit_source 用 {data} 占位", "{data}" in us))
    for prof in domain_profiles():
        frag, tasks, problems, merged, rules = gen(prof)
        concrete = merged["paths"]["data"]
        line = next((l for l in rules.splitlines() if l.startswith("- **unit_source**")), "")
        cases.append(("%s rules.fragment 的 unit_source 含 %s/" % (prof.name, concrete),
                      ("%s/" % concrete) in line))
        cases.append(("%s rules.fragment 无未解析占位符" % prof.name,
                      not PLACEHOLDER.search(rules)))
    bad = 0
    for name, ok in cases:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 7（可选）：真实项目回放 = 假阳控制 ────────────────────────────────────────
def run_project_replay(project: pathlib.Path) -> int:
    print("== 真实项目回放（假阳控制，只读）：%s ==" % project)
    if not (project / ".orchd").exists() and not (project / "20-lit").exists():
        print("  跳过：不像论文项目根")
        return 0
    frag, _, _, merged, rules = gen(PROFILES / "10-wbpu-kh550.yaml")
    concrete = merged["paths"]["data"]
    if ("%s/（含" % concrete) not in rules:
        print("  FAIL  profile 的 unit_source 未带具体数据目录 %s/（回放项目布局与领域档不一致）"
              % concrete)
        return 1
    # 回放口径 = 本任务新增的**实质**断言（通配 forbid/min_bytes 是 paper1 冻结前的旧口径，
    # 单独探测为 INFO，不混进本次假阳控制）
    sub = substantive_view(frag)
    with tempfile.TemporaryDirectory() as td:
        mf = pathlib.Path(td) / "manifest.json"
        mf.write_text(json.dumps(sub, ensure_ascii=False), encoding="utf-8")
        bad = skipped = passed = 0
        for tid in sorted(sub):
            paths = [f["path"] for f in sub[tid]["files"]] + \
                    [j["path"] for j in sub[tid]["json_files"]]
            missing = sorted({p for p in paths if not (project / p).exists()})
            if missing:
                skipped += 1
                print("  SKIP  %-34s 该档无此产物：%s" % (tid, "、".join(missing[:3])))
                continue
            rc, out = run_verify(project, mf, tid)
            if rc == 0:
                passed += 1
                print("  PASS  %s" % tid)
            else:
                bad += 1
                print("  FAIL  %-34s rc=%d\n        %s"
                      % (tid, rc, out.strip().replace("\n", " | ")[:400]))
        print("  实质断言回放：PASS=%d FAIL=%d SKIP=%d（共 %d 个实质任务）"
              % (passed, bad, skipped, len(sub)))
    hits = []
    for tid, e in frag.items():
        for f in e.get("files", []):
            if any(k in f for k in FILE_SUBSTANTIVE) or not f.get("forbid"):
                continue
            p = project / f["path"]
            if not p.exists():
                continue
            body = p.read_text(encoding="utf-8-sig", errors="replace")
            hits += ["%s: %s" % (f["path"], m) for m in f["forbid"] if m in body]
    print("  INFO  通配 forbid 在真实产物命中 %d 处%s"
          % (len(hits), ("：" + "、".join(hits[:4]) + ("…" if len(hits) > 4 else ""
               if hits else "")) if hits else ""))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="真实论文项目根（假阳控制回放，只读）")
    a = ap.parse_args()
    rc = run_floor_guards()
    rc |= run_shape_guards()
    rc |= run_spec_guards()
    rc |= run_synth_guards()
    rc |= run_reverse_guards()
    rc |= run_unit_source_guards()
    if a.project:
        rc |= run_project_replay(pathlib.Path(a.project).resolve())
    print("\nSELFTEST %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
