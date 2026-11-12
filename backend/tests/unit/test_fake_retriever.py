from adapters.retrieval.demo_corpus import KNOWLEDGE_DIR, build_demo_corpus
from adapters.retrieval.fake import FakeRetriever
from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence


def _multimodal_corpus() -> list[Evidence]:
    """模态过滤是通用能力，用显式构造的三模态语料验证，不依赖演示语料的构成。"""
    return [
        Evidence(
            doc_id="card",
            quote="熟米饭每 100 克约含碳水化合物 25.9 克，GI 约 83。",
            source=SourceRef(file_path="常见食物碳水速查_摘编.md", section="米饭与杂粮饭"),
        ),
        Evidence(
            doc_id="photo",
            quote="餐盘照片识别：米饭 225 克，碳水约 58 克。",
            source=SourceRef(file_path="photo://demo", modality="image"),
        ),
        Evidence(
            doc_id="voice",
            quote="语音记录：今天午餐吃了米饭，餐后两小时血糖 10.2。",
            source=SourceRef(file_path="语音记录.m4a", time_code="00:12", modality="audio"),
        ),
    ]


def test_demo_corpus_comes_from_knowledge_cards():
    corpus = build_demo_corpus()
    cards = sorted(KNOWLEDGE_DIR.glob("*.md"))
    # 离线语料就是入库用的知识卡，段数与来源都必须对得上，不允许另编一份假数据
    assert len(corpus) == 37
    assert {e.source.file_path for e in corpus} == {p.name for p in cards}
    assert all(e.source.section for e in corpus)
    assert all(e.quote.strip() for e in corpus)


def test_min_score_filters_weak_hits():
    r = FakeRetriever()
    hits = r.recall("一碗米饭大概多少碳水？")
    assert hits
    assert all(0 < h.score <= 1 for h in hits)
    assert len(hits) <= 5  # top_k 截断
    # 最相关的必须是碳水速查里的米饭段，而不是泛泛的指南原则
    assert hits[0].source.section == "米饭与杂粮饭"


def test_custom_corpus_score_one_filtered():
    corpus = [
        Evidence(doc_id="hit", quote="熟米饭碳水含量与升糖指数"),
        Evidence(doc_id="miss", quote="膳食纤维每日推荐摄入量"),
    ]
    r = FakeRetriever(corpus=corpus)
    hits = r.recall("米饭碳水含量")
    # 只共享 1 个二元组的文档（score=1）必须被过滤
    assert [h.doc_id for h in hits] == ["hit"]


def test_modality_filter():
    r = FakeRetriever(corpus=_multimodal_corpus())
    audio_hits = r.recall("语音记录餐后两小时血糖", filters={"modality": "audio"})
    assert audio_hits
    assert all(h.source.modality == "audio" for h in audio_hits)
    image_hits = r.recall("餐盘照片识别米饭碳水", filters={"modality": "image"})
    assert image_hits
    assert all(h.source.modality == "image" for h in image_hits)
    # 同一查询不加过滤时会混入其他模态，证明过滤真的生效
    mixed = r.recall("餐盘照片识别米饭碳水")
    assert any(h.source.modality != "image" for h in mixed)


def test_results_sorted_by_score_desc():
    r = FakeRetriever()
    hits = r.recall("米饭 杂粮饭 碳水 升糖指数")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)