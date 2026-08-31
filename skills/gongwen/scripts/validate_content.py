#!/usr/bin/env python3
"""Validate document-type content, source-document linkage, and evidence traceability."""

import argparse
import json
import re
from pathlib import Path

from select_document_type import SUBTYPES, select_document_type


PLACEHOLDER_MARKS = ("〔由", "〔待", "待核实", "待补", "由用户", "XX", "xx")
SOURCE_KINDS = {"user_input", "uploaded_file", "internal_library", "pending_verification"}
EVIDENCE_STATUS = {"verified", "unverified", "pending", "conflict", "outdated"}
DRAFT_DEPTHS = {"精简", "标准", "详尽"}
REVISION_MODES = {"保守修订", "规范修订", "深度修订"}


def blocks_text(data):
    parts = []
    for block in data.get("blocks") or []:
        if isinstance(block, dict):
            parts.append(str(block.get("text") or ""))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def is_placeholder(value):
    if isinstance(value, (list, tuple, dict)):
        return any(is_placeholder(item) for item in (value.values() if isinstance(value, dict) else value))
    text = str(value or "")
    return any(mark in text for mark in PLACEHOLDER_MARKS)


def missing(value):
    return value is None or value == "" or value == [] or value == {}


def validate_content(data):
    issues = {"blocking": [], "important": [], "optimization": []}

    def add(level, code, message, field=""):
        issues[level].append({"code": code, "message": message, "field": field})

    doc_type = str(data.get("document_type") or "").strip()
    subtype = str(data.get("document_subtype") or "").strip()
    facts = data.get("content_facts") or {}
    if not isinstance(facts, dict):
        add("blocking", "invalid_content_facts", "content_facts 必须是对象", "content_facts")
        facts = {}
    text = blocks_text(data)
    selection = data.get("type_selection")
    routed = select_document_type(selection) if isinstance(selection, dict) else None

    if subtype and subtype not in SUBTYPES.get(doc_type, set()):
        add("blocking", "invalid_subtype", f"子类型“{subtype}”不适用于文种“{doc_type}”", "document_subtype")
    if routed and routed.get("status") == "ok":
        routed_subtype = str(routed.get("recommended_subtype") or "")
        if routed_subtype and subtype and routed_subtype != subtype:
            add("blocking", "subtype_route_mismatch", f"子类型与路由结果不一致，应为“{routed_subtype}”", "document_subtype")
    if not subtype:
        add("important", "missing_subtype", "未明确文种子类型，将使用该文种通用结构", "document_subtype")

    def value(key):
        if key in facts:
            return facts.get(key)
        if isinstance(selection, dict) and key in selection:
            return selection.get(key)
        return data.get(key)

    def require(key, label, level="blocking"):
        val = value(key)
        if missing(val):
            add(level, "missing_" + key, f"缺少{label}", "content_facts." + key)
        elif is_placeholder(val):
            add("important", "placeholder_" + key, f"{label}仍为占位信息，定稿前须核实", "content_facts." + key)
        return val

    def require_true(key, label):
        val = value(key)
        if val is not True:
            add("blocking", "unconfirmed_" + key, f"{label}尚未得到明确确认", "content_facts." + key)
        return val

    if doc_type == "决议":
        require_true("meeting_held", "会议召开事实")
        require_true("meeting_adopted", "会议表决通过事实")
        require("adopted_matters", "议决事项")
    elif doc_type == "决定":
        require("decision_items", "决定事项")
        require("execution_requirements", "执行要求")
    elif doc_type == "命令（令）":
        require_true("authority_confirmed", "发布权限")
        require("order_matter", "命令事项")
        if subtype in {"公布规章", "重大行政措施"}:
            require("effective_date", "施行日期")
    elif doc_type == "公报":
        require("release_subject", "公布主题")
        require("published_results", "权威公布的结果或事项")
    elif doc_type == "公告":
        require("public_scope", "公开范围")
        require("announced_matter", "公告事项")
    elif doc_type == "通告":
        require("applicable_scope", "适用范围")
        require("compliance_requirements", "周知或遵守要求")
    elif doc_type == "意见":
        require("guiding_principles", "指导原则")
        require("handling_measures", "处理办法")
        require("responsibility_boundaries", "职责边界")
    elif doc_type == "通知":
        require("target_audience", "通知对象")
        require("tasks_or_matters", "通知事项或任务")
        require("execution_requirements", "执行要求")
        if subtype == "会议培训":
            for key, label in (("event_time", "时间"), ("event_location", "地点"), ("participants", "参加对象")):
                require(key, label)
    elif doc_type == "通报":
        require("reported_facts", "通报事实")
        require("evaluation", "评价或定性")
        require("follow_up_requirements", "处理、警示或后续要求")
    elif doc_type == "报告":
        require("reported_facts", "报告事实")
        require("results_or_progress", "工作进展或成果")
        if re.search(r"请(?:批准|批复|审定|指示)|妥否[，,]请批示|是否同意", text):
            add("blocking", "report_contains_request", "报告正文疑似夹带请示事项", "blocks")
    elif doc_type == "请示":
        require("request_matter", "请示事项")
        count = require("request_count", "请示事项数量")
        try:
            if not missing(count) and int(count) != 1:
                add("blocking", "multiple_requests", "请示必须坚持一文一事", "content_facts.request_count")
        except (TypeError, ValueError):
            add("blocking", "invalid_request_count", "request_count 必须是整数1", "content_facts.request_count")
        recipient = str(data.get("recipient") or "")
        if any(mark in recipient for mark in ("、", "，", ",", ";", "；")):
            add("blocking", "multiple_primary_recipients", "请示主送机关应当唯一", "recipient")
    elif doc_type == "批复":
        require("decision_outcome", "批复结论")
        require("responded_item_ids", "逐项答复标识")
    elif doc_type == "议案":
        require_true("authority_confirmed", "提案权限")
        require("deliberation_request", "审议请求")
    elif doc_type == "函":
        require("correspondence_matter", "函告、商洽、询问、请批或答复事项")
    elif doc_type == "纪要":
        require_true("meeting_held", "会议召开事实")
        require("meeting_info", "会议基本信息")
        require("agreed_matters", "议定事项")

    sources = data.get("source_documents") or []
    if not isinstance(sources, list):
        add("blocking", "invalid_source_documents", "source_documents 必须是数组", "source_documents")
        sources = []
    needs_source = doc_type == "批复" or (doc_type == "函" and subtype == "答复") or (doc_type == "报告" and subtype == "答复")
    expected_source_type = "请示" if doc_type == "批复" else ("函" if doc_type == "函" and subtype == "答复" else "")
    if needs_source and not sources:
        add("blocking", "missing_source_document", "答复类公文必须提供原来文；资料未知时应创建含明确占位符的原来文记录", "source_documents")
    for index, source in enumerate(sources):
        prefix = f"source_documents.{index}"
        if not isinstance(source, dict):
            add("blocking", "invalid_source_document", "原来文记录必须是对象", prefix)
            continue
        if expected_source_type and str(source.get("document_type") or "").strip() != expected_source_type:
            add("blocking", "wrong_source_type", f"该答复文种必须对应“{expected_source_type}”来文", prefix + ".document_type")
        for key, label in (("title", "原来文标题"), ("document_number", "原来文发文字号"), ("issuing_body", "原来文发文机关"), ("date", "原来文成文日期")):
            if missing(source.get(key)):
                add("important", "missing_source_" + key, f"缺少{label}，应使用明确占位符", prefix + "." + key)
            elif is_placeholder(source.get(key)):
                add("important", "placeholder_source_" + key, f"{label}仍为占位信息", prefix + "." + key)
        pending = source.get("pending_questions") or []
        responded = set(str(item) for item in (facts.get("responded_item_ids") or []))
        for question in pending:
            qid = str(question.get("id") if isinstance(question, dict) else question)
            if qid and qid not in responded:
                add("blocking", "unanswered_source_item", f"原来文事项“{qid}”尚未逐项答复", "content_facts.responded_item_ids")

    evidence = data.get("evidence_items") or []
    if not isinstance(evidence, list):
        add("blocking", "invalid_evidence_items", "evidence_items 必须是数组", "evidence_items")
        evidence = []
    if data.get("policy_basis") and not evidence:
        add("blocking", "untraced_policy_basis", "正文使用了政策依据，但未提供可追溯的依据记录", "evidence_items")
    verified_values = {}
    for index, item in enumerate(evidence):
        prefix = f"evidence_items.{index}"
        if not isinstance(item, dict):
            add("blocking", "invalid_evidence_item", "依据记录必须是对象", prefix)
            continue
        kind = str(item.get("source_kind") or "")
        status = str(item.get("status") or "")
        if kind not in SOURCE_KINDS:
            add("blocking", "invalid_source_kind", "依据来源类别无效", prefix + ".source_kind")
        if status not in EVIDENCE_STATUS:
            add("blocking", "invalid_evidence_status", "依据核验状态无效", prefix + ".status")
        elif status in {"conflict", "outdated"}:
            add("blocking", "unusable_evidence", "依据存在冲突或已失效，不能据此成文", prefix + ".status")
        elif status in {"unverified", "pending"}:
            add("important", "unverified_evidence", "依据尚未核实，定稿前必须确认", prefix + ".status")
        if kind in {"uploaded_file", "internal_library"} and missing(item.get("file_name")):
            add("important", "missing_evidence_file", "文件类依据缺少文件名", prefix + ".file_name")
        if kind in {"uploaded_file", "internal_library"} and missing(item.get("location")):
            add("important", "missing_evidence_location", "文件类依据缺少条款、章节或页码位置", prefix + ".location")
        key = str(item.get("fact_key") or "")
        val = str(item.get("value") or "")
        if status == "verified" and key and val:
            if key in verified_values and verified_values[key] != val:
                add("blocking", "evidence_value_conflict", f"同一事实“{key}”存在两个已核实但不一致的值", prefix + ".value")
            verified_values[key] = val

    depth = str(data.get("draft_depth") or "").strip()
    revision = str(data.get("revision_mode") or "").strip()
    if depth and depth not in DRAFT_DEPTHS:
        add("blocking", "invalid_draft_depth", "draft_depth 必须为精简、标准或详尽", "draft_depth")
    if revision and revision not in REVISION_MODES:
        add("blocking", "invalid_revision_mode", "revision_mode 必须为保守修订、规范修订或深度修订", "revision_mode")
    limit = data.get("length_limit")
    if limit is not None:
        valid = isinstance(limit, int) and limit > 0
        if isinstance(limit, dict):
            minimum, maximum = limit.get("min"), limit.get("max")
            valid = all(v is None or isinstance(v, int) and v > 0 for v in (minimum, maximum))
            if valid and minimum and maximum and minimum > maximum:
                valid = False
        if not valid:
            add("blocking", "invalid_length_limit", "length_limit 必须是正整数或包含有效 min/max 的对象", "length_limit")

    return {"ok": not issues["blocking"], "issues": issues, "meta": {"document_type": doc_type, "document_subtype": subtype}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="UTF-8 document JSON")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = validate_content(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
