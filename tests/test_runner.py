"""AgentRunner のイベント変換・履歴保存・引用解決を、SDK の tool_runner を模したフェイクで検証する。"""
from types import SimpleNamespace

import pytest

from legal_agent.agent.runner import AgentRunner, serialize_content
from legal_agent.agent.sessions import SessionStore
from legal_agent.models import Hit

pytestmark = pytest.mark.anyio


class Ev(SimpleNamespace):
    pass


class FakeStream:
    def __init__(self, events, final):
        self._events, self._final = events, final

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e
        return gen()

    async def get_final_message(self):
        return self._final


class FakeRunner:
    """1 回目: tool_use を返す。2 回目: 本文を返す。"""

    def __init__(self, tools, messages, **params):
        self.tools = {t.name: t for t in tools}
        self.messages = list(messages)
        self.params = params
        self._last = None

    def __aiter__(self):
        async def gen():
            tool_block = Ev(type="tool_use", id="tu1", name="search_cases", input={"query": "解雇", "sources": ["courts"]})
            m1 = Ev(content=[Ev(type="thinking", thinking="考え中", signature="sig"), tool_block], stop_reason="tool_use", usage=None)
            self._last = m1
            yield FakeStream([Ev(type="thinking", thinking="考え中"), Ev(type="content_block_stop", content_block=tool_block)], m1)
            text = "解雇は無効[[courts:9]]。"
            m2 = Ev(content=[Ev(type="text", text=text)], stop_reason="end_turn", usage=Ev(input_tokens=10, output_tokens=5))
            self._last = m2
            yield FakeStream([Ev(type="text", text="解雇は無効"), Ev(type="text", text="[[courts:9]]。")], m2)
        return gen()

    async def generate_tool_call_response(self):
        results = []
        for b in self._last.content:
            if b.type == "tool_use":
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": await self.tools[b.name].call(b.input)})
        return {"role": "user", "content": results} if results else None


class StubCourts:
    name, label, kind, requires_login = "courts", "裁判所", "case", False

    async def search(self, query, limit=20, **f):
        return [Hit(ref="courts:9", source="courts", kind="case", title="令和5(ワ)9 解雇無効確認", subtitle="東京地裁", url="https://x/9")]


class StubRegistry:
    def __init__(self, settings):
        self.settings = settings
        self.courts = StubCourts()

    def get(self, n):
        assert n == "courts"
        return self.courts


def make_client():
    calls = []

    def tool_runner(**kw):
        calls.append(kw)
        return FakeRunner(**kw)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=tool_runner)))
    return client, calls


async def test_runner_end_to_end(settings, tmp_path):
    store = SessionStore(tmp_path / "sessions")
    client, calls = make_client()
    runner = AgentRunner(settings, StubRegistry(settings), store, client=client)
    session = store.create()
    events = [e async for e in runner.run(session, "解雇の有効性は？", {"courts", "local"})]
    types = [e["type"] for e in events]
    assert types[0] == "thinking"
    assert "tool_use" in types and "tool_call" in types and "tool_result" in types and "text_delta" in types
    done = events[-1]
    assert done["type"] == "done"
    assert done["text"] == "解雇は無効[1]。"
    assert done["citations"][0]["ref"] == "courts:9" and done["citations"][0]["number"] == 1
    assert done["usage"]["input"] == 10 and done["usage"]["output"] == 5 and done["usage"]["cost_usd"] > 0
    # 履歴: user / assistant(tool_use) / user(tool_result) / assistant(text)
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert session.messages[1]["content"][0] == {"type": "thinking", "thinking": "考え中", "signature": "sig"}
    assert session.messages[2]["content"][0]["tool_use_id"] == "tu1"
    assert "[ref=courts:9]" in session.messages[2]["content"][0]["content"]
    assert session.turns[-1]["role"] == "assistant" and session.title.startswith("解雇の有効性")
    assert "courts:9" in session.hits
    # 保存されて再読込できる
    store2 = SessionStore(tmp_path / "sessions")
    assert store2.get(session.id).messages == session.messages
    # リクエストパラメータ
    p = calls[0]
    assert p["model"] == "claude-opus-5" and p["stream"] is True and p["thinking"]["type"] == "adaptive"
    assert p["fallbacks"] == "default" and p["output_config"] == {"effort": "high"}
    assert p["cache_control"] == {"type": "ephemeral"} and p["max_iterations"] == 24
    assert p["messages"][0]["content"].startswith("解雇の有効性は？")
    # 使用量は全ターン合算（1 ターン目 usage なし、2 ターン目 10/5）
    assert done["usage"]["input"] == 10 and done["usage"]["output"] == 5 and done["usage"]["turns"] == 1
    assert done["session_usage"]["output"] == 5 and session.usage["output"] == 5
    assert "usage" in types
    # 2 問目: 前の質問のツール結果は圧縮されてから送られ、セッションに残る履歴も圧縮済み
    client2, calls2 = make_client()
    runner2 = AgentRunner(settings, StubRegistry(settings), store, client=client2)
    events2 = [e async for e in runner2.run(session, "追加の質問", {"courts"})]
    sent = calls2[0]["messages"]
    assert sent[0]["content"].startswith("解雇の有効性は？")
    assert all("thinking" != b.get("type") for m in sent[:4] if isinstance(m["content"], list) for b in m["content"])
    assert "_compacted" not in sent[2]["content"][0]
    assert session.compacted_upto == 4 and events2[-1]["type"] == "done"
    assert session.usage["output"] == 10  # 累計


async def test_runner_reports_error(settings, tmp_path):
    store = SessionStore(tmp_path / "s")
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))))
    runner = AgentRunner(settings, StubRegistry(settings), store, client=client)
    events = [e async for e in runner.run(store.create(), "q", {"courts"})]
    assert events[-1]["type"] == "error" and "boom" in events[-1]["message"]


def test_serialize_content_drops_unknown():
    blocks = [Ev(type="text", text="a"), Ev(type="weird"), Ev(type="redacted_thinking", data="zz")]
    assert serialize_content(blocks) == [{"type": "text", "text": "a"}, {"type": "redacted_thinking", "data": "zz"}]
