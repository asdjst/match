import re

from langgraph.types import interrupt

from core.graph.nodes.common import (
    _budget_stop,
    _deps_block,
    _evidence_block,
    _food_block,
    _history_block,
    _next_id,
    _pool,
    _profile_block,
    _year_numbers,
)
from core.schemas.common import SourceRef
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.evidence import Evidence
from core.schemas.prompt import ANALYST_SYSTEM, PromptBundle, system_for


def make_planner(llm):
    def planner(state: dict) -> dict:
        prompt = PromptBundle(
            role="planner",
            system=system_for("planner"),
            task=(
                f"{_history_block(state.get('history'))}"
                f"{_food_block(state.get('food_items'))}"
                f"{_profile_block(state.get('profile'))}"
                f"QUESTION: {state['question']}"
            ),
            format_hint=(
                '只输出 JSON，形如 {"question":"…","nodes":[{"node_id":"r1","role":"retriever",'
                '"instruction":"…","depends_on":[],"budget":{"max_steps":8,"max_rounds":3,"timeout_s":120},'
                '"tool":null,"query":"检索词"}]}，role 取值 planner/retriever/executor/analyst/critic，'
                "budget 必须是对象不是数字；只有确实要按证据做确定性计算时才加 executor 节点"
                "（当前工具仅 growth_rate：按两条营收数值算同比/环比，其他计算不要调用工具）；"
                "若问题带已识别餐食，不要为照片内容再生成检索节点，系统会自动补一条膳食指南检索；"
                "问题含“它/该/上一条”等指代时，结合对话历史把 question 与 query 改写成可独立检索的问句"
            ),
        )
        dag = llm.complete(prompt, tier="fast", schema=TaskDAG)
        return {"dag": _with_food_tools(dag, state.get("food_items")).model_dump(), "round_no": state.get("round_no", 0)}

    return planner


def _with_food_tools(dag: TaskDAG, food_items: list[dict] | None) -> TaskDAG:
    """拍照问题自动补确定性节点：指南检索 + 成分查询 + GL 估算。
    不依赖 LLM 记得填工具参数，也保证每次拍照演示都会走本地知识库与 MCP 工具链。"""
    if not food_items:
        return dag
    if not any(n.role == "retriever" for n in dag.nodes):
        names = "、".join(
            str(i.get("name")) for i in food_items if isinstance(i, dict) and i.get("name")
        )
        dag.nodes.append(NodeSpec(
            node_id="r_food",
            role="retriever",
            instruction="检索糖尿病膳食指南中与这餐相关的碳水、升糖负荷与搭配建议",
            query=f"{names} 碳水化合物 升糖负荷 膳食指南 进餐顺序",
        ))
    for spec in dag.nodes:
        if spec.role != "analyst":
            continue
        # 拍照题不能只报一个碳水数字：指南建议也要有出处，才算“无源不答”
        spec.instruction = (
            f"{spec.instruction.rstrip('。；; ')}；食物每100g碳水与GI以工具证据为准，"
            "份量以拍照证据为准；另外必须引用本地膳食指南证据，给出这餐的搭配、"
            "进餐顺序与碳水供能是否合适的建议，每条建议都要挂指南证据编号"
        )
    existing = {n.tool for n in dag.nodes if n.role == "executor"}
    if "query_food_nutrition" not in existing:
        dag.nodes.append(NodeSpec(
            node_id="x_food",
            role="executor",
            tool="query_food_nutrition",
            instruction="逐项查询食物成分与 GI",
        ))
    if "calculate_gl" not in existing:
        dag.nodes.append(NodeSpec(
            node_id="x_gl",
            role="executor",
            tool="calculate_gl",
            instruction="按碳水与 GI 估算血糖负荷",
        ))
    return dag


def make_retriever(retriever_port):
    def retriever(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        node_results = dict(state.get("node_results", {}))
        steps = int(state.get("steps", 0))
        budget_stop = state.get("budget_stop")
        for spec in dag.order():
            if spec.role != "retriever":
                continue
            blocked = _deps_block(spec, dag, node_results)
            if blocked is not None:
                node_results[spec.node_id] = {
                    "node_id": spec.node_id,
                    "status": "blocked",
                    "evidence_used": [],
                    "block_reason": blocked,
                }
                continue
            stop = budget_stop or _budget_stop({**state, "steps": steps}, dag)
            if stop:
                budget_stop = stop
                # 上一轮已成功的检索结果保留，只拦从未执行过的节点
                if (node_results.get(spec.node_id) or {}).get("status") != "done":
                    node_results[spec.node_id] = {
                        "node_id": spec.node_id,
                        "status": "blocked",
                        "evidence_used": [],
                        "block_reason": stop,
                    }
                continue
            query = spec.query or dag.question or state["question"]
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
            steps += 1
        return {
            "evidence": {k: v.model_dump() for k, v in pool.items()},
            "node_results": node_results,
            "steps": steps,
            "budget_stop": budget_stop,
        }

    return retriever


def _food_tool_result(spec, state: dict, tools, pool: dict, node_results: dict) -> dict:
    """一次工具节点处理所有餐食条目：查询成分或估算 GL，每条结果落一条可引用证据。"""
    items = [i for i in (state.get("food_items") or []) if isinstance(i, dict) and i.get("name")][:5]
    if not items:
        return {"node_id": spec.node_id, "status": "blocked", "block_reason": "没有可查询的餐食"}

    used: list[str] = []
    errors: list[str] = []
    calls: list[dict] = []
    for item in items:
        name = str(item["name"])[:40]
        if spec.tool == "query_food_nutrition":
            args: dict = {"name": name}
        else:
            carbs = (float(item.get("carbs_g_low") or 0) + float(item.get("carbs_g_high") or 0)) / 2
            args = {"name": name, "carbs_g": round(carbs, 1)}
        try:
            out = tools.call(spec.tool, args)
        except KeyError:
            return {"node_id": spec.node_id, "status": "blocked", "block_reason": f"工具不可用：{spec.tool}"}
        if not out.get("ok"):
            errors.append(f"{name}：{out.get('error', '未知错误')}")
            calls.append({"tool": spec.tool, "args": args, "ok": False, "error": out.get("error", "未知错误")})
            continue
        if spec.tool == "query_food_nutrition":
            result = out.get("result") or {}
            quote = (
                f"食物成分（{name}）：每100g碳水 {result.get('carbs_per_100g')}g，"
                f"GI {result.get('gi')}；{out.get('source', '')}"
            )
        else:
            quote = (
                f"血糖负荷估算（{name} 约 {args['carbs_g']}g 碳水，GI {out.get('gi')}）："
                f"GL≈{out.get('result')}；{out.get('source', '')}"
            )
        eid = _next_id(pool)
        pool[eid] = Evidence(
            evidence_id=eid,
            doc_id="tool",
            quote=quote,
            score=1.0,
            source=SourceRef(file_path=f"tool://{spec.tool}"),
            channel="tool",
        )
        used.append(eid)
        calls.append(
            {
                "tool": spec.tool,
                "args": args,
                "ok": True,
                "result": out.get("result"),
                "unit": out.get("unit"),
                "gi": out.get("gi"),
                "source": out.get("source"),
                "evidence_id": eid,
            }
        )

    prev_used = (node_results.get(spec.node_id) or {}).get("evidence_used") or []
    result_dict: dict = {
        "node_id": spec.node_id,
        "status": "done" if used else "blocked",
        "evidence_used": list(dict.fromkeys([*prev_used, *used])),
        # 真实 MCP 调用流水（入参/出参/来源），供轨迹页审计，失败项也记录
        "output": {"calls": calls},
    }
    if errors:
        result_dict["warnings"] = errors
    if not used:
        result_dict["block_reason"] = "；".join(errors) or "食物库未命中"
    return result_dict


def make_executor(tools):
    def executor(state: dict) -> dict:
        dag = TaskDAG(**state["dag"])
        pool = _pool(state)
        node_results = dict(state.get("node_results", {}))
        available = tools.list_tools()
        steps = int(state.get("steps", 0))
        budget_stop = state.get("budget_stop")
        for spec in dag.order():
            if spec.role != "executor":
                continue
            dep_block = _deps_block(spec, dag, node_results)
            if dep_block is not None:
                node_results[spec.node_id] = {
                    "node_id": spec.node_id,
                    "status": "blocked",
                    "block_reason": dep_block,
                }
                continue
            stop = budget_stop or _budget_stop({**state, "steps": steps}, dag)
            if stop:
                budget_stop = stop
                if (node_results.get(spec.node_id) or {}).get("status") != "done":
                    node_results[spec.node_id] = {
                        "node_id": spec.node_id,
                        "status": "blocked",
                        "block_reason": stop,
                    }
                continue
            steps += 1
            if spec.tool in ("query_food_nutrition", "calculate_gl"):
                if spec.tool not in available:
                    node_results[spec.node_id] = {
                        "node_id": spec.node_id,
                        "status": "blocked",
                        "block_reason": f"工具不可用：{spec.tool}",
                    }
                else:
                    node_results[spec.node_id] = _food_tool_result(spec, state, tools, pool, node_results)
                continue
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
                score=1.0,
                source=SourceRef(file_path=f"tool://{spec.tool}"),
                channel="tool",
            )
            pool[eid] = ev
            node_results[spec.node_id] = {
                "node_id": spec.node_id,
                "status": "done",
                "output": {"args": args, **out},
                "evidence_used": [eid],
            }
        return {
            "evidence": {k: v.model_dump() for k, v in pool.items()},
            "node_results": node_results,
            "steps": steps,
            "budget_stop": budget_stop,
        }

    return executor


MAX_ASSERTIONS = 7


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"\s+", "", text)
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _near_duplicate(left: str, right: str) -> bool:
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.7


def _tidy_assertions(assertions: list) -> list:
    """去重再封顶：同一意思只留第一条，最多 7 条，避免指南句淹没针对这顿的建议。"""
    kept = []
    for assertion in assertions:
        if any(_near_duplicate(assertion.text, item.text) for item in kept):
            continue
        kept.append(assertion)
        if len(kept) >= MAX_ASSERTIONS:
            break
    return kept


def make_analyst(llm):
    def analyst(state: dict) -> dict:
        from core.schemas.agent import AnalystOutput

        # 追问经 planner 消解指代后写进 dag.question，分析用改写后的独立问题
        dag = TaskDAG(**state["dag"])
        question = dag.question or state["question"]
        guidance = "；".join(
            n.instruction for n in dag.nodes if n.role == "analyst" and n.instruction
        )
        issues = (state.get("verdict") or {}).get("issues") or []
        task = f"问题：{question}"
        if guidance:
            task += f"\n任务要求：{guidance}"
        if issues:
            task += "\n上一轮审校意见（逐条修正后再输出）：\n" + "\n".join(
                f"- {issue}" for issue in issues[:8]
            )
        if state.get("profile"):
            task += "\n" + _profile_block(state.get("profile"))
        prompt = PromptBundle(
            role="analyst",
            system=ANALYST_SYSTEM,
            task=task,
            evidence_block=_evidence_block(_pool(state)),
            format_hint='{"assertions":[{text, cites:[…]}]}；证据与问题无关时输出 {"assertions":[]}',
        )
        out = llm.complete(prompt, tier="strong", schema=AnalystOutput)
        pool = _pool(state)
        # 模型判断“证据无关”时不要直接空手交给审校：个人记录核对证据本身已是确定结论
        if not out.assertions:
            checks = [(eid, ev) for eid, ev in pool.items() if ev.doc_id == "meal-check"]
            if checks:
                out = AnalystOutput.model_validate({
                    "assertions": [
                        {"text": ev.quote, "cites": [eid]} for eid, ev in checks[:2]
                    ]
                })
        out = AnalystOutput(assertions=_tidy_assertions(out.assertions))
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
        budget_stop = state.get("budget_stop")
        if budget_stop:
            reasons.append(budget_stop)
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
            degraded=exhausted or conf.degraded or bool(budget_stop),
            degraded_reason=budget_stop,
            refused=refused,
            refusal_reason=("；".join(reasons) if reasons else conf.reason) if refused else None,
        )
        return {"deliverable": deliverable.model_dump()}

    return writer
