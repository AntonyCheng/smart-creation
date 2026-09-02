"""Per-skill outline planner prompts for the API's outline generation.

Each template receives pre-interpolated requirement values and must ask the
model for a JSON array using the platform's five canonical outline field
names (title / purpose / content / kind / notes) so one parse pipeline
serves every skill.
"""

from __future__ import annotations

PLANNER_PROMPTS: dict[str, str] = {
    "ppt-master": (
        "请为主题“{topic}”设计一份结构完整的演示文稿大纲。\n"
        "期望页数范围：{page_range}（仅作参考，请按内容完整性决定实际页数，不要为了凑足页数添加空泛页面）。\n"
        "使用场景：{scenario}；目标受众：{audience}；"
        "整体风格：{style}；核心目标：{objective}。\n"
        "请优先使用材料中的事实、数字、术语和结构，不要编造材料未提供的事实。"
        "返回 JSON 数组，每项字段为 title、purpose、content、kind、notes；"
        "第一项必须是主题页，返回你实际规划的全部页面，不要补齐到固定页数，也不要截断页面。"
    ),
    "gongwen": (
        "请为主题“{topic}”起草一份规范公文的写作提纲。\n"
        "文种：{doc_type}；发文机关：{issuer}；主送机关：{recipient}；"
        "篇幅要求：{word_range}；写作目的：{objective}；语言风格：{style}。\n"
        "提纲须符合公文体例：首项为文头（标题，可含文号与主送机关），"
        "正文按“开头（依据/目的）—主体（事项/情况）—结尾（要求/结语）”组织，"
        "末项为落款（发文机关署名与成文日期）。\n"
        "请优先使用材料中的事实、数字、时间、单位名称与规范表述，不要编造材料未提供的事实。"
        "返回 JSON 数组，每项字段为 title、purpose、content、kind、notes；"
        "返回你实际规划的全部部分，不要截断。"
    ),
}

# Default value for the "kind" field when the model omits it.
DEFAULT_KIND: dict[str, str] = {
    "ppt-master": "内容页",
    "gongwen": "正文",
}


def build_planner_prompt(skill_id: str, values: dict[str, str]) -> str:
    """Render the skill's planner prompt, failing loudly on unknown skills."""

    template = PLANNER_PROMPTS.get(skill_id)
    if template is None:
        raise KeyError(f"No outline planner prompt registered for skill {skill_id!r}")
    return template.format(**values)


def default_kind(skill_id: str) -> str:
    return DEFAULT_KIND.get(skill_id, "正文")


_ROLE_BY_SKILL: dict[str, str] = {
    "ppt-master": "演示文稿创作助手",
    "gongwen": "公文写作助手",
}


def _describe_field(field: dict) -> str:
    """Render one field's name/label/type/options as a prompt line."""

    name = str(field.get("name") or "")
    label = str(field.get("label") or name)
    field_type = str(field.get("type") or "text")
    options = field.get("options") or []
    max_length = field.get("max_length")
    if field_type == "select" and options:
        constraint = f"单选，必须严格取以下之一：{ '、'.join(str(item) for item in options) }"
    elif isinstance(max_length, int) and max_length > 0:
        constraint = f"文本，不超过 {max_length} 字"
    else:
        constraint = "文本"
    return f'- {name}（{label}，{constraint}）'


def build_requirements_prompt(
    skill_id: str,
    fields: list[dict],
    draft_text: str,
    *,
    is_typeset_content: bool = False,
) -> str:
    """Build a field-aware prompt that drafts an initial requirements guess.

    Generic over any mode's field list (manifest-driven for gongwen, a fixed
    equivalent list for ppt-master) so no per-skill prompt branching is
    needed here; the model fills what it can confidently infer and leaves
    the rest for the human confirmation step that always follows.
    """

    role = _ROLE_BY_SKILL.get(skill_id, "创作助手")
    field_lines = "\n".join(_describe_field(field) for field in fields)
    if is_typeset_content:
        source_description = (
            "以下是用户已经写好、即将直接排版的公文正文全文（不是需求描述，请通读全文识别版式线索）：\n"
            f"{draft_text[:6_000]}"
        )
    else:
        source_description = f"用户的原始输入（可能很简短）：\n{draft_text[:2_000]}"
    return (
        f"你是{role}，负责基于用户的输入为后续创作预填一份初步的结构化需求草稿，"
        "供用户在下一步逐项确认或修改，你的结果不是最终定稿。\n"
        f"{source_description}\n\n"
        "请为以下字段给出你能从输入中合理推断的取值；"
        "无法确定的具体细节（如具体单位名称、具体日期、具体数字）不要编造，"
        "宁可用简洁通用的表述或留空，也不要虚构不存在的事实：\n"
        f"{field_lines}\n\n"
        "只返回一个严格 JSON 对象，键为上面每个字段的英文字段名，值为字符串；"
        "不能推断的字段可以省略该键；不要返回 JSON 之外的任何文字，不要使用 Markdown 代码块。"
    )
