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
