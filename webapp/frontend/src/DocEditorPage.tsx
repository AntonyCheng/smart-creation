import { useEffect, useRef, useState } from "react";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { navigate } from "./routes";

type EditorConfig = {
  kind: "docx" | "pptx";
  docKey: string;
  fileType: string;
  title: string;
  documentUrl: string;
  callbackUrl: string;
  apiScript: string;
};

type DocsApiEditor = { destroyEditor: () => void };

type DocsApi = { DocEditor: new (placeholderId: string, config: Record<string, unknown>) => DocsApiEditor };

declare global {
  interface Window {
    DocsAPI?: DocsApi;
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);
    if (existing) {
      if (window.DocsAPI) return resolve();
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("编辑器脚本加载失败")));
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("编辑器脚本加载失败"));
    document.head.appendChild(script);
  });
}

export function DocEditorPage({ projectId, docKind }: { projectId: string; docKind: "docx" | "pptx" }) {
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(false);
  const placeholderRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    let editor: DocsApiEditor | null = null;
    (async () => {
      try {
        const response = await fetch(`/api/v1/projects/${projectId}/doc-editor-config?kind=${docKind}`, { credentials: "include" });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(String(body.detail || "无法载入编辑配置"));
        }
        const config = await response.json() as EditorConfig;
        await loadScript(config.apiScript);
        if (cancelled || !window.DocsAPI || !placeholderRef.current) return;
        // DocsAPI resolves the placeholder with getElementById: it needs the ID.
        editor = new window.DocsAPI.DocEditor("onlyoffice-placeholder", {
          document: {
            fileType: config.fileType,
            key: config.docKey,
            title: config.title,
            url: config.documentUrl,
            permissions: { edit: true, download: true },
          },
          editorConfig: {
            callbackUrl: config.callbackUrl,
            lang: "zh-CN",
            customization: {
              forcesave: true,
              compactHeader: true,
              hideRightMenu: true,
              uiTheme: "theme-classic-light",
            },
          },
          height: "100%",
          width: "100%",
        });
        setReady(true);
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "编辑器初始化失败");
      }
    })();
    return () => {
      cancelled = true;
      try {
        editor?.destroyEditor();
      } catch {
        // The iframe may already be gone during unmount races.
      }
    };
  }, [docKind, projectId]);

  return <main style={{ height: "100dvh", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 12, padding: "14px 18px", background: "#f7f7f8" }}>
    <header className="zc-workbench-head" style={{ margin: 0 }}>
      <button className="zc-icon" type="button" aria-label="返回项目" onClick={() => navigate(`/workspace/${projectId}`)}><ArrowLeft size={19} /></button>
      <div><strong>手动编辑</strong><span>{docKind === "docx" ? "公文 WYSIWYG 编辑，保存后自动同步回创作源" : "PPTX 定稿编辑，保存后更新可下载文稿"}</span></div>
    </header>
    {message
      ? <div className="zc-panel" style={{ maxWidth: 520 }}><p>{message}</p><button className="zc-secondary" type="button" onClick={() => navigate(`/workspace/${projectId}`)}>返回项目</button></div>
      : <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {!ready && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "#f7f7f8", zIndex: 2 }}><LoaderCircle className="zc-spin" size={26} /></div>}
        {/* DocsAPI 会在占位元素内部插入 100% 高度的 iframe，占位元素必须有真实尺寸 */}
        <div ref={placeholderRef} id="onlyoffice-placeholder" style={{ position: "absolute", inset: 0 }} />
      </div>}
  </main>;
}
