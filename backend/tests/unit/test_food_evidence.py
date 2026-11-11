from core.services.food import build_food_evidence

ITEM = {
    "name": "米饭",
    "grams_low": 150,
    "grams_high": 200,
    "carbs_g_low": 38.9,
    "carbs_g_high": 51.8,
    "confidence": 0.6,
    "basis": "米饭约 25.9g 碳水/100g",
}


def test_builds_item_and_total_evidence():
    normalized, pool = build_food_evidence("img1", [ITEM])

    assert normalized[0]["name"] == "米饭"
    assert list(pool) == ["E1", "E2"]
    assert pool["E1"]["channel"] == "image"
    assert pool["E1"]["source"]["file_path"] == "photo://img1"
    assert "碳水 38.9-51.8g" in pool["E1"]["quote"]
    assert pool["E2"]["quote"] == "拍照识别整餐合计：1 样食物，碳水 38.9-51.8g"
    assert pool["E2"]["score"] == 0.6


def test_invalid_items_are_dropped():
    _, pool = build_food_evidence("img2", [{**ITEM, "name": ""}, ITEM])

    assert list(pool) == ["E1", "E2"]
    assert "1 样食物" in pool["E2"]["quote"]


def test_manual_items_without_image_use_text_source():
    _, pool = build_food_evidence(None, [ITEM])

    assert pool["E1"]["source"]["file_path"] == "手动录入"
    assert pool["E1"]["source"]["modality"] == "text"


def test_no_valid_items_means_no_evidence():
    normalized, pool = build_food_evidence("img3", [{"name": "米饭", "grams_low": -1}])

    assert normalized == []
    assert pool == {}
