from adapters.retrieval.demo_corpus import build_demo_corpus
from adapters.retrieval.fake import FakeRetriever
from core.schemas.evidence import Evidence


def test_demo_corpus_shapes():
    corpus = build_demo_corpus()
    # 演示语料 7 条：年报 4 + 截图 1 + 录音 2，覆盖三种模态
    assert len(corpus) == 7
    modalities = {e.source.modality for e in corpus}
    assert modalities == {"text", "image", "audio"}


def test_min_score_filters_weak_hits():
    r = FakeRetriever()
    hits = r.recall("公司2024年营业收入是多少？")
    # 低于 min_score=2 的弱相关（如仅命中"收入"的录音）不回；输出分统一到 0-1
    assert hits
    assert all(0 < h.score <= 1 for h in hits)
    assert all(h.doc_id != "earnings_call" for h in hits)
    assert len(hits) <= 5  # top_k 截断


def test_custom_corpus_score_one_filtered():
    corpus = [
        Evidence(doc_id="hit", quote="公司营业收入再创新高"),
        Evidence(doc_id="miss", quote="公司治理结构稳定"),
    ]
    r = FakeRetriever(corpus=corpus)
    hits = r.recall("公司营业收入")
    # 只共享 1 个二元组的文档（score=1）必须被过滤
    assert [h.doc_id for h in hits] == ["hit"]


def test_modality_filter():
    r = FakeRetriever()
    audio_hits = r.recall("收入增长主要来自核心产品销量提升", filters={"modality": "audio"})
    # modality 过滤后只回对应模态
    assert audio_hits
    assert all(h.source.modality == "audio" for h in audio_hits)
    image_hits = r.recall("报表截图营业收入", filters={"modality": "image"})
    assert image_hits
    assert all(h.source.modality == "image" for h in image_hits)
    # 同一查询不加过滤时会混入其他模态，证明过滤真的生效
    mixed = r.recall("报表截图营业收入")
    assert any(h.source.modality != "image" for h in mixed)


def test_results_sorted_by_score_desc():
    r = FakeRetriever()
    hits = r.recall("营收与毛利率概览 2024年营业收入 2023年")
    scores = [h.score for h in hits]
    # 命中按分数降序返回
    assert scores == sorted(scores, reverse=True)
