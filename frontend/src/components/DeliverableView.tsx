/**
 * 交付物视图：优先呈现成文智能体写出的连贯回答，[E#] 引用可点击。
 * 逐条断言收进「依据」里备查；未成文时直接按断言呈现。
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

type Segment = { kind: "text"; text: string } | { kind: "cite"; id: string };

/** 把正文里的 [E1][E2] 拆成文本片段与引用编号 */
function splitCites(text: string): { segments: Segment[]; inline: Set<string> } {
  const segments: Segment[] = [];
  const inline = new Set<string>();
  const re = /\[(E\d+)\]/g;
  let cursor = 0;
  for (const m of text.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > cursor) segments.push({ kind: "text", text: text.slice(cursor, idx) });
    inline.add(m[1]);
    segments.push({ kind: "cite", id: m[1] });
    cursor = idx + m[0].length;
  }
  if (cursor < text.length) segments.push({ kind: "text", text: text.slice(cursor) });
  return { segments, inline };
}

function CiteChip({
  id,
  active,
  onCiteClick,
}: {
  id: string;
  active: boolean;
  onCiteClick: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className="cite-chip"
      aria-pressed={active}
      onClick={() => onCiteClick(id)}
      title={`查看证据 ${id} 原文`}
    >
      [{id}]
    </button>
  );
}

function CiteText({
  text,
  activeEvidenceId,
  onCiteClick,
}: {
  text: string;
  activeEvidenceId: string | null;
  onCiteClick: (id: string) => void;
}) {
  const { segments } = splitCites(text);
  return (
    <>
      {segments.map((seg, i) =>
        seg.kind === "text" ? (
          <span key={i}>{seg.text}</span>
        ) : (
          <CiteChip key={i} id={seg.id} active={activeEvidenceId === seg.id} onCiteClick={onCiteClick} />
        ),
      )}
    </>
  );
}

/** 断言渲染：文本内嵌引用之外，cites 里剩下的编号补在句尾 */
function AssertionLine({
  assertion,
  activeEvidenceId,
  onCiteClick,
}: {
  assertion: Assertion;
  activeEvidenceId: string | null;
  onCiteClick: (id: string) => void;
}) {
  const { inline } = splitCites(assertion.text);
  const trailing = assertion.cites.filter((c) => !inline.has(c));

  return (
    <p className="answer-para">
      <CiteText text={assertion.text} activeEvidenceId={activeEvidenceId} onCiteClick={onCiteClick} />
      {trailing.map((id) => (
        <CiteChip key={`t-${id}`} id={id} active={activeEvidenceId === id} onCiteClick={onCiteClick} />
      ))}
      {assertion.inferred ? (
        <span className="inferred-tag" title="该断言未挂上任何引用，标为推断">
          推断
        </span>
      ) : null}
    </p>
  );
}

/** 成文回答的流式草稿：writer 边生成边推，校验通过后由正式 deliverable 替换 */
export function StreamingAnswer({
  text,
  activeEvidenceId,
  onCiteClick,
}: {
  text: string;
  activeEvidenceId: string | null;
  onCiteClick: (id: string) => void;
}) {
  return (
    <div className="answer-prose">
      <p className="answer-para">
        <CiteText text={text} activeEvidenceId={activeEvidenceId} onCiteClick={onCiteClick} />
        <span className="stream-caret" aria-hidden />
      </p>
    </div>
  );
}

export function DeliverableView({
  deliverable: d,
  activeEvidenceId,
  onCiteClick,
}: DeliverableViewProps) {
  const refused = d.refused;
  const hasAssertions = d.assertions.length > 0;
  const paragraphs = (d.answer ?? "")
    .split(/\n+/)
    .map((p) => p.trim())
    .filter(Boolean);
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

  const basis = hasAssertions ? (
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
  ) : null;

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

      {paragraphs.length ? (
        <div className="answer-prose">
          {paragraphs.map((text, i) => (
            <p className="answer-para" key={i}>
              <CiteText text={text} activeEvidenceId={activeEvidenceId} onCiteClick={onCiteClick} />
            </p>
          ))}
        </div>
      ) : hasAssertions ? (
        basis
      ) : refused ? (
        <p className="answer-para answer-para--muted">本次未产出任何断言。</p>
      ) : null}

      {paragraphs.length && basis ? (
        <details className="answer-basis">
          <summary>逐条依据（{d.assertions.length} 条）</summary>
          {basis}
        </details>
      ) : null}

      <div className="answer-foot">
        <span>置信度 {Math.round(d.confidence * 100)}%</span>
        <span>{d.confidence_source === "llm" ? "大模型评分" : "公式兜底"}</span>
        <span>引用 {d.citations.length} 条 · {channelNote}</span>
        {d.from_cache ? <span className="cache-tag">语义缓存</span> : null}
      </div>

      {d.confidence_reason ? (
        <p className="answer-reason">评分理由：{d.confidence_reason}</p>
      ) : null}
    </Stack>
  );
}