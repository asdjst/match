"""金标 50 条：从演示语料（scripts/make_demo_assets.py 的段落表）确定性生成草标 CSV，
人工只需复核 human_review 列。expected_sources 用入库元数据的真实定位。

用法: .venv/bin/python eval/golden.py   （生成 eval/golden_50.csv）
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from make_demo_assets import AUDIO_SEGS, PARAS  # noqa: E402

PDF = "A公司2024年报.pdf"
IMG = "报表截图.png"
AUDIO = "业绩说明会.m4a"

Q: list[dict] = []


def fact(qid, q, paras, ans, variant="", extra=""):
    src = " ".join(f"{PDF}#第{p}段" for p in paras)
    if extra:
        src = f"{src} {extra}"
    Q.append({"qid": qid, "qtype": "事实", "question": q, "expected_sources": src, "expected_answer": ans, "variant": variant})


# ---- 事实类：数字段（每段 2 个问法）----
fact("F01", "2024年公司实现营业收入多少亿元？", [87, 92], "120亿元", "", extra=f"{IMG}#第2页")
fact("F02", "A公司2024年的营业收入是多少？", [87, 92], "120亿元", "改写", extra=f"{IMG}#第2页")
fact("F03", "2023年公司实现营业收入多少亿元？", [88, 92], "100亿元", "", extra=f"{IMG}#第2页")
fact("F04", "A公司2023年的营业收入是多少？", [88, 92], "100亿元", "改写", extra=f"{IMG}#第2页")
fact("F05", "2024年公司毛利率是多少？", [90, 92], "38%", "", extra=f"{IMG}#第2页")
fact("F06", "2023年公司毛利率是多少？", [90, 92], "35%", "改写", extra=f"{IMG}#第2页")
fact("F07", "2024年经营活动现金流量净额是多少？", [93], "21亿元")
fact("F08", "报告期末公司员工总数是多少？", [94], "8600人")
fact("F09", "公司研发人员占比是多少？", [94], "28%")
fact("F10", "2024年新增授权专利多少项？", [83], "12项")
fact("F11", "公司累计授权专利达到多少项？", [83], "86项")
fact("F12", "前五大客户收入占比是多少？", [84], "42%")

# ---- 事实类：定性段 ----
fact("F13", "公司董事会对本报告的真实性做了什么保证？", [80], "不存在虚假记载、误导性陈述或重大遗漏")
fact("F14", "公司本年度围绕什么战略开展工作？", [81], "数字化转型的长期战略")
fact("F15", "公司主营业务是什么？", [82], "智能设备与配套软件服务的研发、生产与销售")
fact("F16", "下一年度经营计划做了什么工作？", [86], "可行性研究与风险评估")
fact("F17", "报告中的前瞻性陈述是否构成对投资者的承诺？", [95], "不构成实质承诺")
fact("F18", "本报告未经审计部分与已审计财务报告是否存在重大差异？", [85], "不存在重大差异")

# ---- 原因类 ----
fact("F19", "2024年营业收入增长的主要原因是什么？", [89], "核心产品放量与海外市场拓展")
fact("F20", "毛利率变化主要受什么影响？", [91], "产品结构与原材料价格波动")

# ---- 事实改写补充 ----
fact("F21", "公司经营活动现金流量净额情况如何？", [93], "21亿元，同比保持稳健", "改写")
fact("F22", "报告期末公司有多少员工？", [94], "8600人", "改写")
fact("F23", "公司专利情况怎么样？", [83], "新增12项，累计86项", "改写")
fact("F24", "公司客户集中度如何？", [84], "前五大客户收入占比42%", "改写")
fact("F25", "公司靠什么业务赚钱？", [82], "智能设备与配套软件服务", "改写")
fact("F26", "未经审计的财务数据和已审计报告有出入吗？", [85], "不存在重大差异", "改写")

# ---- 图像类 ----
IMG_SRC = f"{IMG}#第2页"
Q.append({"qid": "I01", "qtype": "图像", "question": "报表截图里2024年营业收入是多少？", "expected_sources": IMG_SRC, "expected_answer": "120亿", "variant": ""})
Q.append({"qid": "I02", "qtype": "图像", "question": "报表截图里2023年营业收入是多少？", "expected_sources": IMG_SRC, "expected_answer": "100亿", "variant": ""})
Q.append({"qid": "I03", "qtype": "图像", "question": "报表截图里2024年毛利率是多少？", "expected_sources": IMG_SRC, "expected_answer": "38%", "variant": ""})
Q.append({"qid": "I04", "qtype": "图像", "question": "报表截图里的表格包含哪两个指标？", "expected_sources": IMG_SRC, "expected_answer": "营业收入、毛利率", "variant": ""})
Q.append({"qid": "I05", "qtype": "图像", "question": "报表截图对比了哪两个年度？", "expected_sources": IMG_SRC, "expected_answer": "2024 与 2023", "variant": ""})

# ---- 音频类 ----
for i, seg in enumerate(AUDIO_SEGS, start=1):
    Q.append({"qid": f"A0{i}", "qtype": "音频", "question": f"业绩说明会里提到{('收入增长' if i == 1 else '毛利率改善')}的原因是什么？", "expected_sources": f"{AUDIO}#{seg['time_code']}", "expected_answer": seg["text"].replace("本年度", "").replace("主要", "").strip("。"), "variant": ""})
Q.append({"qid": "A03", "qtype": "音频", "question": "管理层在业绩说明会上谈到了哪些利好因素？", "expected_sources": f"{AUDIO}#03:12 {AUDIO}#07:45", "expected_answer": "收入增长与毛利率改善的原因", "variant": "汇总"})
Q.append({"qid": "A04", "qtype": "音频", "question": "业绩说明会 03:12 处讲了什么？", "expected_sources": f"{AUDIO}#03:12", "expected_answer": AUDIO_SEGS[0]["text"], "variant": ""})
Q.append({"qid": "A05", "qtype": "音频", "question": "业绩说明会 07:45 处讲了什么？", "expected_sources": f"{AUDIO}#07:45", "expected_answer": AUDIO_SEGS[1]["text"], "variant": ""})

# ---- 对比类 ----
Q.append({"qid": "C01", "qtype": "对比", "question": "2024年和2023年的营业收入相比怎么样？", "expected_sources": f"{PDF}#第87段 {PDF}#第88段 {PDF}#第92段", "expected_answer": "120亿 vs 100亿，增加20亿元", "variant": ""})
Q.append({"qid": "C02", "qtype": "对比", "question": "2024年和2023年的毛利率相比怎么样？", "expected_sources": f"{PDF}#第90段 {PDF}#第92段", "expected_answer": "38% vs 35%，上升3个百分点", "variant": ""})
Q.append({"qid": "C03", "qtype": "对比", "question": "年报和报表截图里的2024年营业收入一致吗？", "expected_sources": f"{PDF}#第87段 {IMG}#第2页", "expected_answer": "一致，均为120亿", "variant": ""})
Q.append({"qid": "C04", "qtype": "对比", "question": "研发人员占比和员工总数分别是多少？", "expected_sources": f"{PDF}#第94段", "expected_answer": "8600人，28%", "variant": ""})
Q.append({"qid": "C05", "qtype": "对比", "question": "营业收入和毛利率哪个指标的变化幅度更大？", "expected_sources": f"{PDF}#第87段 {PDF}#第88段 {PDF}#第90段 {PDF}#第92段 {IMG}#第2页 tool://growth_rate#", "expected_answer": "营收增长20%，毛利率上升3个百分点", "variant": ""})

# ---- 计算类 ----
Q.append({"qid": "M01", "qtype": "计算", "question": "2024年营业收入相比2023年增长了多少？", "expected_sources": f"{PDF}#第87段 {PDF}#第88段 {PDF}#第92段 {IMG}#第2页 tool://growth_rate#", "expected_answer": "20.0%", "variant": ""})
Q.append({"qid": "M02", "qtype": "计算", "question": "2024年毛利率比2023年高多少个百分点？", "expected_sources": f"{PDF}#第90段 {PDF}#第92段", "expected_answer": "3个百分点", "variant": ""})
Q.append({"qid": "M03", "qtype": "计算", "question": "营业收入两年相差多少亿元？", "expected_sources": f"{PDF}#第87段 {PDF}#第88段 {PDF}#第92段 {IMG}#第2页", "expected_answer": "20亿元", "variant": ""})

# ---- 库外负例（期望拒答） ----
for i, q in enumerate([
    "量子力学的薛定谔方程怎么推导？",
    "明天上海会下雨吗？",
    "帮我把这段话翻译成法语。",
    "怎么写一个快速排序算法？",
    "明朝的开国皇帝是谁？",
    "推荐几部好看的科幻电影。",
], start=1):
    Q.append({"qid": f"X{i:02d}", "qtype": "库外", "question": q, "expected_sources": "", "expected_answer": "拒答", "variant": ""})

Q = Q[:50]


def main() -> None:
    out = ROOT / "eval" / "golden_50.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "qtype", "question", "expected_sources", "expected_answer", "variant", "human_review"])
        w.writeheader()
        for row in Q:
            w.writerow({**row, "human_review": ""})
    from collections import Counter

    print(f"golden_50.csv: {len(Q)} 条；分布 {dict(Counter(r['qtype'] for r in Q))}")


if __name__ == "__main__":
    main()
