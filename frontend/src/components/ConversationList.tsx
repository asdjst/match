/** 左侧会话历史：按 session 归组，点开回到那段对话继续追问。 */
import { useEffect, useState } from "react";
import { useRuns, type Conversation } from "../store/runs";

const OPEN_KEY = "glucoguard.historyOpen";

function fmtTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return d.toLocaleString("zh-CN", {
    ...(sameDay ? {} : { month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const CHEVRON = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 18l6-6-6-6" />
  </svg>
);

export function ConversationList() {
  const { conversations, activeSessionId, openConversation, newConversation } = useRuns();
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(OPEN_KEY) !== "0";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(OPEN_KEY, open ? "1" : "0");
    } catch {
      // 隐私模式下写不了也不影响展开
    }
  }, [open]);

  const pick = (conversation: Conversation) => {
    void openConversation(conversation);
  };

  const create = () => {
    newConversation();
  };

  const visible = conversations.slice(0, 30);

  return (
    <section className={`side-history${open ? " is-open" : ""}`}>
      <div className="side-history-head">
        <button
          type="button"
          className="side-history-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="side-history-chevron">{CHEVRON}</span>
          <span>会话历史</span>
          <em>{conversations.length}</em>
        </button>
        <button type="button" className="side-history-new" title="新对话" aria-label="新对话" onClick={create}>
          +
        </button>
      </div>

      {open ? (
        visible.length === 0 ? (
          <p className="side-history-empty">还没有会话。拍一张餐盘或问一句，这里会出现记录。</p>
        ) : (
          <div className="side-history-list">
            {visible.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                className={`side-history-item${conversation.id === activeSessionId ? " is-active" : ""}`}
                title={conversation.title}
                onClick={() => pick(conversation)}
              >
                <strong>{conversation.title}</strong>
                <small>
                  {fmtTime(conversation.updatedAt)}
                  {conversation.count > 1 ? ` · ${conversation.count} 轮` : ""}
                </small>
              </button>
            ))}
          </div>
        )
      ) : null}
    </section>
  );
}
