import re

from core.schemas.agent import AnalystOutput, ComposedAnswer, CriticOutput, ReviewVerdict
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.deliverable import Assertion
from core.schemas.prompt import PromptBundle, TextOut

_GLUCOSE_STATS_RE = re.compile(r"血糖.{0,6}(波动|平均|均值|统计|控制得|怎么样)|最近血糖")
_CARB_TARGET_RE = re.compile(r"(每天|每日|一天).{0,6}(碳水|主食)|三餐.{0,4}(怎么分|分配)")
_OWN_DATA = ("拍照", "工具", "个人记录")


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
        if schema is ComposedAnswer:
            return _compose(prompt)
        if schema is LLMConfidence:
            claims = [l for l in prompt.task.splitlines() if l.strip().startswith("- ")]
            uncited = sum(1 for l in claims if "引用：无" in l)
            score = 0.9 if claims and uncited == 0 else (0.5 if claims else 0.0)
            return LLMConfidence(score=score, reason="假模型评分：按引用覆盖率打分")
        return TextOut(text=prompt.task)


def _plan(task: str) -> TaskDAG:
    question = task.split("QUESTION:", 1)[-1].strip()
    if "【已识别的餐食" in task:
        # 餐食数据已在证据池，离线演示不需要再检索知识卡
        nodes = [NodeSpec(node_id="a1", role="analyst", instruction="依据餐食识别证据估算碳水，保留区间")]
    elif _GLUCOSE_STATS_RE.search(question):
        nodes = [
            NodeSpec(node_id="r1", role="retriever", query=question),
            NodeSpec(
                node_id="x1", role="executor", tool="glucose_summary",
                instruction="统计个人血糖读数的均值与波动", depends_on=["r1"],
            ),
            NodeSpec(node_id="a1", role="analyst", instruction="汇总结论", depends_on=["x1"]),
        ]
    elif _CARB_TARGET_RE.search(question):
        nodes = [
            NodeSpec(node_id="r1", role="retriever", query=question),
            NodeSpec(
                node_id="x1", role="executor", tool="carb_target",
                instruction="按档案估算每日碳水区间与三餐分配", depends_on=["r1"],
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
    rows: list[list[str]] = []
    for line in prompt.evidence_block.splitlines():
        parts = [p.strip() for p in line.split(" :: ", 2)]
        if len(parts) >= 2 and re.fullmatch(r"E\d+", parts[0]):
            rows.append(parts)
    # 断言有上限，本人数据必须排在通用知识卡之前：否则「这餐多少碳水」会引一堆指南原则，
    # 却把真正算出来的碳水与 GL 截掉。组内保持证据池原序。
    rows.sort(key=lambda p: 0 if len(p) > 2 and any(label in p[2] for label in _OWN_DATA) else 1)
    return AnalystOutput(assertions=[Assertion(text=p[1], cites=[p[0]]) for p in rows])


_COMPOSE_LINE_RE = re.compile(r"^- (.+)（引用：(.*)）$")


def _compose(prompt: PromptBundle) -> ComposedAnswer:
    """离线成文：照抄断言并把引用编号补到句尾，保证引用集合与硬数字校验都过。"""
    paragraphs = []
    for line in prompt.task.splitlines():
        matched = _COMPOSE_LINE_RE.match(line.strip())
        if not matched:
            continue
        text, cites = matched.groups()
        inline = set(re.findall(r"\[(E\d+)\]", text))
        tail = "".join(f"[{c}]" for c in re.findall(r"E\d+", cites) if c not in inline)
        paragraphs.append(text + tail)
    return ComposedAnswer(text="\n\n".join(paragraphs))
