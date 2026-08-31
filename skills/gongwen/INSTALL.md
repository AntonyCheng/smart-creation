# 智能公文生成：本地安装与分享

本包是完整的技能源码和资源，不是独立聊天软件，也不含模型服务。

## 安装到 Codex 项目

1. 将整个 `intelligent-official-document-generation` 文件夹放入目标项目的 `.agents/skills/` 目录，保留所有子目录。
2. 使用 Python 3.9 或更新版本，运行下面的命令，将路径替换为本机真实路径：

```text
python3 <技能目录>/scripts/setup_local.py --output <项目输出目录的绝对路径>
```

此命令创建本机专用 runtime.json，不联网、不安装字体、不覆盖已有配置。不要把 runtime.json 发给别人。若已存在配置，先检查其内容，勿盲目覆盖。

3. 在该项目下一轮对话调用 `$intelligent-official-document-generation`，中文显示名为“智能公文生成”。如果当前会话未刷新技能列表，可在同项目新开对话。
4. 输入主题、文种、行文关系和已确认事实。生成器依赖标准库；PDF/Excel/复杂Word资料提取、模型推理、页面渲染及附件下载由宿主提供。没有相应能力时应明确报告，而不是伪造处理结果。

## 字体与文件交付

Word 文档需使用：方正小标宋简体、仿宋_GB2312、黑体、楷体_GB2312、宋体。本包经用户确认附带这5份字体，打开assets/fonts中的字体文件逐一安装；安装后重启Word/WPS。脚本的 font_status 会在具备 fc-list 时检测，否则必须在 Word/WPS 或实际渲染器中确认。字体入包不等于所有电脑已加载，不将新宋体等替代字形冒充所需字体。

本地模式只生成实际路径，由 Codex 的文件链接/附件功能交付，不需要数字员工平台、员工ID或Token。其他宿主需按 `references/runtime-and-delivery.md` 适配，不会自动获得原单位的内部文件库。

## 验收范围

本包完成技能结构、Python语法、资源完整性及已修改函数的基础检查。按用户要求本轮不再生成15类公文，因此不将本包标为新一轮15类视觉验收通过。本地检查不代表字体在其他电脑已经安装，不代表所有 Word/WPS 版本的渲染一致。每份实际公文仍须核对事实、权限、附件完整性，并逐页检查。

其他数字员工平台可按其文件夹型Skill规则导入本ZIP（SKILL.md位于ZIP根目录），并按references/runtime-and-delivery.md配置运行和回传。包内不携带原员工ID、账号或内部文件库；带字体ZIP大于1MB，平台若有上传限制需管理员提供大文件导入方式，不能保证任意平台直接接受。

## 来源

文种结构及流程设计参考 Rimagination/gongwen-draft 和 KaguraNanaga/official-document-writing-skill，未将其中示例事实视为真实业务依据。保留用户提供的 GB/T 9704—2012 规范原件供核对。本包不替字体或第三方规范原件新增商业授权；分享后不得冒称对这些第三方资源享有独占权。
