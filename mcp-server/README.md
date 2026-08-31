# PPT Master MCP Server

独立的 MCP 适配层，只调用 PPT Master 的 HTTP API，不直接访问主项目数据库、项目目录或 Docker Socket。第一版使用一个专用 PPT Master 服务账号；请为它授予创建项目和生成任务所需的普通用户权限。

## 工具

- `create_ppt_task`：从结构化字段和自然语言请求收集需求。`topic`、`audience`、`scenario`、`objective` 任一缺失时返回 `needs_clarification` 和追问；字段齐全后创建项目并异步提交任务。
- `get_ppt_task_status`：查询 `queued`、`running`、`succeeded`、`failed`、`cancelled`。成功时下载 PPTX 到 MCP 临时存储并返回短时 `download_url`。
- `retry_ppt_task`：`cancelled` 调用主项目的检查点继续接口；`failed` 创建以原任务为 `base_job_id` 的新任务。原任务始终不变。

## 本地 stdio

```powershell
cd C:\projects\ppt-master\mcp-server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env，填写 PPTMASTER_USERNAME/PPTMASTER_PASSWORD
.venv\Scripts\python.exe server.py
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "ppt-master": {
      "command": "C:/projects/ppt-master/mcp-server/.venv/Scripts/python.exe",
      "args": ["C:/projects/ppt-master/mcp-server/server.py"]
    }
  }
}
```

## 远程 Streamable HTTP

设置 `MCP_TRANSPORT=streamable-http`、`MCP_HOST=0.0.0.0`、高熵 `MCP_API_KEY`，并将 `MCP_PUBLIC_BASE_URL` 设置为远程 Agent 可访问的地址。客户端使用 `/mcp?api_key=...` 或 `Authorization: Bearer ...` 连接；下载链接位于 `/downloads/<token>`，不包含 MCP 密钥且默认 15 分钟过期。生产环境应在反向代理上启用 HTTPS，并限制来源网络。

```powershell
python server.py
```

## Docker

The recommended deployment path is the root Compose stack. Keep the MCP
credentials in `mcp-server/.env`; Compose overrides `PPTMASTER_API_URL` with
the private `pptmaster-api:8000` address automatically.

```powershell
cd C:\projects\ppt-master
docker compose --env-file docker/.env -f docker/compose.yml up -d --build pptmaster-mcp
docker compose --env-file docker/.env -f docker/compose.yml logs -f pptmaster-mcp
```

Temporary download files are bind-mounted at `docker/data/mcp-artifacts/`.
Set `PPTMASTER_MCP_PORT` in `docker/.env` to change the host port; Windows
often reserves the `6880-7990` range, so `8010` is the default. Stop any
previous standalone `docker run` container named `pptmaster-mcp` before the
first Compose start.

The following standalone command remains useful only for local diagnosis:

```powershell
docker build -t ppt-master-mcp .
docker run --rm --env-file .env -p 7010:7010 -v ppt-master-mcp-artifacts:/app/artifacts ppt-master-mcp
```

容器中的 `PPTMASTER_API_URL` 必须使用主 API 在容器网络中的地址，例如 Compose 服务名，而不是 `127.0.0.1`。
