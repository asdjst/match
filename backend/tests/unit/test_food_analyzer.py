from types import SimpleNamespace

from adapters.vision.food import VlmFoodAnalyzer
from infra.config import TierConfig


def _analyzer() -> VlmFoodAnalyzer:
    return VlmFoodAnalyzer(TierConfig(model="demo", api_key="demo"))


def test_totals_and_conservative_confidence(monkeypatch, tmp_path):
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    analyzer = _analyzer()
    monkeypatch.setattr(analyzer, "_extract", lambda path: [
        {"name": "米饭", "grams_low": 150, "grams_high": 200, "carbs_per_100g": 25.9, "confidence": 0.8},
        {"name": "西兰花", "grams_low": 100, "grams_high": 100, "carbs_per_100g": 5.0, "confidence": 0.4},
    ])
    out = analyzer.analyze("img1", image)

    assert out.degraded is False
    assert [i.name for i in out.items] == ["米饭", "西兰花"]
    # 碳水以本地成分表为准（西兰花 4.3g/100g），不采用 VLM 自报的 5.0
    assert out.carbs_g_low == 43.2
    assert out.carbs_g_high == 56.1
    assert all("中国食物成分表" in i.basis for i in out.items)
    # 取最弱一项，防止一项离谱拉高整餐置信度
    assert out.confidence == 0.4


def test_unknown_food_carbs_are_labelled_as_model_estimate(monkeypatch, tmp_path):
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    analyzer = _analyzer()
    monkeypatch.setattr(analyzer, "_extract", lambda path: [
        {"name": "红油汤底", "grams_low": 50, "grams_high": 100, "carbs_per_100g": 4.0,
         "confidence": 0.5, "basis": "中国食物成分表"},
        {"name": "莲藕", "grams_low": 60, "grams_high": 70, "carbs_per_100g": 12.0, "confidence": 0.7},
    ])
    out = analyzer.analyze("img4", image)

    broth, lotus = out.items
    # 库外食物：模型自报的“成分表”出处不可信，改标为估算
    assert "模型估算" in broth.basis and "食物库未收录" in broth.basis
    assert broth.carbs_g_low == 2.0
    # 库内食物：碳水以成分表为准（16.4g/100g），GI 未收录要写清楚
    assert lotus.carbs_g_low == 9.8 and lotus.carbs_g_high == 11.5
    assert "16.4" in lotus.basis and "GI 未收录" in lotus.basis


def test_vlm_failure_degrades_to_manual_input(monkeypatch, tmp_path):
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    analyzer = _analyzer()

    def boom(path):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(analyzer, "_extract", boom)
    out = analyzer.analyze("img2", image)

    assert out.degraded is True
    assert out.items == []
    assert "手动输入" in out.notes


def test_invalid_item_is_skipped(monkeypatch, tmp_path):
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    analyzer = _analyzer()
    monkeypatch.setattr(analyzer, "_extract", lambda path: [
        {"grams_low": 100},
        {"name": "米饭", "grams_low": 100, "grams_high": 100, "carbs_per_100g": 25.9, "confidence": 0.7},
    ])
    out = analyzer.analyze("img3", image)

    assert [i.name for i in out.items] == ["米饭"]
    assert out.degraded is False


def test_reasoning_only_response_is_parsed(monkeypatch, tmp_path):
    """推理模型可能把 JSON 放在 reasoning_content、content 为空。"""
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    payload = (
        '{"items":[{"name":"米饭","grams_low":150,"grams_high":200,'
        '"carbs_per_100g":25.9,"confidence":0.8}]}'
    )

    def fake_completion(**kwargs):
        assert kwargs["max_tokens"] >= 4096
        message = SimpleNamespace(content="", reasoning_content=payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    out = _analyzer()._extract(image)

    assert out[0]["name"] == "米饭"
    assert out[0]["carbs_per_100g"] == 25.9
