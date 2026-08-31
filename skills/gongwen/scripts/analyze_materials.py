#!/usr/bin/env python3
"""Normalize material facts and detect cross-source conflicts without external dependencies."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


CATEGORIES = {"time", "place", "person", "organization", "task", "number", "problem", "decision", "judgment", "suggestion"}
ORIGINS = {"fact", "judgment", "suggestion", "pending"}
SOURCE_KINDS = {"user_input", "uploaded_file", "internal_library"}


def heuristic_facts(text):
    results = []
    counters = defaultdict(int)
    patterns = (
        ("time", r"\d{4}年\d{1,2}月\d{1,2}日(?:\s*\d{1,2}[:：]\d{2})?"),
        ("time", r"\d{1,2}[:：]\d{2}"),
        ("number", r"(?<!\w)\d+(?:\.\d+)?%"),
        ("number", r"人民币\s*[一二三四五六七八九十百千万亿〇零\d,.，]+元"),
        ("number", r"\d+(?:\.\d+)?\s*(?:人|项|个|次|万元|亿元|台|套)"),
    )
    for category, pattern in patterns:
        for match in re.finditer(pattern, text):
            counters[category] += 1
            results.append({
                "key": f"auto_{category}_{counters[category]}", "category": category,
                "value": match.group(0), "origin": "fact", "confidence": "extracted",
            })
    return results


def analyze_materials(data):
    blocking, important, facts = [], [], []
    materials = data.get("materials") or []
    if not isinstance(materials, list):
        return {"ok": False, "blocking": ["materials 必须是数组"], "important": [], "facts": [], "conflicts": []}

    for index, material in enumerate(materials):
        if not isinstance(material, dict):
            blocking.append(f"第{index + 1}份材料必须是对象")
            continue
        name = str(material.get("file_name") or material.get("name") or f"材料{index + 1}")
        kind = str(material.get("source_kind") or "uploaded_file")
        if kind not in SOURCE_KINDS:
            blocking.append(f"{name} 的 source_kind 无效")
        file_type = str(material.get("file_type") or Path(name).suffix.lstrip(".")).lower()
        text = str(material.get("parsed_text") or material.get("text") or "")
        if file_type in {"pdf", "doc", "docx", "xls", "xlsx"} and not text and not material.get("facts"):
            blocking.append(f"{name} 尚未通过平台文件读取工具提取文本或结构化事实")
        material_facts = material.get("facts") or heuristic_facts(text)
        if not isinstance(material_facts, list):
            blocking.append(f"{name} 的 facts 必须是数组")
            continue
        if not material_facts and text:
            important.append(f"{name} 未提取到可核验的结构化事实；请人工确认材料用途")
        for fact_index, fact in enumerate(material_facts):
            if not isinstance(fact, dict):
                blocking.append(f"{name} 第{fact_index + 1}条事实必须是对象")
                continue
            category = str(fact.get("category") or "")
            origin = str(fact.get("origin") or "fact")
            if category not in CATEGORIES:
                blocking.append(f"{name} 的事实类别“{category}”无效")
            if origin not in ORIGINS:
                blocking.append(f"{name} 的事实属性“{origin}”无效")
            item = dict(fact)
            item.update({"source_name": name, "source_kind": kind})
            item.setdefault("key", f"{category}_{fact_index + 1}")
            item.setdefault("location", material.get("location") or "")
            facts.append(item)

    values = defaultdict(lambda: defaultdict(list))
    for fact in facts:
        if fact.get("origin") == "fact" and str(fact.get("key") or "") and str(fact.get("value") or ""):
            values[str(fact["key"])][str(fact["value"])].append(fact["source_name"])
    conflicts = []
    for key, variants in values.items():
        if len(variants) > 1:
            conflicts.append({"fact_key": key, "variants": [{"value": value, "sources": sources} for value, sources in variants.items()]})
            blocking.append(f"事实“{key}”在不同材料中存在冲突，禁止自动择一")

    for fact in facts:
        if fact.get("origin") in {"judgment", "suggestion", "pending"}:
            important.append(f"{fact['source_name']} 中的“{fact.get('key')}”属于{fact.get('origin')}，不得直接作为已确认事实写入正文")
    return {"ok": not blocking, "blocking": blocking, "important": important, "facts": facts, "conflicts": conflicts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="UTF-8 JSON with a materials array")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = analyze_materials(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
