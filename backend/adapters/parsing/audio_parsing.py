import json
import os
import re
from pathlib import Path

import httpx

from core.schemas.ingest import Passage


class TranscriptParser:
    """预转写 JSON（[{time_code, text}, …] 或 {segments:[…]}）→ 带时间码段落。
    FunASR 服务不可用时的兜底通道，演示物料自带转写文件。"""

    def parse(self, path: Path) -> list[Passage]:
        data = json.loads(path.read_text(encoding="utf-8"))
        segs = data.get("segments", data) if isinstance(data, dict) else data
        return [
            Passage(text=s["text"], time_code=s.get("time_code") or s.get("begin"))
            for s in segs
            if s.get("text")
        ]


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


class FunASRParser:
    """录音 → FunASR runtime HTTP 服务 → 带时间码段落。
    需配 MRAG_FUNASR_URL（如 docker 起的 funasr-runtime），未配置时抛错。"""

    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def parse(self, path: Path) -> list[Passage]:
        url = os.environ.get("MRAG_FUNASR_URL", self._url)
        files = {"files": (path.name, path.read_bytes(), "audio/wav")}
        resp = httpx.post(f"{url}/api/v1/asr", files=files, timeout=self._timeout_s, trust_env=False)
        resp.raise_for_status()
        payload = resp.json()
        sentences = payload.get("sentences") or payload.get("result", {}).get("sentences") or []
        out: list[Passage] = []
        for sent in sentences:
            text = (sent.get("text") or "").strip()
            if not text:
                continue
            begin = sent.get("begin")
            out.append(
                Passage(
                    text=text,
                    time_code=_fmt_ts(begin / 1000) if isinstance(begin, (int, float)) else None,
                )
            )
        if not out:
            raise ValueError(f"FunASR 未返回句子：{path.name}")
        return out
