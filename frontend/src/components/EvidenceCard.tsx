/**
 * 引用证据卡：文件名 + 定位（文本→第N段 / 图像→第N页 / 音频→时间码），
 * 徽标按模态区分；quote 展示证据原文。
 */
import { Badge, Card, Link, Stack, Text } from "@astryxdesign/core";
import { CHANNEL_LABELS, type Evidence } from "../types";

export const CHANNEL_META: Record<
  NonNullable<Evidence["channel"]>,
  { badgeVariant: "info" | "success" | "neutral" }
> = {
  local: { badgeVariant: "neutral" },
  web: { badgeVariant: "info" },
  cloud: { badgeVariant: "success" },
};

export const MODALITY_META: Record<
  Evidence["source"]["modality"],
  { label: string; badgeVariant: "info" | "success" | "warning" }
> = {
  text: { label: "文本", badgeVariant: "info" },
  image: { label: "图像", badgeVariant: "success" },
  audio: { label: "音频", badgeVariant: "warning" },
};

/** 定位文案：文本→第N段、图像→第N页、音频→时间码（对齐 SourceRef.label()）。
 *  兼容两种后端数据：fake 语料 section="87"，live 解析链路 section="第87段"（已带包装），不重复包裹。 */
export function sourceLocation(ev: Evidence): string {
  const s = ev.source;
  const parts: string[] = [];
  if (s.file_path) parts.push(s.file_path);
  if (s.section != null && s.section !== "") {
    parts.push(/段\s*$/.test(s.section) ? s.section : `第${s.section}段`);
  }
  if (s.page != null) parts.push(`第${s.page}页`);
  if (s.time_code) parts.push(s.time_code);
  return parts.join(" · ") || "未知来源";
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
  const score =
    evidence.score < 1 ? evidence.score.toFixed(3) : evidence.score.toFixed(1);
  return (
    <Card
      padding={3}
      elevation={highlighted ? "high" : "none"}
      onClick={onClick}
      style={{
        cursor: onClick ? "pointer" : "default",
        borderColor: highlighted
          ? "var(--color-text-accent)"
          : "var(--color-border)",
        borderStyle: "solid",
        borderWidth: 1,
        transition: "border-color 120ms ease, box-shadow 120ms ease",
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <Stack gap={2}>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Badge variant={mod.badgeVariant} label={mod.label} />
          {evidence.channel ? (
            <Badge
              variant={CHANNEL_META[evidence.channel].badgeVariant}
              label={CHANNEL_LABELS[evidence.channel]}
            />
          ) : null}
          <Text size="sm" weight="semibold" color="primary">
            [{evidence.evidence_id}]
          </Text>
          <Badge variant="neutral" label={`相关度 ${score}`} />
          <Text size="2xs" color="secondary">
            {evidence.doc_id}
          </Text>
        </Stack>
        {isUrl && path ? (
          <Link href={path} isExternalLink>
            {path.length > 72 ? `${path.slice(0, 72)}…` : path}
          </Link>
        ) : (
          <Text size="2xs" color="secondary">
            {sourceLocation(evidence)}
          </Text>
        )}
        <Text size="sm" color="primary" as="p" textWrap="pretty">
          {evidence.quote}
        </Text>
      </Stack>
    </Card>
  );
}
