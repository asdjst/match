"""成文智能体：把审校通过的断言连成一段回答。

改写只许动措辞与语序，引用编号和硬数字由确定性校验守住；
任何一项不通过就退回逐条断言，不把模型自由发挥的文本当交付物。
"""

from dataclasses import dataclass

from core.schemas.agent import ComposedAnswer
from core.schemas.deliverable import Assertion
from core.schemas.prompt import COMPOSE_SYSTEM, PromptBundle
from core.services.citation import CITE_RE
from core.services.confidence import claim_numbers, numbers_match

MIN_RATIO = 0.5
MAX_RATIO = 1.5
# 只有一两句断言时，衔接词本身就能占几十字：给绝对余量，别把短回答误判成注水
SLACK_CHARS = 40


@dataclass
class ComposeResult:
    text: str | None
    source: str = "assertions"
    reason: str | None = None


def _without_cites(text: str) -> str:
    return CITE_RE.sub("", text)


def _claims_block(assertions: list[Assertion]) -> str:
    return "\n".join(
        f"- {a.text}（引用：{''.join(f'[{c}]' for c in a.cites) or '无'}）" for a in assertions
    )


def _problem(text: str, assertions: list[Assertion]) -> str | None:
    if not text:
        return "成文为空"
    wanted = {c for a in assertions for c in a.cites}
    got = set(CITE_RE.findall(text))
    if got - wanted:
        return f"成文引入了未审校的引用 {'、'.join(sorted(got - wanted))}"
    if wanted - got:
        return f"成文丢了引用 {'、'.join(sorted(wanted - got))}"
    available: set[float] = set()
    for a in assertions:
        available |= claim_numbers(_without_cites(a.text))
    if not numbers_match(claim_numbers(_without_cites(text)), available):
        return "成文出现断言里没有的数值"
    base = sum(len(_without_cites(a.text)) for a in assertions)
    length = len(_without_cites(text))
    if not MIN_RATIO * base <= length <= MAX_RATIO * base + SLACK_CHARS:
        return f"成文长度异常（断言 {base} 字，成文 {length} 字）"
    return None


def compose(llm, question: str, assertions: list[Assertion]) -> ComposeResult:
    if not assertions:
        return ComposeResult(None)
    prompt = PromptBundle(
        role="writer",
        system=COMPOSE_SYSTEM,
        task=f"问题：{question}\n审校通过的断言（按此顺序成文）：\n{_claims_block(assertions)}",
        format_hint='{"text": "连贯回答正文，[E1] 这类引用编号原样保留"}',
    )
    try:
        out: ComposedAnswer = llm.complete(prompt, tier="fast", schema=ComposedAnswer)
        text = (out.text or "").strip()
    except Exception:
        return ComposeResult(None, reason="成文模型调用失败，按断言逐条呈现")
    problem = _problem(text, assertions)
    if problem:
        return ComposeResult(None, reason=f"{problem}，按断言逐条呈现")
    return ComposeResult(text, source="llm")