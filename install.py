#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install.py — paper-pipeline 技能安装器（开发/发布分离的装配通道）。

形式：仓根单文件脚本，仅标准库；源 = 本脚本所在的仓库工作副本或其全新 clone。
发布面以仓根 `MANIFEST.in` 纯白名单为单一真源：清单内 = 发布，清单外 = 开发层
（.orchd/、build/、reports/、docs/、scripts/76 号本仓自检等物理上进不了安装流）。

用法：
    python install.py <target> --mode skill                  # 整套发布面装进宿主技能目录
    python install.py <target> --mode project --profile <名>  # 判据基座 vendor 进论文项目
    python install.py <target> ... --cleanup                 # 安装成功后删除源（仅干净 clone）
    python install.py --selftest                             # 离线自测（临时目录，用毕即删）

退出码（conventions §3）：0 = 通过；1 = 判据命中/安装失败；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.in"
DEV_ABSENT = (".orchd", "build", "reports", "docs", ".gitignore",
              "scripts/76-doc-refs-selftest.py")          # 开发层，装配后必须缺席


def die(msg: str) -> None:
    print("ERROR: %s" % msg)
    sys.exit(2)


def read_manifest() -> list:
    """解析纯白名单清单：只支持 `include <路径>` 与 # 注释；未知指令 = 用法错。"""
    if not MANIFEST.exists():
        die("MANIFEST.in 不在盘（%s）——发布面缺单一真源" % MANIFEST)
    out = []
    for i, line in enumerate(MANIFEST.read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("include "):
            out.append(s[len("include "):].strip())
        else:
            die("MANIFEST.in:%d 非白名单指令（只支持 include <路径> 与 # 注释）：%s" % (i, s[:60]))
    if not out:
        die("MANIFEST.in 无任何 include 条目")
    return out


def _git(args: list) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(HERE)] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def provenance(mode: str, files: int) -> dict:
    commit = _git(["rev-parse", "--short", "HEAD"]) or "unknown"
    describe = _git(["describe", "--tags", "--always"]) or commit
    status = _git(["status", "--porcelain"])
    return {
        "skill": "paper-pipeline",
        "version": describe,
        "source": str(HERE),
        "commit": commit,
        "source_dirty": bool(status),
        "mode": mode,
        "files": files,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def install_skill(target: Path, entries: list) -> None:
    for rel in entries:
        src = HERE / rel
        if not src.is_file():
            sys.exit("ERROR: 清单内路径不在盘（发布面破损，先修 MANIFEST）：%s" % rel)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def install_project(target: Path, profile: str | None) -> None:
    """判据基座 vendor：70-verify.py + manifest 模板 → <target>/70-tools/（新项目规范名）。"""
    tools = target / "70-tools"
    tools.mkdir(parents=True, exist_ok=True)
    for src_rel, dst_name in (("scripts/70-verify.py", "70-verify.py"),
                              ("assets/10-verify-manifest.template.json", "71-verify-manifest.template.json")):
        src = HERE / src_rel
        if not src.is_file():
            sys.exit("ERROR: 源缺失（发布面破损）：%s" % src_rel)
        shutil.copy2(src, tools / dst_name)
    if profile:
        src = HERE / "profiles" / profile
        if not src.is_file():
            die("profiles/%s 不在盘（可用档见 profiles/ 目录）" % profile)
        dst = tools / "profiles" / profile
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if not (target / ".orchd").exists():
        print("hint  目标项目未安装 orchd 引擎——请先按 orchd-core 的安装器接入"
              "（本安装器不代装引擎，单一职责）。")


def verify_skill_install(target: Path, entries: list) -> list:
    """装配完整性断言：清单逐项在盘且字节一致；开发层缺席。"""
    bad = []
    for rel in entries:
        dst = target / rel
        if not dst.is_file():
            bad.append("清单项缺失：%s" % rel)
        elif dst.read_bytes() != (HERE / rel).read_bytes():
            bad.append("清单项内容不一致：%s" % rel)
    for rel in DEV_ABSENT:
        if (target / rel).exists():
            bad.append("开发层文件泄漏进发布面：%s" % rel)
    return bad


def run_smoke(target: Path, tmp: Path) -> None:
    """副本内冒烟：生成器对任一发布 profile 生成 rc=0；判据基座 --schema rc=0。"""
    gen = target / "scripts" / "30-gen-proposals.py"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                        "--profile", "profiles/10-materials-chemistry.yaml",
                        "--out", str(tmp / "smoke-out")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        sys.exit("ERROR: 副本内生成器冒烟失败 rc=%d\n%s" % (r.returncode, (r.stdout + r.stderr)[-400:]))
    ver = target / "scripts" / "70-verify.py"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(ver), "--schema"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        sys.exit("ERROR: 副本内判据基座 --schema 冒烟失败 rc=%d\n%s" % (r.returncode, (r.stdout + r.stderr)[-400:]))


def selftest() -> int:
    """离线自测：临时目录双模式装配 + 完整性断言 + 副本冒烟 + --cleanup 拒绝护栏。"""
    import tempfile
    entries = read_manifest()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        target = tmp / "skill-copy"
        target.mkdir()
        install_skill(target, entries)
        bad = verify_skill_install(target, entries)
        failures += bad
        print("  skill 模式装配（%d 文件，清单逐项一致 + 开发层缺席）  %s"
              % (len(entries), "OK" if not bad else "MISMATCH %s" % bad[:2]))
        if not bad:
            run_smoke(target, tmp)
            print("  副本内冒烟（30 号生成 rc=0 / 70 号 --schema rc=0）  OK")
        # project 模式
        ptarget = tmp / "paper-project"
        ptarget.mkdir()
        install_project(ptarget, "10-wbpu-kh550.yaml")
        vbase = ptarget / "70-tools" / "70-verify.py"
        ok_p = vbase.is_file() and (ptarget / "70-tools" / "profiles" / "10-wbpu-kh550.yaml").is_file()
        if ok_p:
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(vbase), "--schema"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            ok_p = r.returncode == 0
        print("  project 模式装配（70-tools 基座 + profile 快照 + --schema）  %s"
              % ("OK" if ok_p else "MISMATCH"))
        if not ok_p:
            failures.append("project 模式装配失败")
        # 幂等：同一目标重复安装仍完整一致
        install_skill(target, entries)
        bad2 = verify_skill_install(target, entries)
        print("  幂等重装（第二次装配后完整性复验）  %s" % ("OK" if not bad2 else "MISMATCH"))
        if bad2:
            failures += bad2
        # --cleanup 护栏：源=本仓（非干净 clone）必须拒绝
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(target), "--mode", "skill", "--cleanup"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        refused = r.returncode != 0 and "cleanup" in ((r.stdout or "") + (r.stderr or "")).lower()
        print("  --cleanup 护栏（非干净 clone 源拒绝自删）  %s" % ("OK" if refused else "MISMATCH"))
        if not refused:
            failures.append("cleanup 护栏未生效")
    if failures:
        print("SELFTEST FAIL（%d）：%s" % (len(failures), failures[:4]))
        return 1
    print("SELFTEST PASS  双模式装配 + 冒烟 + 幂等 + cleanup 护栏")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="paper-pipeline 技能安装器")
    ap.add_argument("target", nargs="?", help="安装目标目录")
    ap.add_argument("--mode", choices=("skill", "project"), default="skill")
    ap.add_argument("--profile", help="project 模式：随基座一起快照的领域档文件名（profiles/ 下）")
    ap.add_argument("--cleanup", action="store_true",
                    help="安装成功后删除源目录（仅限干净 clone：源工作副本有未提交内容即拒绝）")
    ap.add_argument("--selftest", action="store_true", help="离线自测（临时目录，用毕即删）")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.target:
        die("缺少 <target>（或用 --selftest）")
    target = Path(a.target).resolve()
    if target == HERE:
        die("target 不得等于源目录（%s）" % HERE)
    entries = read_manifest()

    if a.mode == "skill":
        install_skill(target, entries)
        bad = verify_skill_install(target, entries)
        if bad:
            sys.exit("ERROR: 装配完整性断言失败（已停止，不触发 cleanup）：\n  " + "\n  ".join(bad[:6]))
        n = len(entries)
    else:
        install_project(target, a.profile)
        n = 2 + (1 if a.profile else 0)

    prov = provenance(a.mode, n)
    (target / "PROVENANCE.json").write_text(
        json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("installed: %d files -> %s (%s; version %s)"
          % (n, target, a.mode, prov["version"]))

    if a.cleanup:
        status = _git(["status", "--porcelain"])
        if status:
            sys.exit("ERROR: --cleanup 已拒绝：源目录存在未提交内容（仅干净 clone 可自删）。"
                     "本次安装不受影响。")
        shutil.rmtree(HERE, ignore_errors=False)
        print("cleanup: 源 clone 已删除")
    return 0


if __name__ == "__main__":
    sys.exit(main())
