import re

from core.graph.nodes.common import _budget_stop, _evidence_block, _pool
from core.schemas.agent import CriticOutput, ReviewVerdict
from core.schemas.dag import TaskDAG
from core.schemas.prompt import PromptBundle, system_for

# 模型偶尔把“通过项/表扬”写进 issues。那不是可执行的修改点，不能据此打回。
_POSITIVE_ISSUE = re.compile(
    r"^(通过|符合|正确|准确|完整|一致|无误|已核实|未发现|无问题|均无|"
    r"没有(发现)?(问题|异常)|引用(编号)?均|断言(均|全部)|证据(均|充足|充分))"
)


def make_critic(llm=None):
    from core.schemas.deliverable import Assertion
    from core.services.citation import validate_assertions

    def critic(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        assertions = [Assertion(**a) for a in state.get("assertions", [])]
        issues = validate_assertions(assertions, pool)
        send_back_to = "retriever"
        budget_stop = state.get("budget_stop") or _budget_stop(state, dag, include_steps=False)
        # LLM 自检双通道：规则之外独立核验证据支撑度；失败静默降级为规则结论。
        # 预算耗尽时不再调用 LLM，也不再打回，直接放行让 writer 输出降级结论。
        if not budget_stop and llm is not None and assertions:
            llm_issues, llm_target = _llm_review(llm, state, pool, assertions)
            issues += [i for i in llm_issues if i not in issues]
            if llm_target:
                send_back_to = llm_target
        round_no = state.get("round_no", 0)
        if budget_stop:
            verdict = ReviewVerdict(verdict="pass", round_no=round_no)
        elif issues:
            verdict = ReviewVerdict(
                verdict="send_back",
                issues=issues,
                send_back_to=send_back_to,
                round_no=round_no + 1,
            )
        else:
            verdict = ReviewVerdict(verdict="pass", round_no=round_no)
        node_results = dict(state.get("node_results", {}))
        node_results["critic"] = {
            "node_id": "critic",
            "status": "done",
            "output": verdict.model_dump(),
            **({"budget_stop": budget_stop} if budget_stop else {}),
        }
        out = {"verdict": verdict.model_dump(), "round_no": verdict.round_no, "node_results": node_results}
        if budget_stop:
            out["budget_stop"] = budget_stop
        return out

    return critic


def _llm_review(llm, state: dict, pool: dict, assertions) -> tuple[list[str], str | None]:
    try:
        claims = "\n".join(f"- {a.text}（引用：{a.cites}）" for a in assertions)
        prompt = PromptBundle(
            role="critic",
            system=system_for("critic"),
            task=f"问题：{state['question']}\n待核验断言：\n{claims}",
            evidence_block=_evidence_block(pool),
            format_hint='{"verdict":"pass 或 send_back","issues":["具体问题"],"send_back_to":"analyst / retriever / planner"}',
        )
        out = llm.complete(prompt, tier="fast", schema=CriticOutput)
    except Exception:
        return [], None
    if out.verdict != "send_back":
        return [], None
    issues = [i for i in out.issues if i and not _POSITIVE_ISSUE.search(i.strip())]
    if not issues:
        # 只给了通过项/表扬，没有具体问题 → 不构成打回理由
        return [], None
    return issues[:5], out.send_back_to
