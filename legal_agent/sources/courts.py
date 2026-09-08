"""裁判所 裁判例検索（courts.go.jp）ソース。公開サイト・ログイン不要。

- 検索: GET https://www.courts.go.jp/hanrei/search1/index.html
  フォームの全項目（空でも）を送らないと結果ブロックが描画されない。
  `filter[judgeDateMode]` は期間指定時のみ "2" を付ける（それ以外で付けると結果が出ない）。
- 詳細: https://www.courts.go.jp/hanrei/{id}/detail{N}/index.html（N は裁判例の種別で異なる）
- 全文 PDF: https://www.courts.go.jp/assets/hanrei/hanrei-pdf-{id}.pdf
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from ..config import Settings
from ..models import Document, Hit
from .base import focus_excerpts, slice_text

BASE = "https://www.courts.go.jp/"
SEARCH_URL = BASE + "hanrei/search1/index.html"
UA = "Mozilla/5.0 (compatible; LegalAgent/0.1; personal research assistant)"

FORM_FIELDS = [
    "query1", "query2",
    "filter[judgeGengoFrom]", "filter[judgeYearFrom]", "filter[judgeMonthFrom]", "filter[judgeDayFrom]",
    "filter[judgeGengoTo]", "filter[judgeYearTo]", "filter[judgeMonthTo]", "filter[judgeDayTo]",
    "filter[jikenGengo]", "filter[jikenYear]", "filter[jikenCode]", "filter[jikenNumber]",
    "filter[courtType]", "filter[courtSection]", "filter[courtName]", "filter[branchName]",
]
PAGE_SIZE = 30


def to_wareki(d: date) -> tuple[str, int]:
    """西暦 → (元号, 年)。令和・平成・昭和のみ対応。"""
    if d >= date(2019, 5, 1):
        return "令和", d.year - 2018
    if d >= date(1989, 1, 8):
        return "平成", d.year - 1988
    return "昭和", d.year - 1925


def parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip().replace("/", "-")
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    return date(y, mo, d)


def build_params(
    query: str, date_from: str | None = None, date_to: str | None = None, court: str | None = None, offset: int = 0
) -> dict[str, str]:
    p = {k: "" for k in FORM_FIELDS}
    p["query1"] = query
    df, dt = parse_iso(date_from), parse_iso(date_to)
    if df or dt:
        p["filter[judgeDateMode]"] = "2"
        if df:
            g, y = to_wareki(df)
            p.update({"filter[judgeGengoFrom]": g, "filter[judgeYearFrom]": str(y),
                      "filter[judgeMonthFrom]": str(df.month), "filter[judgeDayFrom]": str(df.day)})
        if dt:
            g, y = to_wareki(dt)
            p.update({"filter[judgeGengoTo]": g, "filter[judgeYearTo]": str(y),
                      "filter[judgeMonthTo]": str(dt.month), "filter[judgeDayTo]": str(dt.day)})
    if court:
        p["filter[courtName]"] = court
    p["sort"] = "1"
    p["offset"] = str(offset)
    return p


_ID_RE = re.compile(r"/hanrei/(\d+)/detail(\d)/")


def parse_list(html: str) -> tuple[list[Hit], int]:
    """検索結果 HTML → (Hit 一覧, 総件数)"""
    soup = BeautifulSoup(html, "lxml")
    total = 0
    m = re.search(r"(\d+)件中", soup.get_text(" ", strip=True))
    if m:
        total = int(m.group(1))
    hits: list[Hit] = []
    for tr in soup.select("table.search-result-table tbody tr"):
        a = tr.select_one("th a")
        if not a or not a.get("href"):
            continue
        idm = _ID_RE.search(urljoin(SEARCH_URL, a["href"]))
        if not idm:
            continue
        case_id, detail_no = idm.group(1), idm.group(2)
        category = a.get_text(strip=True)
        paras = [[l.strip() for l in p.get_text("\n").split("\n") if l.strip()] for p in tr.select("td p")]
        paras = [p for p in paras if p and p != ["全文"]]
        case_number = case_name = ""
        if paras:
            case_number = paras[0][0] if paras[0] else ""
            case_name = " ".join(paras[0][1:]) if len(paras[0]) > 1 else ""
        judged = court = judge_type = result = original = ""
        if len(paras) > 1:
            info = paras[1]
            judged = info[0] if info else ""
            court = info[1] if len(info) > 1 else ""
            rest = info[2:]
            for item in rest:
                if item in ("判決", "決定", "命令"):
                    judge_type = item
                elif re.search(r"裁判所", item):
                    original = item
                else:
                    result = (result + " " + item).strip()
        extra = " / ".join(" ".join(p) for p in paras[2:] if p)
        pdf = tr.select_one("td.file-col a[href*='.pdf']")
        pdf_url = urljoin(SEARCH_URL, pdf["href"]) if pdf else f"{BASE}assets/hanrei/hanrei-pdf-{case_id}.pdf"
        detail_url = f"{BASE}hanrei/{case_id}/detail{detail_no}/index.html"
        subtitle = " ".join(x for x in (court, judged, judge_type, result) if x)
        hits.append(
            Hit(
                ref=f"courts:{case_id}",
                source="courts",
                kind="case",
                title=f"{case_number} {case_name}".strip() or f"裁判例 {case_id}",
                subtitle=subtitle,
                snippet=extra,
                url=detail_url,
                meta={
                    "case_id": case_id, "detail_no": detail_no, "category": category,
                    "case_number": case_number, "case_name": case_name, "date": judged,
                    "court": court, "type": judge_type, "result": result, "original": original,
                    "pdf_url": pdf_url,
                },
            )
        )
    return hits, total


def parse_detail(html: str) -> dict[str, str]:
    """詳細ページの dl（事件番号・裁判年月日・判示事項・裁判要旨 等）→ dict"""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}
    for dl in soup.select("dl"):
        dt, dd = dl.select_one("dt"), dl.select_one("dd")
        if not dt or not dd:
            continue
        key = dt.get_text(strip=True)
        if key == "全文":
            a = dd.select_one("a[href*='.pdf']")
            if a:
                meta["pdf_url"] = urljoin(BASE + "hanrei/x/detail2/", a["href"])
            continue
        val = dd.get_text("\n", strip=True)
        if key and val:
            meta[key] = val
    return meta


_LINE_NO_RE = re.compile(r"^\s*\d{1,3}\s*$")


def clean_judgment_text(text: str) -> str:
    """判決 PDF の欄外行番号（5,10,15…）やページ番号だけの行を除く。"""
    return "\n".join(l for l in text.splitlines() if not _LINE_NO_RE.match(l))


def pdf_to_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return clean_judgment_text("\n".join(page.get_text("text") for page in doc))


class CourtsSource:
    name = "courts"
    label = "裁判所 裁判例検索（公開）"
    kind = "case"
    requires_login = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_dir = Path(settings.cache_dir) / "courts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._hits: dict[str, Hit] = {}

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        async with self._lock:
            wait = self.settings.min_interval_sec - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            r = await self._client.get(url, params=params)
            self._last_request = time.monotonic()
        r.raise_for_status()
        return r

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        params = build_params(
            query, filters.get("date_from"), filters.get("date_to"), filters.get("court"), int(filters.get("offset", 0))
        )
        r = await self._get(SEARCH_URL, params)
        hits, total = parse_list(r.text)
        for h in hits:
            h.meta["total"] = total
            self._hits[h.meta["case_id"]] = h
        return hits[:limit]

    def _cache_path(self, case_id: str) -> Path:
        return self.cache_dir / f"{case_id}.json"

    async def fetch(self, item_id: str, **options: Any) -> Document:
        case_id = item_id.split(":")[-1].strip()
        if not case_id.isdigit():
            raise KeyError(f"裁判例 ID が不正です: {item_id}")
        offset = int(options.get("offset", 0))
        cache = self._cache_path(case_id)
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            data = await self._download(case_id)
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        focus = (options.get("focus") or "").strip()
        full = data["text"]
        if focus:
            # キーワード周辺だけ（トークン節約）
            text = focus_excerpts(full, focus) or f"（「{focus}」は本文中に見つかりませんでした。全 {len(full)} 字。offset で本文を読むか別の語で focus してください）"
            total = len(full)
            offset = 0
        else:
            # 初回は要旨 + 冒頭のみ。続きは offset で 1 回 max_text_chars 字ずつ
            limit = self.settings.initial_text_chars if offset == 0 else self.settings.max_text_chars
            text, total = slice_text(full, offset, limit)
        meta = {k: data["meta"].get(k, "") for k in ("事件番号", "事件名", "裁判年月日", "法廷名", "裁判所名", "裁判種別", "結果", "判示事項", "裁判要旨", "参照法条")}
        meta = {k: v for k, v in meta.items() if v}
        if focus:
            meta["抜粋"] = f"focus=「{focus}」の周辺のみ（全 {total} 字）"
        title = f"{data['meta'].get('事件番号', '')} {data['meta'].get('事件名', '')}".strip() or f"裁判例 {case_id}"
        return Document(
            ref=f"courts:{case_id}", source=self.name, kind="case", title=title, text=text,
            url=data["detail_url"], meta=meta, offset=offset, total_chars=total if not focus else len(text),
        )

    async def _download(self, case_id: str) -> dict:
        hit = self._hits.get(case_id)
        detail_url = hit.url if hit else ""
        html = ""
        candidates = [detail_url] if detail_url else []
        candidates += [f"{BASE}hanrei/{case_id}/detail{n}/index.html" for n in range(2, 8)]
        for url in candidates:
            try:
                r = await self._get(url)
                html, detail_url = r.text, url
                break
            except httpx.HTTPStatusError:
                continue
        meta = parse_detail(html) if html else {}
        pdf_url = meta.get("pdf_url") or (hit.meta.get("pdf_url") if hit else "") or f"{BASE}assets/hanrei/hanrei-pdf-{case_id}.pdf"
        text = ""
        try:
            r = await self._get(pdf_url)
            text = await asyncio.to_thread(pdf_to_text, r.content)
        except httpx.HTTPError as e:
            text = f"（全文 PDF を取得できませんでした: {e}）"
        if not detail_url:
            detail_url = f"{BASE}hanrei/{case_id}/detail2/index.html"
        return {"case_id": case_id, "detail_url": detail_url, "pdf_url": pdf_url, "meta": meta, "text": text}

    async def status(self) -> dict[str, Any]:
        return {"available": True, "logged_in": None, "detail": "courts.go.jp（公開）"}

    async def aclose(self) -> None:
        await self._client.aclose()
