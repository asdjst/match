/**
 * 引用证据卡：证据编号 + 文件 + 定位（文本→第N段 / 图像→第N页 / 音频→时间码），
 * 左侧色条按模态区分；quote 展示证据原文。
 * 不展示 doc_id（R2R 内部 UUID）与原始检索分（混合检索的 RRF 排名分，量纲对手工阅读无意义）。
 */
import { Badge, Card, Link, Stack, Text } from "@astryxdesign/core";
import { CHANNEL_LABELS, type Evidence } from "../types";

export const CHANNEL_META: Record<
  NonNullable<Evidence["channel"]>,
  { badgeVariant: "info" | "success" | "neutral" | "warning" }
> = {
  local: { badgeVariant: "neutral" },
  web: { badgeVariant: "info" },
  cloud: { badgeVariant: "success" },
  image: { badgeVariant: "info" },
  tool: { badgeVariant: "success" },
  memory: { badgeVariant: "warning" },
};

export const MODALITY_META: Record<
  Evidence["source"]["modality"],
  { label: string; badgeVariant: "info" | "success" | "warning"; color: string }
> = {
  text: { label: "文本", badgeVariant: "info", color: "var(--color-text-info)" },
  image: { label: "图像", badgeVariant: "success", color: "var(--color-text-success)" },
  audio: { label: "音频", badgeVariant: "warning", color: "var(--color-text-warning)" },
};

/** 定位文案：文本→第N段、图像→第N页、音频→时间码（对齐 SourceRef.label()）。
 *  兼容三种后端数据：fake 语料 section="87"、live 解析 section="第87段"、标题切分 section="日常血糖监测"；
 *  只有纯数字才补“第N段”，已带包装或本身是标题就原样展示。 */
export function sourceLocation(ev: Evidence): string {
  const s = ev.source;
  const parts: string[] = [];
  if (s.file_path) parts.push(s.file_path);
  if (s.section != null && s.section !== "") {
    parts.push(/^\d+$/.test(s.section) ? `第${s.section}段` : s.section);
  }
  if (s.page != null) parts.push(`第${s.page}页`);
  if (s.time_code) parts.push(s.time_code);
  return parts.join(" · ") || "未知来源";
}

/** 只有定位、不含文件名（文件名已在标题行） */
function sourceDetail(ev: Evidence): string {
  const s = ev.source;
  const parts: string[] = [];
  if (s.section != null && s.section !== "") {
    parts.push(/^\d+$/.test(s.section) ? `第${s.section}段` : s.section);
  }
  if (s.page != null) parts.push(`第${s.page}页`);
  if (s.time_code) parts.push(s.time_code);
  return parts.join(" · ");
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export interface EvidenceCardProps {
  evidence: Evidence;
  highlighted?: boolean;
  onClick?: () => void;
}

export function EvidenceCard({ evidence, highlighted, onClick }: EvidenceCardProps) {
  const mod = MODALITY_META[evidence.source.modality] ?? MODALITY_META.text;
  const path = evidence.source.file_path;
  const isUrl = Boolean(path && /^https?:\/\//.test(path));
  const detail = sourceDetail(evidence);

  return (
    <Card
      padding={3}
      elevation={highlighted ? "high" : "none"}
      onClick={onClick}
      style={{
        cursor: onClick ? "pointer" : "default",
        borderColor: highlighted ? "var(--color-text-accent)" : "var(--color-border)",
        borderStyle: "solid",
        borderWidth: 1,
        borderLeft: `3px solid ${mod.color}`,
        transition: "border-color 120ms ease, box-shadow 120ms ease",
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <Stack gap={2}>
        <Stack direction="horizontal" gap={2} vAlign="center" justify="between" wrap="wrap">
          <Stack direction="horizontal" gap={2} vAlign="center" style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" weight="bold" color="accent" style={{ flexShrink: 0 }}>
              {`[${evidence.evidence_id}]`}
            </Text>
            {isUrl && path ? (
              <Link href={path} isExternalLink>
                {hostOf(path)}
              </Link>
            ) : (
              <Text
                size="sm"
                weight="semibold"
                color="primary"
                maxLines={1}
                hasTruncateTooltip
                style={{ minWidth: 0 }}
              >
                {path ?? "未知来源"}
              </Text>
            )}
          </Stack>
          <Stack direction="horizontal" gap={2} vAlign="center" style={{ flexShrink: 0 }}>
            <Badge variant={mod.badgeVariant} label={mod.label} />
            {evidence.channel ? (
              <Badge
                variant={CHANNEL_META[evidence.channel].badgeVariant}
                label={CHANNEL_LABELS[evidence.channel]}
              />
            ) : null}
          </Stack>
        </Stack>

        {detail ? (
          <Text size="2xs" color="secondary">
            {detail}
          </Text>
        ) : null}

        <Text size="sm" color="primary" as="p" textWrap="pretty">
          {evidence.quote}
        </Text>
      </Stack>
    </Card>
  );
}
