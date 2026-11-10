/**
 * 交付物视图：拒答/降级/拦截横幅 + 置信度条 + 分点断言。
 * 断言里的 [E1] 引用是可点击 chip → 高亮对应证据卡。
 */
import { Badge, Banner, ProgressBar, Stack, Text } from "@astryxdesign/core";
import { CHANNEL_LABELS, type Assertion, type Channel, type Deliverable } from "../types";
import { CHANNEL_META } from "./EvidenceCard";

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
      className={"cite-chip" + (activeEvidenceId === id ? " cite-chip--active" : "")}
      onClick={() => onCiteClick(id)}
      title={`查看证据 ${id} 原文`}
    >
      {id}
    </button>
  );

  return (
    <Text as="p" size="base" color="primary" textWrap="pretty">
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
    </Text>
  );
}

export function DeliverableView({
  deliverable: d,
  activeEvidenceId,
  onCiteClick,
}: DeliverableViewProps) {
  const refused = d.refused;
  const hasAssertions = d.assertions.length > 0;
  const confidenceVariant = d.confidence >= 0.7 ? "success" : d.confidence >= 0.45 ? "warning" : "error";
  const dist: Record<Channel, number> = { local: 0, web: 0, cloud: 0 };
  for (const ev of d.citations) {
    if (ev.channel && ev.channel in dist) dist[ev.channel] += 1;
  }
  const sourcedChannels = (Object.keys(dist) as Channel[]).filter((ch) => dist[ch] > 0);

  return (
    <Stack gap={3}>
      {refused ? (
        <Banner
          status="warning"
          title={d.degraded ? "兜底结论（人工放行后输出）" : "已拒答"}
          description={d.refusal_reason ?? "证据不足以支撑结论，按“无源不答”原则拒答。"}
        />
      ) : d.degraded ? (
        <Banner status="info" title="降级输出" description={d.refusal_reason ?? undefined} />
      ) : null}

      {hasAssertions ? (
        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            结论断言（每条均带证据引用）
          </Text>
          <ol className="assertion-list">
            {d.assertions.map((a, i) => (
              <li key={i}>
                <AssertionLine
                  assertion={a}
                  activeEvidenceId={activeEvidenceId}
                  onCiteClick={onCiteClick}
                />
              </li>
            ))}
          </ol>
        </Stack>
      ) : refused ? (
        <Text size="sm" color="secondary">
          本次未产出任何断言。
        </Text>
      ) : null}

      {sourcedChannels.length > 0 ? (
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Text size="2xs" color="secondary">
            检索来源
          </Text>
          {sourcedChannels.map((ch) => (
            <Badge
              key={ch}
              variant={CHANNEL_META[ch].badgeVariant}
              label={`${CHANNEL_LABELS[ch]} ${dist[ch]}`}
            />
          ))}
        </Stack>
      ) : null}

      <Stack direction="horizontal" gap={4} vAlign="center" wrap="wrap">
        <Stack direction="horizontal" gap={2} vAlign="center" style={{ minWidth: 220, flex: 1 }}>
          <Text size="sm" color="secondary">
            置信度
          </Text>
          <ProgressBar
            value={Math.round(d.confidence * 100)}
            max={100}
            label="置信度"
            isLabelHidden
            variant={confidenceVariant}
            style={{ flex: 1 }}
          />
          <Text size="sm" weight="semibold" hasTabularNumbers>
            {(d.confidence * 100).toFixed(0)}%
          </Text>
          {d.confidence_source ? (
            <Badge
              variant={d.confidence_source === "llm" ? "info" : "neutral"}
              label={d.confidence_source === "llm" ? "大模型评分" : "公式兜底"}
            />
          ) : null}
        </Stack>
        {d.trace_id ? (
          <Text size="2xs" color="secondary">
            trace: {d.trace_id.slice(0, 8)}
          </Text>
        ) : null}
      </Stack>
      {d.confidence_reason ? (
        <Text size="2xs" color="secondary">
          评分理由：{d.confidence_reason}
        </Text>
      ) : null}
    </Stack>
  );
}
