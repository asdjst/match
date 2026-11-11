import re

# 中文注入规则：覆盖指令覆盖 / 角色扮演 / 数据外泄三类；输入检查与证据净化共用
INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # —— 指令覆盖 ——
    ("指令覆盖", re.compile(r"(忽略|无视|不要管|不用管|不管|停止遵循).{0,12}(指令|规则|限制|要求|设定|准则)")),
    ("指令覆盖", re.compile(r"(覆盖|作废|取消|清空).{0,10}(指令|设定|规则|限制)")),
    ("指令覆盖", re.compile(r"(设定|指令|规则|限制).{0,8}(作废|清零|不算数)")),
    ("指令覆盖", re.compile(r"(不用|无需|不)遵守(任何|所有|一切)?(规则|限制|约束|准则)")),
    ("指令覆盖", re.compile(r"\b(ignore|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts)", re.I)),
    # —— 角色扮演 / 越狱 ——
    ("角色扮演", re.compile(r"(你(现在)?(是|扮演|假装|变成)|假装你是|假设你是|扮演).{0,14}(没有|不存在|不受|不会拒绝|无视|不遵守|越狱|DAN)", re.I)),
    ("角色扮演", re.compile(r"(开发者模式|上帝模式|越狱版?|god ?mode|developer ?mode)", re.I)),
    ("角色扮演", re.compile(r"roleplay\s+as.{0,30}(without|no)\s+\w*\s?(safety|filter|restriction|limit)", re.I)),
    ("角色扮演", re.compile(r"设定.{0,2}(是|为).{0,4}(无视|不遵守|不受|不顾)")),
    ("角色扮演", re.compile(r"(不会|不许|不能|从不)拒绝(任何|所有的?)?(请求|要求|问题)")),
    ("角色扮演", re.compile(r"(什么|任何问题|任何请求)你?都(要|会|能)?(答|回答|照做|执行)")),
    # —— 数据外泄（提示词/内部指令套取）——
    ("数据外泄", re.compile(r"(系统提示|system ?prompt|系统消息|内部指令|初始指令|隐藏指令|内部设定|原始指令|提示词模板)", re.I)),
    ("数据外泄", re.compile(r"(泄露|导出|输出|打印|复述|发给我|告诉我).{0,12}(指令|设定|配置|提示词)")),
    ("数据外泄", re.compile(r"你被(设定|告知|要求).{0,10}(指令|规则)")),
    ("数据外泄", re.compile(r"你的 ?(system ?)?prompt", re.I)),
    ("数据外泄", re.compile(r"\b(list|show|reveal|export)\s+(all\s+)?(hidden|internal|your)\s+(instructions|prompts)", re.I)),
]

_MARK = "［已过滤可疑指令］"


def neutralize(text: str) -> tuple[str, list[str]]:
    """把文本中的注入片段替换为占位标记，返回净化文本与命中的类别。"""
    hits: list[str] = []
    for name, pattern in INJECTION_PATTERNS:
        def _replace(_match, label=name) -> str:
            hits.append(label)
            return _MARK

        text = pattern.sub(_replace, text)
    return text, list(dict.fromkeys(hits))
