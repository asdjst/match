"""金标 50 条：定位信息直接取自 demo_assets/gluco_knowledge 的知识卡标题，
生成时校验每个 (文件, 小标题) 真实存在，避免人工标注漂移。

计算类带 context 列（个人血糖读数/代谢档案），评测时注入 state，工具才有确定性入参。

用法: .venv/bin/python eval/golden.py   （生成 eval/golden_50.csv）
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.parsing.markdown_parsing import MarkdownParser  # noqa: E402

KNOWLEDGE_DIR = ROOT / "demo_assets" / "gluco_knowledge"
CARDS = {
    "NUT": "中国2型糖尿病防治指南2020_医学营养治疗_摘编.md",
    "TARGET": "中国2型糖尿病防治指南2020_血糖控制目标_摘编.md",
    "GI": "中国糖尿病医学营养治疗指南2022_GI与GL_摘编.md",
    "HYPO": "低血糖与监测_摘编.md",
    "FOOD": "常见食物碳水速查_摘编.md",
    "EIGHT": "成人糖尿病食养指南2023_八条原则_摘编.md",
    "PLATE": "成人糖尿病食养指南2023_餐盘与进餐顺序_摘编.md",
    "FIBER": "膳食纤维盐糖_摘编.md",
}
_SECTIONS = {
    name: {p.section for p in MarkdownParser().parse(KNOWLEDGE_DIR / name)}
    for name in CARDS.values()
}

Q: list[dict] = []


def src(*refs: tuple[str, str]) -> str:
    out = []
    for card, section in refs:
        name = CARDS[card]
        if section not in _SECTIONS[name]:
            raise SystemExit(f"知识卡里没有这个小标题：{name}#{section}")
        out.append(f"{name}#{section}")
    return " | ".join(out)


def add(qid, qtype, question, expected_sources, expected_answer, variant="", context=None):
    Q.append({
        "qid": qid,
        "qtype": qtype,
        "question": question,
        "expected_sources": expected_sources,
        "expected_answer": expected_answer,
        "variant": variant,
        "context": json.dumps(context, ensure_ascii=False) if context else "",
    })


def fact(qid, question, refs, answer, variant=""):
    add(qid, "事实", question, src(*refs), answer, variant)


# ---- 事实类：食物成分与份量估算 ----
fact("F01", "一碗米饭大概多少碳水？", [("FOOD", "米饭与杂粮饭"), ("FOOD", "如何估算一碗的碳水")], "熟重150克约39克碳水")
fact("F02", "150克熟米饭的碳水怎么算出来？", [("FOOD", "如何估算一碗的碳水"), ("FOOD", "米饭与杂粮饭")], "150×25.9÷100≈38.9克", "改写")
fact("F03", "米饭每100克含多少碳水？", [("FOOD", "米饭与杂粮饭")], "25.9克")
fact("F04", "米饭的GI大概是多少？", [("FOOD", "米饭与杂粮饭")], "约83")
fact("F05", "馒头每100克含多少碳水？", [("FOOD", "面食与馒头")], "47.0克")
fact("F06", "一个中等馒头大概多少碳水？", [("FOOD", "面食与馒头")], "按100克估算约47克", "改写")
fact("F07", "白粥的碳水和GI是多少？", [("FOOD", "粥与薯类")], "每100克9.9克碳水，GI约78")
fact("F08", "一碗300克白粥多少碳水？", [("FOOD", "粥与薯类")], "约30克")
fact("F09", "红薯每100克含多少碳水？", [("FOOD", "粥与薯类")], "20.1克")
fact("F10", "杂粮饭和糙米饭的GI分别是多少？", [("FOOD", "米饭与杂粮饭")], "杂粮饭约54，糙米饭约55")

# ---- 事实类：GI/GL 口径 ----
fact("F11", "低GI的界限是多少？", [("GI", "升糖指数 GI 的含义")], "GI≤55为低GI")
fact("F12", "多高的GI算高GI食物？", [("GI", "升糖指数 GI 的含义")], "GI≥70", "改写")
fact("F13", "血糖负荷GL怎么计算？", [("GI", "血糖负荷 GL 的含义")], "GL=GI×可利用碳水克数÷100")
fact("F14", "单次摄入GL多高算高负荷？", [("GI", "血糖负荷 GL 的含义")], "GL≥20为高负荷")
fact("F15", "低GI食物可以不限量吃吗？", [("GI", "升糖指数 GI 的含义"), ("GI", "个体差异与监测")], "不能，仍要计入全天碳水总量")

# ---- 事实类：营养素与限量 ----
fact("F16", "碳水供能比建议是多少？", [("NUT", "碳水化合物"), ("EIGHT", "能量适宜与体重管理")], "占总能量45%～60%")
fact("F17", "蛋白质供能比建议是多少？", [("NUT", "蛋白质")], "占总能量15%～20%")
fact("F18", "脂肪供能比建议是多少？", [("NUT", "脂肪")], "占总能量20%～30%")
fact("F19", "每天食盐不超过多少克？", [("NUT", "限制盐、糖和酒"), ("FIBER", "隐形盐")], "不超过5克")
fact("F20", "每日膳食纤维建议摄入多少？", [("FIBER", "膳食纤维")], "25～30克")

# ---- 事实类：控制目标与监测 ----
fact("F21", "大多数成年2型糖尿病患者的糖化血红蛋白目标是多少？", [("TARGET", "多数成年患者的控制目标")], "7.0%以下")
fact("F22", "空腹血糖目标范围是多少？", [("TARGET", "多数成年患者的控制目标")], "4.4～7.0 mmol/L")
fact("F23", "餐后血糖控制到多少算达标？", [("TARGET", "多数成年患者的控制目标")], "非空腹10.0 mmol/L以下", "改写")
fact("F24", "低血糖有哪些常见表现？", [("HYPO", "低血糖的常见表现")], "心慌、出汗、手抖、饥饿感、头晕、乏力")
fact("F25", "意识清醒的低血糖怎么处理？", [("HYPO", "意识清醒时的处理")], "口服15～20克快速吸收碳水，约15分钟后复测")
fact("F26", "患者意识不清时能喂糖水吗？", [("HYPO", "意识不清时")], "不要强行喂食喂水，立即呼叫急救")

# ---- 事实类：餐盘与食养 ----
fact("F27", "健康餐盘怎么分配？", [("PLATE", "健康餐盘比例")], "一半蔬菜、四分之一优质蛋白、四分之一主食")
fact("F28", "进餐顺序有什么建议？", [("PLATE", "推荐进餐顺序")], "先蔬菜，再蛋白质，最后主食")
fact("F29", "水果什么时候吃、吃多少？", [("PLATE", "水果怎么吃")], "两餐之间，每次约100～200克，并减少当餐主食")
fact("F30", "全谷物和杂豆应占主食多少？", [("EIGHT", "主食定量与低升糖主食")], "1/3以上")

# ---- 对比类 ----
add("C01", "对比", "米饭和杂粮饭哪个升糖更慢？",
    src(("FOOD", "米饭与杂粮饭"), ("GI", "低 GI 食物的选择")), "杂粮饭GI约54，低于米饭约83")
add("C02", "对比", "米饭和馒头哪个碳水更高？",
    src(("FOOD", "米饭与杂粮饭"), ("FOOD", "面食与馒头")), "馒头47.0克/100克，高于米饭25.9克/100克")
add("C03", "对比", "白粥和米饭哪个更容易升血糖？",
    src(("FOOD", "粥与薯类"), ("FOOD", "米饭与杂粮饭")), "白粥GI约78且消化快，餐后血糖反应可能并不低")
add("C04", "对比", "GI和GL有什么区别？",
    src(("GI", "升糖指数 GI 的含义"), ("GI", "血糖负荷 GL 的含义")), "GI只反映升糖速度，GL还计入实际碳水数量")
add("C05", "对比", "精制米面和全谷物主食怎么选？",
    src(("EIGHT", "主食定量与低升糖主食"), ("GI", "低 GI 食物的选择")), "优先全谷物与杂豆，占主食1/3以上")
add("C06", "对比", "糖化血红蛋白和指尖血糖各说明什么？",
    src(("TARGET", "多数成年患者的控制目标"), ("TARGET", "自我血糖监测")), "HbA1c反映近2～3个月均值，不反映即刻血糖与波动")

# ---- 计算类：个人读数统计（工具证据）----
READINGS = [5.6, 7.8, 10.2, 6.4, 8.1]
LOW_READINGS = [3.5, 5.2, 12.8, 9.4]
PROFILE = {"height_cm": 170, "activity": "轻度活动"}
GS = "tool://glucose_summary#"
CT = "tool://carb_target#"
add("M01", "计算", "我最近血糖平均是多少？", GS, "5条读数平均7.62 mmol/L", context={"glucose_values": READINGS})
add("M02", "计算", "我最近血糖波动大不大？", GS, "标准差1.77，CV 23.2%", context={"glucose_values": READINGS})
add("M03", "计算", "我最近血糖最高最低差多少？", GS, "LAGE 4.6 mmol/L（10.2−5.6）", context={"glucose_values": READINGS})
add("M04", "计算", "我最近血糖有多少在目标范围内？",
    f"{GS} | {src(('TARGET', '多数成年患者的控制目标'))}", "4/5条在3.9～10.0，按读数占80%",
    context={"glucose_values": READINGS})
add("M05", "计算", "我最近血糖有低于3.9的吗？",
    f"{GS} | {src(('HYPO', '低血糖的常见表现'))}", "1条3.5低于3.9，按读数占25%",
    context={"glucose_values": LOW_READINGS})
add("M06", "计算", "我每天该吃多少碳水？", CT, "219～341克/天", context={"profile": PROFILE})
add("M07", "计算", "三餐碳水怎么分？", CT, "早44～68克，午88～136克，晚88～136克", context={"profile": PROFILE})
add("M08", "计算", "我一天该吃多少主食？", CT, "每日能量1950～2275 kcal，对应碳水219～341克",
    variant="改写", context={"profile": PROFILE})

# ---- 库外负例（期望拒答） ----
for i, q in enumerate([
    "量子力学的薛定谔方程怎么推导？",
    "明天上海会下雨吗？",
    "帮我把这段话翻译成法语。",
    "怎么写一个快速排序算法？",
    "明朝的开国皇帝是谁？",
    "推荐几部好看的科幻电影。",
], start=1):
    add(f"X{i:02d}", "库外", q, "", "拒答")


def main() -> None:
    out = ROOT / "eval" / "golden_50.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "qtype", "question", "expected_sources", "expected_answer", "variant", "context", "human_review"])
        w.writeheader()
        for row in Q:
            w.writerow({**row, "human_review": ""})
    from collections import Counter

    print(f"golden_50.csv: {len(Q)} 条；分布 {dict(Counter(r['qtype'] for r in Q))}")


if __name__ == "__main__":
    main()