import re

from core.schemas.agent import AnalystOutput, CriticOutput, ReviewVerdict
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.deliverable import Assertion
from core.schemas.prompt import PromptBundle, TextOut

_CALC_RE = re.compile(r"同比|环比|增长|变化|计算")


class FakeLLM:
    """确定性假 LLM：按角色脚本出结构化结果，单测与断网演示全离线可复现。"""

    def complete(self, prompt: PromptBundle, tier: str, schema: type | None = None):
        from core.services.confidence import LLMConfidence

        if schema is TaskDAG:
            return _plan(prompt.task)
        if schema is ReviewVerdict or schema is CriticOutput:
            return CriticOutput()
        if schema is AnalystOutput:
            return _analyze(prompt)
        if schema is LLMConfidence:
            claims = [l for l in prompt.task.splitlines() if l.strip().startswith("- ")]
            uncited = sum(1 for l in claims if "引用：无" in l)
            score = 0.9 if claims and uncited == 0 else (0.5 if claims else 0.0)
            return LLMConfidence(score=score, reason="假模型评分：按引用覆盖率打分")
        return TextOut(text=prompt.task)


def _plan(task: str) -> TaskDAG:
    question = task.split("QUESTION:", 1)[-1].strip()
    if "【已识别的餐食" in task:
        # 餐食数据已在证据池，离线演示不需要再检索财报语料
        nodes = [NodeSpec(node_id="a1", role="analyst", instruction="依据餐食识别证据估算碳水，保留区间")]
    elif _CALC_RE.search(question):
        nodes = [
            NodeSpec(node_id="r1", role="retriever", query=question),
            NodeSpec(
                node_id="x1", role="executor", tool="growth_rate",
                instruction="取证据中两个年度营收数值计算同比", depends_on=["r1"],
            ),
            NodeSpec(node_id="a1", role="analyst", instruction="汇总结论", depends_on=["x1"]),
        ]
    else:
        nodes = [
            NodeSpec(node_id="r1", role="retriever", query=question),
            NodeSpec(node_id="a1", role="analyst", instruction="汇总结论", depends_on=["r1"]),
        ]
    return TaskDAG(question=question, nodes=nodes)


def _analyze(prompt: PromptBundle) -> AnalystOutput:
    assertions: list[Assertion] = []
    for line in prompt.evidence_block.splitlines():
        parts = [p.strip() for p in line.split(" :: ", 2)]
        if len(parts) >= 2 and re.fullmatch(r"E\d+", parts[0]):
            assertions.append(Assertion(text=parts[1], cites=[parts[0]]))
    return AnalystOutput(assertions=assertions)
