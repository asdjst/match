import re

from langgraph.types import interrupt

from core.schemas.agent import CriticOutput, ReviewVerdict
from core.schemas.common import SourceRef
from core.schemas.dag import TaskDAG
from core.schemas.evidence import Evidence
from core.schemas.prompt import ANALYST_SYSTEM, PromptBundle, system_for

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*亿")
_CHANNEL_LABELS = {"local": "本地库", "web": "Web", "cloud": "云端网盘"}


def _pool(state: dict) -> dict[str, Evidence]:
    return {k: Evidence(**v) for k, v in state.get("evidence", {}).items()}


def _evidence_block(pool: dict[str, Evidence]) -> str:
    # 分隔符用 " :: "：语料 quote 里可能自带 "|"（表格行），不能用竖线
    return "\n".join(
        f"{eid} :: {ev.quote} :: ({ev.source.label()} · {_CHANNEL_LABELS.get(ev.channel, ev.channel)})"
        for eid, ev in pool.items()
    )


def make_planner(llm):
    def planner(state: dict) -> dict:
        prompt = PromptBundle(
            role="planner",
            system=system_for("planner"),
            task=f"QUESTION: {state['question']}",
            format_hint=(
                '只输出 JSON，形如 {"question":"…","nodes":[{"node_id":"r1","role":"retriever",'
                '"instruction":"…","depends_on":[],"budget":{"max_steps":8,"max_rounds":3,"timeout_s":120},'
                '"tool":null,"query":"检索词"}]}，role 取值 planner/retriever/executor/analyst/critic，'
                "budget 必须是对象不是数字；计算增长率时 executor 节点的 tool 只能填 growth_rate"
            ),
        )
        dag = llm.complete(prompt, tier="strong", schema=TaskDAG)
        return {"dag": dag.model_dump(), "round_no": state.get("round_no", 0)}

    return planner


def make_retriever(retriever_port):
    def retriever(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        node_results = dict(state.get("node_results", {}))
        for spec in dag.by_role("retriever"):
            query = spec.query or state["question"]
            hits = retriever_port.recall(query, filters=state.get("filters"))
            used = []
            existing = {(e.doc_id, e.quote) for e in pool.values()}
            for ev in hits:
                if (ev.doc_id, ev.quote) in existing:
                    continue
                eid = _next_id(pool)
                ev = ev.model_copy(update={"evidence_id": eid})
                pool[eid] = ev
                existing.add((ev.doc_id, ev.quote))
                used.append(eid)
            # 审校打回会重跑检索：证据编号跨轮累计，避免后一轮覆盖前一轮的取证记录
            prev_used = (node_results.get(spec.node_id) or {}).get("evidence_used") or []
            node_results[spec.node_id] = {
                "node_id": spec.node_id,
                "status": "done",
                "evidence_used": list(dict.fromkeys([*prev_used, *used])),
                # 三通道检索记录：渠道/命中数/耗时/状态，持久化后可查
                "retrievals": getattr(retriever_port, "last_report", []) or [],
            }
        return {"evidence": {k: v.model_dump() for k, v in pool.items()}, "node_results": node_results}

    return retriever


def make_executor(tools):
    def executor(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        node_results = dict(state.get("node_results", {}))
        available = tools.list_tools()
        for spec in dag.by_role("executor"):
            args = out = nums = None
            blocked = None
            if spec.tool not in available:
                # 真 planner 可能编造工具名；降级为无工具证据，由 analyst 依检索证据作答
                blocked = f"工具不可用：{spec.tool}"
            else:
                nums = _year_numbers(pool)
                args = {"a": nums[0], "b": nums[1]} if len(nums) >= 2 else None
                if args is None:
                    blocked = "证据中不足两个年度数值，无法计算"
                else:
                    try:
                        out = tools.call(spec.tool, args)
                    except KeyError:
                        blocked = f"工具不可用：{spec.tool}"
            if blocked is None and not out.get("ok", True):
                blocked = f"工具执行失败：{out.get('error', '未知错误')}"
            if blocked is not None:
                node_results[spec.node_id] = {
                    "node_id": spec.node_id,
                    "status": "blocked",
                    "block_reason": blocked,
                }
                continue
            eid = _next_id(pool)
            unit = out.get("unit", "")
            ev = Evidence(
                evidence_id=eid,
                doc_id="tool",
                quote=f"工具计算：{nums[0]} 对比 {nums[1]} → {out.get('result')}{unit}",
                score=3.0,
                source=SourceRef(file_path=f"tool://{spec.tool}"),
            )
            pool[eid] = ev
            node_results[spec.node_id] = {
                "node_id": spec.node_id,
                "status": "done",
                "output": {"args": args, **out},
                "evidence_used": [eid],
            }
        return {"evidence": {k: v.model_dump() for k, v in pool.items()}, "node_results": node_results}

    return executor


def make_analyst(llm):
    def analyst(state: dict) -> dict:
        from core.schemas.agent import AnalystOutput

        prompt = PromptBundle(
            role="analyst",
            system=ANALYST_SYSTEM,
            task=f"问题：{state['question']}",
            evidence_block=_evidence_block(_pool(state)),
            format_hint='{"assertions":[{text, cites:[…]}]}；证据与问题无关时输出 {"assertions":[]}',
        )
        out = llm.complete(prompt, tier="strong", schema=AnalystOutput)
        node_results = dict(state.get("node_results", {}))
        node_results["analyst"] = {
            "node_id": "analyst",
            "status": "done",
            "evidence_used": [c for a in out.assertions for c in a.cites],
        }
        return {
            "assertions": [a.model_dump() for a in out.assertions],
            "node_results": node_results,
        }

    return analyst


def make_critic(llm=None):
    from core.schemas.deliverable import Assertion
    from core.services.citation import validate_assertions

    def critic(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        assertions = [Assertion(**a) for a in state.get("assertions", [])]
        issues = validate_assertions(assertions, pool)
        send_back_to = "retriever"
        # LLM 自检双通道：规则之外独立核验证据支撑度；失败静默降级为规则结论
        if llm is not None and assertions:
            llm_issues, llm_target = _llm_review(llm, state, pool, assertions)
            issues += [i for i in llm_issues if i not in issues]
            if llm_target:
                send_back_to = llm_target
        round_no = state.get("round_no", 0)
        if issues:
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
        }
        return {"verdict": verdict.model_dump(), "round_no": verdict.round_no, "node_results": node_results}

    return critic


def _llm_review(llm, state: dict, pool: dict, assertions) -> tuple[list[str], str | None]:
    try:
        claims = "\n".join(f"- {a.text}（引用：{a.cites}）" for a in assertions)
        prompt = PromptBundle(
            role="critic",
            system=system_for("critic"),
            task=f"问题：{state['question']}\n待核验断言：\n{claims}",
            evidence_block=_evidence_block(pool),
            format_hint='{"verdict":"pass 或 send_back","issues":["具体问题"],"send_back_to":"retriever 或 planner"}',
        )
        out = llm.complete(prompt, tier="fast", schema=CriticOutput)
    except Exception:
        return [], None
    if out.verdict != "send_back":
        return [], None
    issues = [i for i in out.issues if i]
    if not issues:
        issues = ["审校认为断言的证据支撑不足"]
    return issues, out.send_back_to


def make_writer(threshold: float, llm=None):
    from core.schemas.deliverable import Assertion, Deliverable
    from core.services import citation, confidence

    def writer(state: dict) -> dict:
        pool = _pool(state)
        assertions = [Assertion(**a) for a in state.get("assertions", [])]
        verdict = state.get("verdict") or {}
        exhausted = verdict.get("verdict") == "send_back"
        for a in assertions:
            if not a.cites:
                a.inferred = True
        # 置信度由大模型评分（不可用时回退公式），评分来源写进交付物
        if llm is not None:
            conf = confidence.llm_score(llm, state["question"], assertions, pool, threshold)
        else:
            conf = confidence.score(assertions, pool, threshold)
        reasons = list(verdict.get("issues", [])) if exhausted else []
        if conf.refused and conf.reason:
            reasons.insert(0, conf.reason)
        refused = conf.refused
        if exhausted:
            # 人工断点：打回轮数用尽即暂停图，等人工放行后再输出兜底交付物
            gate = interrupt({
                "reason": "审校打回已达上限，需人工放行后输出兜底结论",
                "issues": reasons,
            })
            reasons.append(
                f"已达最大打回轮数（{TaskDAG(**state['dag']).max_rounds()}）"
                f"{'，人工已放行' if gate else ''}，输出兜底结论"
            )
            refused = True
        deliverable = Deliverable(
            question=state["question"],
            assertions=assertions,
            citations=citation.attach_citations(assertions, pool),
            trace_id=state.get("trace_id", ""),
            confidence=conf.score,
            confidence_source=conf.source,
            confidence_reason=conf.reason,
            degraded=exhausted,
            refused=refused,
            refusal_reason=("；".join(reasons) if reasons else conf.reason) if refused else None,
        )
        return {"deliverable": deliverable.model_dump()}

    return writer


def _next_id(pool: dict[str, Evidence]) -> str:
    ids = [int(m) for eid in pool for m in re.findall(r"E(\d+)", eid)]
    return f"E{max(ids, default=0) + 1}"


def _year_numbers(pool: dict[str, Evidence]) -> list[float]:
    """从含"营收/营业收入 …N亿"的证据里按出现顺序取前两个去重数值。"""
    nums: list[float] = []
    for ev in pool.values():
        if "亿" not in ev.quote or not ("营收" in ev.quote or "营业收入" in ev.quote):
            continue
        for raw in _NUM_RE.findall(ev.quote):
            v = float(raw)
            if v not in nums:
                nums.append(v)
    return nums[:2]
