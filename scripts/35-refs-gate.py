#!/usr/bin/env python3
"""35-refs-gate.py — 文献引用验真门控（P3 第②段的可机检面）。

规格：references/30-literature-pipeline.md §1（四索引、k 语义、三态、反伪造偏置、gate.mode）。

输入 = `22-refs.json`（列表或 {"refs": [...]}），每条给 doi 或 arxiv_id 或 title 作为查询键；
      但要拿到 verified 还需可比字段：**最少 = 一个可解析标识符 + title + (year 或 venue)**。
      缺字段一律 unresolvable（题录不全 ≠ 文献可疑），报表以 `缺字段=` 单列提示。
判定：四索引（openalex / crossref / semantic_scholar / arxiv）各出一个**源状态**
      matched / unmatched / unavailable / not_applicable；`answered` = 给出有效应答的索引数，
      `k = answered - hits`；门槛 `need = min(--min-hits, pool)`（pool = 四索引减去 --skip-indices）：
      answered < need → unresolvable（应答面不足，判不了）；hits < need → 有标识符才 suspected（覆盖不足），
      纯标题 → unresolvable；
      再过标题相似度（命中索引多数同意：同意数*2 >= 有标题命中数）、期刊或年份一致、非撤稿三关才 verified。
为什么要有 unavailable 与 not_applicable：**"服务说没有"（404/零条目）、"服务没回答"（429 限流、
      5xx、406 拒收、解码失败）、"该索引对这条文献结构性无从回答"（非 arXiv DOI 之于 arXiv）
      是三回事**。把后两类当"没有"计进 k，会让真文献成片降档：实测免 key 的 Semantic Scholar 连发
      两请求即 429、对个别真 DOI 直接 404；arXiv 对 `search_query` 有 IP 级速率罚时且**以 406 呈现**
      （实测：罚时窗口内 `ti:`/`all:`/`cat:`、带引号与裸词一起 406，而 `id_list` 照常 200，静置 240s
      未恢复），所以它的请求间隔单档提到 >=3s（HOST_INTERVAL_S），而不是改检索式去碰运气。
反伪造偏置：只有**按 DOI/编号**这一面（查不到、或与记录对不上）才允许 suspected；
      **纯标题条目一律 unresolvable**（真实的地方刊、非英语刊、未数字化文献长这样，不该被当成伪造嫌疑）；
      有效应答数低于 --min-answered 时一律 unresolvable（无据可判，不等于判死）。
      不变量：suspected 只可能来自标识符面或撤稿——无标识符条目在四面失败（全查不到 / 相似度不达标 /
      期刊年份对不上 / 命中数不足）上都不产出 suspected，撤稿是唯一例外（它是对文献本身的阳性结论）。
      "DOI/编号"同权是规格原话（references/30-literature-pipeline.md:18）：arXiv 编号独立参与判定，
      无 DOI 只有编号的条目若四索引全否证，reason=arxiv_id_not_found_in_any_index → suspected。
标识符面：arXiv 一栏优先按 id_list 精确查（编号可来自 arxiv_id 字段，也可来自 10.48550 自家 DOI），
      没有可用编号才退成 ti: 短语检索——上一版把这段挂在 DOI 分支下，实测后果是无 DOI 的预印本条目
      带着伪造编号与带着真编号结论逐字相同（模糊标题检索把编号遮掉了）。
标题回退：按**标识符**的命中数凑不齐门槛时，对"按标识符答了没有"的索引再按标题问一次（实测 arXiv
      自家 DOI 在 OpenAlex/Crossref/S2 结构性 404，只有 arXiv 认——不回退则真文献必判可疑）。
      第一轮已按标题答过的索引不再重复问（无 DOI 条目三家本就走的标题面）。
      回退命中的索引记在 `title_fallback` 并随缓存回放，报告行以 `title-fallback=` 标明来路。
审计面：每条结果的 `index_status` 记 `{索引: 源状态:原因[出处]}`，`[id]`/`[title]` 区分精确直查与
      模糊检索命中（`matched:ok` 不分来路会让"伪造编号 + 真标题"读起来像编号核对通过）；
      控制台把 unavailable 连原因一起上屏——限流、5xx、解码失败的处置各不相同，不能只报索引名；
      n/a 与 unavailable 两类计数分行报，别把"结构性无从回答"说成"服务没答上"。
      走过标题回退的索引再缀 `<- id轮 源状态:原因`，标识符为何没命中不得被回退结果抹掉。
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
import io
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
# 节流按 host 分档：arXiv 官方要求程序化请求间隔 >=3s，而它的超速惩罚不是 429 而是 406，
# 且窗口会累积（2026-09-26 实测：连跑 10 条题录后同一 host 上 `id_list` 仍 200、`search_query`
# 整片 406，静置 75s 未恢复）。统一 1s 等于自己把 arXiv 标题面长期打成 unavailable。
HOST_INTERVAL_S = {"export.arxiv.org": 3.5}
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
        interval = HOST_INTERVAL_S.get(host, MIN_INTERVAL_S)
        if gap < interval:
            time.sleep(interval - gap)
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
    """arXiv 标题检索式：短语加引号、词间 %20（2026-09-26 早上那轮真环境挑出来的形态）。

    口径提醒（同日傍晚复测）：这个 host 对 `search_query` 有 IP 级速率罚时，窗口内**所有**形态
    （`ti:`/`all:`/`cat:`、带引号与裸词）一起 406，连静置 240s 都没出来，而 `id_list` 照常 200。
    所以别把这条注释读成"换成别的前缀就能绕过 406"——406 是**没回答**，不是"库里没有"，
    判据层已按 unavailable 处理（不进 k 分母）；真要用 arXiv 标题面，靠的是 F9 的 >=3s 间隔而非改写式。
    """
    words = [w for w in _norm_title(title).split() if w]
    if not words:
        return None
    return "%22" + "%20".join(urllib.parse.quote(w, safe="") for w in words[:12]) + "%22"


def _endpoint(index, doi, title, arxiv_id=None):
    """按标识符优先、否则按标题构造查询端点，返回 (url|None, by_id, why_not_applicable)。

    标识符 = DOI **或** arXiv 编号，二者同权（规格 references/30-literature-pipeline.md:18 写的是
    "按 DOI/编号查不到"）。上一版只在**有 DOI** 的分支里才读 arxiv_id，实测后果：无 DOI 的预印本条目
    （`22-refs.json` 的常见形态）带着编号也只走模糊标题检索，真编号与伪造编号的结果逐字相同。

    url=None 表示该索引对这条文献**结构性无从回答**（既不是"没回答"也不是"没有"），
    必须与 unavailable 分开计：它不进 k 的分母，也不该被当成一次失败。
    arXiv 只认自家 id——实测把非 arXiv DOI 的后缀塞进 id_list 直接 406（请求被拒，不是零结果）。
    """
    if index == "arxiv":
        aid = _arxiv_id(arxiv_id) or _arxiv_id(doi)
        if aid:
            return PREFIX["arxiv"] + "/api/query?id_list=" + aid, True, ""
        if doi:
            return None, True, "no_arxiv_identifier"
    if doi:
        q = urllib.parse.quote(doi, safe="")
        by_id = True
        if index == "openalex":
            return PREFIX["openalex"] + "/works/doi:" + q, by_id, ""
        if index == "crossref":
            return PREFIX["crossref"] + "/works/" + q, by_id, ""
        if index == "semantic_scholar":
            return (PREFIX["semantic_scholar"] + "/graph/v1/paper/DOI:" + q
                    + "?fields=title,year,venue,isRetracted"), by_id, ""
    q = urllib.parse.quote_plus(title or "")
    by_id = False
    if not q:
        return None, by_id, "no_query_key"
    if index == "openalex":
        return PREFIX["openalex"] + "/works?search=" + q + "&per-page=1", by_id, ""
    if index == "crossref":
        return PREFIX["crossref"] + "/works?query.bibliographic=" + q + "&rows=1", by_id, ""
    if index == "semantic_scholar":
        return (PREFIX["semantic_scholar"] + "/graph/v1/paper/search?query=" + q
                + "&limit=1&fields=title,year,venue,isRetracted"), by_id, ""
    phrase = _arxiv_phrase(title)
    if not phrase:
        return None, by_id, "no_query_key"
    return PREFIX["arxiv"] + "/api/query?search_query=ti:" + phrase + "&max_results=1", by_id, ""


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
    """返回 (source, record|None, by_id, reason)，source ∈ SOURCES + NOT_APPLICABLE。异常收敛为 unavailable。"""
    fetch = fetch or FETCH
    url, by_id, why = _endpoint(index, doi, title, arxiv_id=arxiv_id)
    if url is None:
        return NOT_APPLICABLE, None, by_id, why
    try:
        status, body, ctype = fetch(url)
    except TransportError as exc:
        return "unavailable", None, by_id, "transport_" + exc.kind
    obj, reason = _decode(index, status, body, ctype)
    if obj is None:
        return "unavailable", None, by_id, reason
    if obj is NO_RECORD:
        return "unmatched", None, by_id, reason
    rec = _extract(index, _unwrap(index, obj))
    if rec is None or not (rec.get("title") or rec.get("year")):
        return "unmatched", None, by_id, "no_record"
    return "matched", rec, by_id, "ok"


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
    另有两条**前置**分母，缺了就会把判不了说成可疑：
      标识符面 = 条目持有可解析标识符（DOI **或** arXiv 编号，规格 :18 同权）——hits==0 时
                 只有这一面成立才允许 suspected，纯标题一律 unresolvable；
      可评面   = 条目自己给了哪些比较所需的字段（缺 title → 相似度关不可评；year 与 venue 全缺 →
                 期刊/年份关不可评）→ 一律 unresolvable（reason=input_field_missing:…），
                 哪怕标识符查得到：缺的是**比较的输入**，补齐字段再跑，不靠松判据放行。
    其余三处"字段给了但对不上"（相似度、期刊/年份、命中数不足）按**标识符面**分档：
    持有可解析标识符 → suspected（标识符与记录矛盾），纯标题 → unresolvable（检索式跑偏不是伪造证据）。
    retracted 是唯一不分档的：它是对文献本身的阳性结论。
    """
    skipped = tuple(skipped or ())
    applicable, answered, unavailable, not_applicable = [], [], [], []
    index_status = {}
    for ix in INDICES:
        t = per_index.get(ix) or (NOT_APPLICABLE, None, False, "missing")
        # 出处标在状态串里：`[id]` 是按标识符精确查、`[title]` 是模糊检索命中，强度不同。
        # 只写 matched:ok 会让"伪造编号 + 真标题"这条读起来像编号核对通过（实测正是上一轮的失真面）；
        # unmatched 带 [id] 同样重要——那就是规格里的"按编号查不到"这条证据本身。
        # unavailable / not_applicable 根本没给出应答，标出处纯属噪音。
        if t[0] in ("unavailable", NOT_APPLICABLE):
            origin = ""
        elif t[2]:
            origin = "[id]"
        else:
            origin = "[title]" if t[0] == "matched" else ""
        index_status[ix] = "%s:%s%s" % (t[0], t[3], origin)
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
    raw_aid = _arxiv_id(str(entry.get("arxiv_id") or entry.get("arxivId") or ""))
    aid = raw_aid or _arxiv_id(doi)
    id_kinds = (["doi"] if doi else []) + (["arxiv_id"] if raw_aid else [])
    has_id = bool(id_kinds)
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
    # 判据**可评性**：条目自己没给的字段无法比较。缺 title → 相似度关不可评；year 与 venue 全缺 →
    # 期刊/年份关不可评。注意这与"字段给了但对不上"是两回事，后者才该判 suspected。
    title_given = bool(str(entry.get("title") or "").strip())
    ctx_given = entry.get("year") is not None or bool(str(entry.get("venue") or "").strip())
    input_gap = ([] if title_given else ["title"]) + ([] if ctx_given else ["year|venue"])
    # 反伪造偏置（规格 :18）不只管"查不到"那一面，三处"查到了但对不上"同样适用：suspected 的语义是
    # "你给的标识符与权威记录矛盾"，纯标题条目没有可矛盾的标识符。实测：无 DOI 的 "Attention Is All
    # You Need"（year=2017）被 OpenAlex 一条 2025 同名条目带偏，venue/year 全 False，上一版在 strict
    # 下把这篇真文献拦成"伪造嫌疑"。缺标识符是**证据不够**，与 hits==0 那一面同档处理。
    # retracted 是唯一例外：那是对文献本身的阳性结论，与条目有没有标识符无关。
    mismatch_state = "suspected" if has_id else "unresolvable"
    detail = {"answered": len(answered), "applicable": len(applicable), "need": need,
              "k": k, "hits": hits, "similarity": round(sim, 3),
              "similarity_agree": "%d/%d" % (agree, len(sims)),
              "venue_match": venue_ok, "year_match": year_ok, "retracted": retracted,
              "queried_by_id": has_id, "id_kinds": id_kinds, "input_gap": input_gap,
              "unavailable": unavailable,
              "not_applicable": not_applicable, "skipped": list(skipped),
              "index_status": index_status,
              "degraded": bool(unavailable or not_applicable or skipped)}
    if len(answered) < max(1, min_answered):
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits == 0:
        # 反伪造偏置：持有**可解析**标识符（DOI 或 arXiv 编号）而有效应答的索引一致说"没有" → suspected；
        # 纯标题查不到 → unresolvable。规格把 DOI 与编号同权（references/30-literature-pipeline.md:18），
        # 上一版只认 DOI，于是无 DOI 的预印本条目拿着伪造编号也进不了这一档。
        detail["reason"] = ("doi_not_found_in_any_index" if doi
                            else "arxiv_id_not_found_in_any_index" if aid
                            else "title_only_no_match")
        return ("suspected" if has_id else "unresolvable"), detail
    if retracted:
        detail["reason"] = "retracted"
        return "suspected", detail
    if input_gap:
        # 实测：只给 doi+title 的真 Nature 论文（hits=3/3、sim=1.00）上一版被判 suspected，
        # 而 22-refs.json 声明的字段（grade/verify_checks/two_source_verified/doi）里本就没有 year/venue
        # ——门控会对技能自己的主产物系统性指控"可疑"。缺字段是**证据不够**，一律 unresolvable。
        detail["reason"] = "input_field_missing:" + "+".join(input_gap)
        return "unresolvable", detail
    if not sim_ok:
        detail["reason"] = "title_similarity_below_threshold"
        return mismatch_state, detail
    if not (venue_ok or year_ok):
        detail["reason"] = "neither_venue_nor_year_matches"
        return mismatch_state, detail
    if len(answered) < need:
        # 应答面本身凑不齐 need 票：判不了，不是文献可疑（真网络下最常见：S2 限流 + arXiv 对非预印本不适用）。
        # 必须先于命中数判据——否则 answered < need 时 hits 必然也 < need，会被误降成 suspected。
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits < need:
        detail["reason"] = "coverage_below_min_hits"
        return mismatch_state, detail
    detail["reason"] = "all_checks_passed"
    return "verified", detail


def grade_refs(refs, min_hits=MIN_HITS, fetch=None, cache=None, min_answered=MIN_ANSWERED, skipped=()):
    out = []
    for i, entry in enumerate(refs):
        doi = str(entry.get("doi") or "").strip()
        title = str(entry.get("title") or "").strip()
        arxiv_id = str(entry.get("arxiv_id") or entry.get("arxivId") or "").strip()
        per_index, cache_hit = {}, False
        fell_back, id_round = [], {}
        # 缓存键必须含 arxiv_id：无 DOI 的预印本条目彼此只差编号，键里不带编号会让两条不同条目
        # 串用同一行缓存（实测过这种串法：doi 空 + title 相同即碰撞）。
        key = hashlib.sha256(("%s|%s|%s" % (doi, arxiv_id, title)).encode("utf-8")).hexdigest()
        cached = cache.get(key) if cache is not None else None
        if isinstance(cached, dict) and isinstance(cached.get("per_index"), dict):
            per_index = {ix: (str(v[0]), v[1], bool(v[2]), str(v[3]) if len(v) > 3 else "cache")
                         for ix, v in cached["per_index"].items()
                         if isinstance(v, (list, tuple)) and v
                         and str(v[0]) in SOURCES + (NOT_APPLICABLE,)}
            cache_hit = len(per_index) == len(INDICES)
            # 回退结论随缓存一起回放：缓存里已是"标识符 + 标题都问过"的合并结果，
            # 二跑若再回退一次就会破掉"缓存零查询"的承诺。
            if cache_hit:
                fell_back = [str(x) for x in (cached.get("title_fallback") or [])]
                id_round = {str(k): str(v) for k, v in (cached.get("id_round") or {}).items()}
        if not cache_hit:
            per_index = {index: query_index(index, doi or None, title or None, fetch=fetch,
                                            arxiv_id=arxiv_id or None) for index in INDICES}
            need = min(min_hits, len(INDICES) - len(tuple(skipped or ())))
            id_queried = bool(_arxiv_id(arxiv_id) or _arxiv_id(doi) or doi)
            rescue_need = max(1, need)   # --min-hits 0 不得关掉标题轮：那时 need=0，标识符面的否证将无人复核
            if id_queried and title and sum(1 for v in per_index.values() if v[0] == "matched") < rescue_need:
                # 标识符查不到 ≠ 文献不存在：DOI 可能是 arXiv 自家 DOI（三家 JSON API 结构上无收录，
                # 实测正是这条形状）、注册有误、或新注册尚未索引；arXiv 编号同理可能是笔误或旧版号。
                # 只在「按标识符的命中数已不足以放行」时才补问标题，且只补问**按标识符**答了"没有"的索引：
                # 第一轮已经按标题答过的索引再问一次纯属重复（无 DOI 条目三家本就走标题面）。
                # 真文献少付一轮请求，伪造条目多付一轮（这一轮本身就是判据）。
                for ix in INDICES:
                    st, _, by_id, why = per_index[ix]
                    if st != "unmatched" or not by_id:
                        continue
                    id_round[ix] = "%s:%s" % (st, why)
                    alt = query_index(ix, None, title, fetch=fetch)
                    if alt[0] == "matched":
                        per_index[ix] = alt
                        fell_back.append(ix)
            if cache is not None:
                cache[key] = {"per_index": {ix: [st, r, bool(b), why]
                                            for ix, (st, r, b, why) in per_index.items()},
                              "title_fallback": list(fell_back), "id_round": dict(id_round)}
        state, detail = decide(entry, per_index, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
        detail["state"] = state
        detail["from_cache"] = cache_hit
        detail["title_fallback"] = fell_back
        # 回退会把标识符轮的结果覆盖掉，但"编号直查为何没命中"恰恰是判伪造的关键证据（实测见过
        # 真 DOI 因网络抖动记 transport_network、也见过臆造 DOI 记 not_found_404）——留在状态串里。
        for ix, prev in sorted(id_round.items()):
            if ix in detail["index_status"]:
                detail["index_status"][ix] += " <- id轮 " + prev
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
    degraded = unavailable_total = na_total = gap_total = 0
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        degraded += 1 if r.get("degraded") else 0
        unavailable_total += len(r.get("unavailable") or [])
        na_total += len(r.get("not_applicable") or [])
        gap_total += 1 if r.get("input_gap") else 0
        line = ("[%d] %-10s %-56s hits=%d/%d need=%d k=%d sim=%.2f(%s) venue=%s year=%s retr=%s id=%s"
                % (r["index"], r["state"], r["ref"][:56], r["hits"], r["answered"], r.get("need", 0),
                   r["k"], r["similarity"], r.get("similarity_agree", "-"),
                   "Y" if r["venue_match"] else "N", "Y" if r["year_match"] else "N",
                   "Y" if r["retracted"] else "N", ",".join(r.get("id_kinds") or []) or "-"))
        extra = []
        if r.get("title_fallback"):
            # 如实标明：命中来自标题回退而非标识符直查——编号查不到这件事本身要留痕。
            extra.append("title-fallback=" + ",".join(r["title_fallback"]))
        if r.get("input_gap"):
            # 与"可疑"分家的提示：这一条是题录缺字段，补字段再跑即可，不是指控伪造。
            extra.append("缺字段=" + "+".join(r["input_gap"]))
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
    if gap_total:
        print("题录提示：%d 条因条目自身缺字段而判不了（unresolvable，非可疑）。"
              "verified 最少需要 title + (year 或 venue) 加一个可解析标识符；"
              "补齐字段再跑，别去松判据。" % gap_total)
    if unavailable_total or na_total:
        # 两个数分开报：n/a 是"该索引对这条文献结构性无从回答"（非 arXiv 文献的 arXiv 面，正常现象），
        # unavailable 是"服务没答上"（429/5xx/解码失败，该重跑）。混在一句里会出现"应答面不足四全
        # （unavailable 累计 0 次）"这种读起来自相矛盾的提示（实测上一版就是这样）。
        print("覆盖面提示：n/a=%d 次（结构性无从回答，如非预印本之于 arXiv）、unavailable=%d 次"
              "（服务没答上，稍后重跑）。两者都不计入 k 的分母；应答面不足四全的条目共 %d 条，"
              "这类条目是**证据不够**，不是伪造嫌疑。" % (na_total, unavailable_total, degraded))
    if skipped:
        print("人工摘除索引：%s —— 该集合不计入 hits/k 分母，verified 所需命中数随之下降，"
              "须在投稿材料里声明验真覆盖面。" % ",".join(skipped))
    if counts.get("unresolvable", 0):
        print("提示：unresolvable 不等于伪造——suspected 只留给「标识符与权威记录矛盾」（含撤稿）；"
              "缺标识符的条目无论查不到还是题录对不上，都只是证据不够（地方刊/非英语刊/未数字化文献"
              "的正常形态）。请按 30-literature-pipeline.md §2 走人工题录核对，不得据此判死。")


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

    # ---------- F9：节流按 host 分档（arXiv 的 406 是自己 1s 连发喂出来的） ----------
    # 用假 time 驱动，断言的是"真的按 host 取间隔"这个机制，而不是表里的数字；零真实 sleep。
    check("节流表里的 host 必须在节流名单内（否则 HOST_INTERVAL_S 是死配置）",
          [h for h in HOST_INTERVAL_S if h not in THROTTLE_HOSTS], [])
    check("arXiv 间隔 >=3s（官方下限），其余 host 用缺省值",
          (HOST_INTERVAL_S["export.arxiv.org"] >= 3.0, MIN_INTERVAL_S), (True, 1.0))

    class _FakeTime(object):
        def __init__(self, start):
            self.t, self.slept = start, []

        def time(self):
            return self.t

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.t += seconds

    ft = _FakeTime(1000.0)
    saved_time, saved_last = globals()["time"], dict(_LAST_CALL)
    globals()["time"] = ft
    try:
        def probe(host, since):
            globals()["_LAST_CALL"][host] = ft.t - since
            del ft.slept[:]
            _throttle(host)
            return ft.slept[0] if ft.slept else 0.0
        arx = probe("export.arxiv.org", 0.5)
        oal = probe("api.openalex.org", 0.5)
        ok_fast = probe("api.openalex.org", 5.0)
        free = probe("example.org", 0.0)
    finally:
        globals()["time"] = saved_time
        _LAST_CALL.clear()
        _LAST_CALL.update(saved_last)
    check("0.5s 前刚请求过 arXiv -> 补足到 3.5s（旧版只补到 1s，等于持续违规）",
          round(arx, 3), 3.0)
    check("同样 0.5s 间隔对 OpenAlex 只补到 1s（没有一刀切拖慢）", round(oal, 3), 0.5)
    check("距上次 5s 则 arXiv 之外不等待", (ok_fast, free), (0.0, 0.0))

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
    check("index_status 分得开「服务说没有」与「服务没回答」，且带标识符出处 [id]",
          (det_n["index_status"]["semantic_scholar"], det_n["index_status"]["openalex"]),
          ("unmatched:not_found_404[id]", "matched:ok[id]"))
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
    check("index_status 保留标识符轮结论并标出来路（回退不得抹掉「编号为何没命中」）",
          fb["index_status"]["openalex"], "matched:ok[title] <- id轮 unmatched:not_found_404")
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
           "matched:ok[title] <- id轮 unmatched:not_found_404"))

    # ---------- F7：标识符面（arXiv 编号与 DOI 同权，规格 :18 的「按 DOI/编号查不到」） ----------
    url_nod, bid_nod, _ = _endpoint("arxiv", None, "Attention Is All You Need", arxiv_id="1706.03762")
    check("无 DOI 但有编号 → 按 id_list 精确查（旧版在这里退成模糊标题检索）",
          ("id_list=1706.03762" in url_nod, bid_nod), (True, True))
    check("反向对照：既无编号也无 DOI 才退成 ti: 短语检索",
          _endpoint("arxiv", None, "Attention Is All You Need")[0].startswith(
              PREFIX["arxiv"] + "/api/query?search_query=ti:"), True)
    check("反向对照：非 arXiv DOI 且无编号 → 不发请求（实测畸形 id_list 直接被 406 拒）",
          (_endpoint("arxiv", "10.1038/s41545-019-0031-1", "Whatever")[0],
           _endpoint("arxiv", "10.1038/s41545-019-0031-1", "Whatever")[2]),
          (None, "no_arxiv_identifier"))
    preprint = {"arxiv_id": "1706.03762", "title": "Attention Is All You Need", "year": 2017, "venue": "arXiv"}
    dead = {ix: {"status": 404, "body": '{"error":"no match"}'} for ix in INDICES}
    dead["arxiv"] = {"body": ATOM_ZERO}
    st_pid, _, det_pid = grade(preprint, dead)
    check("AC3 编号臂：无 DOI、持失效 arXiv 编号且四索引一致否证 → suspected",
          (st_pid, det_pid["reason"], det_pid["id_kinds"], det_pid["queried_by_id"]),
          ("suspected", "arxiv_id_not_found_in_any_index", ["arxiv_id"], True))
    st_tit, _, det_tit = grade({k: v for k, v in preprint.items() if k != "arxiv_id"}, dead)
    check("反向对照：同一条目去掉编号（纯标题否证）→ unresolvable，不得指控伪造",
          (st_tit, det_tit["reason"], det_tit["id_kinds"]),
          ("unresolvable", "title_only_no_match", []))
    fakeid = json.loads(json.dumps(NOT_IN_DOI))
    fakeid["arxiv"] = {"doi": ATOM_ZERO, "title": atom_transformer}
    fx = grade_refs([dict(preprint, arxiv_id="9999.99999")], fetch=_two_mode_fetch(fakeid, []))[0]
    check("审计面不撒谎：伪造编号 + 真标题被三家认下时，arXiv 行要显示编号那轮否证",
          (fx["index_status"]["arxiv"].startswith("unmatched"), "[id]" in fx["index_status"]["arxiv"],
           fx["state"], fx["index_status"]["openalex"]),
          (True, True, "verified", "matched:ok[title]"))
    check("同一条目写成 10.48550 DOI 形态时，编号轮的否证照样留痕（标题回退不得抹掉它）",
          grade_refs([dict(preprint, doi="10.48550/arXiv.9999.99999", arxiv_id="")],
                     fetch=_two_mode_fetch(fakeid, []))[0]["index_status"]["arxiv"],
          "matched:ok[title] <- id轮 unmatched:no_record")
    id_cache, second_calls = {}, []
    grade_refs([preprint], fetch=_two_mode_fetch(NOT_IN_DOI, []), cache=id_cache)
    grade_refs([dict(preprint, arxiv_id="9999.99999")], fetch=_two_mode_fetch(NOT_IN_DOI, second_calls),
               cache=id_cache)
    check("缓存键含 arxiv_id：只差编号的两条不得串用同一行（第二条必须重查 4 次）",
          (len(id_cache), len(second_calls)), (2, 4))
    z_calls = []
    zentry = {"doi": "10.1000/no.such.doi", "title": "Attention Is All You Need", "year": 2017, "venue": "arXiv"}
    z = grade_refs([zentry], min_hits=0, fetch=_two_mode_fetch(NOT_IN_DOI, z_calls))[0]
    check("--min-hits 0 仍付标题轮：need=0 时标识符面的否证不得无人复核（旧版在此直接判可疑）",
          (len(z_calls), z["state"], z["reason"]), (6, "verified", "all_checks_passed"))
    check("反向对照：同样本在标识符与标题两面都查不到时仍 suspected",
          grade_refs([zentry], min_hits=0, fetch=_two_mode_fetch(NO_WHERE, []))[0]["reason"],
          "doi_not_found_in_any_index")

    # ---------- F6：判据可评性（题录缺字段是判不了，不是可疑） ----------
    no_ctx = {k: v for k, v in ENTRY.items() if k not in ("year", "venue")}
    st_nc, _, det_nc = grade(no_ctx, good)
    check("F6：标识符与标题全命中（hits=4、sim=1.0）但条目没给 year/venue → unresolvable",
          (st_nc, det_nc["reason"], det_nc["input_gap"], det_nc["hits"]),
          ("unresolvable", "input_field_missing:year|venue", ["year|venue"], 4))
    no_title = {k: v for k, v in ENTRY.items() if k != "title"}
    st_nt, _, det_nt = grade(no_title, good)
    check("F6：只给标识符（无 title）→ 相似度关不可评，unresolvable 而非疑似伪造",
          (st_nt, det_nt["reason"], det_nt["input_gap"]),
          ("unresolvable", "input_field_missing:title", ["title"]))
    check("反向对照：字段在场而对不上，照旧 suspected（没把判据松掉）",
          grade(dict(ENTRY, year=1901, venue="Journal of Fictional Studies"), good)[0], "suspected")
    check("只有 year（venue 留空）仍可 verified：判据是「期刊或年份」，单字段缺席不算不可评",
          grade(dict(ENTRY, venue=""), good)[0], "verified")
    check("只有 venue（year 不给）同上", grade(dict(ENTRY, year=None), good)[0], "verified")
    gap_res = grade_refs([no_ctx], fetch=_two_mode_fetch(ENTRY_MODES, []))
    na_res = grade_refs([dict(ENTRY, arxiv_id="")], fetch=_two_mode_fetch(ENTRY_MODES, []))
    buf = io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        print_report(gap_res, "advisory")
        print_report(na_res, "advisory")
    finally:
        sys.stdout = old_out
    rpt = buf.getvalue()
    check("报表把缺字段单列，并给「补字段再跑、别松判据」的题录提示",
          ("缺字段=year|venue" in rpt, "题录提示" in rpt, "id=doi,arxiv_id" in rpt),
          (True, True, True))
    check("n/a 与 unavailable 分开计数（旧版混成一句，实测出现过「应答面不足四全（unavailable 累计 0 次）」）",
          ("覆盖面提示" in rpt, "n/a=1 次" in rpt, "unavailable=0 次" in rpt), (True, True, True))

    # ---------- F8：suspected 只允许由标识符面（或撤稿）触发 ----------
    # 规格 :18 的反伪造偏置字面上只管"查不到"那一面，但"查到了对不上"的三处判据同样在指控作者伪造，
    # 而纯标题条目根本没有可矛盾的标识符：真环境实测（2026-09-26 直连四索引）"Attention Is All You
    # Need"（无 DOI、year=2017）被 OpenAlex 一条 2025 同名条目带偏 → suspected → strict 模式拦下
    # 一篇真文献。四处失败面逐个补对照，另加撤稿这条例外。
    no_id = {k: v for k, v in ENTRY.items() if k not in ("doi", "arxiv_id")}
    thin = json.loads(json.dumps(good))
    for ix in ("crossref", "semantic_scholar"):
        thin[ix] = {"status": 404, "body": '{"error":"no match"}'}
    nowhere = {"openalex": {"status": 404, "body": '{"error":"no work"}'},
               "crossref": {"status": 404, "body": '{"status":"error","message":"not found"}'},
               "semantic_scholar": {"status": 404, "body": '{"error":"Paper not found"}'},
               "arxiv": {"body": ATOM_ZERO}}
    st_ctx, _, det_ctx = grade(dict(no_id, year=1901, venue="Journal of Fictional Studies"), good)
    check("F8：纯标题条目「期刊/年份对不上」→ unresolvable（真网络那条假阳性的离线复现）",
          (st_ctx, det_ctx["reason"], det_ctx["queried_by_id"]),
          ("unresolvable", "neither_venue_nor_year_matches", False))
    check("反向对照：同样记录、条目带 DOI 时照旧 suspected（标识符与记录矛盾才是伪造信号）",
          grade(dict(ENTRY, year=1901, venue="Journal of Fictional Studies"), good)[0], "suspected")
    st_sim, _, det_sim = grade(dict(no_id, title="Zzz Fabricated Title Qqq"), good)
    check("F8：纯标题条目「相似度不达标」→ unresolvable（检索式跑偏不是伪造证据）",
          (st_sim, det_sim["reason"]), ("unresolvable", "title_similarity_below_threshold"))
    check("反向对照：同样样本带 DOI → suspected",
          grade(dict(ENTRY, title="Zzz Fabricated Title Qqq"), good)[0], "suspected")
    st_cov, _, det_cov = grade(no_id, thin, min_hits=4)
    check("F8：纯标题条目「命中数不足」→ unresolvable",
          (st_cov, det_cov["reason"], det_cov["hits"]), ("unresolvable", "coverage_below_min_hits", 2))
    check("反向对照：同样本带 DOI → suspected（规格 :17 的 k=3/4 强信号只属于标识符面）",
          grade(ENTRY, thin, min_hits=4)[0], "suspected")
    st_none, _, det_none = grade(dict(no_id, title="Zzz Fabricated Title Qqq"), nowhere)
    check("F8：纯标题条目「四面全查不到」→ unresolvable",
          (st_none, det_none["reason"]), ("unresolvable", "title_only_no_match"))
    check("反向对照：同样本带 DOI → suspected",
          grade(dict(ENTRY, title="Zzz Fabricated Title Qqq"), nowhere)[0], "suspected")
    retr = json.loads(json.dumps(good))
    retr["openalex"]["body"]["is_retracted"] = True
    st_ret, _, det_ret = grade(no_id, retr)
    check("不变量唯一例外：撤稿是对文献本身的阳性结论，纯标题条目照旧 suspected",
          (st_ret, det_ret["reason"]), ("suspected", "retracted"))
    check("不变量成文：无标识符条目在四类失败面上都不产出 suspected，只有撤稿那一格例外",
          sorted({st_ctx, st_sim, st_cov, st_none}) + ["retracted->" + st_ret],
          ["unresolvable", "retracted->suspected"])
    f8_rows = grade_refs([dict(no_id, year=1901, venue="Journal of Fictional Studies")],
                         fetch=_fixture_fetch(good, []))
    buf8 = io.StringIO()
    old8 = sys.stdout
    sys.stdout = buf8
    try:
        print_report(f8_rows, "advisory")
    finally:
        sys.stdout = old8
    check("报表尾提示跟着改口径：unresolvable 不再只解释成「查不到」（F8 后含「对不上」那一面）",
          "标识符与权威记录矛盾" in buf8.getvalue(), True)

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
