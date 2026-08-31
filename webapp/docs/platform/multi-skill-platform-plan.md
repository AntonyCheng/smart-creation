# 智创AI助手：多 Skill 平台化改造方案

> 状态：方案已评审待实施 ｜ 分支：platform ｜ 日期：2026-08-31

## Context（背景与目标）

当前仓库（branch `platform`）是「ppt-master 开源 skill 项目 + 平台层」的混合体，根目录身兼两职。平台核心实为 `webapp/`（FastAPI api + Celery runner + 容器内 worker + React 前端）、`docker/`、`mcp-server/`，通过 OpenCode 运行时驱动 `skills/ppt-master` 生成 PPTX，且**全链路对 ppt-master 硬编码**（无 skill 字段、worker 只认 svg_output/pptx、prompt 只指 ppt-master）。

改造目标：平台成为主体，skill 降级为可插拔组件；接入第二个 skill「公文写作」（产出标准格式 .docx，同事调试中尚未入库），并为后续 N 个 skill 预留扩展位；前端聊天输入框上方加工作类型开关；品牌改名「智创PPT专家 → 智创AI助手」（仅前端文案）。

**已确认的决策**：
- 上游 ppt-master 更新走**手动拷贝**，同步单元必须与平台文件隔离
- `skills/ppt-master/` 内部**完全不动**（连 manifest 也不放进去）
- 公文 skill 未就绪 → 平台侧**契约先行**（manifest 即接入规范），skill 到位后零平台代码改动
- 根目录 OSS 清理：删 `index.html`、`viewer.html`、`README_CN.md`、`.github/workflows/deploy-pages.yml`；`README.md` 重写为平台版（原 OSS README 移入 `skills/ppt-master/README.md`）；`examples/` 与 `.claude-plugin/` 保留
- 内部标识（`skills/ppt-master`、`pptmaster-*` 服务、`PPTMASTER_*` 环境变量、`pptmaster-web` 包名）一律不动

## 一、目标目录结构

```
<repo root>                          # 智创AI助手 平台仓库
├── AGENTS.md                        # 多 skill 分发入口（改造方式见 §五；烤进 worker 镜像）
├── CLAUDE.md                        # 不变（导入 AGENTS.md 模式）
├── README.md                        # 重写：平台 README
├── skills/                          # ★ 纯 skill 目录：每个子目录 = 一个可插拔 skill，平台不在其中放任何文件
│   ├── ppt-master/                  #   上游同步单元，内部零改动
│   │   └── README.md                #   （新增：原根 OSS README 迁入；同步手册注明保护）
│   └── gongwen/                     #   公文 skill（同事完成后整目录放入）
├── webapp/
│   ├── skills/                      # ★ 新增：平台侧 skill 注册表（manifest 归平台所有，不进 skills/）
│   │   ├── __init__.py
│   │   ├── registry.py              # stdlib 加载器：list_skill_manifests() / get_skill_manifest(id)
│   │   ├── ppt-master/skill.manifest.json
│   │   └── gongwen/skill.manifest.json
│   ├── api/  (main.py, models.py, schemas.py + 新增 outline_prompts.py, docx_preview.py)
│   ├── runner/tasks.py
│   ├── worker/                      # main.py 瘦身为通用驱动 ~200 行
│   │   └── adapters/                # ★ 新增：base.py + ppt_master.py + gongwen.py
│   ├── migrations/versions/20260831_0019_multi_skill.py
│   └── frontend/
├── docker/
│   ├── Dockerfile.web               # +COPY webapp/skills ./skills（现仅拷 api/runner/migrations）
│   ├── Dockerfile.runner            # 同上
│   ├── Dockerfile.worker            # +pip install docker/worker-requirements.txt
│   └── worker-requirements.txt      # 新增：worker 镜像专属依赖（python-docx）
├── mcp-server/                      # 最后阶段泛化
├── docs/
│   ├── rules/                       # 原位不动（AGENTS.md 引用 + 烤进镜像 + svg-pipeline.md:75 交叉引用）
│   ├── audio-narration.md 等        # 原位不动（generate-audio.md:289 交叉引用落点）
│   └── platform/                    # 新增：multi-skill-architecture.md + skill-contract.md + upstream-sync.md
├── projects/                        # 保留（gitignored）：paths.py 相对推导的本地输出根
├── examples/                        # 保留
└── requirements.txt                 # 保留（skill 所有且被指纹校验，禁止编辑）
```

**删除**：`index.html`、`viewer.html`、`README_CN.md`、`.github/workflows/deploy-pages.yml`。

### 用户两个具体问题的结论

- **projects/**：保留为 gitignored 目录。`skills/ppt-master/scripts/project_management/paths.py:22-23` 以 `REPO_ROOT = SKILL_DIR.parent.parent` 相对推导 `PROJECTS_ROOT`，`skills/ppt-master/` 保持根下第二层即自动生效；平台容器运行时经 `HOST_PROJECTS_ROOT` 挂载 job 工作区，与它无关；上游同步永不涉及。
- **docs/**：功能性部分原位保留——`docs/rules/`（仓库级风格规则，对所有 skill 生效）与 `docs/audio-narration.md`（skill 内仅有的 2 处越界文档引用之一）。上游用户文档（FAQ/installation 等）不随同步拷贝；平台文档全部进 `docs/platform/`。

### 上游同步策略（落盘为 docs/platform/upstream-sync.md）

同步单元 = 上游 `skills/ppt-master/` → 本仓库 `skills/ppt-master/`，**唯一保护文件** `skills/ppt-master/README.md` 与 `skill.manifest.json`（后者在 webapp/skills/ 下，天然隔离）。`docs/rules/` 变化时单独手动 diff。platform 分支不再合并上游。

## 二、Skill 接入契约：skill.manifest.json（webapp/skills/<id>/）

```jsonc
{
  "schema_version": 1,
  "skill_id": "ppt-master",              // 必须等于 skills/ 下目录名
  "display_name": "PPT 创作",
  "enabled": true,                        // false = 从 /api/v1/skills 隐藏且创建被拒
  "workspace": {
    "init": { "mode": "command",          // command | adapter_scaffold | none
              "command": ["python", "skills/ppt-master/scripts/project_manager.py",
                          "init", "{workspace_name}", "--dir", "{workspace_parent}",
                          "--format", "ppt169", "--quick-generate"] },
    "continue_seed_dir": "ppt-project",   // 续写种子目录（替代 AUTHORING_ROOT_NAME）
    "fresh_root_suffix": "ppt169",
    "authoring_root": { "marker_dir": "svg_output" },   // runner 根探测（替代 tasks.py:184 硬编码）
    "progress_dirs": ["svg_output", "exports", "validation"]
  },
  "agent": { "entry_doc": "skills/ppt-master/SKILL.md",
             "prompt_strategy": "ppt_quick_generate",   // adapter 钩子名
             "runtime_mode": "quick",                   // 自主运行、无交互确认门
             "repo_conventions_doc": "AGENTS.md" },
  "artifacts": [                          // runner 产物发现（替代 tasks.py:393-401 硬编码元组）
    { "kind": "svg",  "glob": "svg_output/*.svg", "content_type": "image/svg+xml" },
    { "kind": "pptx", "glob": "exports/*.pptx", "content_type": "application/vnd...presentationml.presentation" }
  ],
  "primary_artifact_kind": "pptx",        // MCP/前端「最终交付物」判定
  "validation_adapter": "ppt_revision",   // worker/adapters/ 模块
  "features": { "templates": true, "page_refinement": true, "editor": true,
                "materials_upload": true, "resume": true },   // API/前端能力门控
  "frontend": {                           // 前端全部由 manifest 驱动
    "hero_title": "把一个想法，变成一套能讲清楚的 PPT",
    "composer_placeholder": "描述你想做的 PPT，例如：……",
    "stages": [ {"id":"requirements","label":"需求梳理"}, {"id":"outline","label":"大纲设计"},
                {"id":"template","label":"选择模板"}, {"id":"generating","label":"生成 PPT"},
                {"id":"preview","label":"预览精修"} ],      // id 限于后端已校验的 5 值集合
    "outline": { "item_label": "页", "generator_prompt_key": "ppt-master",
                 "fields": [ {"name":"title","label":"页面标题","required":true}, /* purpose/content/kind/notes */ ],
                 "first_item_is_title_page": true }
  }
}
```

ppt-master 的 manifest 每个值都溯源到现有常量（init ← `worker/main.py:438-448`；种子目录/后缀 ← `main.py:22,200-206`；探测标记 ← `tasks.py:184`；产物 ← `tasks.py:394-400`；阶段/文案 ← `CreativeWorkspace.tsx:82-88`、`ProductApp.tsx:908-912`；大纲字段 ← `schemas.py:93-98`、`main.py:290-313`），保证重构后 PPT 行为逐字节不变。

**gongwen manifest（示意）**：`init.command` 指向其自身脚本（或 `mode: adapter_scaffold` 由 adapter 建 `drafts/`+`exports/`）、`marker_dir: exports`、`artifacts: [exports/*.docx → docx]`、`validation_adapter: gongwen_docx`、`features` 全关（templates/page_refinement/editor）、stages 4 个（无 template）、outline 字段名沿用同 5 个 name 仅换 label（部分标题/本部分作用/内容要点/体例要素/口径备注，item_label=部分）——**大纲管线（outline 存储/解析/编辑 UI）零改动复用**，仅提示词与标签不同。

**分发机制**：manifest 烤进 web/runner 镜像（`COPY webapp/skills ./skills`，`registry.py` 以 `Path(__file__).parent` 定位，两镜像 WORKDIR 均为 /app/webapp）；runner 每个 job 经环境变量 `PPTMASTER_SKILL_ID` + `PPTMASTER_SKILL_MANIFEST_JSON` 下发 worker（沿用 `PPTMASTER_OPENCODE_CONFIG_JSON` 模式，tasks.py:529-542）。改 manifest 只需重建 web+runner；**skill 代码本身仍需重建 worker 镜像**（Dockerfile.worker 已整拷 `skills/`，新 skill 自动进镜像）。

## 三、数据模型与 API（webapp/api/）

- `models.py`：`ArtifactKind` + `DOCX`；`Project.skill_id`（String(64)，默认/回填 `"ppt-master"`，索引，**会话绑死一种工作类型**）；`Job.skill_id`（创建时从 Project 拷贝的**不可变快照**，续写/恢复不跨 skill）。
- 迁移 `20260831_0019_multi_skill.py`（`down_revision="20260825_0018"`）：PG17 下 `ALTER TYPE artifact_kind ADD VALUE 'docx'`（不在同事务使用新值）+ 两表加列回填建索引；downgrade 仅删列（枚举值留存，注明）。`start-web.sh` 启动即 `alembic upgrade head`，全容器自动收敛。
- `schemas.py`：新增 `SkillOut` 族；`ProjectCreateIn.skill_id`（默认 ppt-master，正则校验）；`ProjectOut/JobOut` 增 skill_id；creative-state 的 `outline` 从 `list[OutlineSlideIn]` 放宽为 `list[dict]`，由按 manifest `outline.fields` 白名单的校验器把关——PPT 客户端所见 JSON 不变。
- `main.py`（本次**不拆分**，新逻辑进独立模块）：
  - 新增 `GET /api/v1/skills`（数据源 `skills.registry`）——前端开关的数据源
  - `create_project` 校验 skill_id 合法且 enabled；`create_job` 拷贝快照 + 按 `features` 拒绝越权参数（gongwen 传 `template_id`/`target_slide_number` → 400）；`duplicate_project` 复制 skill_id
  - 大纲提示词移入新模块 `api/outline_prompts.py`（`OUTLINE_PROMPTS["ppt-master"]` 逐字保留现文案 main.py:499-505；新增 `"gongwen"` 公文提纲提示词：文种/发文机关/主送/结构/字数），`_outline_prompt/_generate_outline_with_model/_parse_outline_response` 增加 skill 参数
  - PPT 专属端点守卫：refinement-intent（:2594）、editor/slides（:2905-3017）对非 ppt 项目返回 404/409

## 四、Worker / Runner 改造（去硬编码主战场）

### webapp/worker/adapters/（新包）
- `base.py`：`SkillContext` dataclass + adapter 协议：`init_workspace_command` / `verify_workspace` / `snapshot` / `validate_revision` / `emit_artifacts`（manifest glob 驱动通用实现）/ `build_agent_prompt`（按 `prompt_strategy` 分派）
- `ppt_master.py`：现有 PPT 逻辑**原样迁移**——`verify_project_workspace`（main.py:220-249）、`_snapshot`（252-263）、`_slide_paths/_pptx_slide_texts/_validate_revision`（274-404）、agent prompt 文案（465-484，`/app/AGENTS.md` 引用泛化为 `repo_conventions_doc` + 显式 `entry_doc`）
- `gongwen.py`：docx 最小校验——python-docx 打开成功 + ≥1 非空段落 + CJK 字数 ≥ 可配置下限（默认 200）；续写要求相对基线 ≥1 个 hash 变化；prompt 注入「自主决策、无交互确认、产物写入 exports/」
- `adapters/__init__.py`：`get_adapter(skill_id)` + `schema_version`/adapter 名校验，不匹配发显式 error 事件（防镜像版本错配静默劣化）

### webapp/worker/main.py → 通用驱动（~200 行）
读 `PPTMASTER_SKILL_ID/MANIFEST_JSON`（缺省回退 ppt-master）→ 装 opencode 配置（不变）→ init 或续写种子检查 → `adapter.build_agent_prompt()` → `opencode run --format json`（不变，含 idle 超时）→ `verify_workspace` → `emit_artifacts` → `validate_revision`。`export.py`/`template_import.py` 保持 PPT 专属不动（编辑器/模板库本就是 PPT 独有功能）。

### webapp/runner/tasks.py
- `_source_project_root(root, marker_dir)` 参数化（:184-193）；`_seed_job_workspace` 用 manifest `continue_seed_dir`（:252）；`_discover_job_artifacts` 改 manifest `artifacts` glob 循环（:383-428，ppt 结果与现状完全一致）
- env 追加 `PPTMASTER_SKILL_ID` + `PPTMASTER_SKILL_MANIFEST_JSON`（~3KB，远低于 env 上限）
- `export_editor_revision`/`import_template` 不动

### 镜像依赖
`python-docx` 进新文件 `docker/worker-requirements.txt`（根 `requirements.txt` 为 skill 所有且被 `update_repo.py` 指纹校验，**禁止编辑**）+ Dockerfile.worker 一行 pip。mammoth 仅在后端预览（C2 阶段）时进 `webapp/requirements.txt`。

## 五、AGENTS.md 策略

**Phase A/B 不动它**（此时只有 ppt-master，改了反而制造悬空引用）。Phase C 当 `skills/gongwen/` 实际入库时，在文件头部增加分发段：「本仓库托管多个 skill（skills/*）。按任务类型选择入口：演示文稿 → skills/ppt-master/SKILL.md；公文 → skills/gongwen/SKILL.md；docs/rules/ 对全部 skill 生效」，ppt-master 正文保留。同时 worker prompt 不再依赖 AGENTS.md 的单一 skill 强制，改为直接指向 manifest 的 `agent.entry_doc`，AGENTS.md 降级为仓库规约兜底。

## 六、前端改造（webapp/frontend/src/）

- **工作类型开关**：`ProductApp.tsx:907-913` 的 `kppt-composer` 区块上方加 antd `Segmented`（比裸 Switch 更适合 2..N 选项，风格贴合现有 `kppt-segmented`），选项来自 `/api/v1/skills`；切换时 hero 文案/输入框 placeholder/快捷入口全部换为所选 skill 的 manifest 文案；`beginWorkspace()` 携带 skill_id 建项目
- **项目列表**：卡片加 skill 徽标（`display_name`）；侧栏「我的 PPT」「创建 PPT」等改为通用/manifest 文案
- **CreativeWorkspace.tsx**：阶段数组（:82-88 硬编码）与大纲字段标签改由项目 skill 的 manifest 驱动；gongwen 渲染 4 阶段（无选择模板），大纲编辑器读「部分/内容要点」标签；阶段切换逻辑按 id 索引，天然兼容阶段删减；需求表单的 `page_range` 对 gongwen 隐藏
- **公文预览分两步**：v1（Phase D）仅下载按钮（下载链路本就通用）；C2 增后端 `GET .../artifacts/{id}/preview`——mammoth docx→HTML + nh3 消毒，前端滚动面板渲染（不引浏览器端 mammoth.js，转换实现与 skill 输入侧共享、消毒留在服务端）
- **编辑器保持 PPT 专属**：非 ppt 项目隐藏 `PresentationEditor` 路由与「手动编辑」入口（AssetPages.tsx:110），与 API 守卫双保险
- **改名**：`index.html:8`、`ProductApp.tsx:730,882,908`（:882 处副标题 `AI PRESENTATION AGENT` → 如 `AI CREATION WORKSPACE`）；`App.tsx` 为死代码，顺带改齐便于 grep 卫生；PPT 专属 hero 文案不手改——由 ppt-master manifest 提供，品牌壳通用而 hero 仍 PPT 正确

## 七、MCP 泛化（最后，最小化）

`pptmaster_client.py` 的 `create_project` 带 skill_id + `list_skills()` 透传；`server.py` 的 `create_ppt_task` 加 `skill` 参数（`ppt/ppt-master` 与 `gongwen/doc/公文` 归一化，未知 → needs_clarification），`get_ppt_task_status` 用 job 所属 skill 的 `primary_artifact_kind` 替代 :149 硬编码 `kind=="pptx"`；工具名不变保兼容，可选加 `create_doc_task` 别名。

## 八、实施阶段与验证（每阶段可独立交付、可回归）

| 阶段 | 内容 | 关键文件 | 验证 |
|---|---|---|---|
| **A 契约+模型（零行为变化）** | 目录清理（删宣传页/README 重写）；`webapp/skills/` 注册表 + ppt-master manifest；skill_id 列 + 迁移 + `/api/v1/skills`；Dockerfile.web/runner 拷贝 manifest | webapp/skills/*、api/models.py、api/schemas.py、api/main.py、migrations/0019 | 迁移升级；`/api/v1/skills` 恰返回 ppt-master；存量项目回填后 PPT E2E（登录→建项目→大纲→生成→产物→恢复）全链路不变 |
| **B worker/runner manifest 化** | adapters/ 抽取 + ppt_master.py 原样迁移 + main.py 瘦身 + tasks.py 参数化 + env 下发 | worker/adapters/*、worker/main.py、runner/tasks.py | 重建三镜像；**PPT 全量回归**：全新生成/续写/取消+恢复/逐页精修/模板选择/编辑器保存+重导出/模板导入；对照基线 diff `validation/change_manifest.json` 与 JobEvent 流，须一致 |
| **C 公文接入位就绪** | `skills/gongwen/` 入库 + 其 manifest + `adapters/gongwen.py` + `api/outline_prompts.py` gongwen 条目 + `docker/worker-requirements.txt` + AGENTS.md 分发段 + **`docs/platform/skill-contract.md`（交给同事的接入规范）** | skills/gongwen/、webapp/skills/gongwen/、worker/adapters/gongwen.py、AGENTS.md、docs/platform/* | 真实或桩 skill 走 docx E2E：建 gongwen 项目→公文提纲→job→docx 产物注册（kind=docx）→恢复可用；gongwen 传 template_id/target_slide_number 被 400；重跑 B 的 PPT 回归 |
| **D 前端** | Segmented 开关 + 徽标 + manifest 驱动向导/文案 + 编辑器门控 + 改名 | appTypes.ts、ProductApp.tsx、CreativeWorkspace.tsx、AssetPages.tsx、index.html、App.tsx | 开关切换 hero/placeholder 并建 gongwen 项目；gongwen 向导 4 阶段+公文式大纲；PPT 流程除改名外像素级一致；gongwen 无编辑器入口；预览=下载按钮 |
| **E 预览+MCP（收尾）** | `api/docx_preview.py`（mammoth+nh3）+ 前端预览面板；MCP 泛化 | api/docx_preview.py、CreativeWorkspace.tsx、mcp-server/* | docx 预览渲染消毒后 HTML；MCP `skill="gongwen"` 建任务并取下载 URL；PPT MCP 流程不变 |

注：gongwen skill 未就绪不阻塞 A/B/D——D 阶段 gongwen 选项可先 `enabled:false` 占位，C 阶段真实目录到位后翻转。

## 九、风险与待定项

**依赖 gongwen 实际形态（写入 skill-contract.md，Phase C 前须同事确认）**：
1. 是否有 project_manager 式 init？无则用 `init.mode: adapter_scaffold`，但 SKILL.md 若假设元数据已存在需其自行处理
2. **无交互确认模式必须存在**——ppt-master 有显式 Quick profile；若 gongwen SKILL.md 只有带 ⛔ BLOCKING 门的路由，自主运行会卡到 idle 超时（默认 600s）。契约中强制要求 + prompt 显式声明
3. 产物位置契约固定为 `exports/*.docx`（marker 目录驱动 runner 根探测，嵌套工作区会破坏唯一性）
4. skill 的 pip 依赖须枚举进 `docker/worker-requirements.txt`；若渲染 PDF 预览需补字体（现镜像仅 Noto CJK；docx 仅引用字体名则不需要）
5. 素材上传管线本就 skill 无关（`_copy_project_materials`），确认其从 `materials/` 读即可

**平台侧**：
6. PG 枚举 ADD VALUE 在 PG17 迁移事务内合法，但迁移内不得使用新值；downgrade 不回收枚举值（注明）
7. 镜像版本错配（runner 新于 worker）→ adapter 注册表校验发显式错误事件
8. 重建矩阵：改 manifest = web+runner；改 adapter/skill 代码 = 另需 worker。写入 skill-contract.md
9. `Job.skill_id` 提交即定死；「项目内切换 skill」须被显式拒绝（跨 skill 续写无意义）
10. `main.py`（~3030 行）本次不拆——新逻辑全部进独立模块，gongwen 稳定后再按域拆路由
11. 提示词预设/模板库仍 PPT 形态（`page_range`、PPTX 上传），v1 保持 PPT 专属；前端对非 ppt 隐藏对应入口；gongwen 若要预设，后续迁移加 `PromptSnippet.skill_id`
12. worker 安全姿态（只读 rootfs/tmpfs/符号链接拒绝）对 gongwen 原样生效，skill 必须遵守同一 `/workspace/project` 纪律
