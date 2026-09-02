import { useState } from "react";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import type { Job, JobStatus, Project } from "./appTypes";

const statusLabel: Record<JobStatus, string> = { queued: "等待执行", running: "生成中", succeeded: "已完成", failed: "生成失败", cancelled: "已中止" };
function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function ReplicaProjectCard({ project, job, palette, skillLabel, onOpen, onDelete }: { project: Project; job?: Job; palette: number; skillLabel?: string; onOpen: () => void; onDelete: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const status = job ? statusLabel[job.status] : "草稿";
  return <article className={`kppt-project-card kppt-palette-${palette}${menuOpen ? " is-menu-open" : ""}`}><button className="kppt-project-preview" type="button" onClick={onOpen}>{skillLabel && <em className="kppt-skill-badge">{skillLabel}</em>}<span>AI · DECK</span><div><strong>{project.title}</strong><small>{job?.template_name || "需求确认后可继续生成"}</small></div><i /><i /></button><div className="kppt-project-body"><button type="button" onClick={onOpen}>{project.title}</button><button className="kppt-card-menu" type="button" aria-label="项目更多操作" onClick={() => setMenuOpen((current) => !current)}><MoreHorizontal size={17} /></button>{menuOpen && <div className="kppt-card-menu-popover"><button type="button" onClick={onOpen}><Pencil size={14} />继续创作</button><button className="is-danger" type="button" onClick={onDelete}><Trash2 size={14} />删除项目</button></div>}</div><footer><span className={`kppt-status kppt-status-${job?.status ?? "draft"}`}>{status}</span><small>{formatDate(project.updated_at)}</small></footer></article>;
}


