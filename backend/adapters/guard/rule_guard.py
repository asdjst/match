import re

from core.schemas.guard import GuardVerdict

# 中文注入以规则为主通道（覆盖三类：指令覆盖 / 角色扮演 / 数据外泄），W3 起 LLM 自检双通道
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
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

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_RE = re.compile(r"(?<!\d)(?:62\d{14,17}|[45]\d{15})(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class RuleGuard:
    """规则版守卫：输入查注入，进出均做中文 PII 脱敏（手机号/身份证/银行卡/邮箱）。"""

    def inspect_input(self, text: str) -> GuardVerdict:
        hits = [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]
        if hits:
            return GuardVerdict(allowed=False, reason=f"检测到提示注入（{hits[0]}）", patterns_hit=hits)
        return GuardVerdict(allowed=True, sanitized=text)

    def sanitize(self, text: str) -> str:
        text = _PHONE_RE.sub(lambda m: f"{m.group(0)[:3]}****{m.group(0)[7:]}", text)
        text = _ID_RE.sub(lambda m: f"{m.group(0)[:4]}***********{m.group(0)[-2:]}", text)
        text = _BANK_RE.sub(lambda m: f"{m.group(0)[:4]}{'*' * (len(m.group(0)) - 7)}{m.group(0)[-3:]}", text)
        text = _EMAIL_RE.sub(lambda m: f"{m.group(0).split('@')[0][:2]}***@{m.group(0).split('@')[1]}", text)
        return text

    def inspect_output(self, text: str) -> GuardVerdict:
        cleaned = self.sanitize(text)
        return GuardVerdict(allowed=True, sanitized=cleaned)
