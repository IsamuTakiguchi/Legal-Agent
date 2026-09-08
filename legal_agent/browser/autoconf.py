"""Claude によるセレクタ自動発見。

ログイン後の画面を DOM 要約にして Claude に渡し、検索画面・結果一覧・本文ページのセレクタを提案させ、
実際に Playwright で動かして検証する。成功した設定は data/selectors.override.yaml に保存する。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import anthropic
import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_JS = (Path(__file__).with_name("dom_summary.js")).read_text(encoding="utf-8")
MAX_SUMMARY_CHARS = 40000

SYSTEM = """あなたは Web サイトの画面構造を解析し、Playwright で使う CSS セレクタを提案する専門家です。
与えられる DOM 要約（フォーム、ボタン、リンク、繰り返し構造、本文候補）だけを根拠に、堅牢で単純なセレクタを選んでください。
- Playwright のセレクタ拡張（:has-text("…"), :visible, :has(…)）は使ってよい。XPath は不可。
- id やクラス名が自動生成っぽい（ハッシュ状）場合は避け、構造（要素名・安定した属性）で指定する。
- 該当しない項目は空文字にする。
- 日本語の法律情報サイト（判例データベース／法律書籍ライブラリ）であることを念頭に置く。"""


class SearchEntryProposal(BaseModel):
    """検索の開始方法。"""

    search_url: str = Field(description="検索を行う URL。URL パラメータで検索できるなら {query} を含めた完全な URL。フォーム入力が必要なら検索画面の URL。")
    input_selector: str = Field(default="", description="検索語を入力する要素のセレクタ（search_url に {query} を含む場合は空）。")
    submit_selector: str = Field(default="", description="検索実行ボタンのセレクタ（Enter 送信で済むなら空）。")
    reasoning: str = Field(default="", description="選んだ理由（短く）。")


class ResultsProposal(BaseModel):
    """検索結果一覧の読み取り方。"""

    results_wait: str = Field(description="結果一覧が描画されたと判断できる要素のセレクタ。")
    row: str = Field(description="結果 1 件に対応する要素のセレクタ（複数一致する）。")
    row_title: str = Field(default="", description="row 内でタイトル文字列を持つ要素（row 自体なら空）。")
    row_link: str = Field(default="", description="row 内で詳細ページへの href を持つ要素（row 自体が a なら空）。")
    row_meta: str = Field(default="", description="row 内の付随情報（裁判所・日付・著者など）を持つ要素（無ければ空）。")
    no_results_marker: str = Field(default="", description="0 件のときに表示される要素やテキストがあれば（任意）。")
    reasoning: str = Field(default="")


class DetailProposal(BaseModel):
    """詳細ページの本文の取り方。"""

    wait: str = Field(description="本文が描画されたと判断できる要素のセレクタ。")
    content: str = Field(description="本文（判決文／書籍ページ本文）を innerText で取得する要素のセレクタ。候補をカンマ区切りで複数書いてもよい（先頭優先）。")
    text_is_image: bool = Field(default=False, description="本文が画像／Canvas 描画でテキスト取得不能と判断される場合 true。")
    reasoning: str = Field(default="")


def _trim(summary: dict[str, Any]) -> str:
    s = json.dumps(summary, ensure_ascii=False)
    if len(s) <= MAX_SUMMARY_CHARS:
        return s
    # リンクと繰り返し構造のサンプルを削って収める
    summary = dict(summary)
    summary["links"] = summary.get("links", [])[:80]
    for g in summary.get("repeated", []):
        g["sample"] = g.get("sample", "")[:300]
    s = json.dumps(summary, ensure_ascii=False)
    return s[:MAX_SUMMARY_CHARS]


class AutoConfigurator:
    def __init__(self, source, client: anthropic.AsyncAnthropic | None = None, model: str = "claude-opus-5"):
        self.source = source  # BrowserSiteSource
        self.browser = source.browser
        self.site = source.name
        self.model = model
        self.client = client or anthropic.AsyncAnthropic()
        self.log: list[str] = []

    # ---- ユーティリティ ----
    def _note(self, msg: str) -> None:
        self.log.append(msg)
        log.info("[autoconf %s] %s", self.site, msg)

    async def _summary(self, pg) -> dict[str, Any]:
        return await pg.evaluate(_JS)

    async def _ask(self, model_cls: type[BaseModel], instructions: str, summary: dict[str, Any], feedback: str = "") -> BaseModel:
        content = instructions + ("\n\n前回の提案の問題点:\n" + feedback if feedback else "") + "\n\nDOM 要約(JSON):\n" + _trim(summary)
        resp = await self.client.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=model_cls,
        )
        return resp.parsed_output

    # ---- 本体 ----
    async def run(self, query: str = "解雇") -> dict[str, Any]:
        """検索〜本文までのセレクタを発見して返す（保存は呼び出し側）。失敗時は RuntimeError。"""
        cfg = self.source.cfg
        site_desc = "判例データベース（裁判例の検索）" if self.source.kind == "case" else "法律書籍のライブラリ（書籍本文の横断検索）"
        pg = await self.source._ensure_login()

        entry_feedback = ""
        for attempt_a in range(2):
            start_url = cfg.get("search", {}).get("url", "").replace("{query}", "") or cfg.get("home_url") or cfg["check_url"]
            await pg.goto(start_url, wait_until="domcontentloaded")
            await self.browser.dump(self.site, "autoconf-entry")
            entry: SearchEntryProposal = await self._ask(
                SearchEntryProposal,
                f"このサイトは{site_desc}です。現在のページ（{pg.url}）から、キーワード「{query}」で本文／全文検索を実行する方法を提案してください。"
                "サイト内に複数の検索がある場合は、判例や書籍本文を横断的に全文検索できるものを選ぶこと。",
                await self._summary(pg), entry_feedback,
            )
            if not entry.search_url:
                entry.search_url = pg.url  # 「現在のページで検索」→ そのページ URL を保存する
            self._note(f"検索開始案: url={entry.search_url} input={entry.input_selector!r} submit={entry.submit_selector!r}")
            try:
                await self._do_search(pg, entry, query)
            except Exception as e:  # noqa: BLE001
                entry_feedback = f"検索を実行できませんでした: {e}"
                continue
            await self.browser.dump(self.site, "autoconf-results")

            results_feedback = ""
            for attempt_b in range(3):
                res: ResultsProposal = await self._ask(
                    ResultsProposal,
                    f"キーワード「{query}」で検索した直後のページ（{pg.url}）です。検索結果の一覧を 1 件ずつ読み取るためのセレクタを提案してください。"
                    "各件からはタイトル（事件名／書名など）と詳細ページへのリンクが取れる必要があります。ナビゲーションやメニューのリンクを行として選ばないこと。",
                    await self._summary(pg), results_feedback,
                )
                self._note(f"結果一覧案: row={res.row!r} title={res.row_title!r} link={res.row_link!r}")
                ok, why, first_href = await self._validate_rows(pg, res, query)
                if ok:
                    break
                results_feedback = why
                self._note(f"検証失敗: {why}")
            else:
                entry_feedback = f"結果一覧を読み取れませんでした（{results_feedback}）。別の検索方法を検討してください。"
                continue

            # 詳細ページ
            await pg.goto(urljoin(pg.url, first_href), wait_until="domcontentloaded")
            await self.browser.dump(self.site, "autoconf-detail")
            detail_feedback = ""
            detail: DetailProposal | None = None
            for attempt_c in range(3):
                detail = await self._ask(
                    DetailProposal,
                    f"検索結果の 1 件目を開いた詳細ページ（{pg.url}）です。本文（判決文や書籍ページのテキスト）をできるだけ余計なナビゲーションを含めずに取得するセレクタを提案してください。",
                    await self._summary(pg), detail_feedback,
                )
                self._note(f"本文案: content={detail.content!r} image={detail.text_is_image}")
                if detail.text_is_image:
                    break
                n = await self._text_len(pg, detail.content)
                if n >= 200:
                    break
                detail_feedback = f"content セレクタ {detail.content!r} で取れた本文は {n} 文字しかありません。"
                self._note(detail_feedback)
            new_cfg = {
                "search": {
                    "url": entry.search_url,
                    "input": entry.input_selector or cfg.get("search", {}).get("input", "input[type='text']:visible"),
                    "submit": entry.submit_selector,
                    "results_wait": res.results_wait or res.row,
                    "row": res.row,
                    "row_title": res.row_title,
                    "row_link": res.row_link,
                    "row_meta": res.row_meta,
                    "max_rows": cfg.get("search", {}).get("max_rows", 20),
                },
                "detail": {
                    "wait": (detail.wait if detail else "body") or "body",
                    "content": (detail.content if detail else "body") or "body",
                    "text_is_image": bool(detail and detail.text_is_image),
                },
                "autoconf_log": self.log[-12:],
            }
            return new_cfg
        raise RuntimeError("セレクタの自動発見に失敗しました: " + (entry_feedback or "不明"))

    async def _do_search(self, pg, entry: SearchEntryProposal, query: str) -> None:
        if "{query}" in entry.search_url:
            await pg.goto(entry.search_url.replace("{query}", quote(query)), wait_until="domcontentloaded")
        else:
            if entry.search_url and entry.search_url != pg.url:
                await pg.goto(entry.search_url, wait_until="domcontentloaded")
            if not entry.input_selector:
                raise RuntimeError("input_selector が空で、URL にも {query} がありません")
            box = pg.locator(entry.input_selector).first
            await box.fill(query)
            if entry.submit_selector and await pg.locator(entry.submit_selector).count():
                await pg.locator(entry.submit_selector).first.click()
            else:
                await box.press("Enter")
        try:
            await pg.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # noqa: BLE001
            pass

    async def _validate_rows(self, pg, res: ResultsProposal, query: str = "") -> tuple[bool, str, str]:
        try:
            rows = pg.locator(res.row)
            n = await rows.count()
        except Exception as e:  # noqa: BLE001
            return False, f"row セレクタが不正です: {e}", ""
        if n == 0:
            return False, f"row セレクタ {res.row!r} に一致する要素が 0 件です。", ""
        good = 0
        first_href = ""
        query_seen = False
        terms = [t for t in re.split(r"\s+", query) if t]
        for i in range(min(n, 8)):
            row = rows.nth(i)
            try:
                t_el = row.locator(res.row_title).first if res.row_title else row
                l_el = row.locator(res.row_link).first if res.row_link else row
                title = (await t_el.inner_text()).strip() if await t_el.count() else ""
                href = (await l_el.get_attribute("href")) if await l_el.count() else None
                row_text = (await row.inner_text()).strip()
            except Exception as e:  # noqa: BLE001
                return False, f"row 内のセレクタでエラー: {e}", ""
            if any(t in row_text for t in terms):
                query_seen = True
            if title and href and not re.match(r"^(javascript:|#)", href):
                good += 1
                first_href = first_href or href
        if good < max(1, min(n, 8) // 2):
            return False, f"{min(n, 8)} 行中 {good} 行しかタイトルとリンクが取れません（row_title / row_link を見直す）。", ""
        if terms and not query_seen:
            return False, (
                f"row セレクタ {res.row!r} の行には検索語「{query}」が 1 つも含まれません。"
                "ナビゲーションやメニューを拾っている可能性が高いので、検索結果本体の繰り返し構造を選んでください。"
            ), ""
        return True, "", first_href

    async def _text_len(self, pg, content_sel: str) -> int:
        for sel in [s.strip() for s in content_sel.split(",") if s.strip()]:
            try:
                loc = pg.locator(sel).first
                if await loc.count():
                    return len((await loc.inner_text()).strip())
            except Exception:  # noqa: BLE001
                continue
        return 0


def save_override(path: Path, site: str, new_cfg: dict[str, Any]) -> None:
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data[site] = new_cfg
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
