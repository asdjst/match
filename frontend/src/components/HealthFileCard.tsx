/**
 * 浮动健康档案：工作台左下角图标展开的纸张式卡片。
 * 复用 ProfilePage 的嵌入式排版，可拖动、按方向键微调、卡内滚动。
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import ProfilePage from "../pages/ProfilePage";

type SectionKey = "basics" | "trend";

const TABS: Array<{ key: SectionKey; label: string }> = [
  { key: "basics", label: "基础档案" },
  { key: "trend", label: "健康趋势" },
];

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(value, max));

const prefersReducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 收起时把纸片折到触发图标的位置 */
function foldedTransform(
  paper: HTMLElement,
  anchor: HTMLButtonElement | null,
  position: { x: number; y: number } | null,
) {
  const parent = paper.parentElement;
  if (!anchor || !parent || !position) return "scale(.2)";
  const buttonRect = anchor.getBoundingClientRect();
  const parentRect = parent.getBoundingClientRect();
  const x = buttonRect.left - parentRect.left - position.x + 8;
  const y = buttonRect.top - parentRect.top - position.y - paper.offsetHeight + 35;
  return `translate(${x}px, ${y}px) rotate(-6deg) scale(.13, .1)`;
}

interface HealthFileCardProps {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLButtonElement | null>;
}

export default function HealthFileCard({ open, onClose, anchorRef }: HealthFileCardProps) {
  const paperRef = useRef<HTMLElement | null>(null);
  const gripRef = useRef<HTMLButtonElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const position = useRef<{ x: number; y: number } | null>(null);
  const moved = useRef(false);
  const drag = useRef<{
    id: number;
    startX: number;
    startY: number;
    x: number;
    y: number;
  } | null>(null);
  const animation = useRef<Animation | null>(null);
  const motionVersion = useRef(0);
  const [rendered, setRendered] = useState(open);
  const [section, setSection] = useState<SectionKey>("basics");
  const [dragging, setDragging] = useState(false);
  const [wide, setWide] = useState(false);
  const [hint, setHint] = useState("向下滚动查看更多");

  const place = useCallback((x: number, y: number) => {
    const paper = paperRef.current;
    const parent = paper?.parentElement;
    if (!paper || !parent) return;
    const maxX = Math.max(12, parent.clientWidth - paper.offsetWidth - 12);
    const maxY = Math.max(12, parent.clientHeight - paper.offsetHeight - 14);
    const next = { x: clamp(x, 12, maxX), y: clamp(y, 12, maxY) };
    position.current = next;
    paper.style.left = `${next.x}px`;
    paper.style.top = `${next.y}px`;
  }, []);

  /** 默认停在输入卡上方，避免遮住输入条 */
  const defaultPosition = useCallback(() => {
    const paper = paperRef.current;
    const parent = paper?.parentElement;
    if (!paper || !parent) return { x: 18, y: 12 };
    const parentRect = parent.getBoundingClientRect();
    const composer = parent.querySelector(".composer-shell");
    const composerTop = composer
      ? composer.getBoundingClientRect().top - parentRect.top
      : parent.clientHeight;
    return { x: 18, y: composerTop - paper.offsetHeight - 12 };
  }, []);

  const animate = useCallback(
    (opening: boolean) => {
      const paper = paperRef.current;
      if (!paper) return Promise.resolve();
      const version = ++motionVersion.current;
      animation.current?.cancel();
      const reduced = prefersReducedMotion();
      const folded = reduced
        ? { opacity: 0 }
        : {
            opacity: 0,
            transform: foldedTransform(paper, anchorRef.current, position.current),
            clipPath: "inset(16% 0 0 0 round 10px)",
          };
      const settled = reduced
        ? { opacity: 1 }
        : {
            opacity: 1,
            transform: "translate(0, 0) rotate(0deg) scale(1, 1)",
            clipPath: "inset(0% 0 0 0 round 5px)",
          };
      const current = paper.animate(opening ? [folded, settled] : [settled, folded], {
        duration: reduced ? 140 : opening ? 560 : 300,
        easing: opening ? "cubic-bezier(.18,.8,.25,1)" : "cubic-bezier(.4,0,.65,.3)",
        fill: "none",
      });
      animation.current = current;
      return current.finished.catch(() => undefined).then(() => {
        if (version !== motionVersion.current) return;
        animation.current = null;
      });
    },
    [anchorRef],
  );

  useEffect(() => {
    if (open) setRendered(true);
  }, [open]);

  useLayoutEffect(() => {
    const paper = paperRef.current;
    if (!paper) return;
    if (open) {
      const next =
        moved.current && position.current ? position.current : defaultPosition();
      place(next.x, next.y);
      void animate(true);
      paper.focus({ preventScroll: true });
      return;
    }
    const pending = animate(false);
    const version = motionVersion.current;
    void pending.then(() => {
      if (version !== motionVersion.current) return;
      setRendered(false);
      anchorRef.current?.focus({ preventScroll: true });
    });
  }, [open, rendered, place, animate, anchorRef, defaultPosition]);

  useEffect(() => {
    if (!rendered) return;
    const paper = paperRef.current;
    const parent = paper?.parentElement;
    if (!parent) return;
    const observer = new ResizeObserver(() => {
      const next = moved.current && position.current ? position.current : defaultPosition();
      place(next.x, next.y);
    });
    observer.observe(parent);
    return () => observer.disconnect();
  }, [rendered, place, defaultPosition]);

  // 卡片自身尺寸变了（展开/收起宽报告）父容器不会 resize，这里重新夹一次位置
  useLayoutEffect(() => {
    if (!rendered) return;
    const next = moved.current && position.current ? position.current : defaultPosition();
    place(next.x, next.y);
  }, [wide, rendered, place, defaultPosition]);

  const goTo = (key: SectionKey) => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const anchor =
      key === "basics" ? null : scroller.querySelector<HTMLElement>(`#health-${key}`);
    const top = anchor ? anchor.offsetTop - 6 : 0;
    scroller.scrollTo({
      top,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
    setSection(key);
  };

  const onScroll = () => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const nearEnd = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 8;
    setHint(nearEnd ? "已到档案末页" : "向下滚动查看更多");
    let current: SectionKey = "basics";
    for (const key of ["trend"] as const) {
      const anchor = scroller.querySelector<HTMLElement>(`#health-${key}`);
      if (anchor && anchor.offsetTop <= scroller.scrollTop + 80) current = key;
    }
    if (nearEnd) current = "trend";
    setSection(current);
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || !position.current) return;
    event.preventDefault();
    animation.current?.cancel();
    animation.current = null;
    motionVersion.current += 1;
    drag.current = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      x: position.current.x,
      y: position.current.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const state = drag.current;
    if (!state || state.id !== event.pointerId) return;
    moved.current = true;
    place(state.x + event.clientX - state.startX, state.y + event.clientY - state.startY);
  };

  const endDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag.current) return;
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onGripKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const delta = ARROWS[event.key];
    if (!delta || !position.current) return;
    event.preventDefault();
    moved.current = true;
    const step = event.shiftKey ? 30 : 10;
    place(
      position.current.x + delta[0] * step,
      position.current.y + delta[1] * step,
    );
  };

  if (!rendered) return null;

  return (
    <section
      ref={paperRef}
      id="health-file-card"
      className={`health-file${dragging ? " is-dragging" : ""}${wide ? " is-wide" : ""}`}
      role="dialog"
      aria-modal="false"
      aria-labelledby="health-file-title"
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        onClose();
      }}
    >
      <div className="health-file-top">
        <button
          ref={gripRef}
          type="button"
          className="health-file-grip"
          aria-label="移动档案卡：拖动或按方向键"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={() => {
            drag.current = null;
            setDragging(false);
          }}
          onKeyDown={onGripKeyDown}
        >
          <svg
            width="12"
            height="22"
            viewBox="0 0 16 24"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M5 6h.01M11 6h.01M5 12h.01M11 12h.01M5 18h.01M11 18h.01" strokeWidth="3" />
          </svg>
          <span className="health-file-grip-copy">
            <span id="health-file-title">个人健康档案</span>
            <small>HEALTH RECORD · 拖动此处</small>
          </span>
        </button>
        <button
          type="button"
          className="health-file-wide"
          aria-pressed={wide}
          aria-label={wide ? "收起为小卡片" : "展开为宽报告"}
          title={wide ? "收起为小卡片" : "展开为宽报告"}
          onClick={() => setWide(!wide)}
        >
          <svg
            viewBox="0 0 24 24"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {wide ? (
              <path d="M9 4v5H4M15 20v-5h5M20 9h-5V4M4 15h5v5" />
            ) : (
              <path d="M4 9V4h5M20 15v5h-5M15 4h5v5M9 20H4v-5" />
            )}
          </svg>
        </button>
        <button type="button" className="health-file-close" aria-label="收起档案" onClick={onClose}>
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="m7 7 10 10M17 7 7 17" />
          </svg>
        </button>
      </div>

      <nav className="health-file-tabs" aria-label="档案章节">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            aria-pressed={section === tab.key}
            onClick={() => goTo(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <ProfilePage embedded scrollRef={scrollRef} onScroll={onScroll} />

      <div className="health-file-foot">
        <span>本机保存 · 餐食记录存于后端</span>
        <span>{hint}</span>
      </div>
    </section>
  );
}
