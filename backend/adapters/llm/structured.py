from pydantic import ValidationError


def complete_structured(call, prompt, retries: int = 2):
    """结构化输出 + 失败自动重试：把校验错误回灌进 format_hint，最多重试 2 次。

    call: PromptBundle -> BaseModel（内部负责取文本并解析成 schema）。
    """
    last_error: Exception | None = None
    attempt_prompt = prompt
    for _ in range(retries + 1):
        try:
            return call(attempt_prompt)
        except (ValidationError, ValueError, KeyError) as e:
            last_error = e
            attempt_prompt = prompt.model_copy(update={
                "format_hint": f"{prompt.format_hint}\n上次输出非法（{e}），必须输出可解析的合法 JSON。"
            })
    raise last_error  # type: ignore[misc]


def extract_json(text: str) -> str:
    import re

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"输出中没有 JSON：{text[:80]}")
    return match.group(0)
