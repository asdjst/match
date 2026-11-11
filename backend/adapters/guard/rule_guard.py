import re

from core.schemas.guard import GuardVerdict
from core.services.injection import INJECTION_PATTERNS

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_RE = re.compile(r"(?<!\d)(?:62\d{14,17}|[45]\d{15})(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 医疗红线：只拦「剂量/用药调整」，不拦“胰岛素是什么”这类科普
_MEDICAL_PATTERNS = (
    ("胰岛素剂量", re.compile(r"胰岛素[^。！？\n]{0,16}(剂量|单位|打多少|打几|加多少|加几|减多少|调整|补打|补针)")),
    ("胰岛素注射", re.compile(r"(打|注射)[^。！？\n]{0,10}(胰岛素)?[^。！？\n]{0,6}(单位|IU|iu)")),
    ("用药调整", re.compile(r"(二甲双胍|磺脲|格列|阿卡波糖|降糖药)[^。！？\n]{0,12}(吃几|吃多少|加量|减量|停药|换药|剂量)")),
)


class RuleGuard:
    """规则版守卫：输入查注入与医疗剂量红线，进出均做中文 PII 脱敏（手机号/身份证/银行卡/邮箱）。"""

    def inspect_input(self, text: str) -> GuardVerdict:
        hits = [name for name, pattern in INJECTION_PATTERNS if pattern.search(text)]
        if hits:
            return GuardVerdict(allowed=False, reason=f"检测到提示注入（{hits[0]}）", patterns_hit=hits)
        medical = [name for name, pattern in _MEDICAL_PATTERNS if pattern.search(text)]
        if medical:
            return GuardVerdict(
                allowed=False,
                reason=f"涉及医疗决策（{medical[0]}），本系统不提供胰岛素或用药剂量建议",
                patterns_hit=medical,
            )
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
