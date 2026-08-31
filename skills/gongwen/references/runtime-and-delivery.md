# 安装和交付适配

脚本仅依赖Python 3.9+标准库；Word/PDF/Excel提取、字体安装、页面渲染和文件回传由宿主提供。必须整目录安装，不能只复制SKILL.md。assets/base.docx为必需的OOXML容器，规范PDF为用户提供的参考原件，不删除。

将runtime.example.json复制为runtime.json并配置。平台模式须从当前员工页面或已授权配置取得agent_id、output_root、api_path_prefix，不能从示例或历史会话反推。runtime.json不含Token；令牌不得写入Skill、日志、JSON或分享包。

平台示意（不是可直接复用的真实配置）：

```json
{"delivery_mode":"platform","agent_id":"由安装者填写当前员工ID","output_root":"/当前平台实际工作区/drafts","api_path_prefix":"workspace/drafts"}
```

local模式配置绝对output_root、delivery_mode为local；脚本返回实际文件路径，不制造URL。调用宿主支持的附件机制提供下载；不支持则如实报告，不能输出虚假附件卡。

宿主使用任务专属字体配置时，可选填写fontconfig_file为实际存在的fontconfig XML绝对路径；字体核验及渲染必须使用同一配置。配置只指向管理员已准备的字体目录，不更改系统默认字体，不把别的字形alias成所需字体。运行期不下载字体。字体资源存在于Skill文件区，不代表execute_code沙箱可读取；安装者须将资源放到本员工获准的工作区并实测，不能扫描或访问沙箱以外目录。

prepare_draft返回ok只表示已实现的文种/内容规则与OOXML结构通过，视觉和下载默认not_performed。每次使用UUID子目录，不覆盖同名历史文件。validation-receipt.json只供内部核验；download_link.py --receipt <路径>可在需要恢复交付时验证DOCX哈希后重新得到链接，正常流程无需额外调用。

平台文件回传：prepare一次 → send_channel_file一次 → 审核单和同次候选链接。发送成功只能证明工具接收成功，不等于浏览器HTTP已验证；端到端验收必须实际下载、检查文件内容哈希和ZIP完整性，普通会话无HTTP验证能力时不得声称已验证。

中文文件名URL必须编码；文件名保留“标题（草稿）.docx”。链接不可包在代码块、反引号内。候选链接不含账户凭据，不能假定它能在未登录或不同租户下公开访问。

字体要求：标题小标宋、正文仿宋、一级黑体、二级楷体、页码宋体。当前生成器使用方正小标宋简体、仿宋_GB2312、黑体、楷体_GB2312、宋体；本次经用户确认随包提供5份字体，来源见assets/fonts/SOURCES.md。使用方安装所附字体；运行时不下载字体，不以字体名称写入成功替代实际渲染。字体未知/缺失时最多一次环境检查，不循环搜索或改成其他字体后冒称国标通过。

清理共享包时排除__pycache__、.pyc、.DS_Store、历史输入JSON、输出DOCX、日志、Token及本单位runtime.json。保留runtime.example.json。测试及备份保存在Skill目录之外，便于回滚。
