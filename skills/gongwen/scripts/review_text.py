#!/usr/bin/env python3
"""Independent text review for Chinese official-document drafts."""

import argparse
import json
import re
from pathlib import Path

from validate_content import blocks_text


EMPTY_SLOGANS = ("高度重视", "全面落实", "切实加强", "扎实推进", "狠抓落实")
COLLOQUIAL = ("搞定", "给力", "打call", "点赞", "小伙伴", "抓手中的抓手")
ABSOLUTE = ("百分之百", "绝对不会", "彻底杜绝", "完全消除", "确保零风险")
UNSOURCED_POLICY = ("贯彻落实国家", "贯彻落实上级", "根据有关文件精神", "按照相关政策要求")


def review_text(data):
    issues = {"blocking": [], "important": [], "optimization": []}

    def add(level, code, message, excerpt=""):
        issues[level].append({"code": code, "message": message, "excerpt": excerpt})

    text = str(data.get("text") or "") or blocks_text(data)
    title = str(data.get("title") or "")
    doc_type = str(data.get("document_type") or "")
    if not text.strip():
        add("blocking", "empty_text", "待审校正文为空")
        return {"ok": False, "issues": issues, "meta": {"characters": 0}}

    if doc_type and doc_type != "命令（令）" and title and doc_type not in title:
        add("important", "title_type_mismatch", "标题未体现所选文种", title)
    for phrase in UNSOURCED_POLICY:
        if phrase in text and not data.get("policy_basis"):
            add("blocking", "unsourced_policy", "检测到无来源政策表述", phrase)
    if doc_type == "报告" and re.search(r"请(?:批准|批复|审定|指示)|妥否[，,]请批示|是否同意", text):
        add("blocking", "report_contains_request", "报告疑似夹带请示事项")

    for match in re.finditer(r"[\u4e00-\u9fff][,:;!?][\u4e00-\u9fff]", text):
        add("optimization", "ascii_punctuation", "中文语句中使用了半角标点", match.group(0))
    for phrase in COLLOQUIAL:
        if phrase in text:
            add("important", "colloquial_expression", "存在口语化或网络化表达", phrase)
    for phrase in ABSOLUTE:
        if phrase in text:
            add("important", "absolute_expression", "存在缺少依据的绝对化表述", phrase)
    for phrase in EMPTY_SLOGANS:
        if text.count(phrase) > 1:
            add("optimization", "repeated_slogan", "套话重复出现，应结合具体措施精简", phrase)

    sentences = [item.strip() for item in re.split(r"[。！？\n]", text) if len(item.strip()) >= 6]
    seen = set()
    for sentence in sentences:
        if sentence in seen:
            add("optimization", "duplicate_sentence", "检测到重复句", sentence[:40])
        seen.add(sentence)

    headings = []
    for line in text.splitlines():
        match = re.match(r"^([一二三四五六七八九十]+)、", line.strip())
        if match:
            headings.append("一二三四五六七八九十".index(match.group(1)[0]) + 1)
    if headings and headings[0] != 1:
        add("important", "heading_starts_wrong", "第一层次标题没有从“一、”开始")
    if any(current > previous + 1 for previous, current in zip(headings, headings[1:])):
        add("important", "heading_gap", "第一层次标题存在跳号")

    endings = {
        "请示": ("妥否，请批示", "以上请示，请予批复"),
        "报告": ("特此报告",),
        "批复": ("此复",),
    }
    if doc_type in endings and not any(ending in text for ending in endings[doc_type]):
        add("optimization", "ending_phrase", f"建议核对{doc_type}的规范结语")

    length = len(re.sub(r"\s+", "", text))
    limit = data.get("length_limit")
    minimum = maximum = None
    if isinstance(limit, int):
        maximum = limit
    elif isinstance(limit, dict):
        minimum, maximum = limit.get("min"), limit.get("max")
    if isinstance(minimum, int) and length < minimum:
        add("important", "below_length_limit", f"正文约{length}字，低于要求下限{minimum}字；不得通过虚构内容补足")
    if isinstance(maximum, int) and length > maximum:
        add("blocking", "above_length_limit", f"正文约{length}字，超过上限{maximum}字")

    return {"ok": not issues["blocking"], "issues": issues, "meta": {"characters": length}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="UTF-8 text or JSON file")
    args = parser.parse_args()
    path = Path(args.input)
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {"text": raw}
    except json.JSONDecodeError:
        data = {"text": raw}
    result = review_text(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
