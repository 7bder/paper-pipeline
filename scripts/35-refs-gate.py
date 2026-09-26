#!/usr/bin/env python3
"""35-refs-gate.py — 文献引用验真门控（P3 第②段的可机检面）。

规格：references/30-literature-pipeline.md §1（四索引、k 语义、三态、反伪造偏置、gate.mode）。

输入 = `22-refs.json`（列表或 {"refs": [...]}），每条给 doi 或 title（可选 year/venue/arxiv_id）。
判定：四索引（openalex / crossref / semantic_scholar / arxiv）各出一个**源状态**
      matched / unmatched / unavailable / not_applicable；`answered` = 给出有效应答的索引数，
      `k = answered - hits`；门槛 `need = min(--min-hits, pool)`（pool = 四索引减去 --skip-indices）：
      answered < need → unresolvable（应答面不足，判不了）；hits < need → suspected（覆盖不足）；
      再过标题相似度（命中索引多数同意：同意数*2 >= 有标题命中数）、期刊或年份一致、非撤稿三关才 verified。
为什么要有 unavailable 与 not_applicable：**"服务说没有"（404/零条目）、"服务没回答"（429 限流、
      5xx、406 拒收、解码失败）、"该索引对这条文献结构性无从回答"（非 arXiv DOI 之于 arXiv）
      是三回事**。把后两类当"没有"计进 k，会让真文献成片降档：实测免 key 的 Semantic Scholar 连发
      两请求即 429、对个别真 DOI 直接 404，arXiv 对畸形 id_list 与部分检索式返回 406（与 UA 无关，
      同一 URL 换浏览器 UA 结果一致），且其正常响应是 Atom XML 而非 JSON。
反伪造偏置：只有**按 DOI/编号查不到**才允许 suspected；**纯标题查不到一律 unresolvable**
      （真实的地方刊、非英语刊、未数字化文献长这样，不该被当成伪造嫌疑）；
      有效应答数低于 --min-answered 时一律 unresolvable（无据可判，不等于判死）。
标题回退：按 DOI 的命中数凑不齐门槛时，对回答"没有"的索引再按标题问一次（实测 arXiv 自家 DOI
      在 OpenAlex/Crossref/S2 结构性 404，只有 arXiv 认——不回退则真文献必判可疑）。
      回退命中的索引记在 `title_fallback` 并随缓存回放，报告行以 `title-fallback=` 标明来路。
审计面：每条结果的 `index_status` 记 `{索引: 源状态:原因}`（如 `semantic_scholar:unavailable:http_429`），
      控制台把 unavailable 连原因一起上屏——限流、5xx、解码失败的处置各不相同，不能只报索引名。
      走过标题回退的索引再缀 `<- doi轮 源状态:原因`，DOI 为何没命中这件事不得被回退结果抹掉。
退出码：0 = 通过（advisory 下非 verified 只列建议）；1 = strict 模式存在非 verified 条目，
      或 --selftest 有用例失败；2 = 用法错误（输入缺失/坏 JSON/顶层形态不合/非法 --skip-indices）。
只读承诺：不写任何论文项目目录；仅 --cache / --report 显式给路径时才落盘。
自测口径：`--selftest` 与 `--fixtures` 在 **fetch 层**注入原始字节（Crossref 双层 envelope、
      S2 404/429 报文、arXiv Atom XML 原文），`_decode` 以下全走真实代码；节流与退避在 `_fetch_raw`
      内部，故离线路径不产生 sleep。
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

INDICES = ("openalex", "crossref", "semantic_scholar", "arxiv")
SIM_THRESHOLD = 0.70
STATES = ("verified", "suspected", "unresolvable")
SOURCES = ("matched", "unmatched", "unavailable")
NOT_APPLICABLE = "not_applicable"
MIN_ANSWERED = 2
MIN_HITS = 2
MIN_INTERVAL_S = 1.0
RETRIES = 2
BACKOFF_S = 2.0
THROTTLE_HOSTS = ("api.semanticscholar.org", "api.crossref.org", "api.openalex.org", "export.arxiv.org")
# arXiv 只出 Atom XML（实测 content-type），其余只出 JSON；Accept 一并声明，避免服务端按内容协商拒收。
HEADERS = {
    "User-Agent": "paper-pipeline-refs-gate/1.0 (+https://github.com/7bder/paper-pipeline)",
    "Accept": "application/json, application/atom+xml, text/xml, */*",
}
RETRY_STATUS = (408, 425, 429, 406, 500, 502, 503, 504)
PREFIX = {
    "openalex": "https://api.openalex.org",
    "crossref": "https://api.crossref.org",
    "semantic_scholar": "https://api.semanticscholar.org",
    "arxiv": "https://export.arxiv.org",
}
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class TransportError(Exception):
    """网络层失败（连接/超时）。与"索引回答了但没有这条文献"严格区分，故独立成类型。"""

    def __init__(self, kind, detail=""):
        super().__init__("%s:%s" % (kind, detail[:80]))
        self.kind = kind
        self.detail = detail


# ---------- 取数：fetch 拿原始字节，decode 按索引方言解析 ----------

_LAST_CALL = {}


def _throttle(host):
    now = time.time()
    if host in THROTTLE_HOSTS:
        gap = now - _LAST_CALL.get(host, 0.0)
        if gap < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - gap)
    _LAST_CALL[host] = time.time()


def _fetch_raw(url, retries=None, opener=None):
    """返回 (status, body_bytes, content_type)；传输层失败抛 TransportError。

    4xx/5xx 不抛：404 是"库里没有"的有效应答，429/406/5xx 是"没回答"——两者必须由判据层分开处置。
    `opener` 缺省为 urllib.request.urlopen，自测注入假 opener 以覆盖退避分支（不碰真实网络）。
    """
    retries = RETRIES if retries is None else retries
    opener = opener or urllib.request.urlopen
    host = urllib.parse.urlsplit(url).netloc
    attempt = 0
    while True:
        _throttle(host)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = opener(req, timeout=20)
            try:
                return resp.status, resp.read(), (resp.headers.get("Content-Type") or "")
            finally:
                close = getattr(resp, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read() or b""
            except Exception:
                body = b""
            ctype = (exc.headers.get("Content-Type") or "") if exc.headers else ""
            if exc.code in RETRY_STATUS and attempt < retries:
                attempt += 1
                time.sleep(BACKOFF_S * attempt)
                continue
            return exc.code, body, ctype
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError("network", "%s: %s" % (type(exc).__name__, str(exc)[:100]))


NO_RECORD = object()


def _decode(index, status, body, ctype):
    """(obj, reason)。obj=None → 索引没给出可读应答（unavailable）；NO_RECORD → 明确没有这条（unmatched）。"""
    if status == 404:
        return NO_RECORD, "not_found_404"
    if status != 200:
        return None, "http_%d" % status
    if not body:
        return None, "empty_body"
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    # 方言按索引声明，不按正文首字符猜：arXiv 只出 Atom XML（实测），其余只出 JSON。
    # 猜错的方向性后果不对称——把 HTML 拦截页当 XML 解析会得出"库里没有"（unmatched），
    # 而真相是"没回答"（unavailable），二者必须分开。
    if index == "arxiv" or "xml" in ctype.lower():
        parsed = _parse_atom(text)
        if parsed is not None:
            return parsed, "atom_ok"
        return None, "atom_parse_error"
    try:
        return json.loads(text), "json_ok"
    except ValueError:
        return None, "json_parse_error"


def _parse_atom(text):
    """arXiv API 只出 Atom XML（实测 content-type=application/atom+xml），归一为 {"entry": {...}}。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    entries = [e for e in root.findall(ATOM + "entry") if e.find(ATOM + "title") is not None]
    if not entries:
        return {"entry": None}
    entry = entries[0]
    published = entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated") or ""
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
    return {"entry": {"title": " ".join((entry.findtext(ATOM + "title") or "").split()),
                      "year": year,
                      "journal_ref": entry.findtext(ARXIV_NS + "journal_ref"),
                      "id": entry.findtext(ATOM + "id")}}


def _norm_title(s):
    return " ".join(str(s or "").lower().replace("-", " ").split())


FETCH = _fetch_raw
"""缺省走真实 HTTP；自测与离线复放在这一层注入 fixture（`--fixtures` / `run_selftest`）。"""


def _crossref_year(item):
    """Crossref 的 date-parts 是**列表的列表**（[[2015,5,28]]）→ 取内层首元素为年份。

    旧写法只取外层 [0]，得到 [2015,5,28]，与题录年份 "2015" 永不相等（实测），
    于是 Crossref 对 year_ok 永不贡献。
    """
    for key in ("published-print", "published-online", "issued"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if not (isinstance(parts, list) and parts):
            continue
        inner = parts[0]
        if isinstance(inner, list) and inner:
            inner = inner[0]
        if isinstance(inner, bool):
            continue
        if isinstance(inner, int):
            return inner
        if isinstance(inner, str) and inner[:4].isdigit():
            return int(inner[:4])
    return None


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
        return {"title": (item.get("title") or [None])[0],
                "year": _crossref_year(item),
                "venue": cnt[0] if cnt else None,
                "retracted": bool(item.get("is-retracted"))}
    if index == "semantic_scholar":
        return {"title": doc.get("title"), "year": doc.get("year"),
                "venue": doc.get("venue") or (doc.get("publicationVenue") or {}).get("name"),
                "retracted": bool(doc.get("isRetracted"))}
    if index == "arxiv":
        entry = doc.get("entry")
        if not isinstance(entry, dict):
            return None
        return {"title": entry.get("title"), "year": entry.get("year"),
                "venue": entry.get("journal_ref") or "arXiv", "retracted": False}
    return None


_ARXIV_NEW_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?$")
_ARXIV_SLASH_ID_RE = re.compile(
    r"^[A-Za-z][A-Za-z.\-]*(?:\.[A-Za-z]{2})?/(?:[0-9]{7}|[0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?$")
"""旧式/带类目 arXiv id（quant-ph/9601029、cs.CL/0708.0384、math.GT/0309136）。
按形态匹配而非类目白名单——白名单漏 `quant-ph` 这类带连字符的类目，实测把真 id 判成非 arXiv。"""


def _arxiv_id(raw):
    """把各种写法收成 arXiv API 认的 id_list 形态；不是 arXiv id 就返回 None。

    实测：`id_list=arXiv.1706.03762`（10.48550 DOI 的原样后缀）与 `quant-ph/9601029`（带斜杠的旧式 id）
    都被 arXiv 直接 406 拒收，而 `1706.03762` 返回 200——所以必须规范化，而不是把 DOI 尾巴塞进去。
    """
    s = str(raw or "").strip()
    if not s:
        return None
    low = s.lower()
    for pre in ("arxiv:", "arxiv.", "arxiv/"):
        if low.startswith(pre):
            s, low = s[len(pre):], s[len(pre):].lower()
    if low.startswith("10.48550/"):
        tail = s[len("10.48550/"):]
        for pre in ("arXiv.", "arXiv:", "arxiv.", "arxiv/"):
            if tail.lower().startswith(pre):
                tail = tail[len(pre):]
                break
        s = tail
    if _ARXIV_NEW_ID_RE.match(s):
        return s
    if "/" in s and _ARXIV_SLASH_ID_RE.match(s):
        return urllib.parse.quote(s, safe="")
    return None


def _arxiv_phrase(title):
    """arXiv 标题检索式：实测只有 `%22短语%22` + `%20` 分隔被接受，`+` 分隔与裸多词一律 406。"""
    words = [w for w in _norm_title(title).split() if w]
    if not words:
        return None
    return "%22" + "%20".join(urllib.parse.quote(w, safe="") for w in words[:12]) + "%22"


def _endpoint(index, doi, title, arxiv_id=None):
    """按 DOI 优先、否则按标题构造查询端点，返回 (url|None, by_doi, why_not_applicable)。

    url=None 表示该索引对这条文献**结构性无从回答**（既不是"没回答"也不是"没有"），
    必须与 unavailable 分开计：它不进 k 的分母，也不该被当成一次失败。
    arXiv 只认自家 id——实测把非 arXiv DOI 的后缀塞进 id_list 直接 406（请求被拒，不是零结果）。
    """
    if doi:
        q = urllib.parse.quote(doi, safe="")
        by_doi = True
        if index == "openalex":
            return PREFIX["openalex"] + "/works/doi:" + q, by_doi, ""
        if index == "crossref":
            return PREFIX["crossref"] + "/works/" + q, by_doi, ""
        if index == "semantic_scholar":
            return (PREFIX["semantic_scholar"] + "/graph/v1/paper/DOI:" + q
                    + "?fields=title,year,venue,isRetracted"), by_doi, ""
        aid = _arxiv_id(arxiv_id) or _arxiv_id(doi)
        if not aid:
            return None, by_doi, "no_arxiv_identifier"
        return PREFIX["arxiv"] + "/api/query?id_list=" + aid, by_doi, ""
    q = urllib.parse.quote_plus(title or "")
    by_doi = False
    if not q:
        return None, by_doi, "no_query_key"
    if index == "openalex":
        return PREFIX["openalex"] + "/works?search=" + q + "&per-page=1", by_doi, ""
    if index == "crossref":
        return PREFIX["crossref"] + "/works?query.bibliographic=" + q + "&rows=1", by_doi, ""
    if index == "semantic_scholar":
        return (PREFIX["semantic_scholar"] + "/graph/v1/paper/search?query=" + q
                + "&limit=1&fields=title,year,venue,isRetracted"), by_doi, ""
    phrase = _arxiv_phrase(title)
    if not phrase:
        return None, by_doi, "no_query_key"
    return PREFIX["arxiv"] + "/api/query?search_query=ti:" + phrase + "&max_results=1", by_doi, ""


def _unwrap(index, raw):
    """检索式响应是列表 → 收成单条候选；DOI 直查的单对象响应原样返回。"""
    if not isinstance(raw, dict):
        return None
    if index == "openalex":
        if isinstance(raw.get("results"), list):
            return (raw["results"] or [None])[0]
        return raw
    if index == "crossref":
        msg = raw.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("items"), list):
            return {"message": (msg["items"] or [None])[0]}
        return raw
    if index == "semantic_scholar":
        if isinstance(raw.get("data"), list):
            return (raw["data"] or [None])[0]
        return raw
    return raw


def query_index(index, doi, title, fetch=None, arxiv_id=None):
    """返回 (source, record|None, by_doi, reason)，source ∈ SOURCES + NOT_APPLICABLE。异常收敛为 unavailable。"""
    fetch = fetch or FETCH
    url, by_doi, why = _endpoint(index, doi, title, arxiv_id=arxiv_id)
    if url is None:
        return NOT_APPLICABLE, None, by_doi, why
    try:
        status, body, ctype = fetch(url)
    except TransportError as exc:
        return "unavailable", None, by_doi, "transport_" + exc.kind
    obj, reason = _decode(index, status, body, ctype)
    if obj is None:
        return "unavailable", None, by_doi, reason
    if obj is NO_RECORD:
        return "unmatched", None, by_doi, reason
    rec = _extract(index, _unwrap(index, obj))
    if rec is None or not (rec.get("title") or rec.get("year")):
        return "unmatched", None, by_doi, "no_record"
    return "matched", rec, by_doi, "ok"


# ---------- 判定 ----------

def title_similarity(ref_title, rec_title):
    a, b = _norm_title(ref_title), _norm_title(rec_title)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def decide(entry, per_index, min_hits=MIN_HITS, min_answered=MIN_ANSWERED, skipped=()):
    """per_index = {index: (source, record|None, by_doi, reason)} → (state, detail)。

    四个分母必须分清，混了就会把真文献判成可疑：
      pool        = INDICES 去掉 --skip-indices 人工摘除者；
      applicable  = pool 中对这条文献**结构性可答**者（排除 not_applicable，如非 arXiv DOI 之于 arXiv）；
      answered    = applicable 中真正给出可读应答者（排除 unavailable：429/5xx/解码失败）；
      hits        = answered 中 matched 者。k = answered - hits，只在 answered 上计。
    门槛 need = min(--min-hits, pool)：answered < need → unresolvable（应答面不足，判不了）；
    hits < need → suspected（应答够了但覆盖不足，即规格里的"覆盖率噪音"）。
    """
    skipped = tuple(skipped or ())
    applicable, answered, unavailable, not_applicable = [], [], [], []
    index_status = {}
    for ix in INDICES:
        t = per_index.get(ix) or (NOT_APPLICABLE, None, False, "missing")
        index_status[ix] = "%s:%s" % (t[0], t[3])
        if ix in skipped:
            index_status[ix] = "skipped"
            continue
        source = t[0]
        if source == NOT_APPLICABLE:
            not_applicable.append(ix)
        elif source == "unavailable":
            unavailable.append(ix)
        else:
            applicable.append(ix)
            answered.append(ix)
    hits = sum(1 for ix in answered if per_index[ix][0] == "matched")
    k = len(answered) - hits
    pool = len(INDICES) - len(skipped)
    need = min(min_hits, pool)
    doi = str(entry.get("doi") or "").strip()
    recs = [per_index[ix][1] for ix in answered if per_index[ix][1]]
    sims = [title_similarity(entry.get("title"), r.get("title")) for r in recs if r.get("title")]
    sim = max(sims, default=0.0)
    # 标题判据按"多数索引一致同意"取：单索引检索式跑偏（DOI 命中的是另一篇）时，
    # 只要有一个索引兜住就放行等于没有判据；反之只允许一家跑偏，避免字幕/大小写差异误杀。
    agree = sum(1 for s in sims if s >= SIM_THRESHOLD)
    sim_ok = bool(sims) and agree * 2 >= len(sims)
    venue_ok = any(_norm_title(r.get("venue")) == _norm_title(entry.get("venue")) and _norm_title(r.get("venue"))
                   for r in recs)
    year_ok = any(str(r.get("year")) == str(entry.get("year")) and entry.get("year") is not None for r in recs)
    retracted = any(bool(r.get("retracted")) for r in recs)
    detail = {"answered": len(answered), "applicable": len(applicable), "need": need,
              "k": k, "hits": hits, "similarity": round(sim, 3),
              "similarity_agree": "%d/%d" % (agree, len(sims)),
              "venue_match": venue_ok, "year_match": year_ok, "retracted": retracted,
              "queried_by_doi": bool(doi), "unavailable": unavailable,
              "not_applicable": not_applicable, "skipped": list(skipped),
              "index_status": index_status,
              "degraded": bool(unavailable or not_applicable or skipped)}
    if len(answered) < max(1, min_answered):
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits == 0:
        # 反伪造偏置：有 DOI/编号而有效应答的索引一致说"没有" → suspected；纯标题查不到 → unresolvable。
        detail["reason"] = "doi_not_found_in_any_index" if doi else "title_only_no_match"
        return ("suspected" if doi else "unresolvable"), detail
    if retracted:
        detail["reason"] = "retracted"
        return "suspected", detail
    if not sim_ok:
        detail["reason"] = "title_similarity_below_threshold"
        return "suspected", detail
    if not (venue_ok or year_ok):
        detail["reason"] = "neither_venue_nor_year_matches"
        return "suspected", detail
    if len(answered) < need:
        # 应答面本身凑不齐 need 票：判不了，不是文献可疑（真网络下最常见：S2 限流 + arXiv 对非预印本不适用）。
        # 必须先于命中数判据——否则 answered < need 时 hits 必然也 < need，会被误降成 suspected。
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits < need:
        detail["reason"] = "coverage_below_min_hits"
        return "suspected", detail
    detail["reason"] = "all_checks_passed"
    return "verified", detail


def grade_refs(refs, min_hits=MIN_HITS, fetch=None, cache=None, min_answered=MIN_ANSWERED, skipped=()):
    out = []
    for i, entry in enumerate(refs):
        doi = str(entry.get("doi") or "").strip()
        title = str(entry.get("title") or "").strip()
        arxiv_id = str(entry.get("arxiv_id") or entry.get("arxivId") or "").strip()
        per_index, cache_hit = {}, False
        fell_back, doi_round = [], {}
        key = hashlib.sha256(("%s|%s" % (doi, title)).encode("utf-8")).hexdigest()
        cached = cache.get(key) if cache is not None else None
        if isinstance(cached, dict) and isinstance(cached.get("per_index"), dict):
            per_index = {ix: (str(v[0]), v[1], bool(v[2]), str(v[3]) if len(v) > 3 else "cache")
                         for ix, v in cached["per_index"].items()
                         if isinstance(v, (list, tuple)) and v
                         and str(v[0]) in SOURCES + (NOT_APPLICABLE,)}
            cache_hit = len(per_index) == len(INDICES)
            # 回退结论随缓存一起回放：缓存里已是"DOI + 标题都问过"的合并结果，
            # 二跑若再回退一次就会破掉"缓存零查询"的承诺。
            if cache_hit:
                fell_back = [str(x) for x in (cached.get("title_fallback") or [])]
                doi_round = {str(k): str(v) for k, v in (cached.get("doi_round") or {}).items()}
        if not cache_hit:
            per_index = {index: query_index(index, doi or None, title or None, fetch=fetch,
                                            arxiv_id=arxiv_id or None) for index in INDICES}
            need = min(min_hits, len(INDICES) - len(tuple(skipped or ())))
            if doi and title and sum(1 for v in per_index.values() if v[0] == "matched") < need:
                # DOI 查不到 ≠ 文献不存在：DOI 可能是 arXiv 自家 DOI（三家 JSON API 结构上无收录，
                # 实测正是这条形状）、注册有误、或新注册尚未索引。
                # 只在「按 DOI 的命中数已不足以放行」时才补问标题，且只补问回答"没有"的索引——
                # 真文献少付一轮请求，伪造条目多付一轮（这一轮本身就是判据）。
                for ix in INDICES:
                    if per_index[ix][0] != "unmatched":
                        continue
                    doi_round[ix] = "%s:%s" % (per_index[ix][0], per_index[ix][3])
                    alt = query_index(ix, None, title, fetch=fetch)
                    if alt[0] == "matched":
                        per_index[ix] = alt
                        fell_back.append(ix)
            if cache is not None:
                cache[key] = {"per_index": {ix: [st, r, bool(b), why]
                                            for ix, (st, r, b, why) in per_index.items()},
                              "title_fallback": list(fell_back), "doi_round": dict(doi_round)}
        state, detail = decide(entry, per_index, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
        detail["state"] = state
        detail["from_cache"] = cache_hit
        detail["title_fallback"] = fell_back
        # 回退会把 DOI 轮的结果覆盖掉，但"DOI 直查为何没命中"恰恰是判伪造的关键证据（实测见过
        # 真 DOI 因网络抖动记 transport_network、也见过臆造 DOI 记 not_found_404）——留在状态串里。
        for ix, prev in sorted(doi_round.items()):
            if ix in detail["index_status"]:
                detail["index_status"][ix] += " <- doi轮 " + prev
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


def _note_unavailable(r):
    """把 unavailable 渲染成 `unavail=crossref:http_429`：原因必须跟着上屏——429 该稍后再跑、
    5xx 该换时段、解码失败该查是不是被网关拦了，三种处置不同。"""
    st = r.get("index_status") or {}
    return "unavail=" + ",".join("%s:%s" % (ix, str(st.get(ix, "unavailable:?")).split(":", 1)[-1])
                                 for ix in r["unavailable"])


def print_report(results, mode, skipped=()):
    counts = {s: 0 for s in STATES}
    degraded = unavailable_total = 0
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        degraded += 1 if r.get("degraded") else 0
        unavailable_total += len(r.get("unavailable") or [])
        line = ("[%d] %-10s %-56s hits=%d/%d need=%d k=%d sim=%.2f(%s) venue=%s year=%s retr=%s doi=%s"
                % (r["index"], r["state"], r["ref"][:56], r["hits"], r["answered"], r.get("need", 0),
                   r["k"], r["similarity"], r.get("similarity_agree", "-"),
                   "Y" if r["venue_match"] else "N", "Y" if r["year_match"] else "N",
                   "Y" if r["retracted"] else "N", "Y" if r["queried_by_doi"] else "N"))
        extra = []
        if r.get("title_fallback"):
            # 如实标明：命中来自标题回退而非 DOI 直查——DOI 查不到这件事本身要留痕。
            extra.append("title-fallback=" + ",".join(r["title_fallback"]))
        if r.get("unavailable"):
            extra.append(_note_unavailable(r))
        if r.get("not_applicable"):
            extra.append("n/a=" + ",".join(r["not_applicable"]))
        if skipped:
            extra.append("skipped=" + ",".join(skipped))
        if r["state"] == "verified":
            print("  PASS %s%s" % (line, (" " + " ".join(extra)) if extra else ""))
        else:
            tag = "BLOCK" if mode == "strict" else "ADVISORY"
            print("  %s %s <- %s%s" % (tag, line, r["reason"],
                                       (" [" + "; ".join(extra) + "]") if extra else ""))
    print("汇总：verified=%d suspected=%d unresolvable=%d（mode=%s, 共 %d 条）"
          % (counts.get("verified", 0), counts.get("suspected", 0), counts.get("unresolvable", 0),
             mode, len(results)))
    if degraded or unavailable_total:
        print("覆盖率提示：%d 条文献应答面不足四全（unavailable 累计 %d 次）。k 只在有效应答的索引上计，"
              "这类条目是**证据不够**，不是伪造嫌疑。" % (degraded, unavailable_total))
    if skipped:
        print("人工摘除索引：%s —— 该集合不计入 hits/k 分母，verified 所需命中数随之下降，"
              "须在投稿材料里声明验真覆盖面。" % ",".join(skipped))
    if counts.get("unresolvable", 0):
        print("提示：unresolvable 不等于伪造——纯标题查不到是地方刊/非英语刊/未数字化文献的正常形态，"
              "请按 30-literature-pipeline.md §2 走人工题录核对，不得据此判死。")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="35-refs-gate.py",
                                 description="文献引用验真门控（四索引源状态分立 → k 汇总三态）")
    ap.add_argument("--refs", help="22-refs.json 路径")
    ap.add_argument("--min-hits", type=int, default=MIN_HITS,
                    help="verified 所需最少命中索引数（缺省 2；实测：非预印本文献 arXiv 结构性不适用、"
                         "S2 免 key 常 404/429，按规格原口径 3 会把真文献判成覆盖不足。CS/ML 预印本库建议 3）")
    ap.add_argument("--min-answered", type=int, default=MIN_ANSWERED,
                    help="有效应答索引数低于此值即判 unresolvable（缺省 %d）" % MIN_ANSWERED)
    ap.add_argument("--skip-indices", help="逗号分隔，人工摘除的索引（如 semantic_scholar 长期 429）")
    ap.add_argument("--mode", choices=("advisory", "strict"), default="advisory")
    ap.add_argument("--cache", help="可选：查询缓存 JSON 路径（只读写该显式路径）")
    ap.add_argument("--report", help="可选：把结果 JSON 写到该路径")
    ap.add_argument("--fixtures", help="可选：离线复放 {index: {status,body,content_type}} JSON 路径，不联网")
    ap.add_argument("--max-retries", type=int, default=RETRIES,
                    help="429/5xx 退避重试次数（缺省 %d）" % RETRIES)
    ap.add_argument("--selftest", action="store_true", help="离线自测（真实响应形状 fixture，不联网）")
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if not args.refs:
        print("用法错误：--refs 必需（或用 --selftest）", file=sys.stderr)
        return 2
    skipped = []
    if args.skip_indices:
        skipped = [s.strip() for s in args.skip_indices.split(",") if s.strip()]
        bad = [s for s in skipped if s not in INDICES]
        if bad:
            print("用法错误：--skip-indices 取值非法 %s，可选 %s" % (bad, list(INDICES)), file=sys.stderr)
            return 2
    globals()["RETRIES"] = max(0, args.max_retries)
    if args.fixtures:
        fx, err = _load_json_object(args.fixtures, "fixtures")
        if err:
            print("用法错误：%s" % err, file=sys.stderr)
            return 2
        globals()["FETCH"] = _fixture_fetch(fx, [])
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
    results = grade_refs(refs, min_hits=args.min_hits, cache=cache, min_answered=args.min_answered,
                         skipped=skipped)
    if cache is not None:
        with open(args.cache, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
    print_report(results, args.mode, skipped=skipped)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
    if args.mode == "strict" and any(r["state"] != "verified" for r in results):
        return 1
    return 0


# ---------- 离线自测 ----------

def _fixture_fetch(records, calls):
    """在 fetch 层注入：records = {index: {status, body, content_type}}，body 为原始文本或 dict。

    意义：`_decode` 及其以下（Atom 解析、Crossref date-parts 解包、404/429 分档）走真实代码，
    只有真正联网的那一段被替换——上一版把 fixture 放在解码之上，才让 406/XML 这类真环境失败面测不到。
    """
    def fetch(url):
        for index in INDICES:
            if url.startswith(PREFIX[index]):
                calls.append(index)
                rec = records.get(index)
                if rec is None:
                    raise TransportError("fixture_missing", index)
                body = rec.get("body", "")
                if not isinstance(body, str):
                    body = json.dumps(body, ensure_ascii=False)
                ctype = rec.get("content_type") or (
                    "application/atom+xml; charset=utf-8" if index == "arxiv" else "application/json")
                return int(rec.get("status", 200)), body.encode("utf-8"), ctype
        calls.append("unknown")
        raise TransportError("unknown_endpoint", url[:60])
    return fetch


ATOM_ONE = ("<?xml version='1.0' encoding='UTF-8'?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\" "
            "xmlns:arxiv=\"http://arxiv.org/schemas/atom\">\n  <title>arXiv Query</title>\n"
            "  <entry>\n    <id>http://arxiv.org/abs/1905.11481v1</id>\n"
            "    <updated>2019-05-28T00:00:00Z</updated>\n    <published>2019-05-28T00:00:00Z</published>\n"
            "    <title>Graphene Oxide Membranes for Nanofiltration</title>\n"
            "    <arxiv:journal_ref>Nature Water</arxiv:journal_ref>\n  </entry>\n</feed>\n")
ATOM_ZERO = ("<?xml version='1.0' encoding='UTF-8'?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\">\n"
             "  <title>arXiv Query: no results</title>\n</feed>\n")

ENTRY = {"doi": "10.1038/s41545-019-0031-1", "title": "Graphene Oxide Membranes for Nanofiltration",
         "year": 2019, "venue": "Nature Water", "arxiv_id": "1905.11481"}


def _real_shape_records():
    """2026-09-26 实测的**响应形状**：Crossref 双层 envelope + date-parts 套列表、
    OpenAlex DOI 直查为单对象、S2 直查为单对象、arXiv 为 Atom XML 原文。

    注意口径：形状取自真响应，条目本身是合成样本——ENTRY 那组 doi/venue/year 是编的
    （实测该 DOI 在 OpenAlex/Crossref 均 404）。故这些 fixture 只用于验解码与判据分档，
    不得当作"真文献已验真"的证据；真环境证据另跑（不带 --fixtures 直连四索引）。
    """
    return {
        "openalex": {"body": {"display_name": "Graphene Oxide Membranes for Nanofiltration",
                              "publication_year": 2019,
                              "primary_location": {"source": {"display_name": "Nature Water"}},
                              "is_retracted": False}},
        "crossref": {"body": {"status": "ok", "message-type": "work", "message-version": "1.0.0",
                              "message": {"indexed": {"date-parts": [[2026, 9, 1]]},
                                          "title": ["Graphene Oxide Membranes for Nanofiltration"],
                                          "container-title": ["Nature Water"],
                                          "published-print": {"date-parts": [[2019, 5, 28]]}}}},
        "semantic_scholar": {"body": {"paperId": "a1b2",
                                      "title": "Graphene oxide membranes for nanofiltration",
                                      "year": 2019, "venue": "Nature Water", "isRetracted": False}},
        "arxiv": {"body": ATOM_ONE},
    }


def run_selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
            print("  FAIL %s: got %r want %r" % (name, got, want))
        else:
            print("  OK   %s" % name)

    def grade(entry, records, min_hits=MIN_HITS, min_answered=MIN_ANSWERED, skipped=()):
        calls = []
        fetch = _fixture_fetch(records, calls)
        per = {ix: query_index(ix, str(entry.get("doi") or "") or None,
                               str(entry.get("title") or "") or None, fetch=fetch,
                               arxiv_id=str(entry.get("arxiv_id") or "") or None) for ix in INDICES}
        state, detail = decide(entry, per, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
        return state, calls, detail

    good = _real_shape_records()

    # AC1：真实形状四索引 fixture 下 verified，且样本面确实打到四个端点
    st, calls, _ = grade(ENTRY, good)
    check("真实形状样本（Crossref 双层 envelope + arXiv Atom XML）-> verified", st, "verified")
    check("样本面覆盖四索引", sorted(set(calls)), sorted(INDICES))
    # F1/F2 回归：解码层本身
    check("Crossref date-parts [[2019,5,28]] -> 2019（F2）", _extract("crossref", good["crossref"]["body"])["year"], 2019)
    check("arXiv Atom XML -> 归一条目（F1）",
          _extract("arxiv", _decode("arxiv", 200, ATOM_ONE.encode("utf-8"), "application/atom+xml; charset=utf-8")[0]),
          {"title": "Graphene Oxide Membranes for Nanofiltration", "year": 2019,
           "venue": "Nature Water", "retracted": False})
    check("arXiv Atom 零条目 -> unmatched（应答了但没有，不是没回答）",
          query_index("arxiv", None, "Whatever", fetch=_fixture_fetch({"arxiv": {"body": ATOM_ZERO}}, []))[0],
          "unmatched")
    check("arXiv 406（实测：查询形状不合服务端胃口时直接拒，不是零结果）-> unavailable",
          query_index("arxiv", ENTRY["doi"], None, arxiv_id=ENTRY["arxiv_id"],
                      fetch=_fixture_fetch({"arxiv": {"status": 406, "body": "Not Acceptable"}}, []))[0],
          "unavailable")
    # not_applicable：arXiv 只认自家 id，拿非 arXiv DOI 的后缀去查是发无意义请求（实测直接 406）
    na_calls = []
    na = query_index("arxiv", "10.1038/nature14539", None,
                     fetch=_fixture_fetch(_real_shape_records(), na_calls))
    check("非 arXiv DOI 且无 arxiv_id -> not_applicable", (na[0], na[3]),
          ("not_applicable", "no_arxiv_identifier"))
    check("not_applicable 不发请求（调用面为空）", na_calls, [])
    check("arXiv DOI（10.48550/ 前缀）仍走 id_list",
          query_index("arxiv", "10.48550/arXiv.1706.03762", None,
                      fetch=_fixture_fetch({"arxiv": {"body": ATOM_ONE}}, []))[0],
          "matched")
    # F1 的规范化面：实测 `id_list=arXiv.1706.03762` 与带斜杠旧式 id 都被 406 拒收
    check("_arxiv_id：10.48550 DOI -> 裸 id", _arxiv_id("10.48550/arXiv.1706.03762"), "1706.03762")
    check("_arxiv_id：arXiv: 前缀 + 版本号", _arxiv_id("arXiv:1706.03762v5"), "1706.03762v5")
    check("_arxiv_id：裸 id 原样", _arxiv_id("1706.03762"), "1706.03762")
    check("_arxiv_id：旧式带斜杠 -> %2F 转义（斜杠会被 arXiv 拒）",
          _arxiv_id("quant-ph/9601029"), "quant-ph%2F9601029")
    check("_arxiv_id：非 arXiv DOI -> None（不得发无意义请求）", _arxiv_id("10.1038/s41545-019-0031-1"), None)
    check("_arxiv_id：空/None -> None", (_arxiv_id(""), _arxiv_id(None)), (None, None))
    check("_arxiv_phrase：词间用 %20、短语用 %22 包裹（实测 + 分隔一律 406）",
          _arxiv_phrase("Graphene Oxide Membranes for Nanofiltration"),
          "%22graphene%20oxide%20membranes%20for%20nanofiltration%22")
    check("_arxiv_phrase：空标题 -> None", _arxiv_phrase("  --- "), None)
    check("标题模式 arXiv 端点用 ti: + 短语式",
          _endpoint("arxiv", None, "Graphene Oxide Membranes")[0].endswith(
              "/api/query?search_query=ti:%22graphene%20oxide%20membranes%22&max_results=1"), True)
    check("JSON 解码失败 -> unavailable 而非 unmatched",
          query_index("openalex", ENTRY["doi"], None,
                      fetch=_fixture_fetch({"openalex": {"body": "<html>blocked</html>",
                                                         "content_type": "text/html"}}, []))[0],
          "unavailable")

    # F3 第 4 项：429/406 退避重试（假 opener，离线且零 sleep）
    class _Resp(object):
        def __init__(self, status, body, ctype):
            self.status, self._body = status, body.encode("utf-8")
            self.headers = {"Content-Type": ctype}

        def read(self):
            return self._body

        def close(self):
            pass

    box = {"n": 0, "slept": []}

    def flaky_opener(req, timeout=None):
        box["n"] += 1
        if box["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 406, "Not Acceptable", {"Content-Type": "text/html"}, None)
        return _Resp(200, '{"display_name": "Graphene Oxide Membranes for Nanofiltration",'
                         '"publication_year": 2019, "is_retracted": false}', "application/json")

    saved_backoff, saved_fetch = globals()["BACKOFF_S"], globals()["FETCH"]
    saved_interval = globals()["MIN_INTERVAL_S"]
    globals()["BACKOFF_S"] = 0.0
    globals()["MIN_INTERVAL_S"] = 0.0
    try:
        retried = _fetch_raw(PREFIX["openalex"] + "/works/doi:x", retries=2, opener=flaky_opener)
        time_calls = box["n"]
        globals()["BACKOFF_S"] = 0.0
        exhausted_box = {"n": 0}

        def always_429(req, timeout=None):
            exhausted_box["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                         {"Content-Type": "application/json"}, None)

        gave_up = _fetch_raw(PREFIX["openalex"] + "/works/doi:x", retries=1, opener=always_429)
        globals()["FETCH"] = _fixture_fetch(_real_shape_records(), [])
        live_status = query_index("openalex", ENTRY["doi"], None)[0]
        check("406 首次即退避重试并成功（请求数=2）", time_calls, 2)
        check("退避后拿到 200 即按 matched 走真解码", retried[0], 200)
        check("重试用尽仍 429 -> 返回状态码交判据层分档", (gave_up[0], exhausted_box["n"]), (429, 2))
        check("反向对照：同一条目经缺省 FETCH（含退避路径）仍 matched", live_status, "matched")
    finally:
        globals()["BACKOFF_S"], globals()["FETCH"] = saved_backoff, saved_fetch
        globals()["MIN_INTERVAL_S"] = saved_interval

    # AC2：--min-hits 覆盖 k 阈值后同一条目判定随动
    hits3 = json.loads(json.dumps(good))
    hits3["arxiv"] = {"status": 404, "body": '{"error":"no such id"}'}
    check("hits=3/answered=4 且 min-hits=3 -> verified", grade(ENTRY, hits3, min_hits=3)[0], "verified")
    check("同一条目 min-hits=4 -> suspected（判定随动）", grade(ENTRY, hits3, min_hits=4)[0], "suspected")

    # F3：unavailable 不进 k 分母；限流不等于文献可疑
    throttle = json.loads(json.dumps(good))
    throttle["semantic_scholar"] = {"status": 429, "body": '{"code":"429","message":"Too Many Requests"}'}
    st_t, _, det_t = grade(ENTRY, throttle)
    check("S2 429 -> 该索引记 unavailable", det_t["unavailable"], ["semantic_scholar"])
    check("S2 429 时 answered/hits/k = 3/3/0", (det_t["answered"], det_t["hits"], det_t["k"]), (3, 3, 0))
    check("S2 429 时仍 verified", st_t, "verified")
    check("限流样本标 degraded", det_t["degraded"], True)
    # F3 审计面：三类"没答上"要能分开处置（稍后再跑 / 换时段 / --skip-indices 摘除）
    check("index_status 记 unavailable 的原因串（429 ≠ 5xx ≠ 解码失败）",
          det_t["index_status"]["semantic_scholar"], "unavailable:http_429")
    check("报告行把 unavailable 连原因一起上屏", _note_unavailable(det_t),
          "unavail=semantic_scholar:http_429")
    check("index_status 记结构性不适用（不是失败，是没得答）",
          grade(dict(ENTRY, arxiv_id=""), good)[2]["index_status"]["arxiv"],
          "not_applicable:no_arxiv_identifier")
    check("index_status 记人工摘除",
          grade(ENTRY, throttle, skipped=("semantic_scholar",))[2]["index_status"]["semantic_scholar"],
          "skipped")
    notfound = json.loads(json.dumps(good))
    notfound["semantic_scholar"] = {"status": 404, "body": '{"error":"Paper with id DOI:... not found"}'}
    _, _, det_n = grade(ENTRY, notfound)
    check("反向对照：S2 404（服务答了没有）-> answered=4、k=1、无 unavailable",
          (det_n["answered"], det_n["k"], det_n["unavailable"]), (4, 1, []))
    check("index_status 分得开「服务说没有」与「服务没回答」",
          (det_n["index_status"]["semantic_scholar"], det_n["index_status"]["openalex"]),
          ("unmatched:not_found_404", "matched:ok"))
    check("反向对照：同条件 min-hits=4 时 404 样本降为 suspected、429 样本降为 unresolvable",
          (grade(ENTRY, notfound, min_hits=4)[0], grade(ENTRY, throttle, min_hits=4)[0]),
          ("suspected", "unresolvable"))
    # 实测回归（2026-09-26 真网络首跑）：只有 OpenAlex+Crossref 应答时，按严格口径不得放行
    two_only = json.loads(json.dumps(good))
    two_only["semantic_scholar"] = {"status": 503, "body": "down"}
    two_only["arxiv"] = {"status": 503, "body": "down"}
    st_2, _, det_2 = grade(ENTRY, two_only, min_hits=3)
    check("answered=2 < need=3 -> unresolvable（应答面不足，判不了）", st_2, "unresolvable")
    check("该降级不得伪装成伪造嫌疑（reason 串区分）", det_2["reason"], "insufficient_index_coverage")
    check("反向对照：同样本 min-hits=2（缺省）时放行 verified", grade(ENTRY, two_only)[0], "verified")
    silent = {ix: {"status": 503, "body": "service down"} for ix in INDICES}
    st_s, _, det_s = grade(ENTRY, silent)
    check("四索引全无应答 -> unresolvable（不得判成伪造嫌疑）", st_s, "unresolvable")
    check("无应答时的原因串", det_s["reason"], "insufficient_index_coverage")

    # AC3 反伪造偏置
    all_no = {ix: {"status": 404, "body": '{"error":"not found"}'} for ix in INDICES}
    check("DOI 在有效应答的索引全查不到 -> suspected", grade(ENTRY, all_no)[0], "suspected")
    title_only = {"title": ENTRY["title"], "year": 2019, "venue": "Nature Water"}
    check("纯标题查不到 -> unresolvable", grade(title_only, all_no)[0], "unresolvable")

    # AC4：三条判据各破坏一条 -> suspected
    low_sim = json.loads(json.dumps(good))
    low_sim["openalex"]["body"]["display_name"] = "Totally Different Title About Soils"
    low_sim["crossref"]["body"]["message"]["title"] = ["Totally Different Title About Soils"]
    low_sim["semantic_scholar"]["body"]["title"] = "Totally Different Title About Soils"
    check("相似度 <0.70 -> suspected", grade(ENTRY, low_sim)[0], "suspected")

    one_off = json.loads(json.dumps(good))
    one_off["openalex"]["body"]["display_name"] = "Totally Different Title About Soils"
    check("仅一家索引标题跑偏（3/4 同意）-> 仍 verified（多数判据不过杀）", grade(ENTRY, one_off)[0], "verified")

    no_ctx = json.loads(json.dumps(good))
    no_ctx["openalex"]["body"]["primary_location"]["source"]["display_name"] = "Journal of Fictional Studies"
    no_ctx["openalex"]["body"]["publication_year"] = 1901
    no_ctx["crossref"]["body"]["message"]["container-title"] = ["Journal of Fictional Studies"]
    no_ctx["crossref"]["body"]["message"]["published-print"] = {"date-parts": [[1901, 1, 1]]}
    no_ctx["semantic_scholar"]["body"]["venue"] = "Journal of Fictional Studies"
    no_ctx["semantic_scholar"]["body"]["year"] = 1901
    no_ctx["arxiv"]["body"] = ATOM_ONE.replace("2019-05-28", "1901-01-01").replace(
        "Nature Water", "Journal of Fictional Studies")
    check("期刊与年份均不一致 -> suspected", grade(ENTRY, no_ctx)[0], "suspected")

    year_only = json.loads(json.dumps(good))
    year_only["openalex"]["body"]["primary_location"] = {"source": None}
    year_only["crossref"]["body"]["message"]["container-title"] = []
    year_only["semantic_scholar"]["body"]["venue"] = ""
    year_only["arxiv"]["body"] = ATOM_ONE.replace(
        "<arxiv:journal_ref>Nature Water</arxiv:journal_ref>", "")
    check("期刊全缺、仅年份一致时仍可 verified（F2 的生效面）", grade(ENTRY, year_only)[0], "verified")

    retracted = json.loads(json.dumps(good))
    retracted["openalex"]["body"]["is_retracted"] = True
    check("is_retracted=true -> suspected", grade(ENTRY, retracted)[0], "suspected")

    check("显式摘除 S2 -> skipped 记名且仍 verified",
          (grade(ENTRY, throttle, skipped=("semantic_scholar",))[2]["skipped"],
           grade(ENTRY, throttle, skipped=("semantic_scholar",))[0]),
          (["semantic_scholar"], "verified"))

    # ---------- 标题回退：真网络 2026-09-26 跑出的假阳性 ----------
    # DOI 是 arXiv DOI（10.48550/…）时，OpenAlex/Crossref/S2 结构上没有这篇，只有 arXiv 认；
    # 没有回退时必然 hits=1 < need=2 → 把真实文献判成可疑。fixture 按 URL 区分两种模式。
    def _two_mode_fetch(records, calls):
        def fetch(url):
            mode = "doi" if any(m in url for m in ("doi:", "DOI:", "/works/10.", "id_list=")) else "title"
            for index in INDICES:
                if url.startswith(PREFIX[index]):
                    calls.append(index + ":" + mode)
                    rec = records[index][mode]
                    if rec is None:
                        raise TransportError("fixture_missing", index + ":" + mode)
                    spec = rec if isinstance(rec, dict) and "body" in rec else {"body": rec}
                    body = spec.get("body", "")
                    if not isinstance(body, str):
                        body = json.dumps(body, ensure_ascii=False)
                    ctype = spec.get("content_type") or (
                        "application/atom+xml; charset=utf-8" if index == "arxiv" else "application/json")
                    return int(spec.get("status", 200)), body.encode("utf-8"), ctype
            calls.append("unknown:" + mode)
            raise TransportError("unknown_endpoint", url[:60])
        return fetch

    atom_transformer = ATOM_ONE.replace("Graphene Oxide Membranes for Nanofiltration",
                                        "Attention Is All You Need").replace(
        "2019-05-28", "2017-06-12").replace(
        "\n    <arxiv:journal_ref>Nature Water</arxiv:journal_ref>", "")
    ENTRY_MODES = {"openalex": {"doi": good["openalex"]["body"], "title": None},
                   "crossref": {"doi": good["crossref"]["body"], "title": None},
                   "semantic_scholar": {"doi": good["semantic_scholar"]["body"], "title": None},
                   "arxiv": {"doi": ATOM_ONE, "title": None}}
    arxiv_entry = {"doi": "10.48550/arXiv.1706.03762", "title": "Attention Is All You Need",
                   "year": 2017, "venue": "arXiv"}
    NOT_IN_DOI = {"openalex": {"doi": {"status": 404, "body": '{"error":"no work"}'},
                               "title": {"results": [{"display_name": "Attention Is All You Need",
                                                      "publication_year": 2017,
                                                      "primary_location": {"source": None},
                                                      "is_retracted": False}]}},
                  "crossref": {"doi": {"status": 404, "body": '{"status":"error","message":"not found"}'},
                               "title": {"status": "ok", "message-type": "work-list",
                                         "message-version": "1.0.0",
                                         "message": {"facets": {}, "total-results": 1, "items": [
                                             {"title": ["Attention Is All You Need"],
                                              "container-title": [],
                                              "published-print": {"date-parts": [[2017, 6, 12]]}}]}}},
                  "semantic_scholar": {"doi": {"status": 404, "body": '{"error":"Paper not found"}'},
                                       "title": {"data": [{"paperId": "cccf",
                                                           "title": "Attention Is All You Need",
                                                           "year": 2017, "venue": "",
                                                           "isRetracted": False}]}},
                  "arxiv": {"doi": atom_transformer, "title": atom_transformer}}
    fb_calls = []
    fb = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, fb_calls))[0]
    check("DOI 全 404 而 arXiv 命中 -> 标题回退后 verified（旧版判 suspected 的假阳性）",
          (fb["state"], fb["hits"], fb["reason"]), ("verified", 4, "all_checks_passed"))
    check("回退只补查 DOI 模式判 unmatched 的三家", fb["title_fallback"],
          ["openalex", "crossref", "semantic_scholar"])
    check("回退调用面 = DOI 轮 4 + 标题轮 3", sorted(fb_calls),
          sorted(["openalex:doi", "crossref:doi", "semantic_scholar:doi", "arxiv:doi",
                  "openalex:title", "crossref:title", "semantic_scholar:title"]))
    check("index_status 保留 DOI 轮结论（回退不得抹掉「DOI 为何没命中」）",
          fb["index_status"]["openalex"], "matched:ok <- doi轮 unmatched:not_found_404")
    check("回退后凑满 4 票：min-hits=4 也可 verified（回退补的是真证据）",
          grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(NOT_IN_DOI, []))[0]["state"],
          "verified")
    PARTIAL = json.loads(json.dumps(NOT_IN_DOI))
    PARTIAL["semantic_scholar"]["title"] = {"status": 404, "body": '{"error":"Paper not found"}'}
    check("反向对照：仅 2/4 家标题可查（S2 标题也 404）时 min-hits=4 -> suspected",
          (grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(PARTIAL, []))[0]["state"],
           grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(PARTIAL, []))[0]["reason"]),
          ("suspected", "coverage_below_min_hits"))
    check("反向对照：同样本 min-hits=2 时放行（阈值真的随动）",
          grade_refs([arxiv_entry], min_hits=2, fetch=_two_mode_fetch(PARTIAL, []))[0]["state"], "verified")
    NO_WHERE = json.loads(json.dumps(NOT_IN_DOI))
    for ix in ("openalex", "crossref", "semantic_scholar"):
        NO_WHERE[ix]["title"] = {"status": 404, "body": '{"error":"no match"}'}
    NO_WHERE["arxiv"] = {"doi": ATOM_ZERO, "title": ATOM_ZERO}
    nw_calls = []
    nw = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NO_WHERE, nw_calls))[0]
    check("反向对照：DOI 与标题都查不到 -> suspected，且不得有回退命中",
          (nw["state"], nw["reason"], nw["title_fallback"]),
          ("suspected", "doi_not_found_in_any_index", []))
    check("反向对照：回退两轮共 8 次查询（每索引 DOI + 标题各一次）", len(nw_calls), 8)
    nm_calls = []
    nm = grade_refs([ENTRY], fetch=_two_mode_fetch(ENTRY_MODES, nm_calls))[0]
    check("反向对照：DOI 已命中时不回退标题（调用面恰为 4，省一半请求）",
          (nm["state"], nm["title_fallback"], sorted(set(nm_calls))),
          ("verified", [], ["arxiv:doi", "crossref:doi", "openalex:doi", "semantic_scholar:doi"]))
    fb_cache = {}
    box1, box2 = [], []
    grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, box1), cache=fb_cache)
    r2 = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, box2), cache=fb_cache)[0]
    check("回退结论随缓存回放：首跑 7 次、二跑 0 次",
          (len(box1), len(box2)), (7, 0))
    check("缓存回放不丢回退标记",
          (r2["state"], r2["from_cache"], r2["title_fallback"], r2["index_status"]["openalex"]),
          ("verified", True, ["openalex", "crossref", "semantic_scholar"],
           "matched:ok <- doi轮 unmatched:not_found_404"))

    # AC1/AC5：CLI 全链路 + 退出码
    tmp = os.environ.get("TEMP", "/tmp")
    refs_file = os.path.join(tmp, "rg-selftest-refs.json")
    report_file = os.path.join(tmp, "rg-selftest-report.json")
    fx_file = os.path.join(tmp, "rg-selftest-fixtures.json")
    cache_file = os.path.join(tmp, "rg-selftest-cache.json")
    bogus = {"doi": "10.0000/not-a-real-record", "title": "Zzzz Nonexistent Paper Qqqq",
             "year": 1999, "venue": "Nowhere"}
    with open(fx_file, "w", encoding="utf-8") as fh:
        json.dump(good, fh, ensure_ascii=False)
    saved_fetch = globals()["FETCH"]
    globals()["FETCH"] = _fixture_fetch(good, [])
    try:
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY, bogus], fh, ensure_ascii=False)
        check("advisory 下存在非 verified 仍 rc=0",
              main(["--refs", refs_file, "--mode", "advisory", "--report", report_file]), 0)
        check("strict 下同一样本 rc!=0",
              main(["--refs", refs_file, "--mode", "strict", "--report", report_file]) != 0, True)
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY], fh, ensure_ascii=False)
        check("全 verified 时 strict rc=0（反向对照）", main(["--refs", refs_file, "--mode", "strict"]), 0)
        check("--fixtures 复放走真实解码面", main(["--refs", refs_file, "--fixtures", fx_file]), 0)
        check("非法 --skip-indices -> rc=2", main(["--refs", refs_file, "--skip-indices", "google_scholar"]), 2)
        check("缺 --refs -> rc=2", main([]), 2)
        check("不存在的 --refs -> rc=2", main(["--refs", refs_file + ".nope"]), 2)
        with open(refs_file, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("坏 JSON -> rc=2", main(["--refs", refs_file]), 2)
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump("scalar", fh)
        check("顶层非列表 -> rc=2", main(["--refs", refs_file]), 2)
        for p in (refs_file, cache_file):
            try:
                os.remove(p)
            except OSError:
                pass
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY], fh, ensure_ascii=False)
        calls_box = []
        globals()["FETCH"] = _fixture_fetch(good, calls_box)
        main(["--refs", refs_file, "--cache", cache_file])
        first = len(calls_box)
        main(["--refs", refs_file, "--cache", cache_file])
        check("缓存首跑查四索引", first, 4)
        check("缓存二跑零查询（幂等）", len(calls_box) - first, 0)
        check("缓存回放后仍无网络（取数面零调用）", len(calls_box) - first, 0)
    finally:
        globals()["FETCH"] = saved_fetch
        for p in (refs_file, report_file, cache_file, fx_file):
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
