"""MCP 本地工具链路单测：真起 stdio 子进程（mcp_server.py），全程离线不连外网。

跑法与既有套件一致：cd backend && .venv/bin/python -m pytest -q
不依赖真实网关/真实 LLM；审计文件按唯一参数定位各用例的记录。
"""

import json
import time

import pytest

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


def test_food_tools_contract(gateway):
    nutrition = gateway.call("query_food_nutrition", {"name": "米饭"})
    assert nutrition["ok"] is True
    assert nutrition["result"]["carbs_per_100g"] == 25.9
    assert nutrition["result"]["gi"] == 83

    gl = gateway.call("calculate_gl", {"name": "米饭", "carbs_g": 50})
    assert gl["ok"] is True
    assert gl["result"] == 41.5


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
