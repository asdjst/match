from core.services.memory import SessionMemory


def test_append_and_history():
    m = SessionMemory()
    for i in range(3):
        m.append("s1", {"i": i})
    # history 默认取最近 5 条，可按 last 截取
    assert m.history("s1") == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert m.history("s1", last=2) == [{"i": 1}, {"i": 2}]


def test_history_unknown_session():
    m = SessionMemory()
    # 未知的 session 返回空列表而不报错
    assert m.history("nope") == []
