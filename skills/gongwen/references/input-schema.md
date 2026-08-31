# DOCX 生成输入

将输入保存为 UTF-8 JSON。下列示例仅说明字段结构，任何示例值都不是单位默认配置；实际生成时必须逐字采用用户本次提供的值，尤其不得把示例中的“办公室”复制到 `issuer_mark`、`issuing_body` 或 `issuer`。

下面示例仅说明接口，不能把示例事实当作真实用户资料。按source-evidence.md记录原资料，完成逐项事实核对。日常生成统一调用prepare_draft.py；保留已有文种、内容、证据和材料冲突检查，不以结构检查代替语义审校。

法定公文示例：

```json
{
  "official_document": true,
  "document_type": "通知",
  "document_subtype": "会议培训",
  "direction": "downward",
  "layout_profile": "standard",
  "type_selection": {
    "requested_type": "通知",
    "purpose": "deploy_execute",
    "relationship": "downward",
    "expected_action": "execute",
    "audience": "named_recipients",
    "incoming_type": "",
    "meeting_adopted": false,
    "meeting_held": false,
    "agreed_matters_confirmed": false,
    "authority_confirmed": false,
    "decision_level": "ordinary"
  },
  "content_validation_required": true,
  "content_facts": {
    "target_audience": "相关业务人员",
    "tasks_or_matters": ["开展人工智能办公能力提升培训"],
    "execution_requirements": ["按时报名", "遵守培训纪律"],
    "event_time": "2026年9月6日8:00",
    "event_location": "XX机关楼三楼306室",
    "participants": "相关业务人员"
  },
  "source_documents": [],
  "evidence_items": [
    {"fact_key": "event_time", "claim": "培训时间", "value": "2026年9月6日8:00", "source_kind": "user_input", "status": "verified"}
  ],
  "draft_depth": "标准",
  "length_limit": {"min": 600, "max": 1000},
  "revision_mode": "规范修订",
  "material_analysis_required": false,
  "text_review_required": true,
  "materials": [],
  "user_contract": {
    "document_type": "通知",
    "document_subtype": "会议培训",
    "direction": "downward",
    "issuer_mark": "XX单位办公室文件",
    "document_number": "发文字号：〔由用户单位填写〕",
    "title": "关于开展有关工作的通知",
    "recipient": "各部门、各下属单位",
    "blocks": [
      {"type": "body", "text": "现将有关事项通知如下。"},
      {"type": "heading1", "text": "一、工作安排"},
      {"type": "body", "text": "具体内容。"}
    ],
    "attachments": ["有关工作安排表"],
    "issuing_body": "XX单位办公室",
    "issuer": "XX单位办公室",
    "date": "〔成文日期由用户单位填写〕",
    "seal_requirement": "not_required",
    "signatory": "",
    "signer_title": "",
    "signer_name": "",
    "proposer_title": "",
    "proposer_name": "",
    "copy_to": "〔抄送机关由用户单位填写〕",
    "printing_authority": "XX单位办公室",
    "print_date": "〔印发日期由用户单位填写〕"
  },
  "issuer_mark": "XX单位办公室文件",
  "document_number": "发文字号：〔由用户单位填写〕",
  "title": "关于开展有关工作的通知",
  "recipient": "各部门、各下属单位",
  "recipient_in_edition": false,
  "blocks": [
    {"type": "body", "text": "现将有关事项通知如下。"},
    {"type": "heading1", "text": "一、工作安排"},
    {"type": "body", "text": "具体内容。"}
  ],
  "attachments": ["有关工作安排表"],
  "issuing_body": "XX单位办公室",
  "issuer": "XX单位办公室",
  "date": "〔成文日期由用户单位填写〕",
  "note": "",
  "seal_requirement": "not_required",
  "copy_to": "〔抄送机关由用户单位填写〕",
  "printing_authority": "XX单位办公室",
  "print_date": "〔印发日期由用户单位填写〕"
}
```

## 核心字段

- `document_type`：15种法定文种之一，必填。
- `document_subtype`：文种子类型。合法值及必备事实见 `document-subtypes.md`；不明确且不影响结构时可留空并在审核单提示。
- `type_selection`：新起草法定公文必填，用于在生成前核验文种，不用于版面展示。字段包括：
  - `requested_type`：用户指定的文种；用户未指定时留空。
  - `purpose`：`meeting_resolution`、`important_decision`、`issue_regulation`、`authoritative_release`、`public_announcement`、`scope_compliance`、`policy_guidance`、`deploy_execute`、`praise_criticize`、`important_situation_broadcast`、`report_work`、`report_situation`、`answer_superior_inquiry`、`request_approval`、`request_instruction`、`reply_request`、`npc_submission`、`consult_coordinate`、`inquire_reply`、`meeting_record` 之一。
  - `relationship`：`upward`、`downward`、`parallel`、`public`、`meeting` 或 `npc`；请求批准时必须明确 `upward` 或 `parallel`。
  - `expected_action`：`approve`、`instruct`、`execute`、`know`、`reply`、`comply`、`deliberate` 或 `none`。
  - `audience`：`named_recipients`、`public_broad`、`defined_scope` 或 `meeting_participants`。
  - `incoming_type`：答复类公文填写原来文文种；批复必须为 `请示`，复函填写 `函`。
  - `meeting_adopted`：仅用于决议，表示事项已经会议讨论并表决通过，必须据实填写。
  - `meeting_held`、`agreed_matters_confirmed`：用于纪要，分别表示会议确已召开、确已形成议定事项；二者均须据实为 `true`，不得用来虚构会议事实或结论。
  - `authority_confirmed`：命令（令）和议案必须据实为 `true`；权限不明时停止生成并追问。
  - `decision_level`：`ordinary` 或 `major`，用于区分一般部署通知与重大决策决定。
- 生成前运行 `scripts/select_document_type.py`；脚本推荐的文种、行文方向和版式必须与 `document_type`、`direction`、`layout_profile` 一致。现有 Word 的纯格式审校可不提供 `type_selection`，但如需改判文种则必须提供。
- `content_validation_required`：新起草或改写正文时为 `true`；现有 Word 纯格式重排时可为 `false`。
- `content_facts`：从用户资料中提取的结构化事实。不得因为某文种需要某要素就凭空填写；字段说明见 `document-subtypes.md`。
- `source_documents`：批复、答复函、答复报告的原来文数组，包含文种、标题、文号、机关、日期、待答复事项和材料位置，详见 `source-evidence.md`。
- `evidence_items`：政策依据、关键事实和数字的追溯记录，只用于校验和对话审核单，不写入 Word 正文，详见 `source-evidence.md`。
- `draft_depth`：`精简`、`标准`、`详尽`；未指定时新稿默认 `标准`。
- `length_limit`：正整数上限，或包含 `min`、`max` 的对象。不得通过虚构内容满足下限。
- `revision_mode`：`保守修订`、`规范修订`、`深度修订`。现有 Word 审校默认 `规范修订`，纯格式重排默认 `保守修订`。
- `materials`：平台文件工具已提取的 Word、PDF、Excel、会议记录或文本材料及结构化事实。多材料任务设置 `material_analysis_required: true`；没有材料时为 `false`。
- `text_review_required`：新起草和正文修订时为 `true`，调用 `review_text.py`；纯格式重排可为 `false`。
- `user_contract`：新起草法定公文必填，字段以生成器USER_CONTRACT_FIELDS为准，空值也保留。用于防止传参阶段的无意改写，不证明内容来自用户；事实来源须独立对照原始用户资料核验，不能由user_contract反向证明。用户要求原样使用的正文不得改写。禁止旧字段postscript，附件说明使用attachments。
- `direction`：`upward`、`downward` 或 `parallel`。报告、请示通常为 `upward`；函必须为 `parallel`。
- `layout_profile`：`standard`、`command`、`letter`、`minutes`。命令（令）、函、纪要分别使用后三种，其他法定文种使用 `standard`。
- `issuer_mark`、`document_number`、`title`、`recipient`：版头与标题要素；无主送机关的文种将 `recipient` 留空。
- `recipient_in_edition`：仅在主送机关过多、导致首页不能显示正文时设为 `true`，将 `recipient` 移入版记；主送与抄送之间不加分隔线。
- `blocks`：正文顺序。类型可为 `body`、`noindent`、`center`、`heading1`、`heading2`、`heading3`、`heading4`、`note`。
- `title_lines`：长标题的语义分行数组，每行按完整词组分开；所有行拼接必须逐字等于title。脚本检查22pt下行宽，最终仍须渲染检查。不能拆开“培训”等完整词组或添加/删除标题字符。
- `attachments`：附件说明数组；没有附件时留空数组。
- `attachment_documents`：可选附件正文数组。每项包含与附件说明一致的 `title` 和 `blocks`；生成器将其另面排在版记之前。没有用户提供的附件正文时不得填写。
- `issuing_body`：仅记录用户明确说明的“发文主体”；用户未提供时留空，不得从标题、发文机关标志、署名或印发机关反推。
- `issuer`：发文机关署名。用户明确提供时逐字使用，不要求它与标题中的机关称谓、`issuer_mark` 或 `issuing_body` 完全同名。无印章单一机关行文时，与成文日期按两行文字长度联动对齐；不得从 `printing_authority` 复制或推导。
- 用户输入“发文主体、发文机关标志、发文机关署名、印发机关”时，分别映射到 `issuing_body`、`issuer_mark`、`issuer`、`printing_authority`；四个字段彼此独立，不得混用或替换。
- `date`：成文日期，使用完整阿拉伯数字年月日，如 `2026年8月20日`；未知时使用明确占位。编排在署名下一行，首字比署名首字右移二字；日期长于署名时日期右空二字，并相应调整署名。
- `note`：可选附注；写入成文日期下一行，自动使用圆括号并左空二字。
- `seal_requirement`：`required` 或 `not_required`。`required` 只选择加盖印章公文的落款版式并预留盖章位置，DOCX 中仍不得生成印章图片；`not_required` 使用无印章落款规则。用户未说明时不得凭文种随机推断。
- `copy_to`、`printing_authority`、`print_date`：版记要素；`printing_authority` 是印发机关，通常为办公室或办公厅，不等于发文机关署名。只使用用户资料或单位配置，缺少时使用明确占位或不生成对应可选行。版记末条分隔线必须与最后一面版心下边缘重合，不得与页码重叠。
- `adoption_line`：决议等文种的会议通过信息，资料明确时使用。

## 签发与专用签署

- `signatory`：仅用于上行文版头；报告、请示或明确的上行意见在用户提供姓名时使用。非上行文禁止设置。
- 命令（令）使用 `signer_title`、`signer_name`，不得设置 `signatory`。
- 议案使用 `proposer_title`、`proposer_name`，不得设置 `signatory`。
- 纪要可使用 `attendees`、`nonvoting_attendees`；“出席”“列席”用黑体，名单用仿宋。
- 信函的 `printing_authority`、`print_date` 必须留空；信函版记不含这两个要素和分隔线，且首页不显示页码。
- 禁止输入 `stamp`、`seal`、`signature_image`、`approval_status`；是否需要盖章只能通过 `seal_requirement` 表达。

## 输出

- 文件名必须为 `公文标题（草稿）.docx`。
- 统一调用 `prepare_draft.py 输入.json`（配置见runtime-and-delivery.md）。结构检查ok仅代表已实现的OOXML规则通过；未完成字体和逐页视觉检查时不得称全面符合国标。
