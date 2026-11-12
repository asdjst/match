import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from infra.config import Settings

# 1x1 PNG，够过文件头校验
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def app(tmp_path):
    return create_app(Settings(mode="fake", db_path=str(tmp_path / "runs.db"), upload_dir=str(tmp_path / "uploads")))


@pytest.fixture()
def client(app):
    return TestClient(app)


def test_analyze_saves_image_and_returns_items(client, tmp_path):
    resp = client.post("/api/food/analyze", files={"file": ("meal.png", PNG, "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    # 离线假实现：结构与真链路一致，数值标为示例
    assert body["source"] == "demo"
    assert body["degraded"] is False
    assert body["items"] and body["confidence"] > 0
    assert body["carbs_g_high"] >= body["carbs_g_low"] > 0

    saved = list((tmp_path / "uploads").iterdir())
    assert len(saved) == 1
    assert saved[0].stem == body["image_id"]
    assert saved[0].suffix == ".png"


def test_analyze_rejects_non_image(client):
    resp = client.post("/api/food/analyze", files={"file": ("note.txt", b"hello", "text/plain")})
    assert resp.status_code == 415


def test_saved_image_is_readable_by_id(client):
    image_id = client.post("/api/food/analyze", files={"file": ("meal.png", PNG, "image/png")}).json()["image_id"]

    resp = client.get(f"/api/food/images/{image_id}")

    assert resp.status_code == 200
    assert resp.content == PNG
    assert resp.headers["cache-control"].startswith("private")


def test_image_endpoint_rejects_unknown_or_malformed_id(client):
    assert client.get("/api/food/images/" + "0" * 32).status_code == 404
    # 只认 32 位 hex，路径穿越/任意文件名一律拒绝
    assert client.get("/api/food/images/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/food/images/abc.png").status_code == 404


def test_chat_carries_food_context_into_state(app, client):
    food_items = [{"name": "米饭", "grams_low": 150, "grams_high": 200, "carbs_g_low": 38.9, "carbs_g_high": 51.8, "confidence": 0.6}]
    resp = client.post(
        "/api/chat",
        json={"session_id": "s1", "question": "这餐碳水多少？", "image_id": "abc123", "food_items": food_items},
    )
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"

    run_id = events[0]["run_id"]
    stored = app.state.runs[run_id]
    assert stored["image_id"] == "abc123"
    # state 里存校验后的规范结构（浮点与默认字段已补齐）
    assert stored["food_items"][0]["name"] == "米饭"
    assert stored["food_items"][0]["carbs_g_high"] == 51.8


def test_photo_flow_produces_image_citations(client):
    analysis = client.post("/api/food/analyze", files={"file": ("meal.png", PNG, "image/png")}).json()
    resp = client.post(
        "/api/chat",
        json={
            "session_id": "s1",
            "question": "这餐大概多少碳水？",
            "image_id": analysis["image_id"],
            "food_items": analysis["items"],
        },
    )
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    deliverable = next(e["deliverable"] for e in events if e["type"] == "deliverable")

    assert deliverable["refused"] is False
    assert deliverable["assertions"]
    assert deliverable["confidence"] > 0
    assert deliverable["citations"]
    channels = {c["channel"] for c in deliverable["citations"]}
    # 拍照证据 + 食物成分/GL 工具证据都要能进引用表；命中知识卡时还会带 local
    assert {"image", "tool"} <= channels
    assert channels <= {"image", "tool", "local"}
    assert any(c["source"]["file_path"] == f"photo://{analysis['image_id']}" for c in deliverable["citations"])
    assert any(c["source"]["file_path"] == "tool://calculate_gl" for c in deliverable["citations"])

    run_id = next(e["run_id"] for e in events if e["type"] == "run")
    dag = client.app.state.runs[run_id]["dag"]
    executor_tools = {n["tool"] for n in dag["nodes"] if n["role"] == "executor"}
    assert {"query_food_nutrition", "calculate_gl"} <= executor_tools

    # 轨迹页要展示真实 MCP 调用流水：入参/出参/单位/关联证据都要能取到
    snapshot = client.get(f"/api/tasks/{run_id}").json()
    calls = [
        c
        for r in snapshot["node_results"].values()
        for c in ((r.get("output") or {}).get("calls") or [])
    ]
    assert {"query_food_nutrition", "calculate_gl"} <= {c["tool"] for c in calls}
    gl_call = next(c for c in calls if c["tool"] == "calculate_gl")
    assert gl_call["args"]["carbs_g"] > 0
    assert gl_call["unit"] == "GL"
    assert gl_call["evidence_id"]


def test_invalid_food_items_do_not_break_chat(client):
    resp = client.post(
        "/api/chat",
        json={"session_id": "s1", "question": "这餐碳水多少？", "food_items": [{"name": "", "grams_low": -1}]},
    )
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    deliverable = next(e["deliverable"] for e in events if e["type"] == "deliverable")
    # 没有有效餐食证据时按无证据处理，不因脏 payload 崩
    assert deliverable["citations"] == []


def test_chat_normalizes_profile_into_run(app, client):
    resp = client.post(
        "/api/chat",
        json={
            "session_id": "s-profile",
            "question": "这餐怎么搭配更稳？",
            "profile": {
                "height_cm": 172,
                "weight_kg": 68,
                "age": 45,
                "activity": "久坐",
                "goal": "控制餐后血糖",
            },
        },
    )
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    profile = app.state.runs[events[0]["run_id"]]["profile"]
    # 后端按身高体重算好 BMI，前端只负责填原始数据
    assert profile["bmi"] == 23.0
    assert profile["goal"] == "控制餐后血糖"
    assert profile["activity"] == "久坐"


def test_chat_rejects_out_of_range_profile(client):
    resp = client.post(
        "/api/chat",
        json={"session_id": "s1", "question": "怎么吃？", "profile": {"height_cm": 10}},
    )
    assert resp.status_code == 422
