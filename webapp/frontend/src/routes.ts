export type AdminRouteTab = "templates" | "prompts" | "users" | "models";
export type AppRoute =
  | { kind: "projects" }
  | { kind: "templates" }
  | { kind: "prompts" }
  | { kind: "admin"; tab: AdminRouteTab }
  | { kind: "workspace"; projectId: string; jobId: string | null }
  | { kind: "editor"; projectId: string; jobId: string }
  | { kind: "doc-editor"; projectId: string; docKind: "docx" | "pptx" }
  | { kind: "unknown" };

const adminTabs: AdminRouteTab[] = ["templates", "prompts", "users", "models"];

export function parseRoute(locationValue: string): AppRoute {
  const [rawPath, rawSearch = ""] = locationValue.split("?", 2);
  const path = rawPath.replace(/\/+$/, "") || "/";
  const editor = /^\/editor\/([^/]+)\/([^/]+)$/.exec(path);
  if (editor) return { kind: "editor", projectId: decodeURIComponent(editor[1]), jobId: decodeURIComponent(editor[2]) };
  const docEditor = /^\/doc-editor\/([^/]+)$/.exec(path);
  if (docEditor) {
    const kind = new URLSearchParams(rawSearch).get("kind") === "pptx" ? "pptx" : "docx";
    return { kind: "doc-editor", projectId: decodeURIComponent(docEditor[1]), docKind: kind };
  }
  const workspace = /^\/workspace\/([^/]+)$/.exec(path);
  if (workspace) return { kind: "workspace", projectId: decodeURIComponent(workspace[1]), jobId: new URLSearchParams(rawSearch).get("job") };
  if (path === "/" || path === "/projects") return { kind: "projects" };
  if (path === "/templates") return { kind: "templates" };
  if (path === "/prompts") return { kind: "prompts" };
  const admin = /^\/admin(?:\/([^/]+))?$/.exec(path);
  if (admin) {
    const tab = adminTabs.includes(admin[1] as AdminRouteTab) ? admin[1] as AdminRouteTab : "templates";
    return { kind: "admin", tab };
  }
  return { kind: "unknown" };
}

export function pathForNav(nav: "projects" | "templates" | "prompts" | "admin"): string {
  return nav === "projects" ? "/" : `/${nav}`;
}

export function navigate(pathname: string, replace = false): void {
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({}, "", pathname);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function editorPath(projectId: string, jobId: string): string {
  const workspacePath = `/workspace/${encodeURIComponent(projectId)}?job=${encodeURIComponent(jobId)}`;
  return `/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(jobId)}?returnTo=${encodeURIComponent(workspacePath)}`;
}
