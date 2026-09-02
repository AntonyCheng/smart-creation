# 模板导入管线

平台"上传 PPTX → 可复用模板"的完整链路。所有解析逻辑都委托给 `skills/ppt-master` 的脚本，平台侧只负责调度、产物落地与用户可见的透明化。

## 队列隔离

- `runner.import_template` 通过 celery `task_routes` 固定路由到 `pptmaster-template-imports` 队列（见 `webapp/runner/celery_app.py`）。
- `docker/bin/start-runner.sh` 在同一 runner 容器内启动两个 celery worker（各并发 1）：`pptmaster-jobs` 消费生成任务，`pptmaster-template-imports` 消费模板导入。导入含 AI 评审，耗时数分钟，与生成队列互不阻塞。
- 队列路由改动的生效条件：修改 `celery_app.py` 或 `start-runner.sh` 后需重建 runner 镜像并重建容器。

## worker 阶段（webapp/worker/template_import.py）

| 阶段 | 动作 | 产出 |
| --- | --- | --- |
| extracting | `pptx_template_import.py <src> --output import/ --inheritance-mode both` | `import/analysis/manifest.json`、`import/svg/`、`import/authoring-svg/`（分层可编辑视图 + `authoring_summary.json`）、`import/authoring-svg-flat/`、`import/validation/conversion-report.json` |
| materializing | `mirror_template_materialize.py`（在容器本地 tmpfs 上运行后拷回） | `deck/templates/NNN_*.svg`、`template_execution_manifest.json`、`*.text-slots.json`、`source_themes.json`、`native_payloads` |
| skeleton spec | `_write_template_spec` 写确定性骨架 `deck/templates/design_spec.md`（frontmatter 含 `replication_mode: mirror`） | 语义评审失败时的兜底 spec |
| semantic_review | 若 runner 下发了默认模型配置（`PPTMASTER_OPENCODE_CONFIG_JSON`），运行一次有界 `opencode run` | 覆写 spec 正文：中文、create-deck §2 章节结构、页面角色/槽位/容量、母版-版式关系、降级对象说明、占位符重建建议 |
| preview | `soffice --headless --convert-to pdf` + `pdftoppm -png -r 96` | `deck/preview/NNN_*.png`（浏览器 `<img>` 无法解析 SVG 内的 `../images` 引用，PNG 预览保证像素忠实；失败只告警不失败导入） |
| summarizing | `_build_import_report` 汇总 conversion-report 与 manifest 占位符 | 汇总键（见下） |

注意：`pptx_template_import.py --inheritance-mode both` 自身已产出分层 `authoring-svg/`，worker **不再**单独调用 `svg_authoring_view.py`（重复投影会因目录已存在而失败）。

## 结果汇总键（Template.meta）

runner 将 worker 的 result 汇总整体并入 `Template.meta`：

- `preview_files` / `preview_files_png`：SVG 与 PNG 预览的 workspace 相对路径；前端优先使用 PNG（`templatePreviewFiles`）。
- `import_report`：`warning_count`、`losses`（按诊断码聚合的保真丢失，附中文标签与样本消息）、`normalizations`（`*-normalized` 的良性自动修正）、`slides_affected`、`placeholders`（按语义角色/类型计数）。前端在模板详情"导入保真度"区域展示。
- `page_count`、`colors`、`fonts`、`source_manifest`（`import/analysis/manifest.json`）。

## 语义评审的边界

- 评审 agent 只允许覆写 `deck/templates/design_spec.md`；prompt 禁止改动任何 SVG、图片、native payload 与机器清单（导入后以文件 mtime 复核）。
- 骨架 spec 始终先落盘；agent 超时/失败/输出过短时保留骨架，导入不失败。
- 复用生成任务的默认模型（`SystemSetting("default_model_id")`，`_template_review_opencode_config`），空闲超时沿用平台配置 `PPTMASTER_OPENCODE_IDLE_TIMEOUT_SECONDS`。

## 验证记录（2026-09-02）

- runner 镜像含 `libreoffice-draw` + `poppler-utils`，`soffice`/`pdftoppm` 可用。
- 真实 PPTX E2E：导入成功（2 页），PNG 预览经文件接口取回为有效 PNG；`import_report` 各键齐全；spec 为中文语义版且 frontmatter 保持 `replication_mode: mirror`、`page_count` 正确；除 `design_spec.md` 外无文件被 agent 改动。
- 双 worker 启动日志确认两个队列各就位；`runner.execute_job` 落在 `pptmaster-jobs`，与导入互不影响。
