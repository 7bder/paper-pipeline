#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""75-verify-selftest.py — 判据基座的自测（parity + 每个断言类型的正反控制 + 生成器断言守卫）。

用法：
    python -X utf8 75-verify-selftest.py                    # 合成控制套件 + manifest guards + 生成器守卫
    python -X utf8 75-verify-selftest.py --project <项目根>   # 追加与该项目自带 verify 脚本的 parity 比对

设计：合成一个临时项目，把**每个断言类型**都放一对“应当通过 / 应当失败”的用例；
只接受"该通过的全过、该失败的全败"——单边干净（全过或全败）视为该断言未被真正检查。
parity 模式用真实项目的历史 manifest 比对两个实现的判定是否逐任务一致。
生成器守卫（2026-09-26 审查后新增）：断言展开为空的任务必须被 30-gen-proposals.py 拒绝，
真实 profile 的生成物每个任务必须至少有一条断言——防止 done 门禁空转回归。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "70-verify.py"
sys.path.insert(0, str(HERE))
import importlib.util                                  # noqa: E402
# 本文件以 importlib 直接加载生成器，会在 scripts/ 落下 .pyc；.pyc 内嵌本机绝对路径，
# 是发布物污染（.gitignore 也拦不住已被删过一次又再生的情况），故在加载前关闭写字节码。
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gen30", HERE / "30-gen-proposals.py")
gen30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen30)                        # noqa: E402


def build_case_root(root: pathlib.Path) -> dict:
    """造临时项目 + 覆盖全部断言类型的 manifest，返回 {task_id: 期望 rc}。"""
    (root / "70-tools").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "big.txt").write_text("hello world " * 40, encoding="utf-8")          # ~480 B
    (root / "mid.txt").write_text("needle here\nforbidden\n" + "w " * 50, encoding="utf-8")
    (root / "clean.txt").write_text("needle here\n" + "w " * 50, encoding="utf-8")
    (root / "words.txt").write_text(" ".join(["w"] * 100), encoding="utf-8")
    (root / "many.txt").write_text("\n".join(["[x] item"] * 5), encoding="utf-8")
    (root / "one.txt").write_text("[x] item\n", encoding="utf-8")
    (root / "items_ok.json").write_text(json.dumps([{"a": 1, "b": 2}] * 3), encoding="utf-8")
    (root / "items_bad.json").write_text(json.dumps([{"a": 1}, {"a": 1, "b": 2}]), encoding="utf-8")
    (root / "99-batch").mkdir(exist_ok=True)
    for i in range(3):
        (root / "99-batch" / f"f{i}.png").write_bytes(b"x" * 300)
    (root / "deep" / "nest").mkdir(parents=True)
    for name in ("a.rr", "b.rr"):
        (root / "deep" / "nest" / name).write_text("rr", encoding="utf-8")
    (root / "residual").mkdir(exist_ok=True)
    (root / "residual" / "old.md").write_text("old", encoding="utf-8")

    M = {
        # files / min_bytes
        "c-min-bytes-ok":   {"files": [{"path": "big.txt", "min_bytes": 100}]},
        "c-min-bytes-bad":  {"files": [{"path": "big.txt", "min_bytes": 99999}]},
        "c-missing-file":   {"files": [{"path": "nope.md"}]},
        # files / contains
        "c-contains-ok":    {"files": [{"path": "clean.txt", "contains": ["needle here"]}]},
        "c-contains-bad":   {"files": [{"path": "clean.txt", "contains": ["absent tk"]}]},
        # files / forbid
        "c-forbid-ok":      {"files": [{"path": "clean.txt", "forbid": ["forbidden"]}]},
        "c-forbid-bad":     {"files": [{"path": "mid.txt", "forbid": ["forbidden"]}]},
        # files / word_count
        "c-words-ok":       {"files": [{"path": "words.txt", "word_count": [90, 110]}]},
        "c-words-bad":      {"files": [{"path": "words.txt", "word_count": [1, 10]}]},
        # files / contains_regex
        "c-re-ok":          {"files": [{"path": "many.txt", "contains_regex": [r"^\[x\] item$"]}]},
        "c-re-bad":         {"files": [{"path": "many.txt", "contains_regex": [r"^\[y\] item$"]}]},
        # files / forbid_regex
        "c-nore-ok":        {"files": [{"path": "clean.txt", "forbid_regex": [r"forbidden"]}]},
        "c-nore-bad":       {"files": [{"path": "mid.txt", "forbid_regex": [r"forbidden"]}]},
        # files / min_matches
        "c-matches-ok":     {"files": [{"path": "many.txt", "min_matches": {"pattern": r"\[x\]", "min": 5}}]},
        "c-matches-bad":    {"files": [{"path": "many.txt", "min_matches": {"pattern": r"\[x\]", "min": 6}}]},
        # json_files
        "c-json-items-ok":  {"json_files": [{"path": "items_ok.json", "min_items": 1, "max_items": 5}]},
        "c-json-items-bad": {"json_files": [{"path": "items_ok.json", "min_items": 9}]},
        "c-json-max-bad":   {"json_files": [{"path": "items_ok.json", "max_items": 2}]},
        "c-json-keys-ok":   {"json_files": [{"path": "items_ok.json", "require_keys": ["a", "b"]}]},
        "c-json-keys-bad":  {"json_files": [{"path": "items_ok.json", "require_keys": ["zz"]}]},
        "c-json-keysall-ok":  {"json_files": [{"path": "items_ok.json", "require_keys_all": ["a", "b"]}]},
        "c-json-keysall-bad": {"json_files": [{"path": "items_bad.json", "require_keys_all": ["a", "b"]}]},
        # globs
        "c-glob-ok":        {"globs": [{"pattern": "99-batch/*.png", "min_count": 3, "min_bytes_each": 100}]},
        "c-glob-count-bad": {"globs": [{"pattern": "99-batch/*.png", "min_count": 9}]},
        "c-glob-bytes-bad": {"globs": [{"pattern": "99-batch/*.png", "min_bytes_each": 9999}]},
        # globs / ** 递归（审查：曾未传 recursive=True，`**` 静默 0 命中）
        "c-glob-rr-ok":     {"globs": [{"pattern": "**/*.rr", "min_count": 2}]},
        "c-glob-rr-bad":    {"globs": [{"pattern": "**/*.zz", "min_count": 1}]},
        # absent_paths
        "c-absent-ok":      {"absent_paths": ["nothing-here/"]},
        "c-absent-bad":     {"absent_paths": ["residual/old.md"]},
        # run
        "c-run-ok":         {"run": 'python -c "import sys; sys.exit(0)"'},
        "c-run-bad":        {"run": 'python -c "import sys; sys.exit(1)"'},
    }
    expected = {tid: (0 if "-ok" in tid else 1) for tid in M}
    (root / "70-tools" / "71-verify-manifest.json").write_text(
        json.dumps(M, ensure_ascii=False, indent=2), encoding="utf-8")
    return expected


def run_suite() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        expected = build_case_root(root)
        r = subprocess.run([sys.executable, "-X", "utf8", str(VERIFY), "--all", "--quiet",
                            "--json", "--root", str(root)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = r.stdout or ""
        try:
            got = json.loads(text[text.index("{"):])["results"]
        except Exception as exc:                                   # noqa: BLE001
            print("无法解析自测输出：%s\n%s" % (exc, text[:800]))
            return 1
        bad = []
        for tid, want in expected.items():
            have = got.get(tid, {}).get("rc")
            if have != want:
                bad.append((tid, want, have))
        # missing-entry 用例：manifest 里没有的任务应返回 rc=2
        r2 = subprocess.run([sys.executable, "-X", "utf8", str(VERIFY), "no-such-task",
                             "--quiet", "--json", "--root", str(root)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        rc2 = r2.returncode
        print("== 合成控制套件 ==")
        print("  用例 %d，期望与实际一致 %d，不一致 %d" % (len(expected), len(expected) - len(bad),
                                                        len(bad)))
        for tid, want, have in bad:
            print("   MISMATCH %-22s want=%s got=%s" % (tid, want, have))
        ok_missing = (rc2 == 2)
        print("  %-22s want=2 got=%s" % ("c-missing-entry", rc2))
        return 0 if not bad and ok_missing else 1


def run_manifest_guards() -> int:
    """BOM manifest 与空 manifest 都应返回 rc=2（manifest 问题），而非崩溃或静默 PASS。

    对应审查 B1（带 BOM manifest 曾裸 traceback 且 rc=1 混入 FAIL 语义）与
    B2（空 manifest 下 --all 曾 0 任务静默 PASS，门禁空转）。
    """
    cases: list[tuple[str, int]] = []
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        mp = root / "70-tools" / "71-verify-manifest.json"
        mp.write_text("{}", encoding="utf-8-sig")   # 带 BOM 的空对象（沙盒实际出现过）
        cases.append(("bom-empty-manifest", subprocess.run(
            [sys.executable, "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
             "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode))
        mp.write_text("{}", encoding="utf-8")        # 无 BOM 纯空对象
        cases.append(("empty-manifest", subprocess.run(
            [sys.executable, "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
             "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode))
    print("== manifest guards（B1/B2）==")
    bad = 0
    for name, rc in cases:
        print("  %-24s want=2 got=%s  %s" % (name, rc, "OK" if rc == 2 else "MISMATCH"))
        if rc != 2:
            bad += 1
    return 1 if bad else 0


def run_rc_semantics_guards() -> int:
    """--all 的退出码合成规则（2026-09-26 审查：曾用 max() 把真 FAIL 掩盖成 2）。

    口径：有 rc=1 的断言失败 → 整体 1（首要信号）；无失败但有 rc=2（缺条目/manifest
    问题）→ 整体 2；全过 → 0。单任务 missing-entry 仍 2。
    """
    def rc_all(root: pathlib.Path, manifest_text: str) -> int:
        mp = root / "70-tools" / "71-verify-manifest.json"
        mp.write_text(manifest_text, encoding="utf-8")
        return subprocess.run([sys.executable, "-X", "utf8", str(VERIFY), "--all",
                               "--quiet", "--root", str(root)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace").returncode

    cases = []
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        (root / "ok.txt").write_text("hello", encoding="utf-8")
        m_mix = json.dumps({"t-ok": {"files": [{"path": "ok.txt"}]},
                            "t-fail": {"files": [{"path": "nope.md"}]},
                            "t-empty": {"files": []}})
        # 混合批：真 FAIL 必须把整体判成 1（旧 max() 语义下若批内再混入 rc=2 会被掩盖；
        # per-task rc=2 在 --all 里构不出——missing-entry 只能来自单任务模式，见后一例）。
        cases.append(("all: mixed batch FAIL -> 1", rc_all(root, m_mix)))
        m_usage = json.dumps([])                                     # 顶层非 dict → 2
        cases.append(("all: non-dict manifest -> 2", rc_all(root, m_usage)))
        m_badjson = "{ not json"
        cases.append(("all: invalid JSON -> 2", rc_all(root, m_badjson)))
        m_ok = json.dumps({"t-ok": {"files": [{"path": "ok.txt"}]}})
        cases.append(("all: all pass -> 0", rc_all(root, m_ok)))
        # missing-entry 单任务
        (root / "70-tools" / "71-verify-manifest.json").write_text(m_ok, encoding="utf-8")
        r = subprocess.run([sys.executable, "-X", "utf8", str(VERIFY), "ghost-task",
                            "--quiet", "--root", str(root)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("single: missing entry -> 2", r.returncode))
    want = {0: 1, 1: 2, 2: 2, 3: 0, 4: 2}
    print("== 退出码语义守卫 ==")
    bad = 0
    for i, (name, got) in enumerate(cases):
        exp = want[i]
        print("  %-30s want=%d got=%d  %s" % (name, exp, got, "OK" if got == exp else "MISMATCH"))
        if got != exp:
            bad += 1
    return 1 if bad else 0


def run_generator_guards() -> int:
    """断言展开为空 = done 门禁空转，生成器必须拒绝（2026-09-26 审查：redraw/draw-schematics
    曾因通配模板只覆盖文本文件而生成 `{}`）。正反控制：无二进制模板必须 die，有则必须非空。
    """
    tasks = [{"id": "task-fig-only", "files_to_edit": ["40-figures/x.pdf", "40-figures/x.png"]}]
    prof_text_only = {"verify_assertions_template": [
        {"task": "*", "apply_to": "edit_files_text", "forbid": ["TODO"]}]}
    prof_with_bin = {"verify_assertions_template": [
        {"task": "*", "apply_to": "edit_files_text", "forbid": ["TODO"]},
        {"task": "*", "apply_to": "edit_files_binary", "min_bytes_each": 5000}]}
    cases = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gen30.verify_fragment(prof_text_only, tasks)
        cases.append(("empty-expansion-rejected", False))          # 没抛 die = 失败
    except SystemExit:
        cases.append(("empty-expansion-rejected", True))
    frag = gen30.verify_fragment(prof_with_bin, tasks)
    entry = frag["task-fig-only"]
    cases.append(("binary-covered-nonempty",
                  len(entry.get("files", [])) == 2
                  and all(f.get("min_bytes") == 5000 for f in entry["files"])))
    # 真实 profile 全量：每个任务展开后至少一条断言。抽象父档（被任何 extends 引用的）
    # 从不独立生成，不适用此口径，跳过。
    parents = set()
    for prof in (HERE.parent / "profiles").glob("*.yaml"):
        for line in prof.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("extends:"):
                parents.add(line.split(":", 1)[1].strip())
    for prof in sorted((HERE.parent / "profiles").glob("*.yaml")):
        if prof.name in parents:
            continue
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                built = gen30.build(gen30.load_profile(prof))
            f = gen30.verify_fragment(gen30.load_profile(prof), built["tasks"])
            cases.append(("real:%s" % prof.name,
                          bool(built["tasks"]) and all(
                              any(e.get(k) for k in ("files", "json_files", "globs", "absent_paths"))
                              or e.get("run") for e in f.values())))
        except SystemExit:
            cases.append(("real:%s" % prof.name, False))
    # emit 幂等：profile 删任务后，陈旧 task-*.json 必须被清理（审查：曾只增不删）
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "build"
        prof = gen30.load_profile(HERE.parent / "profiles" / "10-wbpu-kh550.yaml")
        built = gen30.build(prof)
        with contextlib.redirect_stdout(io.StringIO()):
            gen30.emit(built, prof, out)
        stale = out / "proposals" / "task-zz-stale.json"
        stale.write_text("{}", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            gen30.emit(built, prof, out)
        cases.append(("emit-stale-proposal-pruned", not stale.exists()))
    print("== 生成器断言守卫 ==")
    bad = 0
    for name, ok in cases:
        print("  %-44s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_parity(project: pathlib.Path) -> int:
    """与项目自带 verify 脚本逐任务比对判定（rc 必须一致）。"""
    script = project / "scripts" / "verify.py"
    if not script.exists():
        print("== parity ==\n  跳过：%s 不存在" % script)
        return 0
    r = subprocess.run([sys.executable, "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
                        "--root", str(project), "--manifest", str(project / "scripts" / "verify_manifest.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = r.stdout or ""
    try:
        got = json.loads(text[text.index("{"):])["results"]
    except Exception as exc:                                   # noqa: BLE001 — parity 也要有兜底（审查：曾裸崩）
        print("== parity ==\n  无法解析基座输出：%s\n%s" % (exc, text[:800]))
        return 1
    print("== parity（vs %s）==" % script)
    mism = []
    for tid in sorted(got):
        p = subprocess.run([sys.executable, str(script), tid], cwd=str(project),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != got[tid]["rc"]:
            mism.append((tid, p.returncode, got[tid]["rc"]))
        print("  %-34s 项目脚本 rc=%d / 基座 rc=%d  %s"
              % (tid, p.returncode, got[tid]["rc"], "OK" if p.returncode == got[tid]["rc"] else "DIFF"))
    print("  不一致 %d 个" % len(mism))
    return 1 if mism else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="真实项目根（做 parity 比对）")
    a = ap.parse_args()
    rc = run_suite()
    rc |= run_manifest_guards()
    rc |= run_rc_semantics_guards()
    rc |= run_generator_guards()
    if a.project:
        rc |= run_parity(pathlib.Path(a.project).resolve())
    print("\nSELFTEST %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
