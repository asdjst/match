"""餐食记录 API：新增、补血糖、改备注、删除。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from infra.config import Settings


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(Settings(mode="fake", db_path=str(tmp_path / "runs.db"))))


def _create(client, **overrides):
    body = {
        "user_id": "u1",
        "eaten_at": "2026-11-08T12:30",
        "meal_type": "午餐",
        "foods": [{"name": "米饭", "grams": 150, "carbs_g": 39, "gl": 32.4}],
        "note": "食堂",
        "source": "manual",
    }
    body.update(overrides)
    resp = client.post("/api/meals", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["meal"]


def test_create_list_and_glucose(client):
    meal = _create(client)
    meal_id = meal["meal_id"]

    listed = client.get("/api/meals", params={"user_id": "u1"}).json()["meals"]
    assert [m["meal_id"] for m in listed] == [meal_id]

    resp = client.post(f"/api/meals/{meal_id}/glucose", json={"value_mmol": 10.2, "minutes_after": 120})
    assert resp.status_code == 200
    reading = resp.json()["reading"]
    assert reading["value_mmol"] == 10.2

    # 0 分钟表示餐前
    pre = client.post(f"/api/meals/{meal_id}/glucose", json={"value_mmol": 5.6, "minutes_after": 0})
    assert pre.status_code == 200
    assert pre.json()["reading"]["minutes_after"] == 0

    updated = client.patch(f"/api/meals/{meal_id}", json={"note": "加了青菜"}).json()["meal"]
    assert updated["note"] == "加了青菜"
    assert {r["value_mmol"] for r in updated["readings"]} == {10.2, 5.6}

    assert client.delete(f"/api/meals/{meal_id}/glucose/{reading['reading_id']}").status_code == 200
    remaining = client.get(f"/api/meals/{meal_id}").json()["meal"]["readings"]
    assert [r["value_mmol"] for r in remaining] == [5.6]
    assert client.delete(f"/api/meals/{meal_id}/glucose/{pre.json()['reading']['reading_id']}").status_code == 200
    assert client.get(f"/api/meals/{meal_id}").json()["meal"]["readings"] == []

    assert client.delete(f"/api/meals/{meal_id}").status_code == 200
    assert client.get("/api/meals", params={"user_id": "u1"}).json()["meals"] == []


def test_missing_meal_returns_404(client):
    assert client.patch("/api/meals/nope", json={"note": "x"}).status_code == 404
    assert client.post("/api/meals/nope/glucose", json={"value_mmol": 7.0}).status_code == 404
    assert client.delete("/api/meals/nope").status_code == 404


def test_chat_pulls_personal_record_into_evidence_pool(client):
    meal = _create(client)
    client.post(f"/api/meals/{meal['meal_id']}/glucose", json={"value_mmol": 10.2})
    client.post(f"/api/meals/{meal['meal_id']}/glucose", json={"value_mmol": 5.6, "minutes_after": 0})

    resp = client.post(
        "/api/chat",
        json={"session_id": "s1", "user_id": "u1", "question": "我上次吃米饭血糖怎么样"},
    )
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    run_id = events[0]["run_id"]

    snap = client.get(f"/api/tasks/{run_id}").json()
    channels = [e.get("channel") for e in snap["evidence"].values()]
    assert "memory" in channels
    quotes = [e["quote"] for e in snap["evidence"].values() if e.get("channel") == "memory"]
    assert any("10.2" in q for q in quotes)
    assert any("餐前 5.6" in q for q in quotes)
