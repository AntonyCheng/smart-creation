# 文种子类型与内容要素

在文种路由通过后使用本规则确定 `document_subtype` 和 `content_facts`。子类型用于选择内容结构，不改变 GB/T 9704—2012 版式类别。不得从示例补造事实。

| 文种 | 子类型 | 必备内容事实 |
| --- | --- | --- |
| 决议 | 审议通过、重大事项、修改废止 | 会议召开、表决通过、议决事项 |
| 决定 | 决策部署、奖惩、处置、变更撤销 | 决定事项、执行要求；奖惩须有已核实事实 |
| 命令（令） | 公布规章、重大行政措施、嘉奖 | 发布权限、命令事项；前两类还需施行日期 |
| 公报 | 会议公报、事项公报、统计公报 | 公布主题、权威结果或事项及来源 |
| 公告 | 法定事项、重要事项、公开事项 | 公开范围、公告事项、权限或事实来源 |
| 通告 | 周知事项、禁止限制、管理措施 | 适用范围、期限或边界、遵守要求 |
| 意见 | 指导性、实施性、处理性 | 指导原则、处理办法、职责边界 |
| 通知 | 部署、会议培训、转发批转、任免、事项告知 | 对象、事项、执行要求；会议培训另需时间、地点、参加对象 |
| 通报 | 表彰、批评、情况、事故事件 | 经核实事实、评价或定性、处理或后续要求 |
| 报告 | 工作、情况、答复、专项 | 报告事实、进展或成果；答复类关联上级询问；不得请求批准 |
| 请示 | 请求指示、请求批准 | 唯一请示事项、事项数量为1、主送唯一 |
| 批复 | 同意、不同意、原则同意并附条件 | 原请示、明确结论、逐项答复、执行要求或条件 |
| 议案 | 法规草案、重大事项、任免事项 | 提案权限、审议请求、议案事项 |
| 函 | 商洽、询问、请批、答复 | 函件事项；答复类关联原函；请批类明确审批请求 |
| 纪要 | 党委会议、办公会议、专题会议、协调会议 | 会议已召开、会议基本信息、真实议定事项 |

## 子类型处理

- 用户明确且合法的子类型优先。
- 可由业务事实唯一判断时由路由脚本推荐，例如培训安排为“通知/会议培训”，平行机关请批为“函/请批”。
- 无法唯一判断且不影响正文结构时，可使用文种通用结构并在审核单提示。
- 会改变必备事实、结语或来文关系时，必须一次追问一个问题。

## `content_facts`

将用户资料中已明确的内容转换为结构化事实。布尔值必须来自明确资料，不能因文种需要而设为 `true`。推荐字段包括：

- 会议类：`meeting_held`、`meeting_adopted`、`meeting_info`、`adopted_matters`、`agreed_matters`。
- 权限类：`authority_confirmed`、`order_matter`、`deliberation_request`、`effective_date`。
- 部署类：`target_audience`、`tasks_or_matters`、`execution_requirements`、`responsibility_boundaries`。
- 活动类：`event_time`、`event_location`、`participants`。
- 请求答复类：`request_matter`、`request_count`、`decision_outcome`、`responded_item_ids`、`correspondence_matter`。
- 事实成果类：`reported_facts`、`results_or_progress`、`evaluation`、`follow_up_requirements`、`published_results`。

运行 `scripts/validate_content.py 输入.json`。存在 `blocking` 时不得生成；`important` 写入审核单并在草稿使用明确占位符；`optimization` 可在不改变事实含义的前提下自动修正。

