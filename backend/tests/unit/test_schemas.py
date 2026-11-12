import pytest
from pydantic import ValidationError

from core.schemas.common import SourceRef
from core.schemas.dag import Budget, NodeSpec, TaskDAG
from core.schemas.ingest import IngestDoc


def test_nodespec_rejects_illegal_role():
    # 非法 role 必须在构造期就被 pydantic 拒绝
    with pytest.raises(ValidationError):
        TaskDAG(question="q", nodes=[{"node_id": "n1", "role": "hacker"}])


def test_source_ref_label_combinations():
    # 四字段齐全时按 file_path/section/page/time_code 顺序拼接；纯数字 section 补成"第N段"
    full = SourceRef(file_path="指南.pdf", section="87", page=2, time_code="03:12")
    assert full.label() == "指南.pdf 第87段 第2页 03:12"
    # md 小标题原样展示，不能再套一层"第…段"
    heading = SourceRef(file_path="常见食物碳水速查_摘编.md", section="米饭与杂粮饭")
    assert heading.label() == "常见食物碳水速查_摘编.md 米饭与杂粮饭"
    # PDF 解析器已给出定位串，不重复包装
    assert SourceRef(file_path="指南.pdf", section="第87段").label() == "指南.pdf 第87段"
    # 只有文件名
    assert SourceRef(file_path="x.pdf").label() == "x.pdf"
    # 全空 → 兜底文案
    assert SourceRef().label() == "未知来源"
    # 音频：文件名 + 时间码
    audio = SourceRef(file_path="语音记录.m4a", time_code="07:45", modality="audio")
    assert audio.label() == "语音记录.m4a 07:45"


def test_taskdag_by_role():
    dag = TaskDAG(
        question="q",
        nodes=[
            NodeSpec(node_id="r1", role="retriever"),
            NodeSpec(node_id="x1", role="executor"),
            NodeSpec(node_id="a1", role="analyst"),
            NodeSpec(node_id="r2", role="retriever"),
        ],
    )
    # by_role 按声明顺序过滤同角色节点
    assert [n.node_id for n in dag.by_role("retriever")] == ["r1", "r2"]
    assert dag.by_role("executor")[0].node_id == "x1"
    assert dag.by_role("critic") == []


def test_taskdag_max_rounds():
    # max_rounds 取首个节点的 budget
    dag = TaskDAG(
        question="q",
        nodes=[NodeSpec(node_id="n1", role="planner", budget=Budget(max_rounds=5))],
    )
    assert dag.max_rounds() == 5
    # 默认 budget.max_rounds == 3
    assert TaskDAG(question="q", nodes=[NodeSpec(node_id="n1", role="planner")]).max_rounds() == 3
    # 空节点列表回退默认 3
    assert TaskDAG(question="q").max_rounds() == 3


def test_ingest_doc_modality_validation():
    # IngestDoc 只接受三种模态
    doc = IngestDoc(doc_id="d1", modality="image", source=SourceRef(file_path="s.png"), collection_id="c")
    assert doc.modality == "image"
    with pytest.raises(ValidationError):
        IngestDoc(doc_id="d2", modality="video", source=SourceRef(), collection_id="c")
