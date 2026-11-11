from adapters.llm.fake import FakeLLM
from core.graph.nodes.roles import make_planner, make_retriever
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.evidence import Evidence
from core.services.memory import SessionMemory


def test_append_and_history():
    m = SessionMemory()
    for i in range(3):
        m.append("s1", {"i": i})
    # history 默认取最近 5 条，可按 last 截取
    assert m.history("s1") == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert m.history("s1", last=2) == [{"i": 1}, {"i": 2}]


def test_history_unknown_session():
    m = SessionMemory()
    # 未知的 session 返回空列表而不报错
    assert m.history("nope") == []


def test_history_is_bounded():
    m = SessionMemory(max_items=2)
    for i in range(5):
        m.append("s1", {"i": i})

    assert m.history("s1") == [{"i": 3}, {"i": 4}]


class CaptureLLM(FakeLLM):
    def __init__(self):
        self.prompts = []

    def complete(self, prompt, tier, schema=None):
        self.prompts.append(prompt)
        return super().complete(prompt, tier, schema)


def test_planner_prompt_includes_history_but_keeps_question():
    llm = CaptureLLM()

    out = make_planner(llm)(
        {
            "question": "那2023年呢？",
            "round_no": 0,
            "history": [{"question": "公司2024年营业收入是多少？", "answer": "120亿元"}],
        }
    )

    prompt = llm.prompts[0]
    assert "对话历史" in prompt.task
    assert "不得当作证据" in prompt.task
    assert "公司2024年营业收入是多少？" in prompt.task
    assert prompt.task.rstrip().endswith("QUESTION: 那2023年呢？")
    assert "指代" in prompt.format_hint
    # FakeLLM 原样回填，真实 planner 会按提示改写
    assert out["dag"]["question"] == "那2023年呢？"


class EchoPort:
    def __init__(self):
        self.queries = []
        self.last_report = []

    def recall(self, query, filters=None):
        self.queries.append(query)
        return [Evidence(doc_id="d1", quote="证据")]


def test_retriever_uses_rewritten_dag_question():
    dag = TaskDAG(question="公司2023年营业收入是多少？", nodes=[NodeSpec(node_id="r1", role="retriever")])
    port = EchoPort()
    state = {
        "question": "那2023年呢？",
        "round_no": 0,
        "dag": dag.model_dump(),
        "evidence": {},
        "node_results": {},
    }

    make_retriever(port)(state)

    # 节点没有单独 query 时，优先用 planner 消解指代后的 dag.question
    assert port.queries == ["公司2023年营业收入是多少？"]
