import { ReactElement, useState } from "react";
import Select from "antd/es/select";
import { AssetEmptyState, AsyncButton, ConfirmAction, PrimaryButton, UploadButton } from "./ui";
import { ArrowLeft, Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Download, Edit3, Eye, FileStack, LayoutTemplate, ListFilter, LoaderCircle, Pencil, Plus, Search, Send, Sparkles, Square, Trash2, Upload, WandSparkles, X, Zap } from "lucide-react";
import type { Artifact, Job, JobEvent, JobStatus, PromptSnippet, Project, Template } from "./appTypes";
import { editorPath, navigate } from "./routes";


function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function templatePreviewFiles(template: Template): string[] {
  // Server-rendered PNGs are pixel-faithful (SVG <img> previews cannot resolve
  // ../images references); fall back to the raw SVG files for legacy imports.
  const pngs = template.metadata.preview_files_png;
  const pngFiles = Array.isArray(pngs) ? pngs.map(String).filter(Boolean) : [];
  if (pngFiles.length > 0) return pngFiles;
  const value = template.metadata.preview_files;
  const files = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
  const slideFiles = files.filter((file) => /(?:^|\/)\d{3}_.*\.svg$/i.test(file));
  return slideFiles.length > 0 ? slideFiles : files;
}

interface ImportLossSummary { label?: string; count?: number; sample?: string }
interface ImportReport {
  warning_count?: number;
  losses?: Record<string, ImportLossSummary>;
  normalizations?: Record<string, ImportLossSummary>;
  slides_affected?: number[];
  placeholders?: { total?: number; by_semantic_role?: Record<string, number> };
}

const placeholderRoleLabels: Record<string, string> = {
  title: "标题", body: "正文", subtitle: "副标题", image: "图片", picture: "图片", chart: "图表",
  table: "表格", header: "页眉", footer: "页脚", date: "日期", "slide-number": "页码",
  media: "媒体", object: "对象", content: "内容", text: "文本", other: "其他", unknown: "其他",
};

function importReportSummary(template: Template): ImportReport | null {
  const value = (template.metadata as Record<string, unknown>).import_report;
  if (!value || typeof value !== "object") return null;
  const report = value as ImportReport;
  const lossCount = Object.values(report.losses || {}).reduce((total, entry) => total + (entry.count || 0), 0);
  const hasPlaceholders = Boolean(report.placeholders?.total);
  if (!lossCount && !hasPlaceholders) return null;
  return report;
}

function templateFileUrl(templateId: string, filePath: string): string {
  const encodedPath = filePath.split("/").map((part) => encodeURIComponent(part)).join("/");
  return `/api/v1/templates/${templateId}/files/${encodedPath}`;
}

function templateMetadataList(value: unknown): string[] {
  const values = Array.isArray(value) ? value : value && typeof value === "object" ? Object.values(value) : [];
  return values.map((item) => typeof item === "string" ? item : JSON.stringify(item)).filter(Boolean).slice(0, 12);
}

// Import failures surface raw engine output; map the known signatures to
// user-friendly Chinese and keep the original text for tooltips.
const friendlyTemplateErrorRules: Array<[RegExp, string]> = [
  [/no positive source frame/i, "模板中存在零尺寸的图形（常见于直线连接符），无法完成版式解析"],
  [/not a zip|badzipfile|cannot open/i, "文件不是有效的 PPTX（或已损坏），请重新导出后再上传"],
  [/encrypted|password/i, "模板已加密，请先解除密码保护后再上传"],
  [/上传的 PPTX 文件不存在/, "上传文件已缺失，请删除后重新上传"],
];

function friendlyTemplateError(error: string | null | undefined): string {
  const raw = (error || "").trim();
  if (!raw) return "模板解析失败";
  for (const [pattern, message] of friendlyTemplateErrorRules) {
    if (pattern.test(raw)) return message;
  }
  return /^[一-龥]/.test(raw) ? raw : "模板解析失败，请重试或更换文件后重新上传";
}

function templateStatusText(template: Template): string {
  if (template.status === "analyzing") return "正在解析模板内容";
  if (template.status === "failed") return friendlyTemplateError(template.error);
  return template.is_active ? "已启用，可用于新建 PPT" : "已停用，暂不可使用";
}

function TemplatePreviewModal(props: { template: Template; onClose: () => void; onUse: (template: Template) => void }): ReactElement {
  const files = templatePreviewFiles(props.template);
  const [index, setIndex] = useState(0);
  const currentFile = files[index] || files[0] || "";
  const colors = templateMetadataList(props.template.metadata.colors).map((color) => color.startsWith("#") ? color : `#${color}`).filter((color) => /^#[0-9a-f]{6}$/i.test(color));
  const fonts = templateMetadataList(props.template.metadata.fonts);
  const importReport = importReportSummary(props.template);
  const lossEntries = Object.entries(importReport?.losses || {}).filter(([, entry]) => (entry.count || 0) > 0);
  const normalizationEntries = Object.entries(importReport?.normalizations || {}).filter(([, entry]) => (entry.count || 0) > 0);
  const placeholderRoles = Object.entries(importReport?.placeholders?.by_semantic_role || {}).filter(([, count]) => count > 0);
  const canUse = props.template.status === "ready" && props.template.is_active;
  function useTemplate(): void {
    if (!canUse) return;
    props.onUse(props.template);
    props.onClose();
  }
  return <div className="kppt-template-detail-backdrop" role="presentation" onMouseDown={props.onClose}>
    <section className="kppt-template-detail-modal" role="dialog" aria-modal="true" aria-label={`${props.template.name}模板详情`} onMouseDown={(event) => event.stopPropagation()}>
      <header>
        <div><span>{props.template.scope === "system" ? "系统模板详情" : "我的模板详情"}</span><h2>{props.template.name}</h2><p>{props.template.original_filename}</p></div>
        <button className="zc-icon" type="button" aria-label="关闭模板详情" title="关闭" onClick={props.onClose}><X size={18} /></button>
      </header>
      <div className="kppt-template-detail-body">
        <aside className="kppt-template-detail-thumbs"><strong>页面预览 <small>{files.length || props.template.page_count || 0} 页</small></strong>{files.length ? files.map((file, fileIndex) => <button className={index === fileIndex ? "is-active" : ""} type="button" key={file} onClick={() => setIndex(fileIndex)}><img src={templateFileUrl(props.template.id, file)} alt={`第 ${fileIndex + 1} 页`} /><span>{fileIndex + 1}</span></button>) : <p>{templateStatusText(props.template)}</p>}</aside>
        <main className="kppt-template-detail-canvas">{currentFile ? <img src={templateFileUrl(props.template.id, currentFile)} alt={`${props.template.name}第 ${index + 1} 页`} /> : <div><LayoutTemplate size={32} /><strong>{templateStatusText(props.template)}</strong></div>}</main>
        <aside className="kppt-template-detail-summary"><section><span>解析状态</span><strong className={`kppt-template-detail-state kppt-template-detail-state-${props.template.status}`}>{props.template.status === "ready" ? (props.template.is_active ? "已启用" : "已停用") : props.template.status === "analyzing" ? "解析中" : "解析失败"}</strong></section><section><span>页面数量</span><strong>{props.template.page_count || files.length || 0} 页</strong></section><section><span>最近更新</span><strong>{formatDate(props.template.updated_at)}</strong></section>{colors.length > 0 && <section><span>主要配色</span><div className="kppt-template-color-list">{colors.map((color) => <i key={color} title={color} style={{ backgroundColor: color }} />)}</div></section>}{fonts.length > 0 && <section><span>字体</span><p>{fonts.join("、")}</p></section>}{importReport && <section><span>导入保真度</span>{lossEntries.length > 0 ? <ul className="kppt-template-fidelity-list">{lossEntries.map(([code, entry]) => <li key={code} title={entry.sample || code}><em>{entry.label || code}</em>×{entry.count}</li>)}</ul> : <p>主要样式均已完整还原</p>}{placeholderRoles.length > 0 && <p>{placeholderRoles.map(([role, count]) => `${placeholderRoleLabels[role] || role} ×${count}`).join("、")}</p>}{normalizationEntries.length > 0 && <p className="kppt-template-fidelity-note">另有 {normalizationEntries.reduce((total, [, entry]) => total + (entry.count || 0), 0)} 处自动修正</p>}</section>}<section><span>源文件</span><p>{props.template.original_filename}</p></section></aside>
      </div>
      <footer className="kppt-template-detail-footer"><span>{files.length > 1 ? `第 ${index + 1} / ${files.length} 页` : files.length === 1 ? "共 1 页" : templateStatusText(props.template)}</span><div><button className="zc-icon" type="button" aria-label="上一页" title="上一页" disabled={index === 0 || files.length < 2} onClick={() => setIndex((current) => Math.max(0, current - 1))}><ChevronLeft size={17} /></button><button className="zc-icon" type="button" aria-label="下一页" title="下一页" disabled={index >= files.length - 1 || files.length < 2} onClick={() => setIndex((current) => Math.min(files.length - 1, current + 1))}><ChevronRight size={17} /></button><button className="zc-secondary" type="button" onClick={props.onClose}>关闭</button><PrimaryButton className="zc-primary" disabled={!canUse} onClick={useTemplate}><LayoutTemplate size={15} />使用此模板</PrimaryButton></div></footer>
    </section>
  </div>;
}

export function TemplatesPage(props: { templates: Template[]; query: string; setQuery: (value: string) => void; uploading: boolean; notice: string; onUpload: (file: File) => void | Promise<void>; onUse: (template: Template) => void; onRename: (template: Template) => void; onDelete: (template: Template) => void; onRetry: (template: Template) => Promise<void>; retryingTemplateId?: string | null }) {
  const [tab, setTab] = useState<"system" | "mine">("system");
  const [category, setCategory] = useState("全部场景");
  const [previewTemplate, setPreviewTemplate] = useState<Template | null>(null);
  const categories = Array.from(new Set(props.templates.map((template) => template.metadata.category ? String(template.metadata.category) : "商务汇报")));
  const visible = props.templates.filter((template) => {
    const matchesOwner = tab === "system" ? template.scope === "system" : template.scope !== "system";
    const matchesQuery = template.name.toLowerCase().includes(props.query.toLowerCase());
    const templateCategory = template.metadata.category ? String(template.metadata.category) : "商务汇报";
    return matchesOwner && matchesQuery && (category === "全部场景" || templateCategory === category);
  });
  const noMatch = Boolean(props.query.trim()) || category !== "全部场景";
  const emptyTemplateTitle = noMatch ? "没有找到匹配的模板" : tab === "system" ? "暂无系统模板" : "暂无个人模板";
  const emptyTemplateDescription = noMatch ? "尝试更换搜索条件。" : tab === "system" ? "管理员发布系统模板后，会在这里提供给所有用户使用。" : "上传一个 PPTX，建立你的个人模板资产。";
  const card = (template: Template) => {
    const files = templatePreviewFiles(template);
    const canUse = template.status === "ready" && template.is_active;
    return <article className="zc-template-card" key={template.id}><button className="zc-template-preview" type="button" aria-label={`查看模板 ${template.name}`} onClick={() => setPreviewTemplate(template)}>{files[0] ? <img src={templateFileUrl(template.id, files[0])} alt={`${template.name}预览`} /> : <LayoutTemplate size={30} />}<span>{template.scope === "system" ? "系统模板" : template.status === "ready" ? "用于新建 PPT" : template.status === "analyzing" ? "正在分析" : "解析失败"}</span></button><div><strong>{template.name}</strong><small>{template.page_count ? `${template.page_count} 页模板` : "正在读取页面信息"}</small></div><footer><button type="button" onClick={() => setPreviewTemplate(template)}><Eye size={14} />查看详情</button>{canUse && <button type="button" onClick={() => props.onUse(template)}><LayoutTemplate size={14} />使用模板</button>}{template.scope !== "system" && (template.status === "failed" ? <AsyncButton type="button" loading={props.retryingTemplateId === template.id} disabled={Boolean(props.retryingTemplateId)} onClick={() => void props.onRetry(template)}>重新分析</AsyncButton> : <button type="button" onClick={() => props.onRename(template)}><Edit3 size={14} />重命名</button>)}{template.scope !== "system" && <button className="is-danger" type="button" onClick={() => props.onDelete(template)}><Trash2 size={14} />删除</button>}</footer>{template.error && <p className="zc-template-error" title={template.error}>{friendlyTemplateError(template.error)}</p>}</article>;
  };
 return <section className="zc-asset-page kppt-asset-page"><header className="zc-asset-head"><div><div className="zc-eyebrow">设计资产</div><h1>PPT模板库</h1><p>选择平台模板，或上传团队已有的 PPTX 作为生成风格。</p></div><UploadButton className="zc-upload" icon={<Upload size={16} />} loading={props.uploading} disabled={props.uploading} accept=".pptx" onFiles={(files) => { const file = files[0]; if (file) void props.onUpload(file); }}>{props.uploading ? "正在上传…" : "上传模板"}</UploadButton></header><div className="kppt-asset-tabs"><div className="kppt-tab-list" role="tablist"><button type="button" className={tab === "system" ? "is-active" : ""} onClick={() => setTab("system")}>系统模板 <span>{props.templates.filter((template) => template.scope === "system").length}</span></button><button type="button" className={tab === "mine" ? "is-active" : ""} onClick={() => setTab("mine")}>我的模板 <span>{props.templates.filter((template) => template.scope !== "system").length}</span></button></div><div className="kppt-asset-tools"><label className="kppt-compact-search"><Search size={15} /><input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="搜索模板或标签" /></label><Select className="kppt-category-select" popupClassName="kppt-category-select-dropdown" value={category} onChange={setCategory} prefix={<ListFilter size={15} />} options={[{ value: "全部场景", label: "全部场景" }, ...categories.map((item) => ({ value: item, label: item }))]} aria-label="筛选模板场景" /></div></div>{visible.length === 0 && !(tab === "mine" && !noMatch) ? <AssetEmptyState className="kppt-asset-empty-state" title={emptyTemplateTitle} description={emptyTemplateDescription} /> : <div className="zc-template-grid kppt-template-grid">{tab === "mine" && <UploadButton type="default" className="zc-template-upload kppt-upload-template" icon={<Plus size={22} />} accept=".pptx" loading={props.uploading} disabled={props.uploading} onFiles={(files) => { const file = files[0]; if (file) void props.onUpload(file); }}><strong>上传新模板</strong><span>支持 .pptx，建议使用 16:9 页面</span></UploadButton>}{visible.map(card)}</div>}{previewTemplate && <TemplatePreviewModal template={previewTemplate} onClose={() => setPreviewTemplate(null)} onUse={props.onUse} />}</section>;
}

export function PromptsPage(props: { snippets: PromptSnippet[]; query: string; setQuery: (value: string) => void; notice: string; onUse: (snippet: PromptSnippet) => void; onCreate: () => void; onEdit: (snippet: PromptSnippet) => void; onDelete: (snippet: PromptSnippet) => void; skillId?: string }) {
  const query = props.query.trim().toLowerCase();
  const visible = props.snippets.filter((snippet) => (!props.skillId || !snippet.skill_id || snippet.skill_id === props.skillId) && (!query || `${snippet.name}${snippet.content}${snippet.preset?.requirements?.objective || ""}`.toLowerCase().includes(query)));
  const renderCard = (snippet: PromptSnippet) => <article className="zc-prompt-card" key={snippet.id}><header><span><Zap size={15} /></span><small>{snippet.scope === "system" ? "系统预设" : snippet.category}</small><button type="button" onClick={() => props.onUse(snippet)}><WandSparkles size={14} />在首页使用</button></header><h3>{snippet.name}</h3><p>{snippet.preset?.requirements?.objective || snippet.content || "未配置默认要求"}</p><footer><span>已使用 {snippet.used_count} 次</span><div><button type="button" aria-label="复制预设说明" onClick={() => void navigator.clipboard?.writeText(snippet.content)}><Copy size={15} /></button>{snippet.scope !== "system" && <><button type="button" aria-label="编辑创作预设" onClick={() => props.onEdit(snippet)}><Edit3 size={15} /></button><button type="button" aria-label="删除创作预设" onClick={() => props.onDelete(snippet)}><Trash2 size={15} /></button></>}</div></footer></article>;
  const systemSnippets = visible.filter((snippet) => snippet.scope === "system");
  const personalSnippets = visible.filter((snippet) => snippet.scope !== "system");
  const personalCount = props.snippets.filter((snippet) => snippet.scope !== "system").length;
  const noMatch = Boolean(query);
  return <section className="zc-asset-page kppt-asset-page prompt-page"><header className="zc-asset-head"><div><div className="zc-eyebrow">个人效率资产</div><h1>PPT预设</h1><p>把常用需求和页面结构保存为预设，在首页选择后直接填入创作流程。</p></div><button className="zc-primary" type="button" onClick={props.onCreate}><Plus size={16} />新建预设</button></header><div className="zc-prompt-summary"><span><Sparkles size={20} /></span><div><strong>让每一次创作更快开始</strong><small>已保存 {personalCount} 条个人预设，本月累计使用 {props.snippets.reduce((total, item) => total + item.used_count, 0)} 次</small></div><label><Search size={16} /><input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="搜索创作预设" /></label></div><h2 className="zc-library-heading">系统预设</h2>{systemSnippets.length > 0 ? <div className="zc-prompt-grid kppt-prompt-grid">{systemSnippets.map(renderCard)}</div> : <AssetEmptyState title={noMatch ? "未找到匹配的系统预设" : "暂无系统预设"} description={noMatch ? "请尝试其他关键词。" : "管理员发布系统预设后，会在这里提供给所有用户使用。"} />}<h2 className="zc-library-heading">我的预设</h2>{personalSnippets.length > 0 ? <div className="zc-prompt-grid kppt-prompt-grid">{personalSnippets.map(renderCard)}</div> : <AssetEmptyState title={noMatch ? "未找到匹配的个人预设" : "暂无个人预设"} description={noMatch ? "请尝试其他关键词。" : "点击右上角“新建预设”，保存你的常用需求和页面结构。"} />}</section>;
}

