#!/usr/bin/env python3
"""Deterministic routing for the 15 statutory Chinese official-document types."""

import argparse
import json
from pathlib import Path


LEGAL_TYPES = {"决议", "决定", "命令（令）", "公报", "公告", "通告", "意见", "通知", "通报", "报告", "请示", "批复", "议案", "函", "纪要"}
PROFILES = {"命令（令）": "command", "函": "letter", "纪要": "minutes"}
SUBTYPES = {
    "决议": {"审议通过", "重大事项", "修改废止"},
    "决定": {"决策部署", "奖惩", "处置", "变更撤销"},
    "命令（令）": {"公布规章", "重大行政措施", "嘉奖"},
    "公报": {"会议公报", "事项公报", "统计公报"},
    "公告": {"法定事项", "重要事项", "公开事项"},
    "通告": {"周知事项", "禁止限制", "管理措施"},
    "意见": {"指导性", "实施性", "处理性"},
    "通知": {"部署", "会议培训", "转发批转", "任免", "事项告知"},
    "通报": {"表彰", "批评", "情况", "事故事件"},
    "报告": {"工作", "情况", "答复", "专项"},
    "请示": {"请求指示", "请求批准"},
    "批复": {"同意", "不同意", "原则同意并附条件"},
    "议案": {"法规草案", "重大事项", "任免事项"},
    "函": {"商洽", "询问", "请批", "答复"},
    "纪要": {"党委会议", "办公会议", "专题会议", "协调会议"},
}

PURPOSE_DEFAULT_SUBTYPE = {
    "meeting_resolution": "审议通过", "important_decision": "决策部署",
    "issue_regulation": "公布规章", "authoritative_release": "事项公报",
    "public_announcement": "重要事项", "scope_compliance": "周知事项",
    "policy_guidance": "指导性", "deploy_execute": "部署",
    "praise_criticize": "表彰", "important_situation_broadcast": "情况",
    "report_work": "工作", "report_situation": "情况", "answer_superior_inquiry": "答复",
    "request_approval": "请求批准", "request_instruction": "请求指示",
    "npc_submission": "重大事项", "consult_coordinate": "商洽",
    "inquire_reply": "询问", "meeting_record": "专题会议",
}


def _result(status, recommended_type="", direction="", reason="", alternatives=None, questions=None, recommended_subtype=""):
    return {
        "status": status,
        "recommended_type": recommended_type,
        "recommended_subtype": recommended_subtype,
        "direction": direction,
        "layout_profile": PROFILES.get(recommended_type, "standard") if recommended_type else "",
        "reason": reason,
        "alternatives": alternatives or [],
        "questions": questions or [],
    }


def select_document_type(data):
    requested = str(data.get("requested_type") or data.get("document_type") or "").strip()
    requested_subtype = str(data.get("requested_subtype") or data.get("document_subtype") or "").strip()
    purpose = str(data.get("purpose") or "").strip()
    relationship = str(data.get("relationship") or data.get("direction") or "").strip()
    expected = str(data.get("expected_action") or "").strip()
    audience = str(data.get("audience") or "").strip()
    incoming = str(data.get("incoming_type") or "").strip()
    adopted = data.get("meeting_adopted") is True
    meeting_held = data.get("meeting_held") is True
    agreed_matters = data.get("agreed_matters_confirmed") is True
    authority = data.get("authority_confirmed") is True
    decision_level = str(data.get("decision_level") or "").strip()

    recommendation = ""
    direction = ""
    reason = ""
    alternatives = []
    blocker = ""

    if purpose == "meeting_resolution":
        if not adopted:
            blocker = "决议必须有明确的会议讨论并表决通过事实"
        recommendation, direction, reason = "决议", "downward", "会议讨论并通过重大事项"
    elif purpose == "important_decision":
        recommendation, direction, reason = "决定", "downward", "发文机关直接作出重要决策、部署或处理决定"
    elif purpose == "issue_regulation":
        recommendation, direction, reason = "命令（令）", "downward", "发布规章、重大强制措施或法定嘉奖"
        if not authority:
            blocker, alternatives = "命令（令）必须确认发文主体具有相应法定权限", ["决定", "通知"]
    elif purpose == "authoritative_release":
        recommendation, direction, reason = "公报", "downward", "权威、系统公布重要决定、会议成果、重大事项或统计结果"
    elif purpose == "public_announcement":
        recommendation, direction, reason = "公告", "downward", "向国内外或广泛公众宣布重要或法定事项"
    elif purpose == "scope_compliance":
        recommendation, direction, reason = "通告", "downward", "在特定范围公布应当遵守或周知的事项"
    elif purpose == "policy_guidance":
        recommendation, direction, reason = "意见", relationship or "downward", "对重要问题提出原则性见解和处理办法"
    elif purpose == "deploy_execute":
        if decision_level == "major" and expected not in {"execute", "know"}:
            recommendation, alternatives = "决定", ["通知"]
            reason = "事项具有重大、稳定的决策性质"
        else:
            recommendation, alternatives = "通知", (["决定"] if decision_level == "major" else [])
            reason = "面向明确对象传达事项或部署具体执行工作"
        direction = "downward"
    elif purpose in {"praise_criticize", "important_situation_broadcast"}:
        recommendation, direction, reason = "通报", "downward", "传达事实并进行表扬、批评、评价、警示或推广"
    elif purpose in {"report_work", "report_situation", "answer_superior_inquiry"}:
        recommendation, direction, reason = "报告", "upward", "向上级汇报工作、反映情况或答复询问且不请求批准"
        if expected in {"approve", "instruct"}:
            blocker, alternatives = "报告不得夹带请求批准或指示事项", ["请示"]
    elif purpose in {"request_approval", "request_instruction"}:
        if relationship == "parallel":
            recommendation, direction, reason = "函", "parallel", "向不相隶属但有主管权限的机关请求支持、审批或答复"
        elif relationship == "upward":
            recommendation, direction, reason = "请示", "upward", "向有隶属关系的上级请求指示或批准"
        else:
            return _result("needs_clarification", reason="请求事项的行文关系决定使用请示还是函", alternatives=["请示", "函"], questions=["收文机关是有隶属关系的上级机关，还是不相隶属的主管机关？"])
    elif purpose == "reply_request":
        if incoming == "请示" and relationship == "downward":
            recommendation, direction, reason = "批复", "downward", "答复下级机关的请示"
        elif incoming in {"函", "复函"} and relationship == "parallel":
            recommendation, direction, reason = "函", "parallel", "答复不相隶属机关的来函"
        else:
            return _result("needs_clarification", reason="答复文种由来文类型和行文关系共同决定", alternatives=["批复", "函"], questions=["原来文是下级机关的请示，还是不相隶属机关的函？"])
    elif purpose == "npc_submission":
        recommendation, direction, reason = "议案", "parallel", "有权主体按法定程序提请本级人大或其常委会审议"
        if not authority:
            blocker = "议案必须确认提出主体具有法定提案权限"
    elif purpose in {"consult_coordinate", "inquire_reply"}:
        recommendation, direction, reason = "函", "parallel", "不相隶属机关之间商洽、询问、请求支持或答复"
    elif purpose == "meeting_record":
        recommendation, direction, reason = "纪要", "downward", "记载真实会议主要情况和议定事项"
        if not meeting_held or not agreed_matters:
            blocker = "纪要必须基于已召开会议及实际形成的议定事项"
    else:
            return _result("needs_clarification", reason="缺少能确定文种的核心用途", questions=["这份文件希望收文方采取的核心动作是什么？"])

    inferred_subtype = PURPOSE_DEFAULT_SUBTYPE.get(purpose, "")
    if recommendation == "批复":
        inferred_subtype = str(data.get("reply_outcome") or "").strip()
    elif recommendation == "函" and purpose == "reply_request":
        inferred_subtype = "答复"
    elif recommendation == "函" and purpose == "request_approval":
        inferred_subtype = "请批"
    elif recommendation == "通知" and str(data.get("activity_kind") or "").strip() in {"meeting", "training"}:
        inferred_subtype = "会议培训"
    recommended_subtype = requested_subtype or inferred_subtype
    if recommended_subtype and recommended_subtype not in SUBTYPES.get(recommendation, set()):
        return _result("conflict", recommendation, direction,
                       f"子类型“{recommended_subtype}”不适用于文种“{recommendation}”",
                       sorted(SUBTYPES.get(recommendation, set())),
                       ["请确认该文件的具体业务场景或调整子类型。"])

    if audience == "public_broad" and recommendation == "通告":
        alternatives = sorted(set(alternatives + ["公告"]))
    if audience == "defined_scope" and recommendation == "公告":
        alternatives = sorted(set(alternatives + ["通告"]))

    if blocker:
        return _result("conflict", recommendation, direction, blocker, alternatives,
                       ["请补充或确认相关权限、程序或期望动作。"], recommended_subtype)
    if requested and requested not in LEGAL_TYPES:
        return _result("conflict", recommendation, direction, "用户指定的文种不属于15种法定公文", [recommendation], recommended_subtype=recommended_subtype)
    if requested and requested != recommendation:
        return _result("conflict", recommendation, direction,
                       f"指定文种“{requested}”与用途及行文关系不一致；{reason}",
                       sorted(set([requested] + alternatives)),
                       ["是否按推荐文种调整，或补充会改变行文关系、权限或用途的事实？"], recommended_subtype)
    return _result("ok", recommendation, direction, reason, alternatives, recommended_subtype=recommended_subtype)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="UTF-8 JSON containing type-selection facts")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(json.dumps(select_document_type(data), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
