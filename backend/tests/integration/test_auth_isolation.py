"""登录身份与用户隔离：个人餐食、run 快照、会话记忆都不能跨账号读写。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from infra.config import Settings

MEAL = {
    "eaten_at": "2026-11-08T12:30",
    "meal_type": "午餐",
    "foods": [{"name": "米饭", "grams": 150, "carbs_g": 39, "gl": 32.4}],
    "note": "alice 的食堂午餐",
}
PASSWORD = "控糖日记2026"


@pytest.fixture()
def guest(tmp_path):
    return TestClient(create_app(Settings(mode="fake", db_path=str(tmp_path / "runs.db"))))


def _login(guest, username: str) -> TestClient:
    resp = guest.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    return TestClient(guest.app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def alice(guest):
    return _login(guest, "alice")


@pytest.fixture()
def bob(guest):
    return _login(guest, "bob")


def _run_id(resp) -> str:
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    return events[0]["run_id"]


def test_register_login_logout_roundtrip(guest):
    created = guest.post("/api/auth/register", json={"username": "Alice", "password": PASSWORD})
    assert created.status_code == 201
    body = created.json()
    assert body["user"]["username"] == "alice"
    assert body["token"] and PASSWORD not in json.dumps(body)

    # 同名再注册被拒；大小写不同也算同一个人
    assert guest.post("/api/auth/register", json={"username": "alice", "password": PASSWORD}).status_code == 409
    assert guest.post("/api/auth/register", json={"username": "ab", "password": PASSWORD}).status_code == 400
    assert guest.post("/api/auth/register", json={"username": "dave", "password": "123"}).status_code == 400

    logged = guest.post("/api/auth/login", json={"username": "ALICE", "password": PASSWORD})
    assert logged.status_code == 200
    token = logged.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert guest.get("/api/auth/me", headers=headers).json()["user"]["username"] == "alice"

    assert guest.post("/api/auth/logout", headers=headers).json()["ok"] is True
    # 退出后令牌立即作废：个人接口 401，/me 只报过期不抛错
    assert guest.get("/api/meals", headers=headers).status_code == 401
    me = guest.get("/api/auth/me", headers=headers).json()
    assert me == {"user": None, "guest": True, "expired": True}
    # 注册时那枚令牌不受影响，同一账号可以多端登录
    assert guest.get("/api/meals", headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200


def test_wrong_password_is_401_then_throttled(guest):
    guest.post("/api/auth/register", json={"username": "carol", "password": PASSWORD})
    for _ in range(5):
        resp = guest.post("/api/auth/login", json={"username": "carol", "password": "猜错了12345"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "用户名或密码不正确"
    blocked = guest.post("/api/auth/login", json={"username": "carol", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "秒后再试" in blocked.json()["detail"]
    # 冷却只针对这个用户名，别人照常登录
    assert guest.post("/api/auth/register", json={"username": "dave", "password": PASSWORD}).status_code == 201


def test_unknown_user_and_wrong_password_look_the_same(guest):
    guest.post("/api/auth/register", json={"username": "erin", "password": PASSWORD})
    missing = guest.post("/api/auth/login", json={"username": "没人注册", "password": PASSWORD})
    wrong = guest.post("/api/auth/login", json={"username": "erin", "password": "猜错了12345"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()


def test_bad_token_is_401_but_guest_still_works(guest):
    bad = {"Authorization": "Bearer nope"}
    assert guest.get("/api/meals", headers=bad).status_code == 401
    assert guest.get("/api/runs", headers=bad).status_code == 401
    assert guest.post("/api/meals", json=MEAL, headers=bad).status_code == 401
    assert guest.post("/api/chat", json={"question": "米饭多少碳水"}, headers=bad).status_code == 401
    assert guest.post("/api/food/analyze", headers=bad).status_code == 401
    # 没带令牌就是单机演示身份，不是 401
    assert guest.get("/api/meals").status_code == 200
    health = guest.get("/api/health").json()
    assert health["auth"] == "accounts"
    assert "token" not in json.dumps(health).lower()


def test_meal_is_only_visible_to_its_owner(alice, bob):
    meal_id = alice.post("/api/meals", json=MEAL).json()["meal"]["meal_id"]
    reading_id = alice.post(f"/api/meals/{meal_id}/glucose", json={"value_mmol": 10.2}).json()["reading"]["reading_id"]

    assert bob.get("/api/meals").json()["meals"] == []
    assert bob.get(f"/api/meals/{meal_id}").status_code == 404
    assert bob.patch(f"/api/meals/{meal_id}", json={"note": "篡改"}).status_code == 404
    assert bob.post(f"/api/meals/{meal_id}/glucose", json={"value_mmol": 3.0}).status_code == 404
    assert bob.delete(f"/api/meals/{meal_id}/glucose/{reading_id}").status_code == 404
    assert bob.delete(f"/api/meals/{meal_id}").status_code == 404

    mine = alice.get(f"/api/meals/{meal_id}").json()["meal"]
    assert mine["note"] == MEAL["note"]
    assert [r["value_mmol"] for r in mine["readings"]] == [10.2]


def test_request_body_cannot_choose_another_user(alice, bob):
    other = bob.get("/api/auth/me").json()["user"]["user_id"]
    meal = alice.post("/api/meals", json={**MEAL, "user_id": other}).json()["meal"]
    assert meal["user_id"] == alice.get("/api/auth/me").json()["user"]["user_id"]


def test_runs_and_tasks_are_only_visible_to_their_owner(alice, bob):
    run_id = _run_id(alice.post("/api/chat", json={"session_id": "s1", "question": "一碗米饭大概多少碳水？"}))

    assert [r["run_id"] for r in alice.get("/api/runs").json()["runs"]] == [run_id]
    assert bob.get("/api/runs").json()["runs"] == []
    assert bob.get(f"/api/tasks/{run_id}").status_code == 404
    assert bob.post(f"/api/tasks/{run_id}/approve", json={"action": "approve"}).status_code == 404
    assert alice.get(f"/api/tasks/{run_id}").json()["question"] == "一碗米饭大概多少碳水？"


def test_same_session_id_does_not_leak_personal_records(alice, bob):
    meal_id = alice.post("/api/meals", json=MEAL).json()["meal"]["meal_id"]
    alice.post(f"/api/meals/{meal_id}/glucose", json={"value_mmol": 10.2})
    question = {"session_id": "shared", "question": "我上次吃米饭血糖怎么样"}

    alice_run = _run_id(alice.post("/api/chat", json=question))
    bob_run = _run_id(bob.post("/api/chat", json=question))

    def memory_quotes(run_id, client):
        snap = client.get(f"/api/tasks/{run_id}").json()
        return [e["quote"] for e in snap["evidence"].values() if e.get("channel") == "memory"]

    assert any("10.2" in q for q in memory_quotes(alice_run, alice))
    # bob 只拿到「自己还没有记录」的提示，看不到 alice 的任何数值
    bob_quotes = memory_quotes(bob_run, bob)
    assert bob_quotes and all("还没有任何餐食记录" in q for q in bob_quotes)
    assert all("10.2" not in q and "alice" not in q for q in bob_quotes)


def test_guest_data_is_separate_from_logged_in_users(guest, alice):
    meal = guest.post("/api/meals", json=MEAL).json()["meal"]
    assert meal["user_id"] == "local"
    assert [m["meal_id"] for m in guest.get("/api/meals").json()["meals"]] == [meal["meal_id"]]
    run_id = _run_id(guest.post("/api/chat", json={"question": "米饭多少碳水"}))
    assert guest.get(f"/api/tasks/{run_id}").status_code == 200
    # 登录后看不到单机演示身份的数据，退出登录也不会把账号数据留给 local
    assert alice.get("/api/meals").json()["meals"] == []
    assert alice.get(f"/api/tasks/{run_id}").status_code == 404