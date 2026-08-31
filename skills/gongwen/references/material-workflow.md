# 材料抽取与组稿

处理 Word、PDF、Excel、会议记录或用户文本时，先使用平台可用的文件读取工具提取文本、表格和元数据，再形成 `materials`。脚本本身不绕过平台权限读取未知文件。

每份材料包含 `file_name`、`file_type`、`source_kind`、`parsed_text` 和 `facts`。每条事实包含：

- `key`：跨材料稳定事实键，例如 `training_date`。
- `category`：`time`、`place`、`person`、`organization`、`task`、`number`、`problem`、`decision`、`judgment`、`suggestion`。
- `value`、`location`。
- `origin`：`fact`、`judgment`、`suggestion`、`pending`。

运行 `scripts/analyze_materials.py 输入.json`：

- 同一事实键出现不同已确认值时阻断，不自动择一。
- `judgment`、`suggestion`、`pending` 不得直接写成已确认事实。
- 仅将用户确认或有明确来源的事实转换为 `content_facts` 和 `evidence_items`。
- PDF、Word、Excel 未被平台工具成功解析时停止，不静默丢失内容。

