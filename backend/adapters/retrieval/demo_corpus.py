from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence


def build_demo_corpus() -> list[Evidence]:
    """演示语料：年报 PDF / 报表截图 / 业绩说明会录音三种模态，供 fake 检索与单测。"""
    P = SourceRef
    return [
        Evidence(
            doc_id="annual_report",
            quote="2024年公司实现营业收入120亿元。",
            source=P(file_path="A公司2024年报.pdf", section="87"),
        ),
        Evidence(
            doc_id="annual_report",
            quote="2023年公司实现营业收入100亿元。",
            source=P(file_path="A公司2024年报.pdf", section="88"),
        ),
        Evidence(
            doc_id="annual_report",
            quote="2024年公司毛利率为38%，2023年为35%。",
            source=P(file_path="A公司2024年报.pdf", section="90"),
        ),
        Evidence(
            doc_id="annual_report",
            quote="营收与毛利率概览：2024年营业收入120亿元，毛利率38%；2023年营业收入100亿元，毛利率35%。",
            source=P(file_path="A公司2024年报.pdf", section="92"),
        ),
        Evidence(
            doc_id="report_screenshot",
            quote="报表截图表格：营业收入 | 120亿 | 100亿；毛利率 | 38% | 35%",
            source=P(file_path="报表截图.png", page=2, modality="image"),
        ),
        Evidence(
            doc_id="earnings_call",
            quote="本年度收入增长主要来自核心产品销量提升与新市场放量。",
            source=P(file_path="业绩说明会.m4a", time_code="03:12", modality="audio"),
        ),
        Evidence(
            doc_id="earnings_call",
            quote="毛利率改善主要得益于供应链成本优化与产品结构升级。",
            source=P(file_path="业绩说明会.m4a", time_code="07:45", modality="audio"),
        ),
    ]
