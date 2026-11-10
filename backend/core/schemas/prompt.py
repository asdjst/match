from typing import Literal

from pydantic import BaseModel, Field


class PromptBundle(BaseModel):
    """四层 Prompt：system / task / evidence / format，出错能定位到层。"""

    role: Literal["planner", "retriever", "executor", "analyst", "critic", "writer"]
    system: str
    task: str
    evidence_block: str = ""
    format_hint: str = ""


class TextOut(BaseModel):
    text: str


PLANNER_SYSTEM = (
    "你是任务规划器。只输出任务 DAG 的合法 JSON，不输出任何解释。"
    "先出图再执行：检索节点负责查证据，计算类问题加一个 executor 节点调用工具，最后用 analyst 节点汇总结论。"
)
ANALYST_SYSTEM = (
    "你是分析员。只依据给出的编号证据作答，每条结论必须挂对应编号，如 [E1]；"
    "证据里没有的内容不许写。语言简洁，分点陈述。"
    "若证据与问题无关或不足以回答，assertions 必须为空数组 []，禁止把“证据不足”本身写成断言。"
    "翻译、改写、写作、代码、闲聊等任务与公司财报证据无关，assertions 一律输出 []。"
)
CRITIC_SYSTEM = (
    "你是审校员。独立核验：引用编号是否存在、证据是否真的支持该断言、数字是否对得上。"
    "不修改证据，只给 pass / send_back 结论。"
)
CONFIDENCE_SYSTEM = (
    "你是交付置信度评估员。逐条核对断言与引用证据：证据是否直接支持结论、数字是否一致、"
    "是否存在无引用或引用不相关的断言。只输出 0-1 的小数分数与一句理由，不输出其他内容。"
    "评分口径：全部断言有证据直接支撑 0.85-1.0；多数支撑个别存疑 0.6-0.85；"
    "证据部分相关（需推断）0.4-0.6；证据与问题基本无关或大量无引用 0.0-0.4。"
)
GENERIC_SYSTEM = "你是多智能体 RAG 系统的一个执行角色，只依据证据与任务说明工作。"


def system_for(role: str) -> str:
    return {
        "planner": PLANNER_SYSTEM,
        "analyst": ANALYST_SYSTEM,
        "critic": CRITIC_SYSTEM,
        "writer": CONFIDENCE_SYSTEM,
    }.get(role, GENERIC_SYSTEM)
