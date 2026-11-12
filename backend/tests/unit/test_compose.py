"""成文智能体：连贯改写可以，引用与硬数字不许变；校验不过就退回逐条断言。"""

import re

import pytest

from adapters.llm.fake import FakeLLM
from core.graph.nodes.roles import make_writer
from core.schemas.agent import ComposedAnswer
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import COMPOSE_SYSTEM
from core.services.compose import compose
from core.services.confidence import LLMConfidence

GOOD = (
    "上次那 150 克冰激凌之后，餐后 2 小时血糖到了 18 mmol/L[E1]。"
    "这次别照着上次的量吃，减到 75 克以内，先吃蔬菜和蛋白质，最后再吃冰激凌[E1][E2]。"
    "吃完 2 小时再测一次，跟上次的 18 对照着看[E1]。"
)


def _assertions() -> list[Assertion]:
    return [
        Assertion(text="上次吃了约150克冰激凌，餐后2小时血糖18 mmol/L。", cites=["E1"]),
        Assertion(text="这次把份量减到50～75克，先吃蔬菜和蛋白质再吃冰激凌。", cites=["E1", "E2"]),
        Assertion(text="餐后2小时复测一次，和上次的18做对照。", cites=["E1"]),
    ]


class StubLLM:
    def __init__(self, text: str | None = None, exc: Exception | None = None):
        self._text = text
        self._exc = exc
        self.calls: list[dict] = []

    def complete(self, prompt, tier, schema=None):
        self.calls.append({"prompt": prompt, "tier": tier, "schema": schema})
        if self._exc is not None:
            raise self._exc
        if schema is LLMConfidence:
            return LLMConfidence(score=0.9, reason="引用成立")
        return ComposedAnswer(text=self._text)


def test_composed_answer_keeps_cites_and_numbers():
    llm = StubLLM(GOOD)

    res = compose(llm, "冰激凌还能吃吗？", _assertions())

    assert res.text == GOOD
    assert res.source == "llm"
    assert res.reason is None
    call = llm.calls[0]
    # 成文是短文本任务，走快档；用 writer 角色但换成成文 system
    assert call["tier"] == "fast"
    assert call["schema"] is ComposedAnswer
    assert call["prompt"].role == "writer"
    assert call["prompt"].system == COMPOSE_SYSTEM
    assert "冰激凌还能吃吗？" in call["prompt"].task
    assert "[E2]" in call["prompt"].task


@pytest.mark.parametrize("text, fragment", [
    (GOOD.replace("[E2]", ""), "丢了引用 E2"),
    (GOOD + "另外建议每天走 30 分钟[E3]。", "未审校的引用 E3"),
    (GOOD.replace("75 克", "100 克"), "断言里没有的数值"),
    ("", "成文为空"),
    ("少吃点[E1][E2]。", "长度异常"),
    (GOOD * 3, "长度异常"),
])
def test_invalid_composition_falls_back_to_assertions(text, fragment):
    res = compose(StubLLM(text), "冰激凌还能吃吗？", _assertions())

    assert res.text is None
    assert res.source == "assertions"
    assert fragment in res.reason


def test_range_must_not_become_a_single_point():
    assertions = [Assertion(text="拍照识别这碗汤碳水 30-60g，属于估算。", cites=["E1"])]

    res = compose(StubLLM("这碗汤碳水约 45g[E1]，属于估算，喝之前心里有个数。"), "这碗汤多少碳水？", assertions)

    assert res.text is None
    assert "数值" in res.reason


def test_rounded_integer_is_the_same_number():
    assertions = [Assertion(text="这碗米饭碳水约38.9克。", cites=["E1"])]

    res = compose(StubLLM("这碗米饭的碳水大约 39 克[E1]，主食按这个量算就行。"), "米饭多少碳水？", assertions)

    assert res.source == "llm"


def test_llm_failure_falls_back_explicitly():
    res = compose(StubLLM(exc=RuntimeError("模型不可用")), "q", _assertions())

    assert res.text is None
    assert "调用失败" in res.reason


def test_no_assertions_skips_the_model():
    llm = StubLLM(exc=AssertionError("不应被调用"))

    res = compose(llm, "q", [])

    assert res.text is None
    assert llm.calls == []


def _writer_state(**extra) -> dict:
    dag = TaskDAG(question="冰激凌还能吃吗？", nodes=[NodeSpec(node_id="a1", role="analyst")])
    pool = {
        "E1": Evidence(
            evidence_id="E1", doc_id="meal-1", channel="memory", score=0.9,
            quote="个人记录：午餐冰激凌约150g（碳水约25.9g，食物库估算）；血糖：餐后2小时18 mmol/L",
        ).model_dump(),
        "E2": Evidence(
            evidence_id="E2", doc_id="d2", score=0.8, quote="进食顺序：先吃蔬菜与蛋白质，最后吃主食。",
        ).model_dump(),
    }
    state = {
        "question": "冰激凌还能吃吗？",
        "dag": dag.model_dump(),
        "evidence": pool,
        "assertions": [a.model_dump() for a in _assertions()],
        "verdict": {"verdict": "pass", "issues": []},
        "trace_id": "t1",
    }
    state.update(extra)
    return state


def test_writer_delivers_composed_answer_and_keeps_assertions():
    llm = StubLLM(GOOD)

    d = make_writer(0.45, llm)(_writer_state())["deliverable"]

    assert d["answer"] == GOOD
    assert d["answer_source"] == "llm"
    assert d["answer_note"] is None
    # 成文不取代逐条依据：断言与引用表原样保留，可核对
    assert len(d["assertions"]) == 3
    assert [c["evidence_id"] for c in d["citations"]] == ["E1", "E2"]
    assert d["refused"] is False


def test_writer_falls_back_and_records_why():
    d = make_writer(0.45, StubLLM(GOOD.replace("[E2]", "")))(_writer_state())["deliverable"]

    assert d["answer"] is None
    assert d["answer_source"] == "assertions"
    assert "丢了引用 E2" in d["answer_note"]
    assert d["refused"] is False


def test_refused_delivery_is_not_composed():
    class LowScore(StubLLM):
        def complete(self, prompt, tier, schema=None):
            self.calls.append({"prompt": prompt, "tier": tier, "schema": schema})
            return LLMConfidence(score=0.1, reason="证据不足")

    llm = LowScore()

    d = make_writer(0.45, llm)(_writer_state())["deliverable"]

    assert d["refused"] is True
    assert d["answer"] is None
    assert all(c["schema"] is not ComposedAnswer for c in llm.calls)


def test_budget_exhausted_delivery_skips_composition():
    llm = StubLLM(GOOD)

    d = make_writer(0.45, llm)(_writer_state(budget_stop="耗时预算用尽（130s > 120s）"))["deliverable"]

    assert d["degraded"] is True
    assert d["answer"] is None
    assert all(c["schema"] is not ComposedAnswer for c in llm.calls)


def test_writer_without_llm_keeps_assertion_only_delivery():
    d = make_writer(0.45)(_writer_state())["deliverable"]

    assert d["answer"] is None
    assert d["answer_source"] == "assertions"
    assert d["answer_note"] is None


def test_offline_fake_llm_composition_passes_validation():
    d = make_writer(0.45, FakeLLM())(_writer_state())["deliverable"]

    assert d["answer_source"] == "llm"
    assert d["answer"]
    # 离线成文照抄断言，引用编号一条不丢也不多
    assert set(re.findall(r"\[(E\d+)\]", d["answer"])) == {"E1", "E2"}
    assert d["answer_note"] is None