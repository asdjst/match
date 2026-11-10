"""生成演示物料：A公司2024年报.pdf（段落编号 80-95）、报表截图.png（第2页表格）、
业绩说明会.m4a + 转写 JSON（真实时间码 03:12 / 07:45）。

用法: .venv/bin/python scripts/make_demo_assets.py   （输出到 demo_assets/）
"""
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_assets"

PARAS = {
    80: "本公司董事会及董事保证本报告所载资料不存在任何虚假记载、误导性陈述或者重大遗漏。",
    81: "本年度公司围绕数字化转型的长期战略，持续加大研发投入与渠道建设。",
    82: "公司主营业务为智能设备与配套软件服务的研发、生产与销售。",
    83: "报告期内，公司新增授权专利 12 项，累计授权专利达到 86 项。",
    84: "公司主要客户集中于华东与华南地区，前五大客户收入占比为 42%。",
    85: "本报告未经审计部分与已审计财务报告不存在重大差异。",
    86: "公司管理层对下一年度经营计划进行了充分的可行性研究与风险评估。",
    87: "2024年公司实现营业收入120亿元。",
    88: "2023年公司实现营业收入100亿元。",
    89: "营业收入增长主要来自核心产品放量与海外市场拓展。",
    90: "2024年公司毛利率为38%，2023年公司毛利率为35%。",
    91: "毛利率变化主要受产品结构与原材料价格波动影响。",
    92: "营收与毛利率概览：2024年营业收入120亿元，毛利率38%；2023年营业收入100亿元，毛利率35%。",
    93: "公司经营活动产生的现金流量净额为 21 亿元，同比保持稳健。",
    94: "报告期末，公司员工总数为 8,600 人，其中研发人员占比 28%。",
    95: "本节内容中涉及的未来计划、发展战略等前瞻性陈述，不构成公司对投资者的实质承诺。",
}

AUDIO_SEGS = [
    {"time_code": "03:12", "text": "本年度收入增长主要来自核心产品销量提升与新市场放量。"},
    {"time_code": "07:45", "text": "毛利率改善主要得益于供应链成本优化与产品结构升级。"},
]
# 段落在音频里的真实起点（秒）：03:12=192, 07:45=465
SEG_STARTS = [192, 465]
RATE = 16000


def _make_pdf() -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    path = OUT / "A公司2024年报.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("STSong-Light", 18)
    c.drawCentredString(width / 2, height - 3 * cm, "A公司 2024 年年度报告")
    c.setFont("STSong-Light", 12)

    y = height - 5 * cm
    page = 1
    for num in sorted(PARAS):
        if y < 3 * cm:
            c.showPage()
            page += 1
            c.setFont("STSong-Light", 12)
            y = height - 3 * cm
        c.setFont("STSong-Light", 12)
        c.drawString(2.5 * cm, y, f"{num}. {PARAS[num]}")
        c.setFont("Helvetica", 9)
        c.drawRightString(width - 2 * cm, 1.5 * cm, str(page))
        y -= 1.1 * cm
    c.save()
    return path


def _load_cjk_font(size: int):
    from PIL import ImageFont

    for cand, idx in [
        ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
        ("/System/Library/Fonts/PingFang.ttc", 0),
        ("/System/Library/Fonts/STHeiti Light.ttc", 0),
    ]:
        try:
            return ImageFont.truetype(cand, size, index=idx)
        except OSError:
            continue
    raise RuntimeError("未找到系统中文字体")


def _make_png() -> Path:
    from PIL import Image, ImageDraw

    path = OUT / "报表截图.png"
    w, h = 720, 360
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    font_t = _load_cjk_font(22)
    font_c = _load_cjk_font(18)
    d.text((24, 16), "报表第 2 页：主要财务数据摘录", fill="black", font=font_t)
    cols = [24, 300, 480, 620]
    rows_y = [80, 150, 220]
    for x in cols:
        d.line([(x, 70), (x, 290)], fill="gray", width=2)
    for y in rows_y + [290]:
        d.line([(24, y), (696, y)], fill="gray", width=2)
    for i, text in enumerate(["指标", "2024", "2023"]):
        d.text((cols[i] + 12, rows_y[0] + 25), text, fill="black", font=font_c)
    data = [("营业收入", "120亿", "100亿"), ("毛利率", "38%", "35%")]
    for r, row in enumerate(data, start=1):
        for i, cell in enumerate(row):
            d.text((cols[i] + 12, rows_y[r] + 25), cell, fill="black", font=font_c)
    img.save(path, "PNG")
    return path


def _say_to_wav(text: str, wav: Path) -> None:
    aiff = wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), text], check=True)
    subprocess.run(
        ["afconvert", str(aiff), str(wav), "-d", "LEI16@16000", "-f", "WAVE", "-c", "1"],
        check=True,
    )
    aiff.unlink()


def _read_wav(path: Path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
        width = w.getsampwidth()
    if width != 2:
        raise RuntimeError("期望 16bit wav")
    n = len(frames) // 2
    samples = list(struct.unpack(f"<{n}h", frames))
    return rate, samples


def _make_audio() -> tuple[Path, Path]:
    tmp1, tmp2 = OUT / "_seg1.wav", OUT / "_seg2.wav"
    _say_to_wav(AUDIO_SEGS[0]["text"], tmp1)
    _say_to_wav(AUDIO_SEGS[1]["text"], tmp2)
    rate, seg1 = _read_wav(tmp1)
    _, seg2 = _read_wav(tmp2)
    if rate != RATE:
        raise RuntimeError(f"say 输出采样率 {rate} 不是 {RATE}")

    total = SEG_STARTS[1] + len(seg2) // rate + 2
    buf = [0] * (total * RATE)
    for offset, seg in ((SEG_STARTS[0], seg1), (SEG_STARTS[1], seg2)):
        start = offset * RATE
        for i, s in enumerate(seg):
            if start + i < len(buf):
                buf[start + i] = max(-32768, min(32767, int(s * 0.9)))

    wav = OUT / "业绩说明会.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{len(buf)}h", *buf))

    m4a = OUT / "业绩说明会.m4a"
    subprocess.run(
        ["afconvert", str(wav), str(m4a), "-d", "aac", "-f", "m4af"],
        check=True,
    )
    wav.unlink()
    tmp1.unlink()
    tmp2.unlink()

    transcript = OUT / "业绩说明会_转写.json"
    transcript.write_text(
        __import__("json").dumps({"segments": AUDIO_SEGS}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return m4a, transcript


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pdf = _make_pdf()
    png = _make_png()
    m4a, transcript = _make_audio()
    for p in (pdf, png, m4a, transcript):
        print(f"{p.name}: {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    sys.exit(main())
