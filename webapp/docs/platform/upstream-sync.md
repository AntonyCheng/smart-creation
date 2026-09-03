# 上游 ppt-master 同步手册

本仓库的 `skills/ppt-master/` 源自上游开源项目 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)。平台分支不合并上游分支，更新一律走手动拷贝。

## 同步单元

| 上游路径 | 本仓库路径 | 方式 |
| --- | --- | --- |
| `skills/ppt-master/`（整目录） | `skills/ppt-master/` | 覆盖拷贝（robocopy /MIR） |
| `docs/rules/` | `docker/agent/docs/rules/` | 手动 diff 后择优合并 |
| `docs/audio-narration.md` | `docker/agent/docs/audio-narration.md` | 覆盖拷贝 |
| `AGENTS.md` | `AGENTS.md` | 以上游为基线，重新叠加定制（见下） |

规则文件放在 `docker/agent/docs/`（不是仓库根 `docs/`），因为 `docker/Dockerfile.runner` 只 `COPY docker/agent/docs /app/docs`，运行时为 `/app/docs/rules`。

其余上游文件（根 README、宣传页、examples 更新等）**不拷贝**。上游用户文档（FAQ、installation 等）如需要，手动挑拣进 `docker/agent/docs/`。

## AGENTS.md 定制点（每次同步必须重新叠加）

以上游 `AGENTS.md` 为基线，重做这 4 处：

1. 顶部 `## Skill routing` 段（ppt-master / gongwen 分发）
2. 所有 `docs/rules/xxx` 链接改写为 `docker/agent/docs/rules/xxx`，并保留“baked into the runtime as `/app/docs/rules`”说明
3. `Compatibility Boundary` 改为多 skill + web 平台措辞
4. `Core Directories` 增加 `skills/gongwen/SKILL.md` 与 `webapp/docs/`，替换上游 `docs/` 用户文档条目

## 关于 skills/ppt-master/README.md

上游已把该 README 移到仓库根，skill 目录内不再有此文件；本仓库直接跟随删除，不恢复。

平台侧 manifest 位于 `webapp/skills/ppt-master/skill.manifest.json`，不在 `skills/` 内，天然不受同步影响。

## 操作步骤

1. 克隆或下载上游最新代码到临时目录。
2. 删除本仓库 `skills/ppt-master/`，将上游 `skills/ppt-master/` 整目录拷入。
3. 恢复受保护文件（见上表）。
4. `git diff` 审查变更，重点关注：
   - `scripts/project_manager.py` 及 `scripts/project_management/` 的 CLI 参数变化（manifest 的 `workspace.init.command` 可能需要跟着改）
   - `SKILL.md` 路由结构变化（Quick Generate 入口是否存在）
   - `requirements.txt` 变化（worker 镜像重建后生效）
5. 重建镜像并回归：

```bash
cd docker && ./bin/compose.sh up -d --build
```

PPT 全链路回归：登录 → 建项目 → 大纲 → 生成 → 编辑器保存 → 导出，产物与事件流正常即可。
