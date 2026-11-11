/**
 * 交付物视图：直接以几段自然语言回答呈现，[E#] 引用可点击。
 * 仅在拒答/降级时保留横幅，置信度压到回答末尾一行说明。
 */
import { Banner, Stack } from "@astryxdesign/core";
import { CHANNEL_LABELS as CHANNEL_LABEL, type Assertion, type Deliverable } from "../types";

export interface DeliverableViewProps {
  deliverable: Deliverable;
  /** 当前高亮的证据编号（由父级联动） */
  activeEvidenceId: string | null;
  onCiteClick: (evidenceId: string) => void;
}

/** 断言渲染：把 [E1][E2] 拆成可点击引用 chip */
function AssertionLine({
  assertion,
  activeEvidenceId,
  onCiteClick,
}: {
  assertion: Assertion;
  activeEvidenceId: string | null;
  onCiteClick: (id: string) => void;
}) {
  const segments: Array<{ kind: "text"; text: string } | { kind: "cite"; id: string }> = [];
  const inlineCites = new Set<string>();
  const re = /\[(E\d+)\]/g;
  let cursor = 0;
  for (const m of assertion.text.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > cursor) segments.push({ kind: "text", text: assertion.text.slice(cursor, idx) });
    inlineCites.add(m[1]);
    segments.push({ kind: "cite", id: m[1] });
    cursor = idx + m[0].length;
  }
  if (cursor < assertion.text.length) {
    segments.push({ kind: "text", text: assertion.text.slice(cursor) });
  }
  // cites 里有而文本未内嵌的编号，追加在断言尾部（“每条断言后面的 [E1] 引用”）
  const trailing = assertion.cites.filter((c) => !inlineCites.has(c));

  const renderChip = (id: string, key: string) => (
    <button
      key={key}
      type="button"
      className="cite-chip"
      aria-pressed={activeEvidenceId === id}
      onClick={() => onCiteClick(id)}
      title={`查看证据 ${id} 原文`}
    >
      [{id}]
    </button>
  );

  return (
    <p className="answer-para">
      {segments.map((seg, i) =>
        seg.kind === "text" ? (
          <span key={i}>{seg.text}</span>
        ) : (
          renderChip(seg.id, `i-${i}`)
        ),
      )}
      {trailing.map((id) => renderChip(id, `t-${id}`))}
      {assertion.inferred ? (
        <span className="inferred-tag" title="该断言未挂上任何引用，标为推断">
          推断
        </span>
      ) : null}
    </p>
  );
}

export function DeliverableView({
  deliverable: d,
  activeEvidenceId,
  onCiteClick,
}: DeliverableViewProps) {
  const refused = d.refused;
  const hasAssertions = d.assertions.length > 0;
  const counts = d.citations.reduce<Record<string, number>>((acc, ev) => {
    const ch = ev.channel ?? "local";
    acc[ch] = (acc[ch] ?? 0) + 1;
    return acc;
  }, {});
  const channelNote =
    (["memory", "local", "image", "tool", "web", "cloud"] as const)
      .filter((ch) => counts[ch])
      .map((ch) => `${CHANNEL_LABEL[ch]} ${counts[ch]}`)
      .join(" · ") || "本次无引用";

  return (
    <Stack gap={3}>
      {refused ? (
        <Banner
          status="warning"
          title={d.degraded ? "兜底结论（人工放行后输出）" : "已拒答"}
          description={d.refusal_reason ?? "证据不足以支撑结论，按“无源不答”原则拒答。"}
        />
      ) : d.degraded ? (
        <Banner
          status="info"
          title="降级输出"
          description={d.degraded_reason ?? d.refusal_reason ?? d.confidence_reason ?? undefined}
        />
      ) : null}

      {hasAssertions ? (
        <div className="answer-prose">
          {d.assertions.map((a, i) => (
            <AssertionLine
              key={i}
              assertion={a}
              activeEvidenceId={activeEvidenceId}
              onCiteClick={onCiteClick}
            />
          ))}
        </div>
      ) : refused ? (
        <p className="answer-para answer-para--muted">本次未产出任何断言。</p>
      ) : null}

      <div className="answer-foot">
        <span>置信度 {Math.round(d.confidence * 100)}%</span>
        <span>{d.confidence_source === "llm" ? "大模型评分" : "公式兜底"}</span>
        <span>引用 {d.citations.length} 条 · {channelNote}</span>
      </div>

      {d.confidence_reason ? (
        <p className="answer-reason">评分理由：{d.confidence_reason}</p>
      ) : null}
    </Stack>
  );
}
