"""MCP 本地工具链路单测：真起 stdio 子进程（mcp_server.py），全程离线不连外网。

跑法与既有套件一致：cd backend && .venv/bin/python -m pytest -q
不依赖真实网关/真实 LLM；审计文件按唯一参数定位各用例的记录。
"""

import json
import time

import pytest

from adapters.tools.fake import FakeTools
from adapters.tools.mcp_client import MCPToolGateway


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    """模块级共享网关：一个 MCP 子进程跑全部用例，控制启动开销。"""
    audit = tmp_path_factory.mktemp("mcp_audit") / "tool_audit.jsonl"
    with MCPToolGateway(audit_path=audit, timeout_s=3.0) as gw:
        yield gw


def test_list_tools_exposes_expected(gateway):
    tools = gateway.list_tools()
    assert "growth_rate" in tools  # 契约必备
    assert {"yoy_diff", "sum", "avg"} <= set(tools)
    assert {"query_food_nutrition", "calculate_gl"} <= set(tools)
    assert {"glucose_summary", "meal_gl_total", "carb_target"} <= set(tools)


def test_tool_set_matches_offline_gateway(gateway):
    from adapters.tools.fake import FakeTools

    assert set(gateway.list_tools()) == set(FakeTools().list_tools())


def test_health_tools_round_trip_and_match_offline(gateway, tmp_path):
    """真起子进程算一遍，与治理后的离线网关逐字比对：两条路径不许给出两个数字。"""
    from adapters.tools.fake import FakeTools
    from adapters.tools.governance import GovernedGateway

    cases = [
        ("glucose_summary", {"values": [5.6, 10.2, 7.8, 3.5, 14.2]}),
        ("glucose_summary", {"values": [8.0, 9.0], "low": 3.9, "high": 7.8}),
        ("glucose_summary", {"values": [6.1]}),
        ("meal_gl_total", {"foods": [{"name": "米饭", "carbs_g": 38.9}, {"name": "莲藕", "carbs_g": 12}]}),
        ("carb_target", {"height_cm": 170, "activity": "轻度活动", "weight_kg": 72, "goal": "减重"}),
        ("carb_target", {}),
        ("glucose_summary", {"values": []}),
        ("meal_gl_total", {"foods": [{"name": "外星食物", "carbs_g": 1}]}),
    ]
    with GovernedGateway(FakeTools(), audit_path=tmp_path / "offline.jsonl") as offline:
        for name, args in cases:
            assert gateway.call(name, args) == offline.call(name, args), f"{name} {args}"


def test_health_tool_audit_written(gateway):
    out = gateway.call("meal_gl_total", {"foods": [{"name": "米饭", "carbs_g": 50}]})
    assert out["ok"] is True and out["result"]["total_gl"] == 41.5
    records = [
        json.loads(line)
        for line in gateway.audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rec = next(
        r for r in records
        if r["tool"] == "meal_gl_total" and r["args"] == {"foods": [{"name": "米饭", "carbs_g": 50}]}
    )
    assert rec["ok"] is True and rec["timed_out"] is False
    assert "41.5" in rec["summary"]


def test_food_tools_contract(gateway):
    nutrition = gateway.call("query_food_nutrition", {"name": "米饭"})
    assert nutrition["ok"] is True
    assert nutrition["result"]["carbs_per_100g"] == 25.9
    assert nutrition["result"]["gi"] == 83

    gl = gateway.call("calculate_gl", {"name": "米饭", "carbs_g": 50})
    assert gl["ok"] is True
    assert gl["result"] == 41.5


def test_gi_unknown_food_gives_carbs_but_no_gl(gateway):
    nutrition = gateway.call("query_food_nutrition", {"name": "莲藕"})
    assert nutrition["ok"] is True
    assert nutrition["result"]["carbs_per_100g"] == 16.4
    assert nutrition["result"]["gi"] is None
    assert "id 516" in nutrition["source"]

    gl = gateway.call("calculate_gl", {"name": "莲藕", "carbs_g": 12})
    assert gl["ok"] is False and "GI 未收录" in gl["error"]
    # 离线 FakeTools 必须给同样的结论，不能一边算得出、一边算不出
    assert FakeTools().call("calculate_gl", {"name": "莲藕", "carbs_g": 12}) == gl


def test_string_param_rejected(gateway):
    out = gateway.call("query_food_nutrition", {"name": "   "})
    assert out["ok"] is False
    assert "name" in out["error"]


def test_growth_rate_matches_fake_contract(gateway):
    out = gateway.call("growth_rate", {"a": 120, "b": 100})
    # (120-100)/100*100 = 20%，返回契约与 FakeTools 完全一致
    assert out == {"ok": True, "result": 20.0, "unit": "%"}


def test_growth_rate_zero_denominator(gateway):
    out = gateway.call("growth_rate", {"a": 120, "b": 0})
    assert out["ok"] is False
    assert out["error"] == "分母为 0"


def test_sum_avg_yoy_diff(gateway):
    assert gateway.call("sum", {"values": [1, 2, 3]})["result"] == 6.0
    assert gateway.call("avg", {"values": [2, 4]})["result"] == 3.0
    out = gateway.call("yoy_diff", {"a": 120, "b": 100})
    assert out["ok"] is True
    assert out["result"] == 20.0
    assert out.get("unit_note")  # 差值必须带单位说明


def test_invalid_numeric_params_rejected(gateway):
    out = gateway.call("growth_rate", {"a": "abc", "b": 100})
    assert out["ok"] is False
    assert "a" in out["error"]
    out = gateway.call("sum", {"values": [1, "x", 3]})
    assert out["ok"] is False
    out = gateway.call("avg", {"values": []})
    assert out["ok"] is False


def test_missing_param_rejected(gateway):
    out = gateway.call("growth_rate", {"a": 100})
    assert out["ok"] is False
    assert "b" in out["error"]


def test_unknown_tool_raises_key_error(gateway):
    # 与 FakeTools 契约一致：未知工具抛 KeyError（graph 节点按此降级）
    with pytest.raises(KeyError):
        gateway.call("weather", {"city": "北京"})


def test_timeout_returns_ok_false(gateway):
    t0 = time.monotonic()
    out = gateway.call("slow_sum", {"a": 999, "b": 1, "delay_s": 30})
    elapsed = time.monotonic() - t0
    assert out == {"ok": False, "error": "timeout"}
    assert elapsed < 8  # 3s 超时即返回，不等服务端睡完 30s


def test_audit_jsonl_written(gateway):
    records = [
        json.loads(line)
        for line in gateway.audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records, "审计 JSONL 应有落盘记录"
    ok_rec = next(r for r in records if r["tool"] == "growth_rate" and r["args"].get("b") == 100)
    assert ok_rec["args"] == {"a": 120, "b": 100}
    assert ok_rec["ok"] is True
    assert ok_rec["timed_out"] is False
    assert ok_rec["ts"] and ok_rec["duration_ms"] >= 0 and ok_rec["summary"]
    timeout_rec = next(r for r in records if r["tool"] == "slow_sum" and r["args"].get("a") == 999)
    assert timeout_rec["timed_out"] is True
    assert timeout_rec["ok"] is False


def test_clean_lifecycle(tmp_path):
    gw = MCPToolGateway(audit_path=tmp_path / "audit.jsonl", timeout_s=5.0)
    with gw:
        assert gw.call("sum", {"values": [1.5, 1.5]})["result"] == 3.0
    # close 后子进程已收干净，再调用必须报错而非挂死
    with pytest.raises(RuntimeError):
        gw.call("sum", {"values": [1, 1]})
