from typing import TypedDict


class GraphState(TypedDict, total=False):
    """节点间只传 dict（checkpoint 序列化安全）；出入节点处用 schemas 转换。"""

    session_id: str
    question: str
    trace_id: str
    dag: dict
    evidence: dict          # evidence_id -> Evidence.model_dump()
    assertions: list[dict]  # Assertion.model_dump()
    node_results: dict      # node_id -> AgentResult.model_dump()
    verdict: dict | None    # ReviewVerdict.model_dump()
    round_no: int
    deliverable: dict | None
    history: list[dict]     # 最近几轮问答摘要：planner 做指代消解用，不作证据
    steps: int              # 已执行的检索/计算节点次数（预算口径）
    started_at: float       # run 开始的 monotonic 时间戳（预算口径）
    budget_stop: str | None # 预算耗尽原因，非空时 critic 直接放行、writer 标降级
    image_id: str | None    # 餐食图片只存服务端文件名，不把 base64 写进状态
    food_items: list[dict]  # FoodItem.model_dump()，由 /api/food/analyze 产出
    profile: dict           # 用户自填代谢档案（含 BMI），只作个性化上下文，不进证据池
