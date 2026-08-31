# 智创AI助手

多技能 AI 创作平台。当前托管两类创作能力，均以可插拔 skill 形式接入：

| Skill | 目录 | 产物 |
| --- | --- | --- |
| PPT 创作（ppt-master） | `skills/ppt-master/` | 原生可编辑 PPTX + 逐页 SVG 预览 |
| 公文写作（gongwen） | `skills/gongwen/` | GB/T 9704 公文 DOCX + PDF + 逐页排版预览 |

用户在前端通过工作类型开关选择技能；平台后端由 [skill manifest](webapp/docs/platform/multi-skill-platform-plan.md) 驱动，接入新 skill 无需修改平台代码。

## 仓库结构

```
skills/      可插拔 AI skill（每个子目录一个完整 skill，含 SKILL.md 与脚本）
webapp/      平台：api/（FastAPI）+ runner/（Celery + 常驻 Agent 运行时）+ worker/（任务驱动与 skill 适配器）+ frontend/（React）
docker/      Compose 编排（web / runner 两个镜像）；agent/ 存放烤入运行时的 agent 规约文档
mcp-server/  MCP 门面，转调平台 REST API
projects/    本地直跑 skill 的运行时输出（gitignored；平台运行时使用 docker/data/projects）
webapp/docs/ 平台文档（多 skill 架构、skill 接入契约）
```

任务执行模型：runner 是常驻 Agent 运行时（OpenCode + 全部 skill + LibreOffice 渲染），每个任务以受限子进程运行，不再按任务启动容器。

## 快速开始

```bash
cd docker
./bin/compose.sh up -d --build   # 首次构建包含前端与全部 skill
```

访问 `http://localhost:8080`。管理员在「系统管理 → 模型」中配置并验证 OpenAI 兼容模型后即可创建任务。

## 平台架构与 skill 接入

- 平台多 skill 架构与改造方案：[webapp/docs/platform/multi-skill-platform-plan.md](webapp/docs/platform/multi-skill-platform-plan.md)
- 上游 ppt-master 同步手册：[webapp/docs/platform/upstream-sync.md](webapp/docs/platform/upstream-sync.md)
- 公文 skill 接入契约：[webapp/docs/platform/skill-contract.md](webapp/docs/platform/skill-contract.md)

## 管理约定

- 根 `AGENTS.md` 是 agent 入口；`docker/agent/docs/rules/` 是仓库级风格规则（烤入 worker 镜像为 `/app/docs/rules`，对所有 skill 生效）。
- `skills/ppt-master/` 内部保持与上游一致（除 `README.md`），更新走手动拷贝，见同步手册。
- 根 `requirements.txt` 归 ppt-master skill 所有且被指纹校验，位置不可移动；worker 镜像专属依赖放 `docker/worker-requirements.txt`。
