"""ローカルの疑似サイト（ログイン → 検索 → 詳細）に対して、自動ログイン・検索・本文取得・自動設定を通しで検証する。"""
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from legal_agent.browser.session import BrowserSession
from legal_agent.models import LoginRequired
from legal_agent.sources.browser_site import BrowserSiteSource, load_site_config

pytestmark = pytest.mark.anyio
pytest.importorskip("playwright")

USER, PASS = "taro", "secret"


def make_fake_site() -> FastAPI:
    app = FastAPI()
    sessions: set[str] = set()

    def logged(req: Request) -> bool:
        return req.cookies.get("sid") in sessions

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return """<html><body><h1>ログイン</h1><form method=post action=/login>
        <input id=uid name=uid><input id=pw name=pw type=password><input id=keep type=checkbox name=keep>
        <button id=go type=submit>ログイン</button></form></body></html>"""

    @app.post("/login")
    async def do_login(req: Request):
        form = parse_qs((await req.body()).decode())
        uid, pw = form.get("uid", [""])[0], form.get("pw", [""])[0]
        if uid == USER and pw == PASS:
            sessions.add("ok")
            r = RedirectResponse("/", status_code=303)
            r.set_cookie("sid", "ok", max_age=3600)  # 「ログイン状態を維持」相当の永続 Cookie
            return r
        return HTMLResponse("<html><body><p>失敗</p><form><input id=pw type=password></form></body></html>")

    @app.get("/", response_class=HTMLResponse)
    def home(req: Request):
        if not logged(req):
            return RedirectResponse("/login", status_code=303)
        return """<html><body><a href="/logout">ログアウト</a><form action=/search method=get>
        <input id=q name=q type=text placeholder="キーワード"><button type=submit>検索</button></form></body></html>"""

    @app.get("/search", response_class=HTMLResponse)
    def search(req: Request, q: str = ""):
        if not logged(req):
            return RedirectResponse("/login", status_code=303)
        rows = "".join(
            f'<tr class="hit"><td><a href="/doc/{i}">{q} 判決 {i}</a></td><td>東京地裁 令和{i}年</td></tr>' for i in range(1, 6)
        )
        return f'<html><body><a href="/logout">ログアウト</a><div class="Results"><table id="results"><tbody>{rows}</tbody></table></div><ul class="nav"><li><a href="/">ホーム</a></li><li><a href="/faq">FAQ</a></li><li><a href="/x">X</a></li></ul></body></html>'

    @app.get("/doc/{n}", response_class=HTMLResponse)
    def doc(req: Request, n: int):
        if not logged(req):
            return RedirectResponse("/login", status_code=303)
        body = ("主文 本件請求を棄却する。理由 " * 40) + f"（判決 {n}）"
        return f'<html><body><a href="/logout">ログアウト</a><nav>メニュー</nav><article id="judgment">{body}</article></body></html>'

    return app


@pytest.fixture(scope="module")
def site_url():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(make_fake_site(), host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def site_cfg(base: str, good_selectors: bool = True) -> dict:
    return {
        "label": "疑似サイト",
        "home_url": base + "/",
        "login_url": base + "/login",
        "check_url": base + "/",
        "login_url_pattern": "/login",
        "login_form_selector": "input#pw",
        "logged_in_selector": "a[href='/logout']",
        "login": {"user": "#uid", "password": "#pw", "remember": "#keep", "submit": "#go"},
        "search": {
            "url": base + "/search?q={query}" if good_selectors else base + "/",
            "input": "#q", "submit": "button[type=submit]",
            "results_wait": "#results" if good_selectors else "body",
            "row": "tr.hit" if good_selectors else "table.nonexistent tr",
            "row_title": "a", "row_link": "a", "row_meta": "td", "max_rows": 20,
        },
        "detail": {"wait": "article", "content": "#judgment" if good_selectors else "#nope"},
    }


@pytest.fixture
async def browser(settings):
    b = BrowserSession(settings)
    yield b
    await b.close()


async def test_auto_login_search_fetch(settings, browser, site_url):
    cfg = site_cfg(site_url)
    src = BrowserSiteSource("tkc", "case", settings, browser, cfg=cfg)
    # 認証情報なし → LoginRequired
    with pytest.raises(LoginRequired):
        await src.search("解雇")
    # 誤ったパスワード → 失敗
    assert await browser.auto_login("tkc", cfg, USER, "wrong") is False
    assert "自動ログイン" in browser.last_error["tkc"]
    # 正しい認証情報 → 成功し、以後は Cookie で維持
    settings.tkc_user, settings.tkc_password = USER, PASS
    hits = await src.search("解雇", limit=3)
    assert [h.title for h in hits] == ["解雇 判決 1", "解雇 判決 2", "解雇 判決 3"]
    assert hits[0].subtitle == "東京地裁 令和1年"
    assert hits[0].ref.startswith("tkc:doc_1")
    doc = await src.fetch(hits[1].meta["item_id"])
    assert "（判決 2）" in doc.text and "メニュー" not in doc.text
    doc2 = await src.fetch(hits[1].ref, offset=doc.total_chars - 5)
    assert len(doc2.text) == 5
    st = await src.status()
    assert st["logged_in"] is True and st["auto_login"] is True
    # 新しいブラウザセッションでも Cookie が残っていてログイン不要
    await browser.close()
    b2 = BrowserSession(settings)
    try:
        assert await b2.check_logged_in("tkc", cfg) is True
    finally:
        await b2.close()


class FakeParsedClient:
    """messages.parse を模し、要約に含まれる実要素からセレクタを返す。"""

    def __init__(self):
        self.calls = []

    class _Messages:
        def __init__(self, outer):
            self.outer = outer

        async def parse(self, *, output_format, messages, **kw):
            self.outer.calls.append(output_format.__name__)
            name = output_format.__name__
            if name == "SearchEntryProposal":
                return SimpleNamespace(parsed_output=output_format(search_url="", input_selector="#q", submit_selector="button[type=submit]"))
            if name == "ResultsProposal":
                # 1 回目はわざと悪い提案 → 検証で弾かれ、2 回目で正しい提案
                bad = self.outer.calls.count("ResultsProposal") == 1
                return SimpleNamespace(parsed_output=output_format(results_wait="#results", row="ul.nav li" if bad else "tr.hit", row_title="a", row_link="a", row_meta="td"))
            return SimpleNamespace(parsed_output=output_format(wait="article", content="#judgment"))

    @property
    def messages(self):
        return self._Messages(self)


async def test_autoconf_recovers_bad_selectors(settings, browser, site_url, tmp_path):
    settings.tkc_user, settings.tkc_password = USER, PASS
    settings.auto_configure = True
    cfg = site_cfg(site_url, good_selectors=False)
    src = BrowserSiteSource("tkc", "case", settings, browser, cfg=cfg)
    assert await src.search("解雇") == []  # 壊れたセレクタ（自動設定は client 無しでは API に出られないので失敗扱い）
    client = FakeParsedClient()
    new_cfg = await src.autoconfigure("解雇", client=client)
    assert new_cfg["search"]["row"] == "tr.hit" and new_cfg["search"]["input"] == "#q"
    assert new_cfg["detail"]["content"] == "#judgment"
    assert client.calls.count("ResultsProposal") == 2  # 悪い提案は検証で弾かれて再提案された
    assert settings.selectors_override_path.exists()
    merged = load_site_config("tkc", override_path=settings.selectors_override_path)
    assert merged["_override"] is True and merged["search"]["row"] == "tr.hit" and merged["login"]["user"] == "#LoginAccount"
    # 発見した設定で検索できる
    src.cfg.update({"search": new_cfg["search"], "detail": new_cfg["detail"]})
    hits = await src.search("解雇", limit=2)
    assert len(hits) == 2 and "判決" in hits[0].title
