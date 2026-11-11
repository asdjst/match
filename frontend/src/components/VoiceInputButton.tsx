/**
 * 语音输入按钮：浏览器原生 SpeechRecognition，识别结果直接追加到输入框。
 * 不支持的浏览器置灰并给出提示，不阻塞文字输入。
 */
import { useEffect, useRef, useState } from "react";

interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  isFinal: boolean;
  0: SpeechAlternative;
}
interface SpeechResultList {
  length: number;
  [index: number]: SpeechResult;
}
interface SpeechResultEvent {
  results: SpeechResultList;
}
interface SpeechErrorEvent {
  error: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
}
type SpeechCtor = new () => SpeechRecognitionLike;

function speechCtor(): SpeechCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERROR_TEXT: Record<string, string> = {
  "not-allowed": "麦克风权限被拒绝，请在浏览器设置里允许后重试。",
  "service-not-allowed": "麦克风权限被拒绝，请在浏览器设置里允许后重试。",
  "no-speech": "没有听到声音，再点一次试试。",
  "audio-capture": "没有找到可用的麦克风。",
  network: "语音服务连接失败，请检查网络后重试。",
};

const MIC_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" />
  </svg>
);

const STOP_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <rect x="7" y="7" width="10" height="10" rx="2" />
  </svg>
);

export function VoiceInputButton({
  value,
  onChange,
  onError,
}: {
  value: string;
  onChange: (next: string) => void;
  onError: (message: string | null) => void;
}) {
  const [supported, setSupported] = useState(() => Boolean(speechCtor()));
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const baseRef = useRef("");

  useEffect(() => {
    setSupported(Boolean(speechCtor()));
    return () => {
      recRef.current?.abort();
      recRef.current = null;
    };
  }, []);

  const stop = () => {
    recRef.current?.stop();
  };

  const start = () => {
    const Ctor = speechCtor();
    if (!Ctor) {
      onError("当前浏览器不支持语音输入，建议用 Chrome 或 Edge。");
      return;
    }
    const rec = new Ctor();
    rec.lang = "zh-CN";
    rec.continuous = false;
    rec.interimResults = true;
    baseRef.current = value;
    onError(null);

    rec.onresult = (event) => {
      let final = "";
      let interim = "";
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) final += text;
        else interim += text;
      }
      onChange(baseRef.current + (final + interim).trim());
    };
    rec.onerror = (event) => {
      onError(ERROR_TEXT[event.error] ?? `语音识别失败：${event.error}`);
      setListening(false);
    };
    rec.onend = () => {
      setListening(false);
      recRef.current = null;
    };

    try {
      rec.start();
      recRef.current = rec;
      setListening(true);
    } catch {
      onError("语音输入启动失败，请稍后重试。");
    }
  };

  return (
    <button
      type="button"
      className={`composer-mic${listening ? " is-listening" : ""}`}
      aria-label={listening ? "停止语音输入" : "语音输入"}
      aria-pressed={listening}
      title={supported ? (listening ? "停止语音输入" : "语音输入") : "当前浏览器不支持语音输入"}
      disabled={!supported}
      onClick={() => (listening ? stop() : start())}
    >
      {listening ? STOP_ICON : MIC_ICON}
    </button>
  );
}
