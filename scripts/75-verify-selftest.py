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
碎片守卫（规格 §3 能力建成后新增）：未声明 fragments 时生成物与改动前逐字节一致且完全不读
manifest、声明后按声明顺序原样注入（marker + 正文不折叠）、未知 id 必须非零退出且不落半份生成物。
注册表守卫（task-capability-registry-resync 新增）：SKILL.md 能力注册表状态位与磁盘实测一致
（available 行路径在盘、planned 行路径不在盘），含 available→planned 与幽灵路径双向内存反向对照。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

# 与 70-verify.py 同一口径（conventions §2）：cp936 主机上打印 ✅/中文明细不得崩溃。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet",
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
        r2 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "no-such-task",
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
            [sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
             "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode))
        mp.write_text("{}", encoding="utf-8")        # 无 BOM 纯空对象
        cases.append(("empty-manifest", subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
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
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all",
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
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "ghost-task",
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


def pick_profile_fixture(profiles_dir: pathlib.Path, prefer_child: bool = True) -> pathlib.Path | None:
    """运行时选取 CLI 守卫的夹具档（task-selftest-fixture-decouple）：不写死任何领域档文件名。

    prefer_child=True 优先 extends 非空的**子档**（保住"子档继承/deep_merge"类守卫的测试语义）；
    无子档退化任一非 00- 基类档；全缺返回 None——调用方必须显式 SKIP，不得静默判 PASS。
    """
    try:
        files = sorted(p for p in profiles_dir.glob("*.yaml") if not p.name.startswith("00-"))
    except OSError:
        return None
    if not files:
        return None
    if prefer_child:
        for p in files:
            try:
                head = p.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if re.search(r"^extends:\s*\S", head, re.M):
                return p
    return files[0]


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
        fixture = pick_profile_fixture(HERE.parent / "profiles")
        if fixture is None:
            print("  SKIP  emit-stale-proposal-pruned（profiles 无可生成领域档，不判 PASS）")
        else:
            prof = gen30.load_profile(fixture)
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


def run_gen_cli_guards() -> int:
    """N-4（--check/--regress 缺 --project 静默走 emit 落盘）与 N-10（P-1 注入假设）的守卫。

    每类各带一条**锚点**：把旧的口径本身放进子进程跑，证明故障条件真实存在（旧控制流确实
    rc=0 且落了文件 / 旧注入循环在缺锚任务时静默），否则守卫只是陪着修复变绿的装饰。
    """
    cases: list[tuple[str, bool, str]] = []
    gen = HERE / "30-gen-proposals.py"
    profiles = HERE.parent / "profiles"
    mat = profiles / "10-materials-chemistry.yaml"
    fx = pick_profile_fixture(profiles)
    if fx is None:
        print("  SKIP  CLI 夹具档缺失（profiles 无可生成领域档）——相关用例显式跳过，不判 PASS")

    def call(*args, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(cwd) if cwd else None)

    def snippet(code: str, *argv) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code, *argv], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def emptied(d: pathlib.Path) -> bool:
        return not d.exists() or not any(d.rglob("*"))

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)

        # ==== 类 1：缺 --project 的口径（N-4）====
        anchor = snippet(
            "import pathlib,sys\n"
            "out = pathlib.Path(sys.argv[1])\n"
            "(out / 'proposals').mkdir(parents=True)         # 旧口径：emit 无条件先跑\n"
            "(out / '_master.fragment.json').write_text('{}')\n"
            "project = ''                                    # 未给 --project\n"
            "rc = 0\n"
            "if project:                                     # 旧口径：核对整段被包在这里\n"
            "    rc |= 1\n"
            "sys.exit(rc)\n",
            str(base / "anchor"))
        files = list((base / "anchor").rglob("*")) if (base / "anchor").exists() else []
        cases.append(("锚点：旧控制流缺项目仍 rc=0 且落文件",
                      anchor.returncode == 0 and len(files) >= 2,
                      "rc=%d files=%d" % (anchor.returncode, len(files))))
        if fx is not None:
            for flag in ("--check", "--regress"):
                outdir = base / flag.lstrip("-")
                r = call("--profile", str(fx), flag, "--out", str(outdir))
                cases.append(("%s 缺 --project → rc=2（非静默 0）" % flag, r.returncode == 2,
                              "rc=%d %s" % (r.returncode, (r.stdout or r.stderr)[-90:])))
                cases.append(("%s 的消息点名参数 project" % flag,
                              "project" in (r.stdout + r.stderr),
                              "stdout=%r" % (r.stdout or "")[-120:]))
                left = [x.name for x in outdir.rglob("*")] if outdir.exists() else []
                cases.append(("%s 缺 --project 不落任何生成物" % flag, not left, "落了 %s" % left))
            plain = call("--profile", str(fx), "--out", str(base / "plain"))
            cases.append(("纯生成路径仍 rc=0 且落盘（防过度收紧）",
                          plain.returncode == 0 and not emptied(base / "plain"),
                          "rc=%d %s" % (plain.returncode, (plain.stdout or plain.stderr)[-90:])))
            both = call("--profile", str(fx), "--check",
                        "--project", str(base / "noparam"), "--out", str(base / "withproj"))
        # 这里不要求 rc=0（那个"项目"没有 .orchd/，引擎侧当然会报），只要求**不是**被
        # 本任务新增的参数守卫拦下——否则等于把正路也堵了。
            cases.append(("给了 --project 就不被新守卫拦下（不误伤正路）",
                          "必须同时给" not in (both.stdout + both.stderr),
                          "rc=%d %s" % (both.returncode, (both.stdout or both.stderr)[-140:])))

        # ==== 类 2：docstring 与 argparse 的旗标口径（N-4 文档面）====
        h = call("--help")
        declared = set(re.findall(r"(?<!\w)--[a-z][a-z0-9-]*", h.stdout or ""))
        doc = gen.read_text(encoding="utf-8").split('"""')[1]
        usage = [ln.strip() for ln in doc.splitlines()
                 if ln.strip().startswith("python") and "30-gen-proposals.py" in ln]
        documented = set()
        for ln in usage:
            documented |= set(re.findall(r"--[a-z][a-z0-9-]*", ln))
        cases.append(("docstring 用法条数 = 3（生成/check/regress）", len(usage) == 3,
                      "实为 %d：%s" % (len(usage), usage)))
        cases.append(("docstring 旗标全部为 argparse 实际接受项",
                      bool(documented) and documented <= declared,
                      "多出 %s" % sorted(documented - declared)))
        cases.append(("核对类用法行一律带 --project",
                      all(("--project" in ln) for ln in usage if "--check" in ln or "--regress" in ln),
                      "缺 --project 的用法行见上"))
        pos = re.findall(r"--(?:check|regress)\s+<", doc)
        cases.append(("位置参数写法 --regress <项目> 命中 0", not pos, "命中 %s" % pos))
        if fx is not None:
            legacy = call("--profile", str(fx), "--regress", str(HERE.parent))
            cases.append(("锚点：位置参数写法必被 argparse 拒（rc=2）",
                          legacy.returncode == 2 and "unrecognized" in (legacy.stderr or ""),
                          "rc=%d %s" % (legacy.returncode, (legacy.stderr or "")[-90:])))

        # ==== 类 3：multi-paper 的 P-1 注入假设（N-10）====
        anchor = snippet(
            "tasks = [{'id': 'task-audit-dataX', 'depends_on': []}]\n"
            "for t in tasks:                                  # 旧口径：只遍历，不校验锚任务在不在\n"
            "    if t['id'] == 'task-audit-data':\n"
            "        t['depends_on'].append('task-data-asset-mapping')\n"
            "print('silent-ok')\n")
        cases.append(("锚点：旧注入循环缺锚任务时静默无报错",
                      anchor.returncode == 0 and "silent-ok" in (anchor.stdout or ""),
                      "rc=%d %s" % (anchor.returncode, (anchor.stderr or "")[-90:])))
        prof = gen30.load_profile(mat)
        prof.setdefault("entry", {})["mode"] = "multi-paper"
        prof["tasks"] = [t for t in prof["tasks"] if t.get("id") != "task-audit-data"]
        # 把 depends 里对它的引用一并摘掉：否则通用「未知依赖」检查会先报错，
        # 看不出 P-1 守卫本身有没有生效。
        prof["depends"] = {k: [d for d in v if d != "task-audit-data"]
                           for k, v in (prof.get("depends") or {}).items()}
        built = gen30.build(prof)
        hit = [p for p in built["problems"] if "task-data-asset-mapping" in p
               and "task-audit-data" in p]
        cases.append(("删 task-audit-data 后 multi-paper 生成必报错（含两个任务名）",
                      bool(hit), "problems=%s" % built["problems"][:2]))
        cases.append(("报错不靠通用未知依赖检查兜底",
                      not any("depends_on unknown task" in p for p in built["problems"]),
                      "见 %s" % built["problems"][:2]))
        kept = gen30.load_profile(mat)
        kept.setdefault("entry", {})["mode"] = "multi-paper"
        bk = gen30.build(kept)
        ad = [t for t in bk["tasks"] if t["id"] == "task-audit-data"]
        cases.append(("保留 task-audit-data 时 0 问题且 P-1 有人依赖",
                      not bk["problems"] and ad
                      and "task-data-asset-mapping" in ad[0]["depends_on"],
                      "problems=%s" % bk["problems"][:2]))
        datafirst = gen30.build(gen30.load_profile(mat))
        cases.append(("data-first 模式不注册 P-1（默认档不误伤）",
                      not any(t["id"] == "task-data-asset-mapping" for t in datafirst["tasks"])
                      and not datafirst["problems"],
                      "problems=%s" % datafirst["problems"][:2]))
        zero_pairs = [("materials", mat)] + ([(fx.stem, fx)] if fx is not None else [])
        for name, path in zero_pairs:
            b = gen30.build(gen30.load_profile(path))
            cases.append(("%s 档生成期 0 问题（零回归）" % name, not b["problems"],
                          "problems=%s" % b["problems"][:2]))

        # ==== 夹具选取函数反向对照（合成 profiles 目录，不落盘真文件）====
        with tempfile.TemporaryDirectory() as tp:
            pdir = pathlib.Path(tp) / "profiles"
            pdir.mkdir()
            (pdir / "00-base.yaml").write_text("id: base\n", encoding="utf-8")
            cases.append(("夹具选取：仅基类（00- 排除）→ None（SKIP 语义）",
                          pick_profile_fixture(pdir) is None, ""))
            (pdir / "10-child.yaml").write_text("id: child\nextends: 00-base.yaml\n", encoding="utf-8")
            picked = pick_profile_fixture(pdir)
            cases.append(("夹具选取：基类+子档→选中子档（继承语义保留）",
                          picked is not None and picked.name == "10-child.yaml", ""))
            (pdir / "20-plain.yaml").write_text("id: plain\n", encoding="utf-8")
            picked2 = pick_profile_fixture(pdir)
            cases.append(("夹具选取：子档优先于普通档",
                          picked2 is not None and picked2.name == "10-child.yaml", ""))
            (pdir / "10-child.yaml").unlink()
            picked3 = pick_profile_fixture(pdir)
            cases.append(("夹具选取：无子档退化任一非基类档",
                          picked3 is not None and picked3.name == "20-plain.yaml", ""))

    print("== 生成器 CLI 与 P-1 注入守卫（N-4/N-10）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-44s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def _legacy_rules_fragment(profile: dict) -> str:
    """**改动前**（尚无碎片能力时）的 `rules_fragment` 逐字冻结副本，含它依赖的 `_render_scalar`。

    零回归守卫拿它比对 sha256。副本刻意不调用 gen30 的实现——否则本体改了基线跟着改，
    守卫就成了陪跑。基线变了要显式改这里，这是有意的摩擦。
    """
    def render(v):
        if isinstance(v, dict):
            return "；".join("%s=%s" % (k, render(x)) for k, x in v.items())
        if isinstance(v, list):
            return "；".join(render(x) for x in v)
        return str(v)

    pol = profile["evidence_policy"]
    lines = ["# 域口径规则片段（由 profiles/%s 生成，请并入项目 `rules/`）" % profile["id"], ""]
    for k, v in pol.items():
        lines.append("- **%s**：%s" % (k, render(v)))
    for key in ("figure_policy", "citation_policy"):
        if key in profile:
            lines += ["", "## %s" % key]
            for k, v in profile[key].items():
                lines.append("- **%s**：%s" % (k, render(v)))
    return "\n".join(lines) + "\n"


def run_fragment_guards() -> int:
    """static/ 规则碎片能力（规格 `references/60-capability-specs.md` §3）的守卫。

    §3.5 点名的三条里有两条是**否定条件**：未声明零回归、未知 id 必须 die。缺任一条，
    「注入」这件事就等于没检查——正则没覆盖到不等于检查过且干净。另加 manifest 结构守卫，
    把 AC1（≥3 条目、axes ≥2 键、碎片文件在盘）钉成机检而不是靠人看。
    每条正向守卫都配反向对照（把故障条件真造出来一次），否则守卫会陪着修复一起空转变绿。
    """
    import hashlib
    import yaml

    cases: list[tuple[str, bool, str]] = []
    static = HERE.parent / "static"
    gen = HERE / "30-gen-proposals.py"
    profiles = HERE.parent / "profiles"

    # ---- AC1：manifest 结构与碎片文件在盘 ----
    mpath = static / "manifest.yaml"
    idx: dict = {}
    try:
        data = yaml.safe_load(mpath.read_text(encoding="utf-8-sig"))
    except Exception as exc:                                       # noqa: BLE001
        data = None
        cases.append(("manifest.yaml 可读且是合法 YAML", False, repr(exc)))
    if data:
        entries = data.get("fragments")
        ids = [e.get("id") for e in entries or [] if isinstance(e, dict)]
        idx = {e.get("id"): e for e in entries or [] if isinstance(e, dict)}
        cases.append(("碎片条目数 ≥3", isinstance(entries, list) and len(entries) >= 3,
                      "实际 %s" % (len(entries) if isinstance(entries, list) else entries)))
        cases.append(("首条为 elsevier-numbered", bool(ids) and ids[0] == "elsevier-numbered",
                      "首条=%s" % (ids[:1])))
        cases.append(("id 无重复", len(ids) == len(set(ids)), str(ids)))
        cases.append(("version 为 1", str(data.get("version")) == "1", repr(data.get("version"))))
        thin = [i for i, e in idx.items()
                if not isinstance(e.get("axes"), dict) or len(e.get("axes")) < 2]
        cases.append(("每条 axes ≥2 键", not thin, str(thin)))
        allowed = set(gen30.FRAGMENT_AXES_KEYS)
        stray = {i: sorted(set(e.get("axes", {})) - allowed) for i, e in idx.items()
                 if isinstance(e.get("axes"), dict)}
        cases.append(("axes 键 ⊆ 允许集合", not [k for k, v in stray.items() if v],
                      str({k: v for k, v in stray.items() if v})))
        gone = [i for i, e in idx.items()
                if not e.get("fragment") or not (static / str(e["fragment"])).exists()]
        cases.append(("每条 fragment 文件在盘", not gone, str(gone)))
        asciiish = [i for i, e in idx.items()
                    if not re.fullmatch(r"[A-Za-z0-9._-]+\.md", str(e.get("fragment", "")))]
        cases.append(("碎片文件名为平铺 ASCII kebab-case", not asciiish, str(asciiish)))

    # ---- AC2：未声明零回归（含「完全不读 manifest」的证明）----
    # 这里**不**沿用 run_generator_guards 的「跳过被 extends 引用的父档」口径：那条排除的是
    # 断言展开为空的抽象档，而规则片段本体对任何档都成立，父档恰恰是最可能被声明碎片的一档。
    with tempfile.TemporaryDirectory() as td:
        empty_static = pathlib.Path(td) / "no-such-static"
        empty_static.mkdir()
        for prof_path in sorted(profiles.glob("*.yaml")):
            prof = gen30.load_profile(prof_path)
            if prof.get("fragments"):
                cases.append(("真实档 %s 未提前声明 fragments" % prof_path.name, False,
                              "已声明 → 零回归基线无法比对，本任务的收尾不在本档"))
                continue
            new = hashlib.sha256(gen30.rules_fragment(prof).encode("utf-8")).hexdigest()
            old = hashlib.sha256(_legacy_rules_fragment(prof).encode("utf-8")).hexdigest()
            cases.append(("%s 未声明：与改动前逐字节一致" % prof_path.name, new == old,
                          "sha256 %s vs %s" % (new[:12], old[:12])))
            blank = hashlib.sha256(
                gen30.rules_fragment(prof, empty_static).encode("utf-8")).hexdigest()
            cases.append(("%s 未声明：manifest 不在也不影响（不读）" % prof_path.name,
                          blank == new, "sha256 %s vs %s" % (blank[:12], new[:12])))
            # 反向对照：同一份空目录下**声明**碎片必须 die，证明上一条的绿不是恒真
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    gen30.rules_fragment({**prof, "fragments": ["elsevier-numbered"]}, empty_static)
                cases.append(("%s 反向对照：声明后空目录要 die" % prof_path.name, False,
                              "没抛 SystemExit → 「不读」那条守卫是空转"))
            except SystemExit as exc:
                cases.append(("%s 反向对照：声明后空目录要 die" % prof_path.name,
                              exc.code not in (0, None), "rc=%s" % exc.code))

    # ---- AC3：声明后 marker + 正文原样 + 顺序 = 声明顺序 ----
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        sdir = tmp / "static"
        sdir.mkdir()
        body_a = "    首行带四格缩进\n\n下一段前有空的行\n末行\n"
        (sdir / "aa-first.md").write_text(body_a + "\n\n", encoding="utf-8")
        (sdir / "bb-second.md").write_text("# 第二片\n\ntext\n", encoding="utf-8")
        (sdir / "manifest.yaml").write_text(
            "version: 1\nfragments:\n"
            "  - id: bb-second\n    fragment: bb-second.md\n"
            "    axes: {publisher: springer, language: en}\n"
            "  - id: aa-first\n    fragment: aa-first.md\n"
            "    axes: {publisher: elsevier, language: en}\n", encoding="utf-8")
        prof = gen30.load_profile(profiles / "10-materials-chemistry.yaml")
        prof = {**prof, "fragments": ["aa-first", "bb-second"]}   # 声明顺序与 manifest 相反
        cap = io.StringIO()
        with contextlib.redirect_stdout(cap):
            out = gen30.rules_fragment(prof, sdir)
        exp_a = "<!-- fragment: aa-first -->\n" + body_a.rstrip("\n") + "\n"
        exp_b = "<!-- fragment: bb-second -->\n# 第二片\n\ntext\n"
        cases.append(("AC3 顺序=声明顺序且逐字节块（缩进/空行/标记全原样）",
                      out.endswith(exp_a + "\n" + exp_b), repr(out[-90:])))
        cases.append(("AC3 marker 行独占一行", out.count("<!-- fragment: ") == 2
                      and "\n<!-- fragment: aa-first -->\n" in out, ""))
        cases.append(("AC3 axes 不符只 warn 不改判定",
                      "warn" in cap.getvalue() and "bb-second" in cap.getvalue(), ""))
        cases.append(("AC3 未声明时输出无 marker",
                      "<!-- fragment:" not in gen30.rules_fragment(
                          {k: v for k, v in prof.items() if k != "fragments"}, sdir), ""))

    # ---- AC4/AC5：未知 id 走子进程真实退出码，且不得留下半份生成物 ----
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        prof = gen30.load_profile(profiles / "10-materials-chemistry.yaml")
        ghost = "ghost-fragment-9k2"
        pf = tmp / "ghost-profile.yaml"
        pf.write_text(yaml.safe_dump({**prof, "fragments": [ghost]}, allow_unicode=True),
                      encoding="utf-8")
        build = tmp / "build"
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                            "--profile", str(pf), "--out", str(build)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        born = (r.stdout or "") + (r.stderr or "")
        cases.append(("AC4 未知 id：子进程 rc≠0", r.returncode != 0, "rc=%d" % r.returncode))
        cases.append(("AC4 未知 id：消息含该 id", ghost in born, born[:120]))
        cases.append(("AC4 未知 id：消息列出已知 id",
                      "elsevier-numbered" in born and "md-single-source" in born, ""))
        cases.append(("AC4 未知 id：消息不含本机绝对路径",
                      not re.search(r"[A-Za-z]:[\\/]|\\\\Users\\\\", born), ""))
        leftovers = sorted(p.name for p in build.rglob("*")) if build.exists() else []
        cases.append(("AC4 未知 id：先拒后写（不留半份生成物）", not leftovers, str(leftovers)[:120]))
        # 反向对照：同一条命令去掉 ghost 声明必须 rc=0 且落盘，证明上一条的「空」是拒绝而非崩溃
        pf.write_text(yaml.safe_dump(prof, allow_unicode=True), encoding="utf-8")
        r2 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                             "--profile", str(pf), "--out", str(build)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("AC4 反向对照：去掉声明后正常落盘 rc=0",
                      r2.returncode == 0 and (build / "rules.fragment.md").exists(),
                      "rc=%d" % r2.returncode))

    # ---- D1–D4：索引字段形态与正文编码的强制点（2026-09-27 code 审查返工）----
    # 这组判据测的是"规格写了没强制"：`../`、绝对路径、子目录、非 .md、非字符串字段、
    # 非 UTF-8 正文都必须 rc=2 明拒。缺任一条，索引里一个笔误就会把**别的文件**当规则静默注入。
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        sdir = tmp / "static"
        sdir.mkdir()
        good_manifest = ("version: 1\nfragments:\n  - id: good\n    fragment: good.md\n"
                         "    axes: {publisher: elsevier, language: en}\n")
        (sdir / "good.md").write_text("# 好片\n\n正文\n", encoding="utf-8")
        (tmp / "outside.md").write_text("包外正文\n", encoding="utf-8")
        (sdir / "sub").mkdir()
        (sdir / "sub" / "nested.md").write_text("嵌套正文\n", encoding="utf-8")
        (sdir / "good.txt").write_text("非 md 正文\n", encoding="utf-8")
        (sdir / "gbk.md").write_bytes("# 好片\n\n中文正文在此\n".encode("gbk"))
        (sdir / "marker.md").write_text("正文\n\n<!-- fragment: fake -->\n冒名 marker\n",
                                         encoding="utf-8")
        prof0 = gen30.load_profile(profiles / "10-materials-chemistry.yaml")

        def reject(tag, manifest_text, declared=("good",), needle=""):
            """把故障真造一次：期望 die(rc=2) + 有 ERROR: + 不回显本机绝对路径。"""
            (sdir / "manifest.yaml").write_text(manifest_text, encoding="utf-8")
            cap = io.StringIO()
            code, crashed = None, None
            try:
                with contextlib.redirect_stdout(cap):
                    gen30.fragment_blocks({**prof0, "fragments": list(declared)}, sdir)
            except SystemExit as exc:
                code = exc.code
            except Exception as exc:                                   # noqa: BLE001
                crashed = repr(exc)                                    # 期望 die，不接受 traceback
            msg = cap.getvalue()
            if crashed:
                cases.append((tag, False, "以崩代拒：%s" % crashed))
            elif code is None:
                cases.append((tag, False, "未 die → 该失败面静默放过"))
            else:
                cases.append((tag, code == 2 and "ERROR:" in msg
                              and not re.search(r"[A-Za-z]:[\\/]", msg)
                              and (needle in msg if needle else True),
                              "rc=%s %s" % (code, msg.strip()[-140:] or "无输出")))

        def one(kind_frag, kind_id=None):
            return ("version: 1\nfragments:\n  - id: %s\n    fragment: %s\n"
                    "    axes: {publisher: elsevier, language: en}\n"
                    % (kind_id or "good", kind_frag))

        reject("D1 fragment 为列表 → rc=2 明拒", one("[good.md]"))
        reject("D1 fragment 为整数 → rc=2 明拒", one("123"))
        reject("D1 id 为整数 → rc=2（含报错消息构造本身不崩）", one("good.md", kind_id="1"),
               declared=("1",))
        reject("D1 id 为空串 → rc=2", one("good.md", kind_id='""'))
        reject("D3 fragment 越界 ../ → rc=2（不得把包外文件当规则）",
               one("../outside.md"))
        reject("D3 fragment 带子目录 → rc=2（§3.1 平铺）", one("sub/nested.md"))
        reject("D3 fragment 非 .md → rc=2", one("good.txt"))
        reject("D3 fragment 为绝对路径 → rc=2", one('"%s"' % str(tmp / "outside.md").replace("\\", "/")))
        reject("D3 axes 非映射 → rc=2 且不回显本体",
               "version: 1\nfragments:\n  - id: good\n    fragment: good.md\n"
               "    axes: [publisher, elsevier]\n")
        reject("D4 正文非 UTF-8 → rc=2（不得乱码注入/不得崩）", one("gbk.md"))
        reject("O2 正文含注入标记 → rc=2（marker 由拼接层独占）", one("marker.md"))
        reject("O1 声明重复 → rc=2（与索引侧重复 id 对称）", good_manifest,
               declared=("good", "good"))
        reject("D1 声明元素非字符串 → rc=2", good_manifest, declared=("good", 1))
        # 反向对照：以上全部故障条件都不在时，必须逐字节注入成功
        (sdir / "manifest.yaml").write_text(good_manifest, encoding="utf-8")
        cap_ok = io.StringIO()
        with contextlib.redirect_stdout(cap_ok):
            ok_out = gen30.fragment_blocks({**prof0, "fragments": ["good"]}, sdir)
        cases.append(("D1–D4 反向对照：合法索引逐字节注入成功",
                      ok_out == "<!-- fragment: good -->\n# 好片\n\n正文\n", repr(ok_out[:120])))
        # 反向对照：新校验不得把「未声明」拖进失败面——索引坏成非 UTF-8 也要原样返回空串
        (sdir / "manifest.yaml").write_bytes("version: 1\nfragments: [ ]\n".encode("gbk")
                                             + b"\xff\xfe garbage")
        cases.append(("D1–D4 反向对照：未声明时坏索引仍零回归（不读）",
                      gen30.fragment_blocks(prof0, sdir) == "", "返回非空"))
        # 子进程级：越界声明必须 rc=2、无 traceback、零残留（先拒后写没被新校验破坏）。
        # STATIC_DIR 由脚本自身的 __file__ 推出，所以要把生成器复制到临时包里跑，
        # 否则它读的还是仓库真 static/，这条判据测不到我造的坏索引。
        script_dir = tmp / "scripts"
        script_dir.mkdir(exist_ok=True)
        gen_copy = script_dir / gen.name
        gen_copy.write_bytes(gen.read_bytes())
        (sdir / "manifest.yaml").write_text(one("../outside.md"), encoding="utf-8")
        pf2 = tmp / "esc-profile.yaml"
        pf2.write_text(yaml.safe_dump({**prof0, "fragments": ["good"]}, allow_unicode=True),
                       encoding="utf-8")
        build2 = tmp / "build-esc"
        r3 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen_copy),
                             "--profile", str(pf2), "--out", str(build2)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        born3 = (r3.stdout or "") + (r3.stderr or "")
        cases.append(("D3 子进程级：越界声明 rc=2（非 traceback）",
                      r3.returncode == 2 and "Traceback" not in born3,
                      "rc=%d %s" % (r3.returncode, born3.strip()[-160:])))
        cases.append(("D3 子进程级：先拒后写（零残留）",
                      not (build2.exists() and any(build2.rglob("*"))),
                      str(sorted(p.name for p in build2.rglob("*"))[:3]) if build2.exists() else ""))
        # 反向对照：把索引修好，同一个临时包必须 rc=0 并落下 rules.fragment.md
        (sdir / "manifest.yaml").write_text(good_manifest, encoding="utf-8")
        r4 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen_copy),
                             "--profile", str(pf2), "--out", str(tmp / "build-ok")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("D3 子进程级反向对照：好索引 rc=0 且产物在盘",
                      r4.returncode == 0 and (tmp / "build-ok" / "rules.fragment.md").exists(),
                      "rc=%d %s" % (r4.returncode, born3.strip()[-120:])))

    print("== 规则碎片守卫（规格 §3）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-46s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 能力注册表状态位守卫（task-capability-registry-resync）───────────────────────
# 口径（SKILL.md §能力注册表）：「是否可用」由磁盘决定——标 available 的行路径必须存在，
# 标 planned 的行路径必须不存在，任一违反即 rc=1；registry-flip 漏翻或能力文件被误删都会在此变红。
_REGISTRY_ROW = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(planned|available)\s*\|", re.M)


def registry_rows(text: str) -> list:
    """解析 SKILL.md 能力注册表 → [(名称, 检查路径, 状态)]。

    碎片行的 `static/` + `manifest.yaml` 双反引号格归一为 static/manifest.yaml
    （目录与索引同时在盘才算可用）；其余行取路径单元格第一个反引号路径。
    """
    _, sep, body = text.partition("## 能力注册表")
    if not sep:
        return []
    body = body.split("**建好后的动作**")[0]
    rows = []
    for name, cell, _, status in _REGISTRY_ROW.findall(body):
        if "manifest.yaml" in cell:
            path = "static/manifest.yaml"
        else:
            m = re.search(r"`([^`]+)`", cell)
            if not m:
                continue
            path = m.group(1).rstrip("/")
        rows.append((name.strip(), path, status))
    return rows


def registry_violations(text: str, root: pathlib.Path) -> list:
    rows = registry_rows(text)
    if not rows:
        return ["能力注册表未解析到任何行（节缺失或表结构变更）"]
    out = []
    for name, path, status in rows:
        exists = (root / path).exists()
        if status == "available" and not exists:
            out.append("标 available 但路径不在盘：%s（%s）" % (path, name))
        if status == "planned" and exists:
            out.append("标 planned 但路径已在盘（应翻牌 available）：%s（%s）" % (path, name))
    return out


def run_registry_guards() -> int:
    print("== 能力注册表状态位守卫（SKILL.md）==")
    text = (HERE.parent / "SKILL.md").read_text(encoding="utf-8-sig")
    root = HERE.parent
    violations = registry_violations(text, root)
    bad = 1 if violations else 0
    for v in violations:
        print("  MISMATCH %s" % v)
    print("  注册表 %d 行，状态位与磁盘%s" % (len(registry_rows(text)),
          "一致" if not violations else "不一致"))
    if violations:
        print("  SKIP  反向对照（当前注册表本身不一致，先修复再对照）")
        return bad
    # 反向对照（内存变异，不落盘、不动真文件）：改错任一行状态位，守卫必须变红。
    m = re.search(r"^(\|[^|]+\|[^|]+\|[^|]+\|)\s*available(\s*\|)", text, re.M)
    flip = text[:m.start()] + m.group(1) + " planned" + m.group(2) + text[m.end():] if m else None
    ok1 = bool(flip) and bool(registry_violations(flip, root))
    print("  %-46s %s" % ("反向对照：available→planned（路径已在盘）被判违反",
                          "OK" if ok1 else "MISMATCH"))
    m2 = re.search(r"^(\|[^|]+\| `)[^`]+(` \|[^|]+\|)\s*available(\s*\|)", text, re.M)
    flip2 = (text[:m2.start()] + m2.group(1) + "scripts/00-ghost-capability.py" + m2.group(2)
             + " available" + m2.group(3) + text[m2.end():]) if m2 else None
    ok2 = bool(flip2) and any("00-ghost-capability.py" in v
                              for v in registry_violations(flip2, root))
    print("  %-46s %s" % ("反向对照：available 行指向不在盘路径被判违反",
                          "OK" if ok2 else "MISMATCH"))
    return bad or (0 if ok1 and ok2 else 1)


def run_encoding_and_path_guards() -> int:
    """N-1（cp936 下 FAIL 打印崩溃）与 N-5（--manifest 相对路径解析基准）的守卫。

    调用形态刻意用**引擎强制**的那一种：`python 70-verify.py <task>`（不带 -X utf8，
    生成器 :211 的正则锁死了这个形态），并以 `PYTHONIOENCODING=gbk` + 剥掉 `PYTHONUTF8`
    模拟纯 cp936 主机——本机设了 PYTHONUTF8=1 会完全掩盖这个 bug。
    反向对照两层：①同一段 ✅ print 放在不带 reconfigure 的子进程里必须崩（证明环境真的
    复现了故障条件，守卫不是空转）；②✅ 必须确实不能被 GBK 编码（证明用例有牙）。
    """
    env = dict(os.environ, PYTHONIOENCODING="gbk")
    env.pop("PYTHONUTF8", None)
    cases: list[tuple[str, bool, str]] = []

    def call(*args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(VERIFY), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env)

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        (root / "a.md").write_text("nothing here", encoding="utf-8")
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps({"c-emoji-fail": {"files": [{"path": "a.md",
                                                   "contains": ["✅ 已完成"]}]}},
                       ensure_ascii=False), encoding="utf-8")
        try:
            "✅".encode("gbk")
            cases.append(("用例有牙：✅ 不可被 GBK 编码", False, "该字符在 gbk 下可编码，用例失去复现力"))
        except UnicodeEncodeError:
            cases.append(("用例有牙：✅ 不可被 GBK 编码", True, ""))
        old = subprocess.run([sys.executable, "-c",
                              "print('  - missing marker %r' % '\\u2705 已完成')"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", env=env)
        cases.append(("反向对照：旧行为（无 reconfigure）必崩",
                      old.returncode != 0 and "UnicodeEncodeError" in (old.stderr or ""),
                      "rc=%d stderr=%s" % (old.returncode, (old.stderr or "")[-80:])))
        # N-1 修复后的三条正向断言：rc 语义、明细完整、--json 可整份解析
        r = call("c-emoji-fail", "--root", str(root))
        cases.append(("gbk 下 FAIL 退出码 = 1", r.returncode == 1, "rc=%d" % r.returncode))
        cases.append(("FAIL 明细打全（含 ✅ 原文）",
                      "missing marker" in r.stdout and "✅ 已完成" in r.stdout,
                      "stdout 尾部=%r" % r.stdout[-60:]))
        cases.append(("stderr 无 UnicodeEncodeError",
                      "UnicodeEncodeError" not in (r.stderr or ""),
                      (r.stderr or "")[-120:]))
        rj = call("c-emoji-fail", "--json", "--root", str(root))
        try:
            parsed = json.loads(rj.stdout[rj.stdout.index("{"):])
            got_rc = parsed["results"]["c-emoji-fail"]["rc"]
            cases.append(("gbk 下 --json 可完整解析", got_rc == 1, "内层 rc=%s" % got_rc))
        except Exception as exc:                                    # noqa: BLE001
            cases.append(("gbk 下 --json 可完整解析", False,
                          "%s：%r" % (type(exc).__name__, (rj.stdout or "")[-80:])))
        # N-5：相对 --manifest 以 --root 为基准（文档化语义的正/反两面）
        rel = "70-tools/71-verify-manifest.json"
        rpos = call("c-emoji-fail", "--root", str(root), "--manifest", rel)
        cases.append(("相对 --manifest 按 --root 命中",
                      "manifest not found" not in rpos.stdout and rpos.returncode == 1,
                      "rc=%d %s" % (rpos.returncode, rpos.stdout[-80:])))
        wrong = "%s/%s" % (root.name, rel)                           # 带根名前缀的 cwd 视角写法
        rneg = call("c-emoji-fail", "--root", str(root), "--manifest", wrong)
        joined = str(root / wrong)
        cases.append(("二次拼接未命中 → rc=2", rneg.returncode == 2, "rc=%d" % rneg.returncode))
        cases.append(("未命中消息回显原值+解析后绝对路径+基准",
                      wrong in rneg.stdout and joined in rneg.stdout
                      and "--root" in rneg.stdout,
                      "stdout=%r" % rneg.stdout[-160:]))
        rschema = call("--schema")
        cases.append(("--schema 写明解析基准",
                      "--manifest" in rschema.stdout and "--root" in rschema.stdout,
                      ""))
    print("== 编码与 manifest 路径守卫（N-1/N-5）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-38s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_manifest_shape_guards() -> int:
    """N-3（空列表逐条键检查恒真 = fail-open）与 N-2（manifest 形态裸崩）的守卫。

    三类各带一条**锚点**：锚点不复用 70 的代码，而是把出问题的判据表达式本身放进子进程跑，
    证明该形态在朴素写法下确实恒真（类 1）/确实抛异常（类 2、3）。没有锚点的话，守卫可能只是
    陪着修复一起变绿的空转装饰——AC5 要求的反向对照口径就是"把判据拆掉后测试要变红"。
    """
    cases: list[tuple[str, bool, str]] = []

    def call(root: pathlib.Path, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(VERIFY), *args, "--root", str(root)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def snippet(code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def mk(name: str, manifest: dict, files: dict | None = None) -> pathlib.Path:
        root = base / name
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        for rel, content in (files or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return root

    def crashed(r: subprocess.CompletedProcess) -> str:
        err = r.stderr or ""
        return err.splitlines()[-1].strip() if err.strip() else ""

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)

        # ==== 类 1：json_files 空列表（N-3，本仓唯一真 fail-open）====
        anchor = snippet("import sys;sys.exit(0 if all('doi' in it for it in []) else 1)")
        cases.append(("锚点：空列表下逐条键检查恒真", anchor.returncode == 0,
                      "rc=%d" % anchor.returncode))
        req_all = {"t": {"json_files": [{"path": "e.json", "require_keys_all": ["doi"]}]}}
        r = mk("empty-all", req_all, {"e.json": "[]"})
        p1 = call(r, "t")
        cases.append(("空列表 + require_keys_all 不再 rc=0", p1.returncode == 1,
                      "rc=%d %s" % (p1.returncode, crashed(p1) or p1.stdout[-90:])))
        cases.append(("空转消息含 path 与「空列表」",
                      "e.json" in p1.stdout and "空列表" in p1.stdout,
                      "stdout=%r" % p1.stdout[-160:]))
        r = mk("empty-keys", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": "[]"})
        p2 = call(r, "t")
        cases.append(("空列表 + require_keys 不 IndexError",
                      p2.returncode == 1 and not crashed(p2),
                      "rc=%d %s" % (p2.returncode, crashed(p2))))
        r = mk("empty-min", {"t": {"json_files": [{"path": "e.json", "require_keys_all": ["doi"],
                                                  "min_items": 1}]}}, {"e.json": "[]"})
        p3 = call(r, "t")
        cases.append(("配 min_items=1 时原口径不回退",
                      p3.returncode == 1 and "min 1" in p3.stdout, "rc=%d" % p3.returncode))
        r = mk("nonempty", req_all, {"e.json": json.dumps([{"doi": "1"}])})
        p4 = call(r, "t")
        cases.append(("非空且字段齐全仍 PASS（防过度收紧）", p4.returncode == 0,
                      "rc=%d %s" % (p4.returncode, p4.stdout[-90:])))
        rschema = call(base / "empty-all", "--schema")
        cases.append(("--schema 写明 require_keys* 与 min_items 组合语义",
                      "require_keys_all" in rschema.stdout and "min_items" in rschema.stdout
                      and "空列表" in rschema.stdout, "rc=%d" % rschema.returncode))

        # ==== 类 1b：require_keys 对非 dict 首元素（审查 F-2，2026-09-29 实锤）====
        # 朴素 `key not in data[0]`：int 首元素 TypeError 裸崩（rc=1 冒充 FAIL）、
        # str 首元素退化为子串判定（rc=0 假 PASS）。两条锚点证明朴素写法确实错，
        # 行为断言在防御被摘除时分别以 traceback 痕迹 / rc=0 变红。
        anchor = snippet("d=[1,2,3]\n"
                         "try:\n"
                         "    'doi' not in d[0]\n"
                         "except TypeError:\n"
                         "    import sys;sys.exit(3)\n"
                         "sys.exit(0)")
        cases.append(("锚点：int 首元素下 `key not in data[0]` 必 TypeError",
                      anchor.returncode == 3, "rc=%d" % anchor.returncode))
        anchor = snippet("import sys;sys.exit(0 if 'doi' in 'doi is here' else 1)")
        cases.append(("锚点：str 首元素下 `not in` 退化为子串判定（假 PASS 源）",
                      anchor.returncode == 0, "rc=%d" % anchor.returncode))
        r = mk("int-first", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": "[1, 2, 3]"})
        q1 = call(r, "t")
        cases.append(("int 首元素 + require_keys → rc=1 FAIL 且无 traceback",
                      q1.returncode == 1 and not crashed(q1),
                      "rc=%d %s" % (q1.returncode, crashed(q1) or q1.stdout[-120:])))
        cases.append(("FAIL 消息点明首元素实际类型 int",
                      "not an object" in q1.stdout and "int" in q1.stdout,
                      "stdout=%r" % q1.stdout[-160:]))
        r = mk("str-first", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": json.dumps(["doi is here", {"x": 1}])})
        q2 = call(r, "t")
        cases.append(("str 首元素 + require_keys → rc=1（子串假 PASS 已堵）",
                      q2.returncode == 1 and "str" in q2.stdout,
                      "rc=%d %s" % (q2.returncode, q2.stdout[-120:])))
        r = mk("obj-missing", {"t": {"json_files": [{"path": "e.json",
                                                     "require_keys": ["doi"]}]}},
               {"e.json": json.dumps([{"title": "x"}])})
        q3 = call(r, "t")
        cases.append(("对照组：对象列表缺键仍 rc=1（口径不糊）",
                      q3.returncode == 1 and "first item missing key 'doi'" in q3.stdout,
                      "rc=%d %s" % (q3.returncode, q3.stdout[-120:])))
        r = mk("obj-ok", {"t": {"json_files": [{"path": "e.json",
                                                "require_keys": ["doi"]}]}},
               {"e.json": json.dumps([{"doi": "10.1/x"}])})
        q4 = call(r, "t")
        cases.append(("对照组：对象列表含键仍 rc=0（防过度收紧）",
                      q4.returncode == 0, "rc=%d %s" % (q4.returncode, q4.stdout[-120:])))

        # ==== 类 2：条目值形态（N-2，曾以 AttributeError 裸崩冒充 FAIL）====
        anchor = snippet("s='oops';s.get('files')")
        cases.append(("锚点：朴素 spec.get 对字符串必崩",
                      anchor.returncode != 0 and "AttributeError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("str-entry", {"t-str": "oops"})
        s1 = call(r, "--all")
        cases.append(("条目值为字符串 --all → rc=2", s1.returncode == 2, "rc=%d" % s1.returncode))
        cases.append(("形态消息含任务 id 与定位说明",
                      "t-str" in s1.stdout and "条目值必须是对象" in s1.stdout
                      and "str" in s1.stdout, "stdout=%r" % s1.stdout[-160:]))
        cases.append(("无 AttributeError 裸 traceback", "AttributeError" not in (s1.stderr or ""),
                      crashed(s1)))
        s2 = call(r, "t-str")
        cases.append(("单任务形态同样 rc=2", s2.returncode == 2, "rc=%d" % s2.returncode))
        r = mk("null-entry", {"t-null": None})
        s3 = call(r, "--all")
        cases.append(("null 条目值报形态错而非「无条目」",
                      s3.returncode == 2 and "NoneType" in s3.stdout
                      and "no manifest entry" not in s3.stdout, "rc=%d" % s3.returncode))
        r = mk("mixed", {"ok-entry": {"files": [{"path": "a.md", "contains": ["x"]}]},
                         "t-str": "oops"}, {"a.md": "x"})
        s4 = call(r, "--all")
        cases.append(("混合 manifest：坏条目不吞好条目判定",
                      s4.returncode == 2 and "PASS: ok-entry" in s4.stdout
                      and "形态不合: t-str" in s4.stdout,
                      "rc=%d %s" % (s4.returncode, s4.stdout[-200:])))

        # ==== 类 3：段内项形态（缺定位键 / 段或键类型不合）====
        anchor = snippet("{}['path']")
        cases.append(("锚点：缺 path 的朴素取键必 KeyError",
                      anchor.returncode != 0 and "KeyError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("no-path", {"t": {"files": [{"min_bytes": 10}]}}, {"a.md": "x"})
        f1 = call(r, "t")
        cases.append(("files[0] 缺 path → rc=2", f1.returncode == 2, "rc=%d" % f1.returncode))
        cases.append(("缺键消息含段名[下标]与键名",
                      "files[0]" in f1.stdout and "path" in f1.stdout
                      and "min_bytes" in f1.stdout, "stdout=%r" % f1.stdout[-160:]))
        r = mk("json-no-path", {"t": {"json_files": [{"min_items": 1}]}}, {"e.json": "[]"})
        f2 = call(r, "t")
        cases.append(("json_files[0] 缺 path → rc=2", f2.returncode == 2, "rc=%d" % f2.returncode))
        r = mk("glob-no-pattern", {"t": {"globs": [{"min_count": 1}]}}, {})
        f3 = call(r, "t")
        cases.append(("globs[0] 缺 pattern → rc=2 且点名 pattern",
                      f3.returncode == 2 and "pattern" in f3.stdout,
                      "rc=%d %s" % (f3.returncode, f3.stdout[-120:])))
        r = mk("bad-type", {"t": {"json_files": [{"path": "e.json", "min_items": "20"}]}},
               {"e.json": "[]"})
        f4 = call(r, "t")
        cases.append(("min_items 写成字符串 → rc=2 而非 TypeError",
                      f4.returncode == 2 and "必须是 int" in f4.stdout and not crashed(f4),
                      "rc=%d %s" % (f4.returncode, crashed(f4) or f4.stdout[-120:])))
        r = mk("null-knob", {"t": {"files": [{"path": "a.md", "min_bytes": None}]}},
               {"a.md": "x"})
        f5 = call(r, "t")
        cases.append(("段内键值为 null → rc=2（笔误不当省略）",
                      f5.returncode == 2 and "NoneType" in f5.stdout, "rc=%d" % f5.returncode))
        r = mk("null-seg", {"t": {"files": None, "json_files": None, "globs": None,
                                  "absent_paths": None}}, {})
        f6 = call(r, "t")
        cases.append(("整段写 null 等同省略（宽容不回退）", f6.returncode == 0,
                      "rc=%d %s" % (f6.returncode, f6.stdout[-120:])))
        r = mk("scalar-json", {"t": {"json_files": [{"path": "e.json", "min_items": 1}]}},
               {"e.json": "5"})
        f7 = call(r, "t")
        cases.append(("产物 JSON 顶层标量 → rc=1 且无 TypeError",
                      f7.returncode == 1 and "顶层必须是数组或对象" in f7.stdout
                      and not crashed(f7),
                      "rc=%d %s" % (f7.returncode, crashed(f7) or f7.stdout[-120:])))

        # ==== 类 3 续：可选项的**内部**形态（少键 / 元素类型 / 坏正则）====
        anchor = snippet("m={'pattern':'x'};m['min']")
        cases.append(("锚点：min_matches 少 min 必 KeyError",
                      anchor.returncode != 0 and "KeyError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("mm-nomin", {"t": {"files": [{"path": "a.md",
                                            "min_matches": {"pattern": "Fig"}}]}}, {"a.md": "Fig 1"})
        k1 = call(r, "t")
        cases.append(("min_matches 少 min → rc=2 且点名 min",
                      k1.returncode == 2 and "min" in k1.stdout and not crashed(k1),
                      "rc=%d %s" % (k1.returncode, crashed(k1) or k1.stdout[-120:])))
        r = mk("mm-badre", {"t": {"files": [{"path": "a.md",
                                             "min_matches": {"pattern": "(", "min": 1}}]}},
               {"a.md": "x"})
        k2 = call(r, "t")
        cases.append(("坏正则（min_matches）→ rc=2 而非 re.error",
                      k2.returncode == 2 and "不是合法正则" in k2.stdout and not crashed(k2),
                      "rc=%d %s" % (k2.returncode, crashed(k2) or k2.stdout[-120:])))
        r = mk("fr-badre", {"t": {"files": [{"path": "a.md", "forbid_regex": ["("]}]}},
               {"a.md": "x"})
        k3 = call(r, "t")
        cases.append(("坏正则（forbid_regex）→ rc=2", k3.returncode == 2
                      and "不是合法正则" in k3.stdout, "rc=%d" % k3.returncode))
        r = mk("wc-str", {"t": {"files": [{"path": "a.md", "word_count": ["10", 20]}]}},
               {"a.md": "x"})
        k4 = call(r, "t")
        cases.append(("word_count 端点非整数 → rc=2",
                      k4.returncode == 2 and "两个整数" in k4.stdout and not crashed(k4),
                      "rc=%d %s" % (k4.returncode, crashed(k4) or k4.stdout[-120:])))
        r = mk("wc-len", {"t": {"files": [{"path": "a.md", "word_count": [10]}]}}, {"a.md": "x"})
        k5 = call(r, "t")
        cases.append(("word_count 非两元 → rc=2", k5.returncode == 2, "rc=%d" % k5.returncode))
        r = mk("path-int", {"t": {"files": [{"path": 12}]}}, {})
        k6 = call(r, "t")
        cases.append(("定位键写成数字 → rc=2 且点名定位键",
                      k6.returncode == 2 and "定位键" in k6.stdout, "rc=%d" % k6.returncode))
        r = mk("contains-int", {"t": {"files": [{"path": "a.md", "contains": ["x", 3]}]}},
               {"a.md": "x"})
        k7 = call(r, "t")
        cases.append(("contains 混入数字 → rc=2 而非 TypeError",
                      k7.returncode == 2 and "contains[1]" in k7.stdout and not crashed(k7),
                      "rc=%d %s" % (k7.returncode, crashed(k7) or k7.stdout[-120:])))
        r = mk("reqkey-int", {"t": {"json_files": [{"path": "e.json",
                                                    "require_keys_all": [7]}]}},
               {"e.json": '[{"doi": "1"}]'})
        k8 = call(r, "t")
        cases.append(("require_keys_all 混入数字 → rc=2", k8.returncode == 2,
                      "rc=%d" % k8.returncode))

    print("== manifest 形态守卫（N-2/N-3）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-38s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_parity(project: pathlib.Path) -> int:
    """与项目自带 verify 脚本逐任务比对判定（rc 必须一致）。"""
    script = project / "scripts" / "verify.py"
    if not script.exists():
        print("== parity ==\n  跳过：%s 不存在" % script)
        return 0
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
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
        p = subprocess.run([sys.executable, "-B", str(script), tid], cwd=str(project),
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
    rc |= run_gen_cli_guards()
    rc |= run_fragment_guards()
    rc |= run_registry_guards()
    rc |= run_encoding_and_path_guards()
    rc |= run_manifest_shape_guards()
    if a.project:
        rc |= run_parity(pathlib.Path(a.project).resolve())
    print("\nSELFTEST %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
