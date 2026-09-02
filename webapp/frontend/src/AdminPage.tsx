import { FormEvent, useEffect, useState } from "react";
import { Edit3, Eye, LayoutTemplate, LoaderCircle, Plus, Settings, Trash2, Upload, UserPlus, Users, WandSparkles, X, Zap } from "lucide-react";
import { AdminRouteTab } from "./routes";
import type { PromptPreset, PromptPresetSlide, Provider, PromptSnippet, Template, TemplateProgress, User } from "./appTypes";
import { AssetEmptyState, AsyncButton, ConfirmAction, NoticeHost, UploadButton } from "./ui";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", headers: { "Content-Type": "application/json", ...options?.headers }, ...options });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "请求失败，请稍后重试。"); }
  return response.status === 204 ? (undefined as T) : response.json();
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function templatePreviewFiles(template: Template): string[] {
  // Prefer server-rendered PNGs; fall back to raw SVGs for legacy imports.
  const pngs = template.metadata.preview_files_png;
  const pngFiles = Array.isArray(pngs) ? pngs.map(String).filter(Boolean) : [];
  if (pngFiles.length > 0) return pngFiles;
  const value = template.metadata.preview_files;
  const files = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
  const slideFiles = files.filter((file) => /(?:^|\/)\d{3}_.*\.svg$/i.test(file));
  return slideFiles.length > 0 ? slideFiles : files;
}

function templateProgress(template: Template): TemplateProgress {
  const value = template.metadata.progress;
  return value && typeof value === "object" ? value as TemplateProgress : {};
}

function templateStatusLabel(template: Template): string {
  if (template.status === "analyzing") return "解析中";
  if (template.status === "failed") return "解析失败";
  return template.is_active ? "已启用" : "已停用";
}

function templateColors(template: Template): string[] {
  const value = template.metadata.colors;
  const values = Array.isArray(value) ? value : value && typeof value === "object" ? Object.values(value) : [];
  return values.map(String).map((color) => color.startsWith("#") ? color : `#${color}`).filter((color) => /^#[0-9a-f]{6}$/i.test(color)).slice(0, 10);
}

function templateFonts(template: Template): string[] {
  const value = template.metadata.fonts;
  const values = Array.isArray(value) ? value : value && typeof value === "object" ? Object.values(value) : [];
  return values.map((font) => typeof font === "string" ? font : JSON.stringify(font)).filter(Boolean).slice(0, 12);
}

function templateAssetUrl(templateId: string, filePath: string): string {
  const encodedPath = filePath.split("/").map((part) => encodeURIComponent(part)).join("/");
  return `/api/v1/admin/system-templates/${templateId}/files/${encodedPath}`;
}

const emptySystemPromptPreset = (): PromptPreset => ({
  requirements: { scenario: "", audience: "", page_range: "8-10 页", style: "", objective: "" },
  outline: [],
  notes_enabled: true,
});

function systemPromptPageCount(value: unknown): number {
  const text = String(value || "8-10 页").trim();
  const range = text.match(/(\d+)\s*[-至]\s*(\d+)/);
  if (range) return Math.max(1, Number(range[2]));
  const above = text.match(/(\d+)\s*页以上/);
  return above ? Math.max(1, Number(above[1])) : 8;
}

function blankSystemPromptSlide(): PromptPresetSlide {
  return { title: "", purpose: "", content: "", kind: "内容页", notes: "" };
}

function normalizeSystemPromptSlides(preset: PromptPreset): PromptPresetSlide[] {
  const rawOutline = (preset as PromptPreset & { outline?: unknown }).outline;
  if (!Array.isArray(rawOutline)) return [];
  return rawOutline.map((slide) => ({
    title: String(slide?.title || ""),
    purpose: String(slide?.purpose || ""),
    content: String(slide?.content || ""),
    kind: String(slide?.kind || "内容页"),
    notes: String(slide?.notes || ""),
  }));
}

function ensureSystemPromptSlideCount(slides: PromptPresetSlide[], count: number): PromptPresetSlide[] {
  const next = [...slides];
  const isBlank = (slide: PromptPresetSlide) => !slide.title.trim() && !slide.purpose.trim() && !slide.content.trim() && !slide.notes.trim();
  if (next.length > count && next.slice(count).every(isBlank)) return next.slice(0, count);
  while (next.length < count) next.push(blankSystemPromptSlide());
  return next;
}

function systemPromptRequirementsComplete(requirements: PromptPreset["requirements"] | undefined): boolean {
  return Boolean(requirements?.scenario?.trim() && requirements?.audience?.trim() && requirements?.page_range?.trim() && requirements?.style?.trim() && requirements?.objective?.trim());
}

function SystemPromptOutlineEditor(props: { slides: PromptPresetSlide[]; busy: boolean; onEdit: (index: number, key: keyof PromptPresetSlide, value: string) => void; onMove: (index: number, direction: -1 | 1) => void; onAdd: () => void; onRemove: (index: number) => void }) {
  return <section className="zc-preset-form zc-preset-outline-form"><div className="zc-preset-section-heading"><div><strong>默认大纲</strong><small>按页面逐一填写，发布后会带入用户的大纲设计步骤。</small></div><button className="zc-secondary" type="button" onClick={props.onAdd} disabled={props.busy}><Plus size={14} />新增页面</button></div><div className="zc-preset-outline-list">{props.busy ? Array.from({ length: Math.max(1, props.slides.length) }, (_, index) => <article className="zc-preset-slide-skeleton" key={`system-prompt-skeleton-${index}`} aria-hidden="true"><span className="zc-skeleton-block zc-preset-skeleton-number" /><div><span className="zc-skeleton-block zc-preset-skeleton-title" /><span className="zc-skeleton-block zc-preset-skeleton-line" /><span className="zc-skeleton-block zc-preset-skeleton-line zc-preset-skeleton-line-short" /><span className="zc-skeleton-block zc-preset-skeleton-notes" /></div></article>) : props.slides.map((slide, index) => <article className="zc-preset-slide-card" key={`system-prompt-slide-${index}`}><div className="zc-preset-slide-number">{String(index + 1).padStart(2, "0")}</div><div className="zc-preset-slide-fields"><label><span>页面标题</span><input value={slide.title} onChange={(event) => props.onEdit(index, "title", event.target.value)} placeholder="例如：现状与关键挑战" /></label><label><span>建议表现形式</span><input value={slide.kind} onChange={(event) => props.onEdit(index, "kind", event.target.value)} placeholder="例如：数据图表" /></label><label><span>本页目标</span><textarea rows={2} value={slide.purpose} onChange={(event) => props.onEdit(index, "purpose", event.target.value)} placeholder="希望观众理解什么" /></label><label><span>本页内容</span><textarea rows={3} value={slide.content} onChange={(event) => props.onEdit(index, "content", event.target.value)} placeholder="填写本页需要呈现的核心信息、数据或要点" /></label><label><span>讲解重点</span><textarea rows={2} value={slide.notes} onChange={(event) => props.onEdit(index, "notes", event.target.value)} placeholder="补充讲解顺序、口径或提醒" /></label></div><div className="zc-preset-slide-actions"><button type="button" aria-label="上移页面" title="上移页面" onClick={() => props.onMove(index, -1)} disabled={index === 0}>↑</button><button type="button" aria-label="下移页面" title="下移页面" onClick={() => props.onMove(index, 1)} disabled={index === props.slides.length - 1}>↓</button><button type="button" aria-label="删除页面" title="删除页面" onClick={() => props.onRemove(index)} disabled={props.slides.length <= 1}><X size={14} /></button></div></article>)}</div></section>;
}

function SystemPromptManager(props: { snippets: PromptSnippet[]; onRefresh: () => Promise<void> }) {
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [promptName, setPromptName] = useState("");
  const [promptCategory, setPromptCategory] = useState("平台");
  const [promptSkill, setPromptSkill] = useState("ppt-master");
  const [promptContent, setPromptContent] = useState("");
  const [editingPromptId, setEditingPromptId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [promptPreset, setPromptPreset] = useState<PromptPreset>(emptySystemPromptPreset());
  const [promptSlides, setPromptSlides] = useState<PromptPresetSlide[]>(ensureSystemPromptSlideCount([], 8));
  const [generating, setGenerating] = useState(false);
  const [outlineNotice, setOutlineNotice] = useState("");

  function resetEditor(): void {
    setPromptName(""); setPromptCategory("平台"); setPromptContent(""); setPromptSkill("ppt-master"); setEditingPromptId(null); setPromptPreset(emptySystemPromptPreset()); setPromptSlides(ensureSystemPromptSlideCount([], 8)); setGenerating(false); setOutlineNotice(""); setEditorOpen(false);
  }

  function editPrompt(snippet: PromptSnippet): void {
    const preset = { ...emptySystemPromptPreset(), ...(snippet.preset || {}), requirements: { ...emptySystemPromptPreset().requirements, ...(snippet.preset?.requirements || {}) } };
    setEditingPromptId(snippet.id); setPromptName(snippet.name); setPromptCategory(snippet.category); setPromptContent(snippet.content); setPromptSkill(snippet.skill_id || ""); setPromptPreset(preset); setPromptSlides(ensureSystemPromptSlideCount(normalizeSystemPromptSlides(preset), systemPromptPageCount(preset.requirements?.page_range))); setOutlineNotice(""); setEditorOpen(true);
  }

  function openNewPrompt(): void {
    resetEditor();
    setEditorOpen(true);
  }

  function updatePageRange(value: string): void {
    setPromptPreset((current) => ({ ...current, requirements: { ...current.requirements, page_range: value } }));
    setPromptSlides((current) => ensureSystemPromptSlideCount(current, systemPromptPageCount(value)));
  }

  async function generateOutline(): Promise<void> {
    if (!systemPromptRequirementsComplete(promptPreset.requirements)) { setOutlineNotice("请先填写完整的默认需求，再生成大纲。"); return; }
    setGenerating(true); setOutlineNotice("");
    try {
      const outline = await request<PromptPresetSlide[]>("/api/v1/prompt-snippets/generate-outline", { method: "POST", body: JSON.stringify({ requirements: promptPreset.requirements }) });
      setPromptSlides(ensureSystemPromptSlideCount(outline.map((slide) => ({ ...blankSystemPromptSlide(), ...slide })), systemPromptPageCount(promptPreset.requirements?.page_range)));
      setOutlineNotice("已生成系统默认大纲，你可以继续逐页调整。");
    } catch (error) { setOutlineNotice(error instanceof Error ? error.message : "大纲生成失败，请稍后重试。"); }
    finally { setGenerating(false); }
  }

  async function savePrompt(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!promptName.trim() || busy || generating) return;
    setBusy(true); setNotice("");
    try {
      const payload = { name: promptName.trim(), category: promptCategory.trim() || "平台", content: promptContent.trim(), preset: { ...promptPreset, outline: promptSlides.filter((slide) => slide.title.trim()).map((slide) => ({ ...slide, title: slide.title.trim() })) }, skill_id: promptSkill };
      await request<PromptSnippet>(editingPromptId ? `/api/v1/admin/system-prompts/${editingPromptId}` : "/api/v1/admin/system-prompts", { method: editingPromptId ? "PATCH" : "POST", body: JSON.stringify(payload) });
      await props.onRefresh(); resetEditor(); setNotice(editingPromptId ? "系统预设已更新。" : "系统预设已发布。");
    } catch (error) { setNotice(error instanceof Error ? error.message : "系统预设保存失败。"); }
    finally { setBusy(false); }
  }

  async function togglePrompt(snippet: PromptSnippet): Promise<void> {
    setBusy(true); setNotice("");
    try { await request(`/api/v1/admin/system-prompts/${snippet.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !snippet.is_active }) }); await props.onRefresh(); setNotice(snippet.is_active ? "系统预设已停用。" : "系统预设已启用。"); }
    catch (error) { setNotice(error instanceof Error ? error.message : "系统预设状态更新失败。"); }
    finally { setBusy(false); }
  }

  async function deletePrompt(snippet: PromptSnippet): Promise<void> {
    setBusy(true); setNotice("");
    try { await request<void>(`/api/v1/admin/system-prompts/${snippet.id}`, { method: "DELETE" }); if (editingPromptId === snippet.id) resetEditor(); await props.onRefresh(); setNotice("系统预设已删除。"); }
    catch (error) { setNotice(error instanceof Error ? error.message : "系统预设删除失败。"); }
    finally { setBusy(false); }
  }

  function updateSlide(index: number, key: keyof PromptPresetSlide, value: string): void { setPromptSlides((current) => current.map((slide, slideIndex) => slideIndex === index ? { ...slide, [key]: value } : slide)); }
  function moveSlide(index: number, direction: -1 | 1): void { setPromptSlides((current) => { const target = index + direction; if (target < 0 || target >= current.length) return current; const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next; }); }
  function removeSlide(index: number): void { setPromptSlides((current) => current.length <= 1 ? current : current.filter((_, slideIndex) => slideIndex !== index)); }

  return <div className="kppt-system-prompt-manager"><div className="kppt-system-prompt-toolbar"><div><strong>PPT系统预设</strong><small>集中管理用户可选择的结构化创作预设。</small></div><button className="zc-primary" type="button" onClick={openNewPrompt} disabled={busy || generating}><Plus size={16} />添加系统预设</button></div><div className={editorOpen ? "kppt-system-prompt-editor-shell is-open" : "kppt-system-prompt-editor-shell"} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) resetEditor(); }}><section className="zc-modal kppt-system-prompt-editor-modal" role="dialog" aria-modal="true" aria-label={editingPromptId ? "编辑系统预设" : "添加系统预设"} onMouseDown={(event) => event.stopPropagation()}><button className="zc-icon zc-modal-close" type="button" aria-label="关闭系统预设编辑器" onClick={resetEditor}><X size={18} /></button><h2>{editingPromptId ? "编辑系统预设" : "添加系统预设"}</h2><p>完成默认需求和逐页大纲后，系统预设会在用户创建 PPT 时自动带入。</p><form className="zc-admin-prompt-form kppt-admin-preset-form" onSubmit={(event) => void savePrompt(event)}><div className="kppt-admin-prompt-basic"><input value={promptName} onChange={(event) => setPromptName(event.target.value)} placeholder="系统预设名称" required /><input value={promptCategory} onChange={(event) => setPromptCategory(event.target.value)} placeholder="分类" required /><select value={promptSkill} onChange={(event) => setPromptSkill(event.target.value)} aria-label="适用技能"><option value="ppt-master">适用：PPT写作</option><option value="">适用：全部技能</option></select></div><div className="zc-preset-form"><div className="zc-preset-section-heading"><div><strong>默认需求</strong><small>这些内容会在用户选择系统预设后自动填入需求梳理。</small></div><button className="zc-secondary zc-preset-ai-button" type="button" onClick={() => void generateOutline()} disabled={!systemPromptRequirementsComplete(promptPreset.requirements) || generating || busy}><WandSparkles size={14} />{generating ? "生成中…" : "AI 生成默认大纲"}</button></div><div className="zc-preset-grid"><label>使用场景<input value={promptPreset.requirements?.scenario || ""} onChange={(event) => setPromptPreset((current) => ({ ...current, requirements: { ...current.requirements, scenario: event.target.value } }))} /></label><label>目标受众<input value={promptPreset.requirements?.audience || ""} onChange={(event) => setPromptPreset((current) => ({ ...current, requirements: { ...current.requirements, audience: event.target.value } }))} /></label><label>页数范围<select value={promptPreset.requirements?.page_range || "8-10 页"} onChange={(event) => updatePageRange(event.target.value)}>{["1-4 页", "5-7 页", "8-10 页", "11-12 页", "13-15 页", "16-19 页", "20 页以上"].map((item) => <option key={item}>{item}</option>)}</select></label><label>整体风格<input value={promptPreset.requirements?.style || ""} onChange={(event) => setPromptPreset((current) => ({ ...current, requirements: { ...current.requirements, style: event.target.value } }))} /></label><label className="is-wide">核心目标<textarea rows={3} value={promptPreset.requirements?.objective || ""} onChange={(event) => setPromptPreset((current) => ({ ...current, requirements: { ...current.requirements, objective: event.target.value } }))} /></label></div><label className="zc-preset-notes"><input type="checkbox" checked={promptPreset.notes_enabled !== false} onChange={(event) => setPromptPreset((current) => ({ ...current, notes_enabled: event.target.checked }))} />默认生成每页讲解词</label></div>{outlineNotice && <small className="zc-preset-ai-notice">{outlineNotice}</small>}<SystemPromptOutlineEditor busy={generating} slides={promptSlides} onEdit={updateSlide} onMove={moveSlide} onAdd={() => setPromptSlides((current) => [...current, blankSystemPromptSlide()])} onRemove={removeSlide} /><label className="kppt-admin-advanced-prompt">高级模型指令（可选）<textarea value={promptContent} onChange={(event) => setPromptContent(event.target.value)} placeholder="仅用于补充模型行为约束，不替代上面的结构化需求和大纲。" rows={3} /></label><div className="zc-modal-actions"><button className="zc-secondary" type="button" onClick={resetEditor} disabled={busy || generating}>取消编辑</button><button className="zc-primary" type="submit" disabled={busy || generating || !promptName.trim()}>{busy ? <LoaderCircle className="zc-spin" size={15} /> : null}{editingPromptId ? "保存系统预设" : "发布系统预设"}</button></div></form></section></div><NoticeHost message={notice} onClose={() => setNotice("")} />{props.snippets.length ? <div className="zc-prompt-grid">{props.snippets.map((snippet) => <article className="zc-prompt-card" key={snippet.id}><header><span><Zap size={15} /></span><small>{snippet.skill_id ? "PPT" : "通用"} · {snippet.category} · {snippet.preset?.outline?.length ? "结构化预设" : "待完善"}</small><div className="kppt-admin-row-actions"><button type="button" className="zc-secondary" disabled={busy || generating} onClick={() => editPrompt(snippet)}><Edit3 size={14} />编辑预设</button><button type="button" disabled={busy || generating} onClick={() => void togglePrompt(snippet)}>{snippet.is_active ? "停用" : "启用"}</button></div></header><h3>{snippet.name}</h3><p>{snippet.preset?.requirements?.objective || snippet.content || "未配置默认需求"}</p><footer><span>{snippet.is_active ? "用户可选择" : "已停用"} · 已使用 {snippet.used_count} 次</span><ConfirmAction title="确认删除这个系统预设？" description="删除后用户将无法继续使用。" disabled={busy || generating} onConfirm={() => deletePrompt(snippet)}><button type="button" disabled={busy || generating} aria-label="删除系统预设"><Trash2 size={15} /></button></ConfirmAction></footer></article>)}</div> : <AssetEmptyState title="暂无系统预设" description="点击上方按钮添加第一个系统预设。" />}</div>;
}

export function AdminPage(props: { initialTab: AdminRouteTab; onTabChange: (tab: AdminRouteTab) => void; templates: Template[]; snippets: PromptSnippet[]; users: User[]; providers: Provider[]; onRefresh: () => Promise<void> }) {
  const [tab, setTab] = useState<AdminRouteTab>(props.initialTab);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [userForm, setUserForm] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [providerForm, setProviderForm] = useState(false);
  const [providerSlug, setProviderSlug] = useState("");
  const [providerName, setProviderName] = useState("");
  const [providerUrl, setProviderUrl] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [modelProvider, setModelProvider] = useState<string | null>(null);
  const [modelId, setModelId] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelTesting, setModelTesting] = useState(false);
  const [modelVerified, setModelVerified] = useState(false);
  const [modelTestMessage, setModelTestMessage] = useState("");
  const [verifyingModelId, setVerifyingModelId] = useState<string | null>(null);
  const [defaultingModelId, setDefaultingModelId] = useState<string | null>(null);
  const [templateDetail, setTemplateDetail] = useState<Template | null>(null);
  const [templateDetailLoading, setTemplateDetailLoading] = useState(false);
  const [templatePreviewIndex, setTemplatePreviewIndex] = useState(0);

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true); setNotice("");
    try { await action(); await props.onRefresh(); setNotice(success); }
    catch (error) { setNotice(error instanceof Error ? error.message : "操作失败，请稍后重试。"); }
    finally { setBusy(false); }
  }
  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => { if (password !== confirmation) throw new Error("两次输入的密码不一致。"); await request("/api/v1/admin/users", { method: "POST", body: JSON.stringify({ username: username.trim(), password, password_confirmation: confirmation }) }); setUsername(""); setPassword(""); setConfirmation(""); setUserForm(false); }, "用户已创建。");
  }
  async function uploadTemplate(file: File) {
    if (!file) return;
    await run(async () => { const form = new FormData(); form.append("file", file); const response = await fetch("/api/v1/admin/system-templates/import", { method: "POST", credentials: "include", body: form }); if (!response.ok) throw new Error("系统模板上传失败。"); }, "系统模板已加入解析队列。");
  }
  async function createProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => { await request("/api/v1/admin/providers", { method: "POST", body: JSON.stringify({ slug: providerSlug.trim(), display_name: providerName.trim(), base_url: providerUrl.trim(), api_key: providerKey.trim(), is_active: true }) }); setProviderSlug(""); setProviderName(""); setProviderUrl(""); setProviderKey(""); setProviderForm(false); }, "供应商已创建。");
  }
  async function createModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const provider = props.providers.find((item) => item.id === modelProvider); if (!provider) return;
    if (!modelVerified) { setModelTestMessage("请先通过模型连通性测试。"); return; }
    await run(async () => { await request("/api/v1/admin/providers/" + provider.id + "/models", { method: "POST", body: JSON.stringify({ model_id: modelId.trim(), display_name: modelName.trim(), is_active: true }) }); setModelProvider(null); setModelId(""); setModelName(""); setModelVerified(false); setModelTestMessage(""); }, "模型已创建并通过验证。");
  }
  async function testModelConnectivity(): Promise<void> {
    const provider = props.providers.find((item) => item.id === modelProvider);
    if (!provider || !modelId.trim() || modelTesting) return;
    setModelTesting(true); setModelTestMessage("正在验证模型连通性，最长等待约 40 秒，请勿重复点击。"); setModelVerified(false);
    try {
      await request(`/api/v1/admin/providers/${provider.id}/model-connectivity-test`, { method: "POST", body: JSON.stringify({ model_id: modelId.trim() }) });
      setModelVerified(true); setModelTestMessage("连通性测试通过，可以保存并启用模型。");
    } catch (error) { setModelTestMessage(error instanceof Error ? error.message : "连通性测试失败。"); }
    finally { setModelTesting(false); }
  }
  async function verifyExistingModel(modelId: string): Promise<void> {
    if (verifyingModelId) return;
    setVerifyingModelId(modelId);
    setNotice("");
    try {
      await request(`/api/v1/admin/models/${modelId}/verify`, { method: "POST" });
      await props.onRefresh();
      setNotice("模型连通性验证通过，模型已标记为已验证。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "模型连通性验证失败。");
      try { await props.onRefresh(); } catch { /* Keep the connectivity error visible if the refresh fails. */ }
    } finally {
      setVerifyingModelId(null);
    }
  }
  async function setDefaultModel(provider: Provider, model: Provider["models"][number]): Promise<void> {
    if (defaultingModelId) return;
    setDefaultingModelId(model.id);
    setNotice("");
    try {
      await request(`/api/v1/admin/model-catalog/default`, { method: "PATCH", body: JSON.stringify({ model_id: provider.slug + "/" + model.model_id }) });
      await props.onRefresh();
      setNotice("默认模型已更新。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "默认模型更新失败。");
    } finally {
      setDefaultingModelId(null);
    }
  }
  async function openTemplateDetail(template: Template) {
    setTemplateDetail(template);
    setTemplatePreviewIndex(0);
    setTemplateDetailLoading(true);
    try {
      const detail = await request<Template>(`/api/v1/admin/system-templates/${template.id}/detail`);
      setTemplateDetail(detail);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法读取模板详情。");
    } finally {
      setTemplateDetailLoading(false);
    }
  }
  function closeTemplateDetail() {
    setTemplateDetail(null);
    setTemplateDetailLoading(false);
    setTemplatePreviewIndex(0);
  }
  const detailFiles = templateDetail ? templatePreviewFiles(templateDetail) : [];
  const detailColors = templateDetail ? templateColors(templateDetail) : [];
  const detailFonts = templateDetail ? templateFonts(templateDetail) : [];
  const detailProgress = templateDetail ? templateProgress(templateDetail) : {};
  const detailCurrentFile = detailFiles[templatePreviewIndex] || detailFiles[0] || "";
  const heading = tab === "templates" ? "PPT系统模板" : tab === "prompts" ? "PPT系统预设" : tab === "users" ? "用户管理" : "模型管理";
  const nav = [["templates", "PPT系统模板", LayoutTemplate], ["prompts", "PPT系统预设", Zap], ["users", "用户管理", Users], ["models", "模型管理", Settings]] as const;
  useEffect(() => { setTab(props.initialTab); }, [props.initialTab]);
  function changeTab(next: AdminRouteTab) { setTab(next); props.onTabChange(next); }
  return <section className="zc-admin-page kppt-admin-page"><div className="zc-admin-layout"><aside aria-label="管理设置导航">{nav.map(([key, label, Icon]) => <button key={key} className={tab === key ? "is-active" : ""} type="button" onClick={() => changeTab(key)}><Icon size={17} />{label}</button>)}</aside><main><NoticeHost message={notice} onClose={() => setNotice("")} /><header className="zc-admin-section-head"><div><h1>{heading}</h1><p>{tab === "models" ? "维护模型供应商、可用模型和默认生成模型。" : "维护所有用户可见的系统资源。"}</p></div>{tab === "templates" && <UploadButton className="zc-upload" icon={<Upload size={16} />} loading={busy} disabled={busy} accept=".pptx" onFiles={(files) => { const file = files[0]; if (file) void uploadTemplate(file); }}>上传系统模板</UploadButton>}{tab === "users" && <button className="zc-primary" type="button" onClick={() => setUserForm((current) => !current)}><UserPlus size={16} />{userForm ? "收起表单" : "新增用户"}</button>}{tab === "models" && <button className="zc-primary" type="button" onClick={() => setProviderForm((current) => !current)}><Plus size={16} />{providerForm ? "收起表单" : "新增供应商"}</button>}</header>
      {tab === "templates" && <div className="zc-template-grid">{props.templates.length ? props.templates.map((template) => { const progress = templateProgress(template); const canToggle = template.status === "ready"; return <article className="zc-template-card" key={template.id}><div className="zc-template-preview">{templatePreviewFiles(template)[0] ? <img src={templateAssetUrl(template.id, templatePreviewFiles(template)[0])} alt={`${template.name}预览`} /> : <LayoutTemplate size={30} />}<span className={`zc-template-status zc-template-status-${template.status}`}>{templateStatusLabel(template)}</span></div><strong>{template.name}</strong><small>{template.page_count ? template.page_count + " 页模板" : template.status === "analyzing" ? "正在解析页面信息" : "暂无页面信息"}</small>{template.status !== "ready" && <p className="zc-template-progress">{progress.message || template.error || "模板正在处理"}</p>}<footer><button type="button" onClick={() => void openTemplateDetail(template)}><Eye size={14} />查看详情</button><button type="button" disabled={busy || !canToggle} onClick={() => void run(() => request("/api/v1/admin/system-templates/" + template.id, { method: "PATCH", body: JSON.stringify({ is_active: !template.is_active }) }).then(() => undefined), "模板状态已更新。")}>{template.is_active ? "停用" : "启用"}</button><ConfirmAction title="确认删除系统模板？" description="删除后将从所有用户的模板库中移除。" disabled={busy} onConfirm={() => run(() => request<void>("/api/v1/admin/system-templates/" + template.id, { method: "DELETE" }), "系统模板已删除。")}><button className="is-danger" type="button" disabled={busy}><Trash2 size={14} />删除</button></ConfirmAction></footer></article>; }) : <AssetEmptyState className="kppt-admin-empty-state" title="暂无系统模板" description="上传一个 PPTX 后，所有用户即可使用。" />}</div>}
       {tab === "prompts" && <SystemPromptManager snippets={props.snippets} onRefresh={props.onRefresh} />}
      {tab === "users" && <>{userForm && <form className="kppt-admin-form" onSubmit={(event) => void createUser(event)}><label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,63}" minLength={3} required /></label><label>初始密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required /></label><label>确认密码<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} minLength={8} required /></label><div className="kppt-admin-form-actions"><button className="zc-secondary" type="button" onClick={() => setUserForm(false)}>取消</button><AsyncButton className="zc-primary" type="submit" loading={busy}>创建用户</AsyncButton></div></form>}<div className={`zc-user-table${props.users.length ? "" : " is-empty"}`}><header><span>用户</span><span>账号</span><span>角色</span><span>状态</span><span>操作</span></header>{props.users.map((account) => <div key={account.id}><strong>{account.display_name}</strong><span>{account.username}</span><span>{account.role === "super_admin" ? "超级管理员" : account.role === "admin" ? "管理员" : "成员"}</span><span className={account.is_active ? "zc-user-active" : "zc-user-inactive"}>{account.is_active ? "启用" : "已停用"}</span><div className="kppt-admin-row-actions"><button className="zc-secondary" disabled={busy || account.role === "super_admin"} type="button" onClick={() => void run(() => request("/api/v1/admin/users/" + account.id, { method: "PATCH", body: JSON.stringify({ is_active: !account.is_active }) }).then(() => undefined), account.is_active ? "用户已停用。" : "用户已启用。")}>{account.is_active ? "停用" : "启用"}</button><ConfirmAction title="确认删除这个用户？" description="删除后其项目和任务也会被清理，且无法恢复。" disabled={busy || account.role === "super_admin"} onConfirm={() => run(() => request<void>("/api/v1/admin/users/" + account.id, { method: "DELETE" }), "用户已删除。")}><button className="zc-secondary is-danger" type="button" disabled={busy || account.role === "super_admin"}><Trash2 size={14} />删除</button></ConfirmAction></div></div>)}</div>{!props.users.length && <AssetEmptyState className="kppt-admin-empty-state" title="暂无用户" description="新增用户后，账号会显示在这里。" />}</>}
      {tab === "models" && <>{providerForm && <form className="kppt-admin-form kppt-provider-form" onSubmit={(event) => void createProvider(event)}><label>供应商标识<input value={providerSlug} onChange={(event) => setProviderSlug(event.target.value)} pattern="[a-z][a-z0-9_-]*" minLength={2} required /></label><label>显示名称<input value={providerName} onChange={(event) => setProviderName(event.target.value)} required /></label><label>Base URL<input type="url" value={providerUrl} onChange={(event) => setProviderUrl(event.target.value)} required /></label><label>API Key<input type="password" value={providerKey} onChange={(event) => setProviderKey(event.target.value)} required /></label><div className="kppt-admin-form-actions"><button className="zc-secondary" type="button" onClick={() => setProviderForm(false)}>取消</button><AsyncButton className="zc-primary" type="submit" loading={busy}>创建供应商</AsyncButton></div></form>}<div className="kppt-provider-list">{props.providers.length ? props.providers.map((provider) => <article className="kppt-provider-card" key={provider.id}><header><div><strong>{provider.display_name}</strong><span>{provider.slug} · {provider.base_url}</span></div><ConfirmAction title="确认删除这个供应商？" description="删除后其中的模型配置也会被移除。" disabled={busy} onConfirm={() => run(() => request<void>("/api/v1/admin/providers/" + provider.id, { method: "DELETE" }), "供应商已删除。")}><button className="zc-secondary is-danger" type="button" disabled={busy}><Trash2 size={14} />删除</button></ConfirmAction></header><p className="kppt-provider-key">API Key：{provider.api_key_hint}</p><div className="kppt-model-list"><div className="kppt-model-list-head"><strong>模型</strong><button className="zc-secondary" type="button" disabled={busy} onClick={() => { setModelProvider(provider.id); setModelId(""); setModelName(""); setModelVerified(false); setModelTestMessage(""); }}><Plus size={14} />新增模型</button></div>{provider.models.map((model) => <div className="kppt-model-row" key={model.id}><div><strong>{model.display_name}</strong><span>{model.model_id}</span><small>{model.is_verified ? "已验证" : "未验证"}{model.last_test_error ? ` · ${model.last_test_error}` : ""}</small></div>{model.is_default && <em>默认</em>}<div className="kppt-admin-row-actions">{!model.is_verified && <AsyncButton className="zc-secondary" type="button" loading={verifyingModelId === model.id} disabled={Boolean(verifyingModelId) || !provider.is_active || !model.is_active} onClick={() => void verifyExistingModel(model.id)}>{verifyingModelId === model.id ? "验证中（最长 40 秒）" : "手动验证"}</AsyncButton>}{model.is_verified && <AsyncButton className="zc-secondary" type="button" loading={verifyingModelId === model.id} disabled={Boolean(verifyingModelId) || !provider.is_active || !model.is_active} onClick={() => void verifyExistingModel(model.id)}>{verifyingModelId === model.id ? "验证中（最长 40 秒）" : "重新验证"}</AsyncButton>}{!model.is_default && <AsyncButton className="zc-secondary" type="button" loading={defaultingModelId === model.id} disabled={busy || Boolean(verifyingModelId) || Boolean(defaultingModelId) || !model.is_active || !model.is_verified || !provider.is_active} onClick={() => void setDefaultModel(provider, model)}>设为默认</AsyncButton>}<ConfirmAction title="确认删除这个模型？" description="删除后模型将无法继续用于生成。" disabled={busy || Boolean(verifyingModelId) || Boolean(defaultingModelId)} onConfirm={() => run(() => request<void>("/api/v1/admin/models/" + model.id, { method: "DELETE" }), "模型已删除。")}><button className="zc-secondary is-danger" type="button" disabled={busy || Boolean(verifyingModelId) || Boolean(defaultingModelId)}><Trash2 size={14} />删除</button></ConfirmAction></div></div>)}{modelProvider === provider.id && <form className="kppt-admin-model-form" onSubmit={(event) => void createModel(event)}><label>模型 ID<input value={modelId} onChange={(event) => { setModelId(event.target.value); setModelVerified(false); setModelTestMessage(""); }} required /></label><label>显示名称<input value={modelName} onChange={(event) => setModelName(event.target.value)} required /></label>{modelTestMessage && <small className={modelVerified ? "kppt-model-test-success" : "kppt-model-test-error"}>{modelTestMessage}</small>}<div className="kppt-admin-form-actions"><AsyncButton className="zc-secondary" type="button" loading={modelTesting} onClick={() => void testModelConnectivity()} disabled={modelTesting || !modelId.trim()}>{modelTesting ? "测试中（最长 40 秒）" : "测试连通性"}</AsyncButton><button className="zc-secondary" type="button" onClick={() => setModelProvider(null)} disabled={modelTesting || busy}>取消</button><AsyncButton className="zc-primary" type="submit" loading={busy} disabled={modelTesting || !modelVerified || !modelName.trim()}>保存并启用</AsyncButton></div></form>}</div></article>) : <AssetEmptyState className="kppt-admin-empty-state" title="暂无模型供应商" description="先添加供应商，再测试并配置模型。" />}</div></>}
    </main></div>{templateDetail && <div className="kppt-template-detail-backdrop" role="presentation" onMouseDown={closeTemplateDetail}><section className="kppt-template-detail-modal" role="dialog" aria-modal="true" aria-label={`${templateDetail.name}模板详情`} onMouseDown={(event) => event.stopPropagation()}><header><div><span>系统模板详情</span><h2>{templateDetail.name}</h2><p>{templateDetail.original_filename}</p></div><button className="zc-icon" type="button" aria-label="关闭模板详情" onClick={closeTemplateDetail}><X size={18} /></button></header><div className="kppt-template-detail-body"><aside className="kppt-template-detail-thumbs"><strong>页面预览 <small>{detailFiles.length || templateDetail.page_count || 0} 页</small></strong>{detailFiles.length ? detailFiles.map((file, index) => <button className={templatePreviewIndex === index ? "is-active" : ""} type="button" key={file} onClick={() => setTemplatePreviewIndex(index)}><img src={templateAssetUrl(templateDetail.id, file)} alt={`第 ${index + 1} 页`} /><span>{index + 1}</span></button>) : <p>{templateDetailLoading ? "正在加载页面预览…" : "暂无页面预览"}</p>}</aside><main className="kppt-template-detail-canvas">{detailCurrentFile ? <img src={templateAssetUrl(templateDetail.id, detailCurrentFile)} alt={`${templateDetail.name}第 ${templatePreviewIndex + 1} 页`} /> : <div><LayoutTemplate size={32} /><strong>{templateDetailLoading ? "正在读取模板详情" : templateDetail.error || "暂无可预览页面"}</strong></div>}</main><aside className="kppt-template-detail-summary"><section><span>解析状态</span><strong className={`kppt-template-detail-state kppt-template-detail-state-${templateDetail.status}`}>{templateStatusLabel(templateDetail)}</strong></section><section><span>页面数量</span><strong>{templateDetail.page_count || detailFiles.length || 0} 页</strong></section><section><span>最近更新</span><strong>{formatDate(templateDetail.updated_at)}</strong></section>{detailProgress.message && templateDetail.status !== "ready" && <section><span>处理进度</span><p>{detailProgress.message}</p></section>}{detailColors.length > 0 && <section><span>主要配色</span><div className="kppt-template-color-list">{detailColors.map((color) => <i key={color} title={color} style={{ backgroundColor: color }} />)}</div></section>}{detailFonts.length > 0 && <section><span>字体</span><p>{detailFonts.join("、")}</p></section>}<section><span>源文件</span><p>{templateDetail.original_filename}</p></section></aside></div></section></div>}</section>;
}
