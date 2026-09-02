import { Dispatch, FormEvent, ReactElement, ReactNode, SetStateAction, useCallback, useEffect, useMemo, useState } from "react";
import { PresentationEditor } from "./PresentationEditor";
import { DocEditorPage } from "./DocEditorPage";
import { CreativeWorkspace } from "./CreativeWorkspace";
import { AdminRouteTab, navigate, parseRoute, pathForNav } from "./routes";
import { PromptsPage as AssetPromptsPage, TemplatesPage as AssetTemplatesPage } from "./AssetPages";
import { AdminPage as AssetAdminPage } from "./AdminPage";
import { ReplicaProjectCard as AssetReplicaProjectCard } from "./ProjectsPage";
import { AssetEmptyState, AsyncButton, NoticeHost, PageRangeSelect, UploadButton } from "./ui";
import { useTheme } from "./theme";
import type { Artifact, Job, JobEvent, JobStatus, ModalState, NavKey, Project, ProjectMaterial, PromptPreset, PromptPresetSlide, PromptSnippet, Provider, ProviderModel, Skill, Template, User } from "./appTypes";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  ChevronDown,
  Copy,
  Download,
  Edit3,
  Eye,
  FileDown,
  FileStack,
  LayoutGrid,
  LayoutTemplate,
  ListFilter,
  List,
  LoaderCircle,
  LogIn,
  LogOut,
  Menu,
  MoreHorizontal,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  Plus,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Upload,
  UserPlus,
  UserRound,
  Users,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";

const statusLabel: Record<JobStatus, string> = {
  queued: "等待执行",
  running: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
  cancelled: "已中止",
};

const workbenchStages = ["需求梳理", "大纲设计", "选择模板", "生成 PPT", "预览精修"];
type ModelStatus = { configured: boolean; model_id: string | null; provider_display_name: string | null; message: string };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "请求失败，请稍后重试。");
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function promptPresetTopic(snippet: PromptSnippet): string {
  const topic = (snippet.preset?.requirements as { topic?: unknown } | undefined)?.topic;
  return typeof topic === "string" && topic.trim() ? topic.trim() : snippet.name.trim();
}

function artifactUrl(jobId: string, artifactId: string): string {
  return `/api/v1/projects/${jobId.split(":")[0]}/jobs/${jobId.split(":")[1]}/artifacts/${artifactId}/download`;
}

const emptyPromptPreset = (): PromptPreset => ({
  requirements: { scenario: "", audience: "", page_range: "8-10 页", style: "", objective: "" },
  outline: [],
  notes_enabled: true,
});

function presetOutlineFromText(value: string): PromptPresetSlide[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [title = "", purpose = "", kind = "内容页", notes = ""] = line.split("|").map((part) => part.trim());
    return { title, purpose, content: "", kind: kind || "内容页", notes };
  }).filter((slide) => slide.title);
}

function normalizePresetSlides(preset: PromptPreset): PromptPresetSlide[] {
  const rawOutline = (preset as PromptPreset & { outline?: unknown }).outline;
  const outline = typeof rawOutline === "string" ? presetOutlineFromText(rawOutline) : Array.isArray(rawOutline) ? rawOutline : [];
  return outline.length
    ? outline.map((slide) => ({
      title: String(slide.title || ""),
      purpose: String(slide.purpose || ""),
      content: String(slide.content || ""),
      kind: String(slide.kind || "内容页"),
      notes: String(slide.notes || ""),
    }))
    : [];
}

function presetPageCountForRange(value: unknown): number {
  const text = String(value || "8-10 页").trim();
  const range = text.match(/(\d+)\s*[-至]\s*(\d+)/);
  if (range) return Math.max(1, Number(range[2]));
  const above = text.match(/(\d+)\s*页以上/);
  return above ? Math.max(1, Number(above[1])) : 8;
}

function blankPresetSlide(): PromptPresetSlide {
  return { title: "", purpose: "", content: "", kind: "内容页", notes: "" };
}

function ensurePresetSlideCount(slides: PromptPresetSlide[], count: number): PromptPresetSlide[] {
  const next = [...slides];
  const isBlank = (slide: PromptPresetSlide) => !slide.title.trim() && !slide.purpose.trim() && !slide.content.trim() && !slide.notes.trim();
  if (next.length > count && next.slice(count).every(isBlank)) return next.slice(0, count);
  while (next.length < count) next.push(blankPresetSlide());
  return next;
}

function presetRequirementsComplete(requirements: PromptPreset["requirements"] | undefined): boolean {
  return Boolean(requirements?.scenario?.trim() && requirements?.audience?.trim() && requirements?.page_range?.trim() && requirements?.style?.trim() && requirements?.objective?.trim());
}

function PromptPresetOutlineEditor(props: {
  slides: PromptPresetSlide[];
  busy: boolean;
  skeletonCount: number;
  onEdit: (index: number, key: keyof PromptPresetSlide, value: string) => void;
  onMove: (index: number, direction: -1 | 1) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}): ReactElement {
  return <section className="zc-preset-form zc-preset-outline-form">
    <div className="zc-preset-section-heading"><div><strong>默认大纲</strong><small>按页面逐一填写，选择预设后会带入大纲设计步骤。</small></div><button className="zc-secondary" type="button" onClick={props.onAdd} disabled={props.busy}><Plus size={14} />新增页面</button></div>
    <div className="zc-preset-outline-list">
      {props.busy
        ? Array.from({ length: Math.max(1, props.skeletonCount) }, (_, index) => <article className="zc-preset-slide-skeleton" key={`preset-skeleton-${index}`} aria-hidden="true">
            <span className="zc-skeleton-block zc-preset-skeleton-number" />
            <div>
              <span className="zc-skeleton-block zc-preset-skeleton-title" />
              <span className="zc-skeleton-block zc-preset-skeleton-line" />
              <span className="zc-skeleton-block zc-preset-skeleton-line zc-preset-skeleton-line-short" />
              <span className="zc-skeleton-block zc-preset-skeleton-notes" />
            </div>
          </article>)
        : props.slides.map((slide, index) => <article className="zc-preset-slide-card" key={`preset-slide-${index}`}>
            <div className="zc-preset-slide-number">{String(index + 1).padStart(2, "0")}</div>
            <div className="zc-preset-slide-fields">
              <label><span>页面标题</span><input value={slide.title} onChange={(event) => props.onEdit(index, "title", event.target.value)} placeholder="例如：现状与关键挑战" /></label>
              <label><span>建议表现形式</span><input value={slide.kind} onChange={(event) => props.onEdit(index, "kind", event.target.value)} placeholder="例如：数据图表" /></label>
              <label><span>本页目标</span><textarea rows={2} value={slide.purpose} onChange={(event) => props.onEdit(index, "purpose", event.target.value)} placeholder="希望观众理解什么" /></label>
              <label><span>本页内容</span><textarea rows={3} value={slide.content} onChange={(event) => props.onEdit(index, "content", event.target.value)} placeholder="填写本页需要呈现的核心信息、数据或要点" /></label>
              <label><span>讲解重点</span><textarea rows={2} value={slide.notes} onChange={(event) => props.onEdit(index, "notes", event.target.value)} placeholder="补充讲解顺序、口径或提醒" /></label>
            </div>
            <div className="zc-preset-slide-actions"><button type="button" aria-label="上移页面" title="上移页面" onClick={() => props.onMove(index, -1)} disabled={index === 0}>↑</button><button type="button" aria-label="下移页面" title="下移页面" onClick={() => props.onMove(index, 1)} disabled={index === props.slides.length - 1}>↓</button><button type="button" aria-label="删除页面" title="删除页面" onClick={() => props.onRemove(index)} disabled={props.slides.length <= 1}><X size={14} /></button></div>
          </article>)}
    </div>
  </section>;
}

export function ProductApp() {
  const [user, setUser] = useState<User | null>(null);
  const [authResolved, setAuthResolved] = useState(false);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [nav, setNav] = useState<NavKey>("projects");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { darkMode, setDarkMode } = useTheme();
  const [searchOpen, setSearchOpen] = useState(false);
  const [globalQuery, setGlobalQuery] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [draftSkillId, setDraftSkillId] = useState("ppt-master");
  const [draftModeId, setDraftModeId] = useState("");
  const [jobsByProject, setJobsByProject] = useState<Record<string, Job[]>>({});
  const [materialsByProject, setMaterialsByProject] = useState<Record<string, ProjectMaterial[]>>({});
  const [pendingMaterialFiles, setPendingMaterialFiles] = useState<File[]>([]);
  const [materialUploading, setMaterialUploading] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [snippets, setSnippets] = useState<PromptSnippet[]>([]);
  const [adminTemplates, setAdminTemplates] = useState<Template[]>([]);
  const [adminSnippets, setAdminSnippets] = useState<PromptSnippet[]>([]);
  const [adminUsers, setAdminUsers] = useState<User[]>([]);
  const [adminProviders, setAdminProviders] = useState<Provider[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [selectedPromptPreset, setSelectedPromptPreset] = useState<PromptSnippet | null>(null);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectView, setProjectView] = useState<"grid" | "list">("grid");
  const [templateQuery, setTemplateQuery] = useState("");
  const [promptQuery, setPromptQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [targetProject, setTargetProject] = useState<Project | null>(null);
  const [targetTemplate, setTargetTemplate] = useState<Template | null>(null);
  const [targetSnippet, setTargetSnippet] = useState<PromptSnippet | null>(null);
  const [editorName, setEditorName] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [editorCategory, setEditorCategory] = useState("个人");
  const [editorPreset, setEditorPreset] = useState<PromptPreset>(emptyPromptPreset());
  const [editorSlides, setEditorSlides] = useState<PromptPresetSlide[]>([]);
  const [isGeneratingPresetOutline, setIsGeneratingPresetOutline] = useState(false);
  const [editorOutlineNotice, setEditorOutlineNotice] = useState("");
  const [templateUploading, setTemplateUploading] = useState(false);
  const [retryingTemplateId, setRetryingTemplateId] = useState<string | null>(null);
  const [projectDeleting, setProjectDeleting] = useState(false);
  const [assetAction, setAssetAction] = useState<string | null>(null);
  const token = new URLSearchParams(window.location.search).get("invite");
  const [locationKey, setLocationKey] = useState(`${window.location.pathname}${window.location.search}`);
  const route = useMemo(() => parseRoute(locationKey), [locationKey]);

  useEffect(() => {
    const handlePopState = () => setLocationKey(`${window.location.pathname}${window.location.search}`);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (route.kind === "projects") setNav("projects");
    if (route.kind === "templates") setNav("templates");
    if (route.kind === "prompts") setNav("prompts");
    if (route.kind === "admin") setNav("admin");
    if (route.kind === "workspace") {
      setActiveProjectId(route.projectId);
      setSelectedJobId(route.jobId);
    } else {
      setActiveProjectId(null);
      setSelectedJobId(null);
    }
  }, [route]);

  useEffect(() => {
    if (route.kind !== "workspace" || !projects.some((project) => project.id === route.projectId)) return;
    setActiveProjectId(route.projectId);
    setSelectedJobId(route.jobId);
    void loadMaterials(route.projectId).catch(() => setNotice("无法载入项目材料。"));
  }, [projects, route]);

  const loadProjects = useCallback(async () => {
    const next = await request<Project[]>("/api/v1/projects");
    setProjects(next);
    const jobs = await Promise.all(next.map(async (project) => [project.id, await request<Job[]>(`/api/v1/projects/${project.id}/jobs`)] as const));
    setJobsByProject(Object.fromEntries(jobs));
  }, []);

  const loadTemplates = useCallback(async () => setTemplates(await request<Template[]>("/api/v1/templates")), []);
  const loadSnippets = useCallback(async () => setSnippets(await request<PromptSnippet[]>("/api/v1/prompt-snippets")), []);
  const loadSkills = useCallback(async () => setSkills(await request<Skill[]>("/api/v1/skills")), []);
  const loadModelStatus = useCallback(async () => setModelStatus(await request<ModelStatus>("/api/v1/model-status")), []);
  const loadMaterials = useCallback(async (projectId: string) => {
    const materials = await request<ProjectMaterial[]>(`/api/v1/projects/${projectId}/materials`);
    setMaterialsByProject((current) => ({ ...current, [projectId]: materials }));
    return materials;
  }, []);
  const loadAdminData = useCallback(async () => {
    const [nextTemplates, nextSnippets, nextUsers, nextProviders] = await Promise.all([
      request<Template[]>("/api/v1/admin/system-templates"),
      request<PromptSnippet[]>("/api/v1/admin/system-prompts"),
      request<User[]>("/api/v1/admin/users"),
      request<Provider[]>("/api/v1/admin/providers"),
    ]);
    setAdminTemplates(nextTemplates);
    setAdminSnippets(nextSnippets);
    setAdminUsers(nextUsers);
    setAdminProviders(nextProviders);
  }, []);

  useEffect(() => {
    request<User>("/api/v1/auth/me")
      .then(async (currentUser) => {
        setUser(currentUser);
        await Promise.all([loadProjects(), loadTemplates(), loadSnippets(), loadModelStatus(), loadSkills()]);
      })
      .catch(() => undefined)
      .finally(() => setAuthResolved(true));
  }, [loadModelStatus, loadProjects, loadSkills, loadSnippets, loadTemplates]);

  useEffect(() => {
    if (!user || nav !== "templates") return;
    void loadTemplates();
    const timer = window.setInterval(() => void loadTemplates(), 5000);
    return () => window.clearInterval(timer);
  }, [loadTemplates, nav, user]);

  useEffect(() => {
    if (!user || nav !== "admin" || user.role !== "super_admin") return;
    void loadAdminData().catch(() => setNotice("无法载入平台管理数据。"));
  }, [loadAdminData, nav, user]);

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;
  const activeJobs = activeProjectId ? jobsByProject[activeProjectId] ?? [] : [];
  const activeJob = activeJobs.find((job) => job.id === selectedJobId) ?? activeJobs[0] ?? null;
  const workingJob = activeJobs.find((job) => job.status === "queued" || job.status === "running") ?? null;
  const refinementBaseJob = activeJob?.target_slide_number && !activeJob.base_job_id
    ? activeJobs.find((job) => job.status === "succeeded" && !job.target_slide_number) ?? null
    : null;
  const previewSlides = useMemo(
    () => {
      const previewKinds = skills.find((skill) => skill.id === activeProject?.skill_id)?.frontend.preview_kinds ?? ["svg"];
      return artifacts.filter((artifact) => previewKinds.includes(artifact.kind)).sort((left, right) => left.filename.localeCompare(right.filename, undefined, { numeric: true }));
    },
    [artifacts, activeProject?.skill_id, skills],
  );
  const latestPptx = useMemo(
    () => artifacts.filter((artifact) => artifact.kind === "pptx").sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null,
    [artifacts],
  );
  const readyTemplates = templates.filter((template) => template.status === "ready" && template.is_active);
  const isPlatformAdmin = user?.role === "super_admin";
  const globalMatches = useMemo(() => {
    const query = globalQuery.trim().toLowerCase();
    if (!query) return [];
    return [
      ...projects.filter((project) => project.title.toLowerCase().includes(query)).map((project) => ({ type: "项目", id: project.id, label: project.title })),
      ...templates.filter((template) => template.name.toLowerCase().includes(query)).map((template) => ({ type: "模板", id: template.id, label: template.name })),
      ...snippets.filter((snippet) => (!snippet.skill_id || snippet.skill_id === draftSkillId) && `${snippet.name}${snippet.content}`.toLowerCase().includes(query)).map((snippet) => ({ type: "预设", id: snippet.id, label: snippet.name })),
    ].slice(0, 8);
  }, [globalQuery, projects, snippets, templates]);

  useEffect(() => {
    if (!activeProject || !activeJob) {
      setArtifacts([]);
      setEvents([]);
      return;
    }
    let disposed = false;
    const prefix = `/api/v1/projects/${activeProject.id}/jobs/${activeJob.id}`;
    void Promise.all([request<Artifact[]>(`${prefix}/artifacts`), request<JobEvent[]>(`${prefix}/events`)])
      .then(([nextArtifacts, nextEvents]) => {
        if (!disposed) {
          setArtifacts(nextArtifacts);
          setEvents(nextEvents);
        }
      })
      .catch(() => undefined);
    const stream = new EventSource(`${prefix}/events/stream`);
    stream.addEventListener("job-event", (raw) => {
      const incoming = JSON.parse((raw as MessageEvent).data) as JobEvent;
      setEvents((current) => current.some((event) => event.id === incoming.id) ? current : [...current, incoming]);
      if (incoming.event_type === "status" || incoming.event_type === "artifact") {
        void request<Artifact[]>(`${prefix}/artifacts`).then(setArtifacts).catch(() => undefined);
        void request<Job[]>(`/api/v1/projects/${activeProject.id}/jobs`).then((jobs) => {
          setJobsByProject((current) => ({ ...current, [activeProject.id]: jobs }));
        }).catch(() => undefined);
      }
    });
    stream.addEventListener("complete", () => stream.close());
    return () => {
      disposed = true;
      stream.close();
    };
  }, [activeJob?.id, activeProject?.id]);

  async function submitAuth(event: FormEvent) {
    event.preventDefault();
    setNotice("");
    try {
      if (token) {
        await request<User>("/api/v1/auth/register", { method: "POST", body: JSON.stringify({ token, username, display_name: displayName, password }) });
        setNotice("账号已创建，请使用新账号登录。");
        return;
      }
      setUser(await request<User>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }));
      await Promise.all([loadProjects(), loadTemplates(), loadSnippets()]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "登录失败，请稍后重试。");
    }
  }

  async function createProject(title: string, promptSnippetId?: string | null, skillId?: string, mode?: string | null): Promise<Project> {
    const project = await request<Project>("/api/v1/projects", { method: "POST", body: JSON.stringify({ title, skill_id: skillId || "ppt-master", mode: mode || null, prompt_snippet_id: promptSnippetId || null }) });
    setProjects((current) => [project, ...current]);
    setJobsByProject((current) => ({ ...current, [project.id]: [] }));
    setMaterialsByProject((current) => ({ ...current, [project.id]: [] }));
    return project;
  }

  async function uploadMaterialFiles(projectId: string, files: File[]): Promise<void> {
    if (!files.length) return;
    setMaterialUploading(true);
    try {
      const uploaded: ProjectMaterial[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const response = await fetch(`/api/v1/projects/${projectId}/materials`, { method: "POST", credentials: "include", body: form });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `${file.name} 上传失败。`);
        uploaded.push(await response.json() as ProjectMaterial);
      }
      setMaterialsByProject((current) => ({ ...current, [projectId]: [...(current[projectId] ?? []), ...uploaded] }));
      setNotice(`已添加 ${uploaded.length} 份材料，生成时会自动读取。`);
    } finally {
      setMaterialUploading(false);
    }
  }

  async function deleteMaterial(projectId: string, materialId: string): Promise<void> {
    await request<void>(`/api/v1/projects/${projectId}/materials/${materialId}`, { method: "DELETE" });
    setMaterialsByProject((current) => ({ ...current, [projectId]: (current[projectId] ?? []).filter((item) => item.id !== materialId) }));
  }

  function startDraft(seed = "") {
    setDraft(seed);
    setSelectedTemplateId(null);
    setSelectedPromptPreset(null);
    setActiveProjectId(null);
    setSelectedJobId(null);
    setNotice("");
    setPendingMaterialFiles([]);
    setNav("projects");
    navigate(pathForNav("projects"));
  }

  async function openProject(project: Project) {
    setActiveProjectId(project.id);
    setSelectedJobId(null);
    setDraft((jobsByProject[project.id]?.[0]?.prompt) || project.title);
    setSelectedTemplateId(null);
    setNav("projects");
    navigate(`/workspace/${encodeURIComponent(project.id)}`);
    setNotice("");
    void loadMaterials(project.id).catch(() => setNotice("无法载入项目材料。"));
  }

  async function startGeneration(promptOverride?: string, templateOverride?: string | null, baseJobId?: string | null, targetSlideNumber?: number | null, conversationMessage?: string, clientMessageId?: string, resumeFromCancelled = false): Promise<Job | null> {
    const content = (promptOverride ?? draft).trim();
    if (!content || isSubmitting || workingJob) return null;
    setIsSubmitting(true);
    setNotice("");
    try {
      const currentModelStatus = await request<ModelStatus>("/api/v1/model-status");
      setModelStatus(currentModelStatus);
      if (!currentModelStatus.configured) {
        setNotice(currentModelStatus.message);
        return null;
      }
      let project = activeProject;
      if (!project) project = await createProject(content.slice(0, 48), selectedPromptPreset?.id, draftSkillId);
      const job = resumeFromCancelled && baseJobId
        ? await request<Job>(`/api/v1/projects/${project.id}/jobs/${baseJobId}/resume`, { method: "POST" })
        : await request<Job>(`/api/v1/projects/${project.id}/jobs`, {
          method: "POST",
          body: JSON.stringify({ prompt: content, template_id: activeJobs.length || baseJobId ? null : (templateOverride ?? selectedTemplateId), base_job_id: baseJobId || null, resume_from_cancelled: false, target_slide_number: targetSlideNumber || null, conversation_message: conversationMessage || null, client_message_id: clientMessageId || null }),
        });
      setJobsByProject((current) => ({ ...current, [project!.id]: [job, ...(current[project!.id] ?? [])] }));
      setActiveProjectId(project.id);
      navigate(`/workspace/${encodeURIComponent(project.id)}`);
      setSelectedJobId(job.id);
      setShowLogs(true);
      await loadProjects();
      return job;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建生成任务失败。");
      return null;
    } finally {
      setIsSubmitting(false);
    }
  }

  async function beginWorkspace() {
    const content = draft.trim();
    if (!content || isSubmitting) return;
    setIsSubmitting(true);
    setNotice("");
    try {
      const appliedPreset = selectedPromptPreset;
      const modes = skills.find((skill) => skill.id === draftSkillId)?.frontend.modes ?? [];
      const mode = modes.length ? (modes.find((item) => item.id === draftModeId) ?? modes[0]).id : null;
      const project = await createProject(content.slice(0, 48), appliedPreset?.id, draftSkillId, mode);
      if (appliedPreset) {
        setSnippets((current) => current.map((snippet) => (
          snippet.id === appliedPreset.id
            ? { ...snippet, used_count: snippet.used_count + 1 }
            : snippet
        )));
      }
      await uploadMaterialFiles(project.id, pendingMaterialFiles);
      setPendingMaterialFiles([]);
      setSelectedPromptPreset(null);
      setActiveProjectId(project.id);
      navigate(`/workspace/${encodeURIComponent(project.id)}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建项目失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function cancelJob() {
    if (!activeProject || !workingJob) return;
    try {
      const next = await request<Job>(`/api/v1/projects/${activeProject.id}/jobs/${workingJob.id}/cancel`, { method: "POST" });
      setJobsByProject((current) => ({ ...current, [activeProject.id]: (current[activeProject.id] ?? []).map((job) => job.id === next.id ? next : job) }));
      setNotice(next.status === "cancelled" ? "任务已中止。" : "正在中止当前任务…");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "中止任务失败。");
    }
  }

  function returnToBaseJob(baseJobId: string): void {
    const baseJob = activeJobs.find((job) => job.id === baseJobId);
    if (!baseJob) {
      setNotice("原演示文稿暂时不可用，请刷新项目后重试。" );
      return;
    }
    setSelectedJobId(baseJob.id);
    setPreviewIndex(0);
    setShowLogs(false);
    setNotice("");
  }

  function selectPromptPreset(snippet: PromptSnippet): void {
    setSelectedPromptPreset(snippet);
    setDraft(promptPresetTopic(snippet));
    setNav("projects");
    setActiveProjectId(null);
    setSelectedJobId(null);
    setNotice("");
    navigate(pathForNav("projects"));
  }

  async function removeProject() {
    if (!targetProject) return;
    if (projectDeleting) return;
    setProjectDeleting(true);
    try {
      await request<void>(`/api/v1/projects/${targetProject.id}`, { method: "DELETE" });
      setProjects((current) => current.filter((project) => project.id !== targetProject.id));
      setJobsByProject((current) => {
        const next = { ...current };
        delete next[targetProject.id];
        return next;
      });
      if (activeProjectId === targetProject.id) startDraft();
      setModal(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除项目失败。");
      setModal(null);
    } finally {
      setProjectDeleting(false);
    }
  }

  async function uploadTemplate(file: File) {
    if (!file) return;
    setTemplateUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/v1/templates/import", { method: "POST", credentials: "include", body: form });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "模板上传失败。");
      const template = await response.json() as Template;
      setTemplates((current) => [template, ...current]);
      setNotice("模板已上传，正在提取版式和主题信息。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "模板上传失败。");
    } finally {
      setTemplateUploading(false);
    }
  }

  async function saveTemplateName() {
    if (!targetTemplate || !editorName.trim()) return;
    if (assetAction) return;
    setAssetAction(`template-rename-${targetTemplate.id}`);
    try {
      const next = await request<Template>(`/api/v1/templates/${targetTemplate.id}`, { method: "PATCH", body: JSON.stringify({ name: editorName.trim() }) });
      setTemplates((current) => current.map((template) => template.id === next.id ? next : template));
      setModal(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "模板重命名失败。");
    } finally {
      setAssetAction(null);
    }
  }

  async function retryTemplate(template: Template): Promise<void> {
    if (retryingTemplateId) return;
    setRetryingTemplateId(template.id);
    try {
      const next = await request<Template>(`/api/v1/templates/${template.id}/retry`, { method: "POST" });
      setTemplates((current) => current.map((item) => item.id === next.id ? next : item));
      setNotice("模板已重新提交分析，请稍候。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "重新分析模板失败。");
    } finally {
      setRetryingTemplateId(null);
    }
  }

  async function deleteTemplate(template: Template) {
    if (assetAction) return;
    setAssetAction(`template-delete-${template.id}`);
    try {
      await request<void>(`/api/v1/templates/${template.id}`, { method: "DELETE" });
      setTemplates((current) => current.filter((item) => item.id !== template.id));
      setModal(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除模板失败。");
    } finally {
      setAssetAction(null);
    }
  }

  async function saveSnippet() {
    if (!editorName.trim()) return;
    if (assetAction) return;
    setAssetAction(`snippet-save-${targetSnippet?.id || "new"}`);
    try {
      const payload = {
        name: editorName.trim(),
        content: editorContent.trim(),
        category: editorCategory.trim() || "个人",
        preset: { ...editorPreset, outline: editorSlides.filter((slide) => slide.title.trim()).map((slide) => ({ ...slide, title: slide.title.trim() })) },
      };
      const next = targetSnippet
        ? await request<PromptSnippet>(`/api/v1/prompt-snippets/${targetSnippet.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await request<PromptSnippet>("/api/v1/prompt-snippets", { method: "POST", body: JSON.stringify(payload) });
      setSnippets((current) => targetSnippet ? current.map((item) => item.id === next.id ? next : item) : [next, ...current]);
      setModal(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存预设失败。");
    } finally {
      setAssetAction(null);
    }
  }

  async function deleteSnippet() {
    if (!targetSnippet) return;
    if (assetAction) return;
    setAssetAction(`snippet-delete-${targetSnippet.id}`);
    try {
      await request<void>(`/api/v1/prompt-snippets/${targetSnippet.id}`, { method: "DELETE" });
      setSnippets((current) => current.filter((item) => item.id !== targetSnippet.id));
      setModal(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除预设失败。");
    } finally {
      setAssetAction(null);
    }
  }

  function openPromptEditor(snippet: PromptSnippet | null): void {
    setTargetSnippet(snippet);
    setEditorName(snippet?.name || "");
    setEditorContent(snippet?.content || "");
    setEditorCategory(snippet?.category || "个人");
    setEditorOutlineNotice("");
    const preset = snippet?.preset || emptyPromptPreset();
    setEditorPreset({ ...emptyPromptPreset(), ...preset, requirements: { ...emptyPromptPreset().requirements, ...preset.requirements } });
    const slides = normalizePresetSlides(preset);
    setEditorSlides(ensurePresetSlideCount(slides, presetPageCountForRange(preset.requirements?.page_range)));
    setModal("prompt-editor");
  }

  function updateEditorPageRange(value: string): void {
    setEditorPreset((current) => ({ ...current, requirements: { ...current.requirements, page_range: value } }));
    setEditorSlides((current) => ensurePresetSlideCount(current, presetPageCountForRange(value)));
  }

  async function generatePresetOutline(): Promise<void> {
    const requirements = editorPreset.requirements || {};
    if (!presetRequirementsComplete(requirements)) {
      setEditorOutlineNotice("请先填写使用场景、目标受众、页数范围、整体风格和核心目标。");
      return;
    }
    setIsGeneratingPresetOutline(true);
    setEditorOutlineNotice("");
    try {
      const outline = await request<PromptPresetSlide[]>("/api/v1/prompt-snippets/generate-outline", { method: "POST", body: JSON.stringify({ requirements }) });
      setEditorSlides(ensurePresetSlideCount(outline.map((slide) => ({ ...blankPresetSlide(), ...slide })), presetPageCountForRange(requirements.page_range)));
      setEditorOutlineNotice("已生成默认大纲草稿，你可以继续逐页调整。");
    } catch (error) {
      setEditorOutlineNotice(error instanceof Error ? error.message : "大纲生成失败，请稍后重试。");
    } finally {
      setIsGeneratingPresetOutline(false);
    }
  }

  function updateEditorSlide(index: number, key: keyof PromptPresetSlide, value: string): void {
    setEditorSlides((current) => current.map((slide, slideIndex) => slideIndex === index ? { ...slide, [key]: value } : slide));
  }

  function moveEditorSlide(index: number, direction: -1 | 1): void {
    setEditorSlides((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function logout() {
    await request<void>("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
  }

  if (route.kind === "editor") return <PresentationEditor projectId={route.projectId} jobId={route.jobId} />;
  if (route.kind === "doc-editor" && user) return <DocEditorPage projectId={route.projectId} docKind={route.docKind} />;

  // While the browser session is still being verified, render nothing instead
  // of the login screen so full-page navigation never flashes it.
  if (!user && !authResolved) return null;

  if (!user) {
    return <><NoticeHost message={notice} onClose={() => setNotice("")} /><main className="zc-auth"><section className="zc-auth-card"><div className="zc-logo"><img src="/logo-128.png" alt="" /><span>智创AI助手</span></div><h1>{token ? "创建工作区账号" : "登录智创AI助手"}</h1><p>从一个想法，到一份能交付的作品</p><form onSubmit={submitAuth}><label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} required autoComplete="username" /></label>{token && <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label>}<label>密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={8} required autoComplete={token ? "new-password" : "current-password"} /></label><button className="zc-primary" type="submit">{token ? <UserPlus size={17} /> : <LogIn size={17} />}{token ? "完成注册" : "登录"}</button></form></section></main></>;
  }

  if (route.kind === "workspace" && activeProject?.id === route.projectId) {
    return <><NoticeHost message={notice} onClose={() => setNotice("")} /><CreativeWorkspace project={activeProject!} mode={activeProject!.mode} job={activeJob} workingJob={workingJob} skill={skills.find((skill) => skill.id === activeProject!.skill_id) ?? null} templates={readyTemplates} artifacts={artifacts} events={events} materials={materialsByProject[activeProject!.id] ?? []} materialUploading={materialUploading} onUploadMaterials={(files) => void uploadMaterialFiles(activeProject!.id, files)} onDeleteMaterial={(materialId) => void deleteMaterial(activeProject!.id, materialId)} initialTemplateId={selectedTemplateId} baseJobId={refinementBaseJob?.id ?? null} onBack={() => startDraft()} onGenerate={(prompt, templateId, baseJobId, targetSlideNumber, conversationMessage, clientMessageId, resumeFromCancelled) => startGeneration(prompt, templateId, baseJobId, targetSlideNumber, conversationMessage, clientMessageId, resumeFromCancelled)} onCancel={() => void cancelJob()} onReturnToBase={returnToBaseJob} /></>;
  }

  const replicaPageBody = nav === "templates"
    ? <AssetTemplatesPage templates={templates} query={templateQuery} setQuery={setTemplateQuery} uploading={templateUploading} notice={notice} onUpload={uploadTemplate} onUse={(template) => { startDraft(); setSelectedTemplateId(template.id); }} onRename={(template) => { setTargetTemplate(template); setEditorName(template.name); setModal("template-rename"); }} onDelete={(template) => { setTargetTemplate(template); setModal("template-delete"); }} onRetry={retryTemplate} retryingTemplateId={retryingTemplateId} />
    : nav === "prompts"
      ? <AssetPromptsPage snippets={snippets} query={promptQuery} setQuery={setPromptQuery} notice={notice} onUse={selectPromptPreset} onCreate={() => openPromptEditor(null)} onEdit={openPromptEditor} onDelete={(snippet) => { setTargetSnippet(snippet); setModal("prompt-delete"); }} skillId={draftSkillId} />
      : nav === "admin" && isPlatformAdmin
         ? <AssetAdminPage initialTab={route.kind === "admin" ? route.tab : "templates"} onTabChange={(tab) => navigate(`/admin/${tab}`)} templates={adminTemplates} snippets={adminSnippets} users={adminUsers} providers={adminProviders} onRefresh={loadAdminData} />
         : null;

  const renderAssetModal = () => <>
    {modal === "template-rename" && <><h2>重命名模板</h2><label>模板名称<input value={editorName} onChange={(event) => setEditorName(event.target.value)} autoFocus /></label><div className="zc-modal-actions"><button className="zc-secondary" onClick={() => setModal(null)} disabled={Boolean(assetAction)}>取消</button><AsyncButton className="zc-primary" onClick={() => void saveTemplateName()} loading={Boolean(assetAction)}>保存</AsyncButton></div></>}
    {modal === "template-delete" && <><h2>删除这个模板？</h2><p>“{targetTemplate?.name}”将从你的模板库中移除，且无法恢复。</p><div className="zc-modal-actions"><button className="zc-secondary" onClick={() => setModal(null)} disabled={Boolean(assetAction)}>取消</button><AsyncButton className="zc-danger" onClick={() => targetTemplate && void deleteTemplate(targetTemplate)} loading={Boolean(assetAction)}><Trash2 size={15} />确认删除</AsyncButton></div></>}
    {modal === "prompt-editor" && <><h2>{targetSnippet ? "编辑创作预设" : "新建创作预设"}</h2><p className="zc-modal-description">预设会在首页选择后，填入需求梳理和大纲设计；主题始终以首页输入为准。</p><label>预设名称<input value={editorName} onChange={(event) => setEditorName(event.target.value)} autoFocus /></label><label>分类<input value={editorCategory} onChange={(event) => setEditorCategory(event.target.value)} /></label><div className="zc-preset-form"><div className="zc-preset-section-heading"><div><strong>默认需求</strong><small>填写完整后，可让大模型先生成一版默认大纲。</small></div><button className="zc-secondary zc-preset-ai-button" type="button" onClick={() => void generatePresetOutline()} disabled={!presetRequirementsComplete(editorPreset.requirements) || isGeneratingPresetOutline || Boolean(assetAction)}><WandSparkles size={14} />{isGeneratingPresetOutline ? "生成中…" : "AI 生成默认大纲"}</button></div><div className="zc-preset-grid"><label>使用场景<input value={editorPreset.requirements?.scenario || ""} onChange={(event) => setEditorPreset((current) => ({ ...current, requirements: { ...current.requirements, scenario: event.target.value } }))} /></label><label>目标受众<input value={editorPreset.requirements?.audience || ""} onChange={(event) => setEditorPreset((current) => ({ ...current, requirements: { ...current.requirements, audience: event.target.value } }))} /></label><label>页数范围<PageRangeSelect value={editorPreset.requirements?.page_range || "8-10 页"} onChange={updateEditorPageRange} /></label><label>整体风格<input value={editorPreset.requirements?.style || ""} onChange={(event) => setEditorPreset((current) => ({ ...current, requirements: { ...current.requirements, style: event.target.value } }))} /></label><label className="is-wide">核心目标<textarea rows={3} value={editorPreset.requirements?.objective || ""} onChange={(event) => setEditorPreset((current) => ({ ...current, requirements: { ...current.requirements, objective: event.target.value } }))} /></label></div><label className="zc-preset-notes"><input type="checkbox" checked={editorPreset.notes_enabled !== false} onChange={(event) => setEditorPreset((current) => ({ ...current, notes_enabled: event.target.checked }))} />默认生成每页讲解词</label></div>{editorOutlineNotice && <small className="zc-preset-ai-notice">{editorOutlineNotice}</small>}<PromptPresetOutlineEditor busy={isGeneratingPresetOutline} skeletonCount={presetPageCountForRange(editorPreset.requirements?.page_range)} slides={editorSlides} onEdit={updateEditorSlide} onMove={moveEditorSlide} onAdd={() => setEditorSlides((current) => [...current, blankPresetSlide()])} onRemove={(index) => setEditorSlides((current) => current.length <= 1 ? current : current.filter((_, slideIndex) => slideIndex !== index))} /><label>附加要求<small>可选，会追加到需求梳理的核心目标。</small><textarea rows={3} value={editorContent} onChange={(event) => setEditorContent(event.target.value)} /></label><div className="zc-modal-actions"><button className="zc-secondary" onClick={() => setModal(null)} disabled={Boolean(assetAction)}>取消</button><AsyncButton className="zc-primary" onClick={() => void saveSnippet()} loading={Boolean(assetAction)} disabled={!editorName.trim() || isGeneratingPresetOutline}>保存预设</AsyncButton></div></>}
    {modal === "prompt-delete" && <><h2>删除这个预设？</h2><p>“{targetSnippet?.name}”将不再能用于新的创作和精修。</p><div className="zc-modal-actions"><button className="zc-secondary" onClick={() => setModal(null)} disabled={Boolean(assetAction)}>取消</button><AsyncButton className="zc-danger" onClick={() => void deleteSnippet()} loading={Boolean(assetAction)}><Trash2 size={15} />确认删除</AsyncButton></div></>}
  </>;

  if (["projects", "templates", "prompts", "admin"].includes(route.kind) && !activeProject) {
    return <><NoticeHost message={notice} onClose={() => setNotice("")} /><ReplicaDashboardShell
      user={user}
      activeNav={nav}
      pageBody={replicaPageBody}
      projects={projects}
      jobsByProject={jobsByProject}
      skills={skills}
      draftSkillId={draftSkillId}
      onDraftSkillChange={(skillId) => { setDraftSkillId(skillId); setDraftModeId(""); }}
      draftModeId={draftModeId}
      onDraftModeChange={setDraftModeId}
      templates={readyTemplates}
      snippets={snippets}
      pendingMaterialFiles={pendingMaterialFiles}
      onSelectMaterials={(files) => setPendingMaterialFiles((current) => [...current, ...files])}
      onRemovePendingMaterial={(index) => setPendingMaterialFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}
      materialUploading={materialUploading}
      draft={draft}
      setDraft={setDraft}
      selectedTemplateId={selectedTemplateId}
      setSelectedTemplateId={setSelectedTemplateId}
      isSubmitting={isSubmitting}
      darkMode={darkMode}
      setDarkMode={setDarkMode}
      searchOpen={searchOpen}
      setSearchOpen={setSearchOpen}
      globalQuery={globalQuery}
      setGlobalQuery={setGlobalQuery}
      globalMatches={globalMatches}
      sidebarCollapsed={sidebarCollapsed}
      setSidebarCollapsed={setSidebarCollapsed}
      sidebarOpen={sidebarOpen}
      setSidebarOpen={setSidebarOpen}
      isPlatformAdmin={isPlatformAdmin}
      onNavigate={(next) => { setNav(next); setActiveProjectId(null); navigate(pathForNav(next)); setNotice(""); setSidebarOpen(false); }}
      onCreate={() => startDraft()}
      onBegin={() => void beginWorkspace()}
      onOpen={openProject}
      onDelete={(project) => { setTargetProject(project); setModal("project-delete"); }}
      targetProject={targetProject}
      deleteOpen={modal === "project-delete"}
      deleteBusy={projectDeleting}
      onCloseDelete={() => setModal(null)}
      onConfirmDelete={() => void removeProject()}
      selectedPromptPreset={selectedPromptPreset}
      onSelectPromptPreset={selectPromptPreset}
      onClearPromptPreset={() => setSelectedPromptPreset(null)}
      onNotice={setNotice}
      notice={notice}
      onLogout={() => void logout()}
    />{modal && modal !== "project-delete" && <ModalFrame onClose={() => setModal(null)}>{renderAssetModal()}</ModalFrame>}</>;
  }

  // 未知路由或项目尚未载入时的兜底视图；正常路径由上方分支全部覆盖。
  return <><NoticeHost message={notice} onClose={() => setNotice("")} /><AssetEmptyState title="页面不存在" description="请从左侧导航选择要访问的页面。" /></>;
}

type ReplicaDashboardShellProps = {
  user: User;
  activeNav: NavKey;
  pageBody: ReactNode;
  projects: Project[];
  jobsByProject: Record<string, Job[]>;
  skills: Skill[];
  draftSkillId: string;
  onDraftSkillChange: (skillId: string) => void;
  draftModeId: string;
  onDraftModeChange: (modeId: string) => void;
  templates: Template[];
  snippets: PromptSnippet[];
  pendingMaterialFiles: File[];
  onSelectMaterials: (files: File[]) => void;
  onRemovePendingMaterial: (index: number) => void;
  materialUploading: boolean;
  draft: string;
  setDraft: Dispatch<SetStateAction<string>>;
  selectedTemplateId: string | null;
  setSelectedTemplateId: Dispatch<SetStateAction<string | null>>;
  selectedPromptPreset: PromptSnippet | null;
  onSelectPromptPreset: (snippet: PromptSnippet) => void;
  onClearPromptPreset: () => void;
  isSubmitting: boolean;
  darkMode: boolean;
  setDarkMode: Dispatch<SetStateAction<boolean>>;
  searchOpen: boolean;
  setSearchOpen: Dispatch<SetStateAction<boolean>>;
  globalQuery: string;
  setGlobalQuery: Dispatch<SetStateAction<string>>;
  globalMatches: Array<{ type: string; id: string; label: string }>;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: Dispatch<SetStateAction<boolean>>;
  sidebarOpen: boolean;
  setSidebarOpen: Dispatch<SetStateAction<boolean>>;
  isPlatformAdmin: boolean;
  onNavigate: (key: NavKey) => void;
  onCreate: () => void;
  onBegin: () => void;
  onOpen: (project: Project) => void;
  onDelete: (project: Project) => void;
  targetProject: Project | null;
  deleteOpen: boolean;
  deleteBusy: boolean;
  onCloseDelete: () => void;
  onConfirmDelete: () => void;
  onNotice: (message: string) => void;
  notice: string;
  onLogout: () => void;
};

function ReplicaDashboardShell(props: ReplicaDashboardShellProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"全部" | "草稿" | "进行中" | "已完成">("全部");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const visibleProjects = props.projects.filter((project) => {
    const job = props.jobsByProject[project.id]?.[0];
    const matchesQuery = project.title.toLowerCase().includes(query.trim().toLowerCase());
    const matchesFilter = filter === "全部"
      || (filter === "草稿" ? !job : filter === "进行中" ? job?.status === "queued" || job?.status === "running" : job?.status === "succeeded");
    return matchesQuery && matchesFilter;
  });
  const selectedTemplate = props.templates.find((template) => template.id === props.selectedTemplateId);
  const selectedPromptPreset = props.selectedPromptPreset;
  const activeSkill = props.skills.find((skill) => skill.id === props.draftSkillId) ?? props.skills[0] ?? null;
  const skillFrontend = activeSkill?.frontend ?? null;
  const draftModes = activeSkill?.frontend.modes ?? [];
  const activeDraftMode = draftModes.find((mode) => mode.id === props.draftModeId) ?? draftModes[0] ?? null;
  const composerPlaceholder = activeDraftMode?.composer_placeholder || skillFrontend?.composer_placeholder || "描述你想做的 PPT，例如：为集团管理层准备一份 15 页的云业务季度经营汇报……";
  const visiblePresets = props.snippets.filter((snippet) => !snippet.skill_id || snippet.skill_id === activeSkill?.id);
  const supportsTemplateTools = activeSkill ? activeSkill.features.templates : true;
  const quickStarts = skillFrontend?.quick_starts.length ? skillFrontend.quick_starts : ["季度经营分析", "产品发布方案", "行业解决方案"];
  const emptyProjectTitle = query.trim()
    ? "没有找到匹配的项目"
    : filter === "草稿" ? "暂无草稿项目" : filter === "进行中" ? "暂无进行中的项目" : filter === "已完成" ? "暂无已完成项目" : "暂无项目";
  const emptyProjectDescription = query.trim() ? "尝试更换搜索关键词。" : "切换筛选条件或创建一个新项目。";

  return <div className={`zc-shell kppt-shell ${props.sidebarCollapsed ? "is-collapsed" : ""} ${props.darkMode ? "kppt-dark" : ""}`}>
    <button className={`zc-scrim ${props.sidebarOpen ? "is-visible" : ""}`} aria-label="关闭导航" onClick={() => props.setSidebarOpen(false)} />
    <aside className={`zc-sidebar kppt-sidebar ${props.sidebarOpen ? "is-open" : ""}`}>
      <div className="kppt-brand-row">
        <button className="kppt-brand" type="button" onClick={props.onCreate} aria-label="返回我的项目">
          <img src="/logo-128.png" alt="" />
          <span><strong>智创AI助手</strong><small>AI CREATION WORKSPACE</small></span>
        </button>
      </div>
      <button className="kppt-create" type="button" onClick={props.onCreate}><Plus size={18} /><span>{skillFrontend?.create_button_label || "创建 PPT"}</span></button>
      <nav className="kppt-primary-nav" aria-label="工作空间">
        <small>工作空间</small>
        {([ ["projects", "我的项目", FileStack], ["templates", "PPT模板库", LayoutTemplate], ["prompts", "PPT预设", Zap] ] as const).map(([key, label, Icon]) => <button className={props.activeNav === key ? "is-active" : ""} key={key} type="button" onClick={() => props.onNavigate(key)}><Icon size={18} /><span>{label}</span>{key === "projects" && <i>{props.projects.length}</i>}</button>)}
      </nav>
      <div className="kppt-sidebar-spacer" />
      <nav className="kppt-secondary-nav" aria-label="辅助导航">
        <button type="button" onClick={() => props.isPlatformAdmin ? props.onNavigate("admin") : props.onNotice("个人设置将在后续版本接入。") }><Settings size={17} /><span>设置</span></button>
      </nav>
      <div className="kppt-account">
        <span>{props.user.display_name.slice(0, 1)}</span>
        <div><strong>{props.user.display_name}</strong><small>{props.isPlatformAdmin ? "平台超级管理员" : "工作区成员"}</small></div>
        <button type="button" onClick={props.onLogout} title="退出登录" aria-label="退出登录"><LogOut size={15} /></button>
      </div>
    </aside>
    <main className="zc-main kppt-main">
      <header className="kppt-topbar">
        <div className="kppt-topbar-title"><button className="zc-icon zc-mobile-menu" type="button" aria-label="打开导航" onClick={() => props.setSidebarOpen(true)}><Menu size={19} /></button><button className="kppt-collapse" type="button" aria-label={props.sidebarCollapsed ? "展开导航" : "收起导航"} onClick={() => props.setSidebarCollapsed((current) => !current)}>{props.sidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</button><div><strong>{props.activeNav === "projects" ? "我的项目" : props.activeNav === "templates" ? "PPT模板库" : props.activeNav === "prompts" ? "PPT预设" : "管理设置"}</strong><span>{props.activeNav === "projects" ? "创作与管理你的项目" : props.activeNav === "templates" ? "管理你的个人 PPT 模板" : props.activeNav === "prompts" ? "把常用创作需求保存为 PPT 预设" : "管理PPT系统模板、系统预设、用户与模型"}</span></div></div>
        <div className="kppt-topbar-actions"><button className="kppt-global-search" type="button" onClick={() => props.setSearchOpen(true)}><Search size={16} /><span>搜索项目、模板和预设</span></button><button className="kppt-topbar-icon" type="button" aria-label={props.darkMode ? "切换浅色主题" : "切换深色主题"} onClick={() => props.setDarkMode((current) => !current)}><Moon size={17} /></button></div>
      </header>
      <div className={`zc-content kppt-content ${props.activeNav === "admin" ? "kppt-content--admin" : ""}`}>
        {props.activeNav !== "projects" ? <div className="kppt-page-body">{props.pageBody}</div> : <>
        <section className="kppt-dashboard-hero" aria-labelledby="kppt-create-title">
          <div className="kppt-eyebrow"><Sparkles size={14} />智创AI助手</div>
          <h1 id="kppt-create-title">{skillFrontend?.hero_title || "把一个想法，变成一套能讲清楚的 PPT"}</h1>
          <p>{skillFrontend?.hero_subtitle || "先梳理需求，再设计大纲；每一步都由你确认，生成后还能逐页对话精修。"}</p>
          {props.skills.length > 1 && <div className="kppt-segmented kppt-skill-switch" role="tablist" aria-label="创作类型">{props.skills.map((skill) => <button key={skill.id} type="button" role="tab" aria-selected={skill.id === props.draftSkillId} className={skill.id === props.draftSkillId ? "is-active" : ""} onClick={() => props.onDraftSkillChange(skill.id)}>{skill.display_name}</button>)}</div>}
          <div className="kppt-composer"><textarea value={props.draft} onChange={(event) => props.setDraft(event.target.value)} placeholder={composerPlaceholder} rows={4} /><div className="kppt-composer-actions"><div><UploadButton type="default" className={`kppt-soft-button${props.pendingMaterialFiles.length > 0 ? " is-selected" : ""}`} icon={<Paperclip size={16} />} loading={props.materialUploading} disabled={props.materialUploading} multiple accept=".pdf,.doc,.docx,.docm,.ppt,.pps,.pot,.pptx,.pptm,.ppsx,.ppsm,.xls,.xlsx,.xlsm,.xlsb,.odt,.ods,.odp,.rtf,.epub,.csv,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp" onFiles={props.onSelectMaterials}>{props.materialUploading ? "正在上传…" : "添加材料"}</UploadButton>{(() => { const modes = activeSkill?.frontend.modes ?? []; return modes.length > 1 ? <div className="kppt-segmented kppt-mode-switch" role="tablist" aria-label="创作模式">{modes.map((mode) => <button key={mode.id} type="button" role="tab" aria-selected={mode.id === props.draftModeId || (!props.draftModeId && mode.id === modes[0]?.id)} className={mode.id === (props.draftModeId || modes[0]?.id) ? "is-active" : ""} onClick={() => props.onDraftModeChange(mode.id)}>{mode.label}</button>)}</div> : null; })()}{supportsTemplateTools && <><button className={`kppt-tool-button kppt-template-button${selectedTemplate ? " is-selected" : ""}`} type="button" aria-label="添加模板" title="添加模板" onClick={() => { setToolsOpen((current) => !current); setPromptOpen(false); }}><LayoutTemplate size={16} /><span>添加模板</span></button><button className={`kppt-tool-button kppt-prompt-button${selectedPromptPreset ? " is-selected" : ""}`} type="button" aria-label="添加预设" title="添加预设" onClick={() => { setPromptOpen((current) => !current); setToolsOpen(false); }}><Zap size={16} /><span>添加预设</span></button></>}</div><button className="kppt-send" type="button" aria-label="开始创建" disabled={!props.draft.trim() || props.isSubmitting} onClick={props.onBegin}><Send size={17} /></button></div>{props.pendingMaterialFiles.length > 0 && <div className="kppt-material-chips" aria-label="待上传材料">{props.pendingMaterialFiles.map((file, index) => <span key={`${file.name}-${index}`}>{file.name}<button type="button" aria-label={`移除 ${file.name}`} onClick={() => props.onRemovePendingMaterial(index)}><X size={12} /></button></span>)}</div>}{toolsOpen && <div className="kppt-tools-popover">{props.templates.length > 0 ? <><button type="button" className={!props.selectedTemplateId ? "is-selected" : ""} onClick={() => { props.setSelectedTemplateId(null); setToolsOpen(false); }}>自由创作</button>{props.templates.map((template) => <button key={template.id} type="button" className={props.selectedTemplateId === template.id ? "is-selected" : ""} onClick={() => { props.setSelectedTemplateId(template.id); setToolsOpen(false); }}>{template.name}<small>{template.page_count ?? 0} 页模板</small></button>)}</> : <p className="kppt-tools-empty">暂无模板</p>}</div>}{promptOpen && <div className="kppt-tools-popover kppt-prompt-popover">{visiblePresets.length ? visiblePresets.map((snippet) => <button key={snippet.id} type="button" className={selectedPromptPreset?.id === snippet.id ? "is-selected" : ""} onClick={() => { props.onSelectPromptPreset(snippet); setPromptOpen(false); }}><span>{snippet.scope === "system" ? "系统预设" : "我的预设"}</span>{snippet.name}</button>) : <p className="kppt-tools-empty">暂无可用创作预设</p>}{selectedPromptPreset && <button type="button" className="kppt-prompt-clear" onClick={() => { props.onClearPromptPreset(); setPromptOpen(false); }}><X size={13} />取消添加预设</button>}</div>}</div>
          <div className="kppt-quick-starts"><span>试试：</span>{quickStarts.map((item) => <button key={item} type="button" onClick={() => props.setDraft(activeSkill && activeSkill.id !== "ppt-master" ? `帮我做一份${item}` : `帮我制作一份${item} PPT`)}>{item}</button>)}</div>
        </section>
        <section className="kppt-project-section" aria-labelledby="kppt-recent-title">
          <header className="kppt-section-heading"><div><h2 id="kppt-recent-title">最近项目</h2><p>继续上次的创作，所有阶段都已自动保存</p></div><button className="kppt-text-button" type="button" onClick={() => { setFilter("全部"); setQuery(""); }}>查看全部<ArrowRight size={15} /></button></header>
          <div className="kppt-project-toolbar"><div className="kppt-segmented">{(["全部", "草稿", "进行中", "已完成"] as const).map((item) => <button key={item} className={filter === item ? "is-active" : ""} type="button" onClick={() => setFilter(item)}>{item}</button>)}</div><div><label className="kppt-compact-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目" /></label><button className="kppt-tool-button" type="button" aria-label="切换项目视图" onClick={() => setView((current) => current === "grid" ? "list" : "grid")}>{view === "grid" ? <List size={16} /> : <LayoutGrid size={16} />}</button></div></div>
          <div className={`kppt-project-grid ${view === "list" ? "is-list" : ""}`}>{visibleProjects.length ? visibleProjects.map((project, index) => <AssetReplicaProjectCard key={project.id} project={project} job={props.jobsByProject[project.id]?.[0]} palette={index % 3} skillLabel={props.skills.find((skill) => skill.id === project.skill_id)?.display_name} onOpen={() => props.onOpen(project)} onDelete={() => props.onDelete(project)} />) : <AssetEmptyState className="kppt-project-empty" title={emptyProjectTitle} description={emptyProjectDescription} />}</div>
        </section></>}
      </div>
    </main>
    {props.searchOpen && <div className="kppt-search-backdrop" onMouseDown={() => props.setSearchOpen(false)}><section className="kppt-search-dialog" role="dialog" aria-modal="true" aria-label="全局搜索" onMouseDown={(event) => event.stopPropagation()}><label><Search size={17} /><input autoFocus value={props.globalQuery} onChange={(event) => props.setGlobalQuery(event.target.value)} placeholder="搜索项目、模板和预设" /></label><div>{props.globalMatches.length ? props.globalMatches.map((match) => <button key={`${match.type}-${match.id}`} type="button" onClick={() => { props.setSearchOpen(false); if (match.type === "项目") { const project = props.projects.find((item) => item.id === match.id); if (project) props.onOpen(project); } else if (match.type === "模板") { props.onNavigate("templates"); } else { const snippet = props.snippets.find((item) => item.id === match.id); if (snippet) props.onSelectPromptPreset(snippet); } }}><small>{match.type}</small><span>{match.label}</span></button>) : <p>{props.globalQuery ? "没有找到匹配内容" : "输入关键词，搜索项目、模板和预设"}</p>}</div></section></div>}
    {props.deleteOpen && <div className="zc-modal-backdrop" onMouseDown={props.deleteBusy ? undefined : props.onCloseDelete}><section className="zc-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><h2>删除这个项目？</h2><p>项目中的全部生成记录和演示文稿将被删除，且无法恢复。</p><div className="zc-modal-actions"><button className="zc-secondary" type="button" onClick={props.onCloseDelete} disabled={props.deleteBusy}>取消</button><AsyncButton className="zc-danger" type="button" onClick={props.onConfirmDelete} loading={props.deleteBusy}><Trash2 size={15} />确认删除</AsyncButton></div></section></div>}
  </div>;
}


function ModalFrame({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return <div className="zc-modal-backdrop" role="presentation"><section className="zc-modal" role="dialog" aria-modal="true"><button className="zc-icon zc-modal-close" type="button" aria-label="关闭" onClick={onClose}><X size={18} /></button>{children}</section></div>;
}
