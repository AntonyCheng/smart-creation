# 来文关联与依据追溯

仅在答复类公文、引用政策依据、使用重要事实或数字时读取本文件。来源记录只用于校验和对话审核单，不得写入正式公文正文。

## 原来文 `source_documents`

每条记录包含：

- `document_type`、`title`、`document_number`、`issuing_body`、`date`。
- `relationship`、`core_matter`。
- `pending_questions`：每项使用稳定 `id` 和原问题文本。
- `file_name`、`location`：上传材料中的文件名、条款或页码。

批复必须关联下级请示，答复函必须关联不相隶属机关来函，答复报告必须关联上级询问。正文使用 `content_facts.responded_item_ids` 对应全部待答复事项。资料未知但用户仍需草稿时，先创建含 `〔由用户单位填写〕` 的原来文记录并在审核单提示；不得猜测文号和内容。

## 依据 `evidence_items`

每条记录包含：

- `fact_key`、`claim`、`value`：它支持的事实或正文表述。
- `source_kind`：`user_input`、`uploaded_file`、`internal_library`、`pending_verification`。
- `file_name`、`document_number`、`location`：可取得时填写。
- `status`：`verified`、`unverified`、`pending`、`conflict`、`outdated`。

处理顺序：本次用户资料 > 内部专属文件库 > 正式规范。两个已核实来源对同一 `fact_key` 给出不同值时阻断生成；`conflict` 或 `outdated` 不得用于正文；`unverified` 或 `pending` 只能使用占位符并要求确认。正文出现政策依据时必须有对应依据记录。

