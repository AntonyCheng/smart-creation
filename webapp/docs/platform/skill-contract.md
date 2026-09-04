# 公文写作 Skill 接入契约

面向公文写作（gongwen）skill 的作者与维护者。本 skill 已接入平台（2026-08-31），本文档同时是后续 skill 接入的参照契约。

## 平台侧组件（已就绪）

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| skill 注册表 | `webapp/skills/gongwen/skill.manifest.json` | `enabled: true`；产物 glob 含 `exports/**/*.docx`（skill 按 uuid 子目录输出） |
| worker 适配器 | `webapp/worker/adapters/gongwen.py` | 运行时配置、docx 校验、排版忠实性校验、`finalize()` 渲染预览 |
| 提纲提示词 | `webapp/api/outline_prompts.py` 的 `"gongwen"` 条目 | 文种/发文机关/主送/篇幅/结构 |
| 数据模型 | `projects.skill_id` / `jobs.skill_id` / `projects.mode` / `jobs.mode` / `ArtifactKind`（含 DOCX/PDF/PNG） | 迁移 0019/0020/0021 |
| 执行环境 | runner 镜像（常驻） | 含 LibreOffice、poppler、anydoc、中文 OCR（PaddleOCR PP-OCRv5 mobile，独立 `/opt/ocr-venv`，模型烤进镜像 `docker/ocr-models`）；公文字体由 skill 自带（`assets/fonts/`），经运行时 fontconfig 生效 |

## 创作模式（frontend.modes）

skill 可在 manifest `frontend.modes` 声明多个创作流程，每个模式自带 `stages` 与 `fields`（表单 schema）；`projects.mode` 在创建时选定并冻结，`jobs.mode` 为提交时快照，经 `PPTMASTER_JOB_MODE` 下发 worker。无 `modes` 的 skill（如 ppt-master）沿用顶层 `frontend.stages` 单模式，行为不变。

- **draft（公文起草）**：阶段 `requirements → outline → generating → preview`；字段含文种、发文机关、主送、字数范围、起草深度等；大纲经 `creative-outline` 生成后注入任务。
- **typeset（公文排版）**：阶段 `content → format → generating → preview`；`content` 阶段收集正文（粘贴进 `requirements.content` 或上传材料——材料经 `runner.extract_material` 异步解析：原生文档走 anydoc，扫描件/图片走中文 OCR 回退，统一生成 `materials/<id>.extracted.md` sidecar，解析中 `status="processing"` 会拦截生成）；`format` 阶段收集红头、发文字号、主送、成文日期、印章等版式字段。任务 prompt 由 `_typeset_prompt` 组装：**正文逐字保留契约**（粘贴正文包裹在哨兵行之间）+ 版式要素清单；不允许生成大纲。

## 对话改稿（features.document_refinement）

`document_refinement: true` 表示生成完成后支持全文级 AI 对话修改，与 PPT 的 `page_refinement`（页级）共用管线：`refinement-intent`（`slide_number=0` 表示全文）→ 意图分类 → 带 `conversation_message` 的任务（无 `target_slide_number`，必须基于已完成任务）→ `PageRefinementMessage` 按 `slide_number=0` 持久化 → worker 以 continuation 基线比对校验修改生效。修订深度由 skill 依 `writing-modes.md` 自行判定（默认规范修订）。前端对话文案来自 manifest `frontend.refinement`。

## 运行时链路

1. 任务启动时 adapter 执行 `scripts/setup_local.py --output <工作区>/exports --config <工作区>/gongwen-runtime.json`，生成运行时配置与 fontconfig（指向 skill 自带字体，不装系统字体，符合 skill"运行期不安装字体"纪律）。
2. driver 经 manifest `agent.env` 注入 `GONGWEN_RUNTIME_CONFIG=<工作区>/gongwen-runtime.json`，agent 调用 `prepare_draft.py` 时读取。
3. 产物落 `exports/<uuid>/标题（草稿）.docx`；校验通过后 `finalize()` 用 `soffice --convert-to pdf`（带 `FONTCONFIG_FILE`）产出 PDF，再 `pdftoppm` 产出逐页 PNG 到 `preview/`。
4. PDF 与页面 PNG 一并注册为产物；前端"预览下载"阶段复用与 PPT 相同的逐页预览面板展示真实排版。

## 对 skill 的硬性要求（接入任何新 skill 时同样适用）

1. 目录 `skills/<skill_id>/`，入口 `SKILL.md`；`skill_id` 与目录名一致。
2. 支持无交互自主运行（缺失事实用明确占位，不追问、不编造）。
3. 最终交付文件写入 `<工作区>/exports/`（路径在 manifest `artifacts` 中声明）；不得创建第二个项目目录。
4. pip 依赖进 `docker/worker-requirements.txt`（根 `requirements.txt` 归 ppt-master 且被指纹校验，禁止编辑）。
5. 不自行做文件投递/发链接——平台自动收集产物。
6. 收到"逐字排版/忠实性"指令时必须原样保留正文文字，只做结构与版式调整（平台会对 typeset 任务自动抽样比对源文与 DOCX，命中率低于 90% 判任务失败）。

## 镜像与重建矩阵

| 改动 | 需要重建 |
| --- | --- |
| `webapp/skills/**/skill.manifest.json` | web + runner |
| `webapp/worker/**` 或 `skills/**`（含字体） | runner（执行环境所在镜像） |
| 前端 | web |
| `docker/worker-requirements.txt` | runner |
