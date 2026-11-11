"""餐食记录存储与个人记忆召回。"""

from datetime import date, timedelta

from core.services.meals import memory_evidences
from core.services.store import MealStore


def _store(tmp_path) -> MealStore:
    return MealStore(tmp_path / "runs.db")


def _rice(store: MealStore, user_id: str = "u1", insulin: str = "") -> dict:
    return store.add_meal(
        user_id=user_id,
        eaten_at="2026-11-08T12:30",
        meal_type="午餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39, "gl": 32.4}],
        note="食堂",
        insulin_note=insulin,
    )


def test_meal_crud_and_glucose(tmp_path):
    store = _store(tmp_path)
    meal = _rice(store)
    assert meal["meal_id"]
    assert meal["carbs_g"] == 39
    assert meal["gl"] == 32.4

    reading = store.add_glucose(meal["meal_id"], 10.2, minutes_after=120)
    assert reading and reading["value_mmol"] == 10.2

    listed = store.list_meals("u1")
    assert len(listed) == 1
    assert listed[0]["readings"][0]["value_mmol"] == 10.2

    updated = store.update_meal(meal["meal_id"], {"note": "加了青菜"})
    assert updated and updated["note"] == "加了青菜"

    assert store.delete_glucose(meal["meal_id"], reading["reading_id"])
    assert store.get_meal(meal["meal_id"])["readings"] == []

    assert store.delete_meal(meal["meal_id"])
    assert store.list_meals("u1") == []


def test_meal_types_are_isolated_by_user(tmp_path):
    store = _store(tmp_path)
    _rice(store, "u1")
    assert store.list_meals("u2") == []


def test_memory_matches_food_and_includes_glucose(tmp_path):
    store = _store(tmp_path)
    meal = _rice(store, insulin="8 单位")
    store.add_glucose(meal["meal_id"], 10.2, minutes_after=120)
    store.add_glucose(meal["meal_id"], 5.6, minutes_after=0)

    hits = memory_evidences(store, "u1", "我上次吃米饭血糖怎么样")
    assert len(hits) == 1
    assert hits[0].channel == "memory"
    assert "米饭" in hits[0].quote
    assert "餐后 2 小时 10.2" in hits[0].quote
    assert "餐前 5.6" in hits[0].quote
    # 用户自记的用药不进入问答证据
    assert "8 单位" not in hits[0].quote


def test_memory_food_name_hit_without_recall_cue(tmp_path):
    store = _store(tmp_path)
    _rice(store)
    assert len(memory_evidences(store, "u1", "米饭大概多少碳水")) == 1


def test_memory_falls_back_to_recent_on_recall_cue(tmp_path):
    store = _store(tmp_path)
    _rice(store)
    store.add_meal(
        user_id="u1",
        eaten_at="2026-11-09T18:40",
        meal_type="晚餐",
        foods=[{"name": "西兰花", "grams": 180, "carbs_g": 7.7}],
    )
    hits = memory_evidences(store, "u1", "上次那顿吃得怎么样")
    assert len(hits) == 2
    assert "西兰花" in hits[0].quote  # 最近一条排在最前


def test_memory_ignores_unrelated_question_and_other_users(tmp_path):
    store = _store(tmp_path)
    _rice(store, "u1")
    assert memory_evidences(store, "u1", "今天天气怎么样") == []
    assert memory_evidences(store, "u2", "我上次吃米饭怎么样") == []


def test_photo_target_foods_get_explicit_check_evidence(tmp_path):
    store = _store(tmp_path)
    _rice(store)
    hits = memory_evidences(
        store,
        "u1",
        "我之前吃过这些吗？",
        target_foods=["米饭", "甜玉米"],
    )
    check = hits[0]
    assert check.doc_id == "meal-check"
    assert "找到" in check.quote and "米饭" in check.quote
    # 未命中的食物也要写清楚，避免分析员拿无关记录硬答
    assert "甜玉米" not in check.quote


def test_photo_check_evidence_without_any_record(tmp_path):
    store = _store(tmp_path)
    hits = memory_evidences(store, "u1", "我之前吃过这些吗？", target_foods=["甜玉米"])
    assert [h.doc_id for h in hits] == ["meal-check"]
    assert "还没有任何餐食记录" in hits[0].quote


def test_today_list_returns_todays_meals_in_time_order(tmp_path):
    store = _store(tmp_path)
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    store.add_meal(
        user_id="u1",
        eaten_at=f"{today.isoformat()}T18:10",
        meal_type="晚餐",
        foods=[{"name": "米饭", "grams": 225, "carbs_g": 58.3}],
    )
    store.add_meal(
        user_id="u1",
        eaten_at=f"{today.isoformat()}T08:00",
        meal_type="早餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39}],
    )
    store.add_meal(
        user_id="u1",
        eaten_at=f"{yesterday}T12:30",
        meal_type="午餐",
        foods=[{"name": "甜玉米段", "grams": 150, "carbs_g": 34.2}],
    )

    hits = memory_evidences(store, "u1", "我今天吃了什么？")
    assert len(hits) == 2
    assert "早餐" in hits[0].quote and "晚餐" in hits[1].quote
    assert all(yesterday not in hit.quote for hit in hits)


def test_today_list_without_records_says_empty(tmp_path):
    store = _store(tmp_path)
    store.add_meal(
        user_id="u1",
        eaten_at=f"{(date.today() - timedelta(days=1)).isoformat()}T12:30",
        meal_type="午餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39}],
    )
    hits = memory_evidences(store, "u1", "今天吃了什么")
    assert [h.doc_id for h in hits] == ["meal-day"]
    assert "今天" in hits[0].quote and "没有餐食记录" in hits[0].quote


def test_today_list_on_empty_archive(tmp_path):
    hits = memory_evidences(_store(tmp_path), "u1", "今天吃了什么")
    assert [h.doc_id for h in hits] == ["meal-day"]
    assert "还没有任何餐食记录" in hits[0].quote


def test_recent_glucose_question_gets_stats_evidence(tmp_path):
    store = _store(tmp_path)
    today = date.today().isoformat()
    meal = store.add_meal(
        user_id="u1",
        eaten_at=f"{today}T12:30",
        meal_type="午餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39}],
    )
    store.add_glucose(meal["meal_id"], 10.2, minutes_after=120)
    store.add_glucose(meal["meal_id"], 5.6, minutes_after=0)

    hits = memory_evidences(store, "u1", "我最近血糖怎么样")
    assert [h.doc_id for h in hits] == ["meal-stats"]
    assert "共 2 条血糖记录" in hits[0].quote
    assert "10.2" in hits[0].quote and "餐前 5.6" in hits[0].quote


def test_week_carbs_question_sums_by_day(tmp_path):
    store = _store(tmp_path)
    today = date.today()
    store.add_meal(
        user_id="u1",
        eaten_at=f"{today.isoformat()}T12:30",
        meal_type="午餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39}],
    )
    store.add_meal(
        user_id="u1",
        eaten_at=f"{(today - timedelta(days=1)).isoformat()}T12:30",
        meal_type="午餐",
        foods=[{"name": "甜玉米段", "grams": 150, "carbs_g": 34.2}],
    )

    hits = memory_evidences(store, "u1", "我这周碳水多少")
    assert [h.doc_id for h in hits] == ["meal-stats"]
    assert "共 2 餐" in hits[0].quote
    assert "碳水合计 73.2g" in hits[0].quote


def test_glucose_question_without_readings_says_empty(tmp_path):
    store = _store(tmp_path)
    store.add_meal(
        user_id="u1",
        eaten_at=f"{date.today().isoformat()}T12:30",
        meal_type="午餐",
        foods=[{"name": "米饭", "grams": 150, "carbs_g": 39}],
    )
    hits = memory_evidences(store, "u1", "我最近血糖怎么样")
    assert [h.doc_id for h in hits] == ["meal-stats"]
    assert "没有记录血糖" in hits[0].quote
