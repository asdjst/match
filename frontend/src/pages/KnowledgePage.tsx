/**
 * 知识库维护台：只读查看 R2R 的摄入结构、维护体检与召回排序。
 * 不改现有问答页布局；所有数据来自 /api/kb/*。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Banner, Button } from "@astryxdesign/core";
import { getKbOverview, searchKb } from "../api/client";
import type { KbFile, KbOverview, KbSearchHit, KbSearchResult, KbSection } from "../types";

const ICON_PROPS = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const SEARCH_ICON = (
  <svg {...ICON_PROPS} width={18} height={18}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="m15.4 15.4 4.1 4.1" />
  </svg>
);

const LAYERS_ICON = (
  <svg {...ICON_PROPS} width={16} height={16}>
    <path d="m12 3 9 5-9 5-9-5 9-5Z" />
    <path d="m3 12 9 5 9-5" />
    <path d="m3 16 9 5 9-5" />
  </svg>
);

const FILE_ICON = (
  <svg {...ICON_PROPS} width={16} height={16}>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4" />
    <path d="M9 12h6M9 16h4" />
  </svg>
);

const TAG_ICON = (
  <svg {...ICON_PROPS} width={16} height={16}>
    <path d="M3 11V4h7l10 10-7 7L3 11Z" />
    <circle cx="7.5" cy="7.5" r="1.2" />
  </svg>
);

const GAUGE_ICON = (
  <svg {...ICON_PROPS} width={16} height={16}>
    <path d="M4 17a8 8 0 1 1 16 0" />
    <path d="m12 13 4-4" />
    <circle cx="12" cy="13" r="1.4" />
  </svg>
);

const CHEVRON_ICON = (
  <svg {...ICON_PROPS} width={14} height={14}>
    <path d="m8 5 7 7-7 7" />
  </svg>
);

const EMPTY_ICON = (
  <svg {...ICON_PROPS} width={34} height={34}>
    <path d="M5 4h9l5 5v11H5z" />
    <path d="M14 4v5h5" />
    <path d="M8 13h7M8 17h4" />
  </svg>
);

const SUGGESTIONS = [
  "一碗米饭大概多少碳水？",
  "低血糖时应该怎么处理？",
  "每天食盐建议不超过多少？",
];

const MODALITY: Record<string, { label: string; tone: string; badge: "neutral" | "info" | "warning" }> = {
  text: { label: "文本", tone: "text", badge: "neutral" },
  image: { label: "图片", tone: "image", badge: "info" },
  audio: { label: "音频", tone: "audio", badge: "warning" },
};

const STATUS_META = {
  ok: { label: "知识库健康", tone: "ok" },
  warn: { label: "需要维护", tone: "warn" },
  bad: { label: "影响召回", tone: "bad" },
} as const;

interface Selection {
  id: string;
  file_path: string;
  section: string;
  modality: string;
  tokens: number;
  text: string;
}

function modalityMeta(key: string) {
  return MODALITY[key] ?? { label: key || "其他", tone: "text", badge: "neutral" as const };
}

function fmtNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function fmtTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function fileSummary(file: KbFile): string {
  const parts = [`${file.documents} 切片`];
  if (file.tokens) parts.push(`${fmtNumber(file.tokens)} tokens`);
  if (file.in_collection < file.documents) parts.push(`${file.documents - file.in_collection} 集合外`);
  return parts.join(" · ");
}

function sectionOf(file: KbFile, section: KbSection): Selection {
  return {
    id: section.id,
    file_path: file.file_path,
    section: section.section,
    modality: section.modality,
    tokens: section.tokens,
    text: section.text,
  };
}

export default function KnowledgePage() {
  const [overview, setOverview] = useState<KbOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openFile, setOpenFile] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [copied, setCopied] = useState(false);

  const [query, setQuery] = useState("");
  const [searchPending, setSearchPending] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchResult, setSearchResult] = useState<KbSearchResult | null>(null);

  const inspectorRef = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getKbOverview();
      setOverview(data);
      setError(null);
      // 首次进入展开“小节信息最完整”的文件，避免默认展开一堆无语义段号
      const preferred = data.files
        .map((file) => ({
          file,
          named: file.sections.filter((item) => item.section && !item.section.startsWith("第")).length,
        }))
        .sort((a, b) => b.named - a.named || a.file.documents - b.file.documents)[0]?.file.file_path;
      setOpenFile((current) => current ?? preferred ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取知识库状态失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runSearch = useCallback(async (text: string) => {
    const next = text.trim();
    if (!next) return;
    setQuery(next);
    setSearchPending(true);
    setSearchError(null);
    try {
      setSearchResult(await searchKb(next, 6));
    } catch (err) {
      setSearchResult(null);
      setSearchError(err instanceof Error ? err.message : "知识库召回失败");
    } finally {
      setSearchPending(false);
    }
  }, []);

  const pickSection = (file: KbFile, section: KbSection) => {
    setSelection(sectionOf(file, section));
    setCopied(false);
  };

  const pickHit = (hit: KbSearchHit) => {
    const section = overview?.files
      .flatMap((file) => file.sections.map((item) => ({ file, item })))
      .find(({ item }) => item.id === hit.doc_id);
    if (section) setOpenFile(section.file.file_path);
    setSelection({
      id: hit.doc_id,
      file_path: hit.file_path ?? section?.file.file_path ?? "未标注文件",
      section: hit.section ?? section?.item.section ?? "",
      modality: hit.modality,
      tokens: section?.item.tokens ?? 0,
      text: hit.text,
    });
    setCopied(false);
    requestAnimationFrame(() => {
      inspectorRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  };

  const copyText = async () => {
    if (!selection) return;
    try {
      await navigator.clipboard.writeText(selection.text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const totals = overview?.totals;
  const status = overview ? STATUS_META[overview.status] : null;
  const selectedMeta = selection ? modalityMeta(selection.modality) : null;

  return (
    <div className="app-scroll">
      <div className="page-body kb-page">
        <header className="kb-hero">
          <div className="kb-hero-copy">
            <span className="page-eyebrow">KNOWLEDGE OPS · R2R</span>
            <h1>
              知识库 <em>维护台</em>
            </h1>
            <p>
              看清资料怎样被切分、过滤与召回。这里只读：发现问题后回到入库脚本或 R2R 控制台处理。
            </p>
          </div>
          <div className="kb-hero-status">
            <div className={`kb-health is-${status?.tone ?? "idle"}`} role="status" aria-live="polite">
              <span className="kb-health-dot" />
              <div>
                <strong>{status?.label ?? (loading ? "正在读取" : "尚未连接")}</strong>
                <small>
                  {overview
                    ? `${overview.storage_collection} · ${fmtNumber(overview.storage_documents)} 文档`
                    : "R2R 维护视图"}
                </small>
              </div>
            </div>
            <Button
              label={loading ? "刷新中" : "刷新"}
              variant="ghost"
              size="sm"
              isDisabled={loading}
              onClick={() => void load()}
            />
          </div>
        </header>

        {error ? (
          <Banner
            status="error"
            title="知识库状态没读到"
            description={error}
            endContent={<Button label="重试" variant="secondary" size="sm" onClick={() => void load()} />}
          />
        ) : null}

        {!overview && loading ? (
          <div className="kb-skeleton" aria-label="正在读取知识库">
            <span />
            <span />
            <span />
          </div>
        ) : null}

        {overview && totals ? (
          <>
            <section className="kb-metrics" aria-label="知识库概览">
              <article className="kb-metric">
                <span className="kb-metric-icon">{LAYERS_ICON}</span>
                <span className="kb-metric-label">切片总数</span>
                <strong>{fmtNumber(totals.chunks)}</strong>
                <small>{fmtNumber(totals.documents)} 个文档 · {fmtNumber(totals.tokens)} tokens</small>
              </article>
              <article className="kb-metric">
                <span className="kb-metric-icon">{FILE_ICON}</span>
                <span className="kb-metric-label">来源文件</span>
                <strong>{fmtNumber(totals.files)}</strong>
                <small>{Object.keys(totals.modalities).length} 种模态 · 按文件聚合</small>
              </article>
              <article className={`kb-metric ${totals.in_collection < totals.documents ? "is-warn" : ""}`}>
                <span className="kb-metric-icon">{TAG_ICON}</span>
                <span className="kb-metric-label">集合命中</span>
                <strong>
                  {fmtNumber(totals.in_collection)}
                  <i>/{fmtNumber(totals.documents)}</i>
                </strong>
                <small>
                  {totals.in_collection === totals.documents
                    ? `全部带 collection=${overview.configured_collection}`
                    : `${totals.mismatched} 个切片不会被线上召回`}
                </small>
              </article>
              <article className="kb-metric">
                <span className="kb-metric-icon">{GAUGE_ICON}</span>
                <span className="kb-metric-label">平均切片</span>
                <strong>{fmtNumber(Math.round(totals.tokens / Math.max(1, totals.documents)))}</strong>
                <small>tokens / 切片 · 更新于 {fmtTime(overview.generated_at)}</small>
              </article>
            </section>

            <div className="kb-grid">
              <section className="kb-card kb-files" aria-label="知识结构与切片">
                <div className="kb-card-head">
                  <div>
                    <span className="kb-kicker">INGESTION MAP</span>
                    <h2>知识结构</h2>
                    <p>按来源文件展开切片；点一个小节，在右侧查看原文。</p>
                  </div>
                  <Badge variant="neutral" label={`${overview.files.length} 个来源`} />
                </div>

                <div className="kb-file-list">
                  {overview.files.map((file) => {
                    const isOpen = openFile === file.file_path;
                    const share = Math.max(4, Math.round((file.documents / Math.max(1, totals.documents)) * 100));
                    return (
                      <article className={`kb-file ${isOpen ? "is-open" : ""}`} key={file.file_path}>
                        <button
                          type="button"
                          className="kb-file-row"
                          aria-expanded={isOpen}
                          onClick={() => setOpenFile(isOpen ? null : file.file_path)}
                        >
                          <span className="kb-file-icon">{FILE_ICON}</span>
                          <span className="kb-file-main">
                            <strong>{file.file_path}</strong>
                            <small>{fileSummary(file)}</small>
                          </span>
                          <span className="kb-file-side">
                            <span className="kb-file-meter" aria-hidden="true">
                              <i style={{ width: `${share}%` }} />
                            </span>
                            <span className="kb-file-count">{file.documents}</span>
                            <span className="kb-chevron">{CHEVRON_ICON}</span>
                          </span>
                        </button>

                        {isOpen ? (
                          <div className="kb-section-list">
                            {file.sections.map((section) => {
                              const meta = modalityMeta(section.modality);
                              const active = selection?.id === section.id;
                              return (
                                <button
                                  key={section.id}
                                  type="button"
                                  className={`kb-section ${active ? "is-selected" : ""}`}
                                  aria-pressed={active}
                                  onClick={() => pickSection(file, section)}
                                >
                                  <span className={`kb-section-dot is-${meta.tone}`} aria-hidden="true" />
                                  <span className="kb-section-main">
                                    <strong>{section.section || "未标注小节"}</strong>
                                    <small>
                                      {fmtNumber(section.tokens)} tokens
                                      {section.section ? "" : " · 引用只能定位到文件"}
                                    </small>
                                  </span>
                                  <span className="kb-section-tags">
                                    {!section.in_collection ? <Badge variant="warning" label="集合外" /> : null}
                                    <Badge variant={meta.badge} label={meta.label} />
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </section>

              <aside className="kb-rail">
                <section className="kb-card kb-checks" aria-label="维护体检">
                  <div className="kb-card-head">
                    <div>
                      <span className="kb-kicker">HEALTH CHECKS</span>
                      <h2>维护体检</h2>
                      <p>从集合过滤、重复切片和引用定位看风险。</p>
                    </div>
                    <Badge
                      variant={overview.status === "ok" ? "success" : overview.status === "warn" ? "warning" : "error"}
                      label={status?.label ?? ""}
                    />
                  </div>
                  <ul className="kb-signals">
                    {overview.signals.map((signal) => (
                      <li className={`kb-signal is-${signal.level}`} key={`${signal.title}-${signal.detail}`}>
                        <span className="kb-signal-dot" aria-hidden="true" />
                        <div>
                          <strong>{signal.title}</strong>
                          <p>{signal.detail}</p>
                          {signal.action ? <small>{signal.action}</small> : null}
                        </div>
                      </li>
                    ))}
                  </ul>

                  <div className="kb-map">
                    <div>
                      <span>应用过滤</span>
                      <strong>collection={overview.configured_collection}</strong>
                    </div>
                    <div>
                      <span>存储集合</span>
                      <strong>{overview.storage_collection}</strong>
                    </div>
                    <div>
                      <span>R2R 地址</span>
                      <strong className="kb-map-url">{overview.base_url}</strong>
                    </div>
                  </div>
                  <div className="kb-map-actions">
                    <Button
                      label="打开 R2R API 文档"
                      variant="ghost"
                      size="sm"
                      onClick={() => window.open(`${overview.base_url}/docs`, "_blank", "noopener,noreferrer")}
                    />
                  </div>

                  {overview.duplicates.length ? (
                    <div className="kb-duplicates">
                      <div className="kb-duplicates-head">
                        <strong>重复切片</strong>
                        <span>{overview.duplicates.length} 组</span>
                      </div>
                      {overview.duplicates.slice(0, 3).map((dup) => (
                        <div className="kb-duplicate" key={`${dup.file_path}-${dup.preview.slice(0, 24)}`}>
                          <strong>
                            {dup.file_path}
                            {dup.section ? ` · ${dup.section}` : ""}
                          </strong>
                          <small>重复 {dup.count} 次</small>
                          <p>{dup.preview}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>

                <section className="kb-card kb-inspector" aria-label="切片预览" ref={inspectorRef}>
                  <div className="kb-card-head">
                    <div>
                      <span className="kb-kicker">CHUNK INSPECTOR</span>
                      <h2>切片预览</h2>
                    </div>
                    {selection ? (
                      <Badge variant={selectedMeta?.badge ?? "neutral"} label={selectedMeta?.label ?? "文本"} />
                    ) : null}
                  </div>

                  {selection ? (
                    <div className="kb-inspect-body">
                      <div className="kb-inspect-path">
                        <strong>{selection.file_path}</strong>
                        <span>{selection.section || "未标注小节"}</span>
                      </div>
                      <div className="kb-inspect-text">{selection.text}</div>
                      <div className="kb-inspect-foot">
                        <small>{selection.tokens ? `${fmtNumber(selection.tokens)} tokens` : "来源切片"}</small>
                        <Button
                          label={copied ? "已复制" : "复制原文"}
                          variant="ghost"
                          size="sm"
                          onClick={() => void copyText()}
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="kb-inspect-empty">
                      <span>{EMPTY_ICON}</span>
                      <strong>还没有选中切片</strong>
                      <p>从左侧展开一个文件，点小节查看原文；召回结果也可以直接打开。</p>
                    </div>
                  )}
                </section>
              </aside>
            </div>

            <section className="kb-card kb-recall" aria-label="召回测试">
              <div className="kb-card-head">
                <div>
                  <span className="kb-kicker">RETRIEVAL LAB</span>
                  <h2>召回体检</h2>
                  <p>用与线上相同的集合过滤跑一次向量召回，检查排序和命中来源。</p>
                </div>
                <Badge variant="neutral" label={`collection=${overview.configured_collection}`} />
              </div>

              <form
                className="kb-search"
                onSubmit={(event) => {
                  event.preventDefault();
                  void runSearch(query);
                }}
              >
                <span className="kb-search-icon">{SEARCH_ICON}</span>
                <input
                  value={query}
                  aria-label="召回测试问题"
                  placeholder="输入一个用户可能会问的问题"
                  onChange={(event) => setQuery(event.target.value)}
                />
                <Button
                  label={searchPending ? "检索中" : "测试召回"}
                  variant="primary"
                  size="sm"
                  isLoading={searchPending}
                  isDisabled={searchPending || !query.trim()}
                  onClick={() => void runSearch(query)}
                />
              </form>

              <div className="kb-suggestions">
                <span>试试</span>
                {SUGGESTIONS.map((item) => (
                  <button type="button" key={item} disabled={searchPending} onClick={() => void runSearch(item)}>
                    {item}
                  </button>
                ))}
              </div>

              {searchError ? <Banner status="error" title="召回请求失败" description={searchError} /> : null}

              {searchPending ? (
                <div className="kb-hits-loading" aria-hidden="true">
                  {[0, 1, 2].map((item) => (
                    <span key={item} />
                  ))}
                </div>
              ) : searchResult ? (
                <div className="kb-recall-result">
                  <div className="kb-recall-meta">
                    <span>
                      命中 {searchResult.hits.length} 条 · {searchResult.latency_ms} ms
                    </span>
                    <span>Top 6 · 余弦相关度</span>
                  </div>
                  {searchResult.hits.length ? (
                    <ol className="kb-hits">
                      {searchResult.hits.map((hit, index) => {
                        const meta = modalityMeta(hit.modality);
                        const score = Math.max(0, Math.min(100, Math.round(hit.score * 100)));
                        return (
                          <li key={hit.id}>
                            <button type="button" className="kb-hit" onClick={() => pickHit(hit)}>
                              <span className="kb-hit-rank">{String(index + 1).padStart(2, "0")}</span>
                              <span className="kb-hit-body">
                                <span className="kb-hit-head">
                                  <strong>{hit.file_path ?? "未标注文件"}</strong>
                                  <span>{hit.section || "未标注小节"}</span>
                                  <Badge variant={meta.badge} label={meta.label} />
                                </span>
                                <span className="kb-hit-score">
                                  <span className="kb-score-track">
                                    <i style={{ width: `${score}%` }} />
                                  </span>
                                  <b>{hit.score.toFixed(3)}</b>
                                </span>
                                <span className="kb-hit-text">{hit.text}</span>
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <div className="kb-no-hit">
                      <strong>没有命中任何切片</strong>
                      <p>
                        先确认知识库里确实有相关内容，再检查 collection={searchResult.configured_collection} 与入库 metadata 是否一致。
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="kb-recall-empty">
                  <span>{SEARCH_ICON}</span>
                  <p>输入问题或点一个示例，查看知识库当前能把哪些切片排到前面。</p>
                </div>
              )}
            </section>

            <section className="kb-card kb-loop" aria-label="入库闭环">
              <div className="kb-card-head">
                <div>
                  <span className="kb-kicker">MAINTENANCE LOOP</span>
                  <h2>入库闭环</h2>
                  <p>维护动作留在脚本和控制台；这一页负责在每次入库后复核结果。</p>
                </div>
              </div>
              <div className="kb-loop-steps">
                <article>
                  <span>01</span>
                  <strong>准备资料</strong>
                  <p>Markdown 按 H2 分节，小节名会直接成为引用定位。</p>
                </article>
                <article>
                  <span>02</span>
                  <strong>重新入库</strong>
                  <p>运行 seed 脚本写入 R2R；已有重复先在控制台删除。</p>
                </article>
                <article>
                  <span>03</span>
                  <strong>回页复核</strong>
                  <p>看集合命中、重复切片和召回排序是否恢复正常。</p>
                </article>
              </div>
              <div className="kb-loop-command">
                <code>python scripts/seed_r2r.py</code>
                <span>后端目录运行 · 命令只做说明，不在此页执行</span>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
