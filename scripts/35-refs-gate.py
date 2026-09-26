#!/usr/bin/env python3
"""35-refs-gate.py — 文献引用验真门控（P3 第②段的可机检面）。

规格：references/30-literature-pipeline.md §1（四索引、k 语义、三态、反伪造偏置、gate.mode）。

输入 = `22-refs.json`（列表或 {"refs": [...]}），每条至少给 title 与 year/venue 之一，可选 doi。
判定：四索引（openalex / crossref / semantic_scholar / arxiv）各出一个 unmatched 布尔，
      命中数 hits = 4 - k；verified 需 hits ≥ --min-hits 且 标题相似度 ≥0.70 且 期刊或年份一致
      且 is_retracted 为 false；任一不成立降为 suspected。
反伪造偏置：只有**按 DOI/编号查不到**才允许 suspected；**纯标题查不到一律 unresolvable**
      （真实的地方刊、非英语刊、未数字化文献长这样，不该被当成伪造嫌疑）。
退出码：0 = 通过（advisory 下非 verified 只列建议）；1 = strict 模式存在非 verified 条目，
      或 --selftest 有用例失败；2 = 用法错误（输入缺失/坏 JSON/顶层形态不合）。
只读承诺：不写任何论文项目目录；仅 --cache / --report 显式给路径时才落盘。
"""

import argparse
import difflib
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

INDICES = ("openalex", "crossref", "semantic_scholar", "arxiv")
SIM_THRESHOLD = 0.70
STATES = ("verified", "suspected", "unresolvable")


# ---------- 索引访问（生产走 HTTP；自测注入 transport，完全离线） ----------

def _http_get(url, timeout=20.0):
    req = urllib.request.Request(url, headers={"User-Agent": "paper-pipeline-refs-gate/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _norm_title(s):
    return " ".join(str(s or "").lower().replace("-", " ").split())


TRANSPORT = _http_get
"""缺省走真实 HTTP；自测与离线复放把它换成 fixture 函数（`--fixtures` / `run_selftest`）。"""


def _extract(index, doc):
    """把各家响应归一为 {title, year, venue, retracted}；取不到即 None。"""
    if not isinstance(doc, dict):
        return None
    if index == "openalex":
        return {"title": doc.get("display_name") or doc.get("title"),
                "year": doc.get("publication_year"),
                "venue": ((doc.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "retracted": bool(doc.get("is_retracted"))}
    if index == "crossref":
        item = doc.get("message") if isinstance(doc.get("message"), dict) else doc
        cnt = item.get("container-title") or []
        yr = (item.get("published-print") or item.get("published-online") or item.get("issued") or {})
        yr = (yr.get("date-parts") or [None])[0]
        return {"title": (item.get("title") or [None])[0], "year": yr,
                "venue": cnt[0] if cnt else None,
                "retracted": bool(item.get("is-retracted"))}
    if index == "semantic_scholar":
        return {"title": doc.get("title"), "year": doc.get("year"),
                "venue": doc.get("venue") or (doc.get("publicationVenue") or {}).get("name"),
                "retracted": bool(doc.get("isRetracted"))}
    if index == "arxiv":
        entry = doc["entry"] if isinstance(doc.get("entry"), dict) else doc
        return {"title": entry.get("title"), "year": entry.get("year"),
                "venue": entry.get("journal_ref") or "arXiv", "retracted": False}
    return None


def _endpoint(index, doi, title):
    """按 DOI 优先、否则按标题构造查询端点。by_doi 决定反伪造偏置分支。"""
    if doi:
        q = urllib.parse.quote(doi, safe="")
        by_doi = True
        if index == "openalex":
            return "https://api.openalex.org/works/doi:" + q, by_doi
        if index == "crossref":
            return "https://api.crossref.org/works/" + q, by_doi
        if index == "semantic_scholar":
            return "https://api.semanticscholar.org/graph/v1/paper/DOI:" + q + "?fields=title,year,venue,isRetracted", by_doi
        return "https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(doi.split("/")[-1]), by_doi
    q = urllib.parse.quote(title or "")
    by_doi = False
    if index == "openalex":
        return "https://api.openalex.org/works?search=" + q + "&per-page=1", by_doi
    if index == "crossref":
        return "https://api.crossref.org/works?query.bibliographic=" + q + "&rows=1", by_doi
    if index == "semantic_scholar":
        return ("https://api.semanticscholar.org/graph/v1/paper/search?query=" + q
                + "&limit=1&fields=title,year,venue,isRetracted"), by_doi
    return "https://export.arxiv.org/api/query?search_query=ti:" + q + "&max_results=1", by_doi


def query_index(index, doi, title, get_json=None):
    """返回 (matched, record, by_doi)。网络/解析异常一律按未命中处理，不抛给上层。"""
    get_json = get_json or TRANSPORT
    url, by_doi = _endpoint(index, doi, title)
    if not (doi or title):
        return False, None, by_doi
    try:
        raw = get_json(url)
    except Exception:
        return False, None, by_doi
    if not isinstance(raw, dict):
        return False, None, by_doi
    doc = raw
    if index == "openalex" and isinstance(raw.get("results"), list):
        doc = (raw["results"] or [None])[0]
    elif index == "crossref" and isinstance(raw.get("message"), dict):
        items = raw["message"].get("items")
        doc = {"message": items[0]} if isinstance(items, list) and items else raw
    elif index == "semantic_scholar" and isinstance(raw.get("data"), list):
        doc = (raw["data"] or [None])[0]
    rec = _extract(index, doc)
    if rec is None or not (rec.get("title") or rec.get("year")):
        return False, None, by_doi
    return True, rec, by_doi


# ---------- 判定 ----------

def title_similarity(ref_title, rec_title):
    a, b = _norm_title(ref_title), _norm_title(rec_title)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def decide(entry, per_index, min_hits=3, sim_threshold=SIM_THRESHOLD):
    """per_index = {index: (matched, record|None, by_doi)} → (state, detail)。"""
    hits = sum(1 for m, _, _ in per_index.values() if m)
    k = len(INDICES) - hits
    doi = str(entry.get("doi") or "").strip()
    recs = [r for _, r, _ in per_index.values() if r]
    sim = max([title_similarity(entry.get("title"), r.get("title")) for r in recs], default=0.0)
    venue_ok = any(_norm_title(r.get("venue")) == _norm_title(entry.get("venue")) and _norm_title(r.get("venue"))
                   for r in recs)
    year_ok = any(str(r.get("year")) == str(entry.get("year")) and entry.get("year") is not None for r in recs)
    retracted = any(bool(r.get("retracted")) for r in recs)
    detail = {"k": k, "hits": hits, "similarity": round(sim, 3), "venue_match": venue_ok,
              "year_match": year_ok, "retracted": retracted, "queried_by_doi": bool(doi)}
    if hits == 0:
        # 反伪造偏置：有 DOI/编号而四索引全查不到 → suspected；纯标题查不到 → unresolvable。
        detail["reason"] = "doi_not_found_in_any_index" if doi else "title_only_no_match"
        return ("suspected" if doi else "unresolvable"), detail
    if retracted:
        detail["reason"] = "retracted"
        return "suspected", detail
    if sim < sim_threshold:
        detail["reason"] = "title_similarity_below_threshold"
        return "suspected", detail
    if not (venue_ok or year_ok):
        detail["reason"] = "neither_venue_nor_year_matches"
        return "suspected", detail
    if hits < min_hits:
        detail["reason"] = "coverage_below_min_hits"
        return "suspected", detail
    detail["reason"] = "all_checks_passed"
    return "verified", detail


def grade_refs(refs, min_hits=3, get_json=None, cache=None):
    out = []
    for i, entry in enumerate(refs):
        doi = str(entry.get("doi") or "").strip()
        title = str(entry.get("title") or "").strip()
        per_index, cache_hit = {}, False
        key = hashlib.sha256(("%s|%s" % (doi, title)).encode("utf-8")).hexdigest()
        if cache is not None and key in cache:
            per_index, cache_hit = cache[key]["per_index"], True
            per_index = {ix: (bool(v[0]), v[1], bool(v[2])) for ix, v in per_index.items()}
        else:
            for index in INDICES:
                per_index[index] = query_index(index, doi or None, title or None, get_json=get_json)
            if cache is not None:
                cache[key] = {"per_index": {ix: [bool(m), r, bool(b)] for ix, (m, r, b) in per_index.items()}}
        state, detail = decide(entry, per_index, min_hits=min_hits)
        detail["state"] = state
        detail["from_cache"] = cache_hit
        detail["ref"] = (doi or title)[:120]
        detail["index"] = i
        out.append(detail)
    return out


# ---------- I/O ----------

def _load_json_object(path, what):
    """返回 (obj, error)。文件缺失/坏 JSON/顶层非对象 → error 非空。"""
    if not os.path.exists(path):
        return None, "%s 文件不存在：%s" % (what, path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (ValueError, OSError) as exc:
        return None, "%s 不是合法 JSON（%s）：%s" % (what, type(exc).__name__, str(exc)[:120])
    if not isinstance(data, dict):
        return None, "%s 顶层须为对象，实际为 %s" % (what, type(data).__name__)
    return data, None


def load_refs(path):
    """返回 (refs, error)。error 非空即 rc=2。"""
    if not os.path.exists(path):
        return None, "输入文件不存在：%s" % path
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (ValueError, OSError) as exc:
        return None, "输入不是合法 JSON（%s）：%s" % (type(exc).__name__, str(exc)[:120])
    if isinstance(data, dict):
        data = data.get("refs")
    if not isinstance(data, list):
        return None, "输入顶层须为列表或含 refs 列表的对象，实际为 %s" % type(data).__name__
    bad = [i for i, e in enumerate(data) if not isinstance(e, dict)]
    if bad:
        return None, "refs 第 %s 项不是对象" % bad
    return data, None


def print_report(results, mode):
    counts = {s: 0 for s in STATES}
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        line = "[%d] %-10s %-60s k=%d hits=%d sim=%.2f venue=%s year=%s retracted=%s doi=%s" % (
            r["index"], r["state"], r["ref"][:60], r["k"], r["hits"], r["similarity"],
            "Y" if r["venue_match"] else "N", "Y" if r["year_match"] else "N",
            "Y" if r["retracted"] else "N", "Y" if r["queried_by_doi"] else "N")
        if r["state"] == "verified":
            print("  PASS %s" % line)
        else:
            tag = "BLOCK" if mode == "strict" else "ADVISORY"
            print("  %s %s ← %s" % (tag, line, r["reason"]))
    print("汇总：verified=%d suspected=%d unresolvable=%d（mode=%s, 共 %d 条）"
          % (counts.get("verified", 0), counts.get("suspected", 0), counts.get("unresolvable", 0), mode, len(results)))
    if counts.get("unresolvable", 0):
        print("提示：unresolvable 不等于伪造——纯标题查不到是地方刊/非英语刊/未数字化文献的正常形态，"
              "请按 30-literature-pipeline.md §2 走人工题录核对，不得据此判死。")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="35-refs-gate.py", description="文献引用验真门控（四索引 k 汇总三态）")
    ap.add_argument("--refs", help="22-refs.json 路径")
    ap.add_argument("--min-hits", type=int, default=3, help="verified 所需最少命中索引数（缺省 3）")
    ap.add_argument("--mode", choices=("advisory", "strict"), default="advisory")
    ap.add_argument("--cache", help="可选：查询缓存 JSON 路径（只读写该显式路径）")
    ap.add_argument("--report", help="可选：把结果 JSON 写到该路径")
    ap.add_argument("--fixtures", help="可选：离线复放用 {index: 响应} JSON 路径，不联网")
    ap.add_argument("--selftest", action="store_true", help="离线自测（合成 fixture，不联网）")
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if not args.refs:
        print("用法错误：--refs 必需（或用 --selftest）", file=sys.stderr)
        return 2
    if args.fixtures:
        fx, err = _load_json_object(args.fixtures, "fixtures")
        if err:
            print("用法错误：%s" % err, file=sys.stderr)
            return 2
        globals()["TRANSPORT"] = _fixture_transport(fx, [])
    refs, err = load_refs(args.refs)
    if err:
        print("用法错误：%s" % err, file=sys.stderr)
        return 2
    cache = None
    if args.cache:
        if os.path.exists(args.cache):
            try:
                with open(args.cache, "r", encoding="utf-8-sig") as fh:
                    loaded = json.load(fh)
                cache = loaded if isinstance(loaded, dict) else {}
            except (ValueError, OSError):
                cache = {}
        else:
            cache = {}
    results = grade_refs(refs, min_hits=args.min_hits, cache=cache)
    if cache is not None:
        with open(args.cache, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
    print_report(results, args.mode)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
    if args.mode == "strict" and any(r["state"] != "verified" for r in results):
        return 1
    return 0


# ---------- 离线自测 ----------

def _fixture_transport(records, calls):
    """records: {index: 归一响应}；按 URL 前缀识别索引，并记录调用面。"""
    def get_json(url):
        for index in INDICES:
            if url.startswith({"openalex": "https://api.openalex.org",
                               "crossref": "https://api.crossref.org",
                               "semantic_scholar": "https://api.semanticscholar.org",
                               "arxiv": "https://export.arxiv.org"}[index]):
                calls.append(index)
                doc = records.get(index)
                if doc is None:
                    raise RuntimeError("fixture miss")
                return doc
        raise RuntimeError("unknown endpoint")
    return get_json


def run_selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
            print("  FAIL %s: got %r want %r" % (name, got, want))
        else:
            print("  OK   %s" % name)

    good = {"openalex": {"display_name": "Graphene Oxide Membranes for Nanofiltration",
                         "publication_year": 2019,
                         "primary_location": {"source": {"display_name": "Nature Water"}},
                         "is_retracted": False},
            "crossref": {"message": {"title": ["Graphene Oxide Membranes for Nanofiltration"],
                                     "container-title": ["Nature Water"],
                                     "published-print": {"date-parts": [[2019]]}}},
            "semantic_scholar": {"data": [{"title": "Graphene oxide membranes for nanofiltration",
                                           "year": 2019, "venue": "Nature Water", "isRetracted": False}]},
            "arxiv": {"entry": {"title": "Graphene Oxide Membranes for Nanofiltration",
                                "year": 2019, "journal_ref": "Nature Water"}}}
    entry = {"doi": "10.1038/s41545-019-0031-1", "title": "Graphene Oxide Membranes for Nanofiltration",
             "year": 2019, "venue": "Nature Water"}

    def state_of(ent, records, min_hits=3):
        calls = []
        per = {ix: query_index(ix, str(ent.get("doi") or "") or None, str(ent.get("title") or "") or None,
                              get_json=_fixture_transport(records, calls)) for ix in INDICES}
        state, detail = decide(ent, per, min_hits=min_hits)
        return state, calls, detail

    st, calls, _ = state_of(entry, good)
    check("all-four-hit -> verified", st, "verified")
    check("样本面覆盖四索引", sorted(set(calls)), sorted(INDICES))
    # AC2：--min-hits 覆盖 k 阈值后判定随动
    check("min-hits=5 同一条目降为 suspected", state_of(entry, good, min_hits=5)[0], "suspected")

    # AC3 反伪造偏置：DOI 查不到 = suspected；纯标题查不到 = unresolvable
    empty = {}
    check("doi 四索引全查不到 -> suspected", state_of(entry, empty)[0], "suspected")
    title_only = {"title": "Graphene Oxide Membranes for Nanofiltration", "year": 2019, "venue": "Nature Water"}
    check("纯标题查不到 -> unresolvable", state_of(title_only, empty)[0], "unresolvable")

    # AC4：三条判据各破坏一条 → suspected
    low_sim = json.loads(json.dumps(good))
    low_sim["openalex"]["display_name"] = "Totally Different Title About Soils"
    low_sim["crossref"] = {"message": {"title": ["Totally Different Title About Soils"],
                                       "container-title": ["Nature Water"],
                                       "published-print": {"date-parts": [[2019]]}}}
    low_sim["semantic_scholar"] = {"data": [{"title": "Totally Different Title About Soils", "year": 2019,
                                             "venue": "Nature Water", "isRetracted": False}]}
    low_sim["arxiv"] = {"entry": {"title": "Totally Different Title About Soils", "year": 2019,
                                  "journal_ref": "Nature Water"}}
    check("相似度 <0.70 -> suspected", state_of(entry, low_sim)[0], "suspected")

    no_ctx = json.loads(json.dumps(good))
    no_ctx["openalex"]["primary_location"]["source"]["display_name"] = "Journal of Fictional Studies"
    no_ctx["openalex"]["publication_year"] = 1901
    no_ctx["crossref"]["message"]["container-title"] = ["Journal of Fictional Studies"]
    no_ctx["crossref"]["message"]["published-print"] = {"date-parts": [[1901]]}
    no_ctx["semantic_scholar"]["data"][0]["venue"] = "Journal of Fictional Studies"
    no_ctx["semantic_scholar"]["data"][0]["year"] = 1901
    no_ctx["arxiv"]["entry"]["journal_ref"] = "Journal of Fictional Studies"
    no_ctx["arxiv"]["entry"]["year"] = 1901
    check("期刊与年份均不一致 -> suspected", state_of(entry, no_ctx)[0], "suspected")

    retracted = json.loads(json.dumps(good))
    retracted["openalex"]["is_retracted"] = True
    check("is_retracted=true -> suspected", state_of(entry, retracted)[0], "suspected")

    # AC1/AC5：gate.mode 退出码（走 CLI 全链路，TRANSPORT 换成 fixture → 不联网）
    bogus = {"doi": "10.0000/not-a-real-record", "title": "Zzzz Nonexistent Paper Qqqq",
             "year": 1999, "venue": "Nowhere"}
    saved_transport = globals()["TRANSPORT"]
    globals()["TRANSPORT"] = _fixture_transport(good, [])
    refs_file = os.path.join(os.environ.get("TEMP", "/tmp"), "rg-selftest-refs.json")
    report_file = os.path.join(os.environ.get("TEMP", "/tmp"), "rg-selftest-report.json")
    with open(refs_file, "w", encoding="utf-8") as fh:
        json.dump([entry, bogus], fh, ensure_ascii=False)
    saved = sys.argv
    try:
        rc_adv = main(["--refs", refs_file, "--mode", "advisory", "--report", report_file])
        rc_str = main(["--refs", refs_file, "--mode", "strict", "--report", report_file])
    finally:
        sys.argv = saved
        globals()["TRANSPORT"] = saved_transport
    check("advisory 下存在非 verified 仍 rc=0", rc_adv, 0)
    check("strict 下同一样本 rc!=0", rc_str != 0, True)
    # 反向对照：全部 verified 时 strict 必须变绿（否则该门禁是空转）
    saved_transport = globals()["TRANSPORT"]
    globals()["TRANSPORT"] = _fixture_transport(good, [])
    with open(refs_file, "w", encoding="utf-8") as fh:
        json.dump([entry], fh, ensure_ascii=False)
    rc_green = main(["--refs", refs_file, "--mode", "strict"])
    globals()["TRANSPORT"] = saved_transport
    check("全 verified 时 strict rc=0（反向对照）", rc_green, 0)
    rc_missing = main([])
    rc_nofile = main(["--refs", refs_file + ".nope"])
    with open(refs_file, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    rc_badjson = main(["--refs", refs_file])
    with open(refs_file, "w", encoding="utf-8") as fh:
        json.dump("scalar", fh)
    rc_scalar = main(["--refs", refs_file])
    check("缺 --refs -> rc=2", rc_missing, 2)
    check("不存在的 --refs -> rc=2", rc_nofile, 2)
    check("坏 JSON -> rc=2", rc_badjson, 2)
    check("顶层非列表 -> rc=2", rc_scalar, 2)
    # 缓存面：二次运行不再查（离线且幂等）
    cache_file = os.path.join(os.environ.get("TEMP", "/tmp"), "rg-selftest-cache.json")
    for p in (cache_file,):
        try:
            os.remove(p)
        except OSError:
            pass
    calls_box = []
    saved_transport = globals()["TRANSPORT"]
    globals()["TRANSPORT"] = _fixture_transport(good, calls_box)
    with open(refs_file, "w", encoding="utf-8") as fh:
        json.dump([entry], fh, ensure_ascii=False)
    main(["--refs", refs_file, "--cache", cache_file])
    first = len(calls_box)
    main(["--refs", refs_file, "--cache", cache_file])
    second = len(calls_box) - first
    globals()["TRANSPORT"] = saved_transport
    check("缓存首跑查四索引", first, 4)
    check("缓存二跑零查询（幂等）", second, 0)
    for p in (refs_file, report_file, cache_file):
        try:
            os.remove(p)
        except OSError:
            pass

    if fails:
        print("REFS-GATE SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("REFS-GATE SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
