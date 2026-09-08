import pytest

pytestmark = pytest.mark.anyio

from legal_agent.index.db import IndexDB, make_snippet, query_to_match, to_bigrams
from legal_agent.sources.local_pdf import LocalPDFSource


def test_bigrams_and_query():
    assert to_bigrams("労働契約 Article9") == "労働 働契 契約 article9"
    m, singles = query_to_match("労働契約 解雇 法")
    assert m == '"労働 働契 契約" AND "解雇"'
    assert singles == ["法"]


@pytest.fixture
def db(tmp_path):
    db = IndexDB(tmp_path / "idx.sqlite3")
    db.add_document(
        "doc1", "/books/labor.pdf", "労働法講義", "山田太郎", "", 1.0, 100,
        [(1, "第1章 労働契約の成立\n労働契約は合意により成立する。"), (2, "第2章 解雇\n解雇は客観的に合理的な理由を欠く場合は無効である（労働契約法16条）。"), (3, "")],
    )
    db.add_document("doc2", "/books/civil.pdf", "民法入門", "", "", 1.0, 100, [(1, "契約は申込みと承諾で成立する。")])
    return db


def test_search_ranking_and_snippet(db):
    hits = db.search("解雇 合理的")
    assert [(h.doc_id, h.page_no) for h in hits] == [("doc1", 2)]
    assert "解雇" in make_snippet(hits[0].text, "解雇")
    hits = db.search("契約")
    assert {(h.doc_id, h.page_no) for h in hits} == {("doc1", 1), ("doc1", 2), ("doc2", 1)}
    assert db.search("契約", doc_id="doc2")[0].doc_id == "doc2"
    # 1 文字語は LIKE + 事後フィルタ
    assert [(h.doc_id, h.page_no) for h in db.search("解雇 条")] == [("doc1", 2)]
    assert db.search("存在しない語") == []
    assert db.stats()["documents"] == 2


def test_delete_and_reindex(db):
    db.add_document("doc1", "/books/labor.pdf", "労働法講義 第2版", "山田太郎", "", 2.0, 120, [(1, "改訂版の本文 解雇")])
    assert db.stats() == {"documents": 2, "pages": 2, "db_path": db.stats()["db_path"]}
    assert db.search("解雇")[0].title == "労働法講義 第2版"
    db.delete_document("doc1")
    assert db.search("解雇") == []


async def test_local_source(settings, db):
    src = LocalPDFSource(settings, db)
    hits = await src.search("解雇")
    assert hits[0].ref == "local:doc1:p2"
    assert hits[0].url == "/pdf/doc1#page=2"
    assert hits[0].meta["book_id"] == "doc1"
    doc = await src.fetch("doc1", page=2, span=1)
    assert "――― p.1 ―――" in doc.text and "――― p.2 ―――" in doc.text
    assert doc.title == "労働法講義"
    doc = await src.fetch("local:doc1:p1", span=0)
    assert "第1章" in doc.text and "第2章" not in doc.text
    with pytest.raises(KeyError):
        await src.fetch("nope")
    st = await src.status()
    assert st["available"] is True


def test_indexer_with_real_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from legal_agent.index.indexer import index_dirs

    books = tmp_path / "books"
    books.mkdir()
    pdf = books / "佐藤_契約法概説.pdf"
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} contract law", fontsize=12)
    doc.save(str(pdf))
    doc.close()
    db = IndexDB(tmp_path / "idx.sqlite3")
    st = index_dirs(db, [books], log=lambda s: None)
    assert st["added"] == 1 and st["documents"] == 1 and st["pages"] == 2
    row = db.list_documents()[0]
    assert row["title"] == "契約法概説" and row["author"] == "佐藤"
    assert db.search("contract")[0].page_no == 1
    # 変更なしならスキップ
    assert index_dirs(db, [books], log=lambda s: None)["skipped"] == 1
    pdf.unlink()
    assert index_dirs(db, [books], log=lambda s: None)["removed"] == 1
