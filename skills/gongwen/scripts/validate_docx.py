#!/usr/bin/env python3
"""Validate official-document DOCX structure and type-specific invariants."""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from select_document_type import select_document_type
from analyze_materials import analyze_materials
from review_text import review_text
from validate_content import validate_content
from edition_layout import plan as edition_plan
from date_rules import normalize as normalize_cn_date, error as date_error

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LEGAL_TYPES = {"决议", "决定", "命令（令）", "公报", "公告", "通告", "意见", "通知", "通报", "报告", "请示", "批复", "议案", "函", "纪要"}
RECIPIENT_USUALLY_OMITTED = {"公报", "公告", "通告", "纪要"}
SIGNATORY_TYPES = {"报告", "请示"}
FORBIDDEN_POLICY = ("贯彻落实国家", "贯彻落实上级", "国家关于", "上级部署要求", "根据有关文件", "按照相关政策")
BODY_BOTTOM = 16838 - 1984
CHAR_TWIPS = 320
FONT_BODY, FONT_TITLE = "仿宋_GB2312", "方正小标宋简体"
FONT_HEI, FONT_KAI = "黑体", "楷体_GB2312"
STANDARD_MARK_TOP_GAP = 1890
COMMAND_MARK_TOP_GAP = 1040
HEADER_NUMBER_TOP_GAP = 840


def text_width_twips(text):
    units = sum(1.0 if unicodedata.east_asian_width(ch) in {"W", "F", "A"} else 0.5 for ch in str(text or ""))
    return round(units * CHAR_TWIPS)


def signature_indents(issuer, date):
    issuer_width, date_width = text_width_twips(issuer), text_width_twips(date)
    if date_width <= issuer_width:
        return 2 * CHAR_TWIPS, max(0, issuer_width - date_width)
    return 4 * CHAR_TWIPS + date_width - issuer_width, 2 * CHAR_TWIPS


def text_of(node):
    return "".join(t.text or "" for t in node.iter(W + "t"))


def signature_position_matches(paragraph, text, expected_right):
    """Check text group positions, not merely a claimed paragraph indent."""
    stops = paragraph.findall('./' + W + 'pPr/' + W + 'tabs/' + W + 'tab')
    if not stops:
        return False
    parts = re.findall(r'[\x20-\x7e]+|[^\x20-\x7e]+', text)
    cursor = 8845 - expected_right - text_width_twips(text)
    expected = []
    for part in parts:
        cursor += text_width_twips(part)
        expected.append(str(cursor))
    actual = [stop.get(W + 'pos') for stop in stops]
    text_runs = [text_of(run) for run in paragraph.findall(W + 'r') if text_of(run)]
    tabs = paragraph.findall('./' + W + 'r/' + W + 'tab')
    alignment = paragraph.find('./' + W + 'pPr/' + W + 'jc')
    return (actual == expected and text_runs == parts and len(tabs) == len(parts)
            and all(stop.get(W + 'val') == 'right' for stop in stops)
            and (ind_value(paragraph, 'right') == '-10' if expected_right == 0 else ind_value(paragraph, 'right') in {None, '0'})
            and alignment is not None and alignment.get(W + 'val') == 'left')


def east_asia_fonts(paragraph):
    fonts = []
    for r_fonts in paragraph.iter(W + "rFonts"):
        value = r_fonts.get(W + "eastAsia")
        if value:
            fonts.append(value)
    return fonts


def paragraph_has_font(paragraphs, text, expected):
    matches = [p for p, value in paragraphs if value == text]
    return bool(matches) and any(
        east_asia_fonts(p) and all(font == expected for font in east_asia_fonts(p))
        for p in matches
    )


def paragraph_explicitly_not_bold(paragraphs, text):
    matches = [p for p, value in paragraphs if value == text]
    if not matches:
        return False
    for paragraph in matches:
        runs = list(paragraph.iter(W + "r"))
        if not runs:
            continue
        valid = True
        for run in runs:
            bold = run.find("./" + W + "rPr/" + W + "b")
            bold_cs = run.find("./" + W + "rPr/" + W + "bCs")
            if bold is None or bold_cs is None:
                valid = False
                break
            if bold.get(W + "val", "1") not in {"0", "false", "off"}:
                valid = False
                break
            if bold_cs.get(W + "val", "1") not in {"0", "false", "off"}:
                valid = False
                break
        if valid:
            return True
    return False


def issuer_from_mark(value):
    text = str(value or "").strip()
    for suffix in ("会议纪要", "纪要", "命令", "令", "文件"):
        if text.endswith(suffix):
            return text[:-len(suffix)].strip()
    return text


def p_texts(root):
    return [(p, text_of(p).strip()) for p in root.iter(W + "p")]


def ind_value(p, name):
    ind = p.find("./" + W + "pPr/" + W + "ind")
    # In OOXML an omitted indentation element/attribute means zero.  Treat it
    # as such so an exactly zero calculated signature indent is not rejected.
    return "0" if ind is None else (ind.get(W + name) or "0")


def spacing_value(p, name):
    spacing = p.find("./" + W + "pPr/" + W + "spacing")
    return None if spacing is None else spacing.get(W + name)


def validate(path, input_json=None):
    errors, warnings = [], []
    path = Path(path)
    data = json.loads(Path(input_json).read_text(encoding="utf-8")) if input_json else {}
    if not path.exists() or path.stat().st_size == 0:
        return ["文件不存在或为空"], warnings, {}
    try:
        with ZipFile(path) as zf:
            names = set(zf.namelist())
            required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/settings.xml", "word/footer1.xml", "word/footer2.xml"}
            missing = sorted(required - names)
            if missing:
                errors.append("缺少 DOCX 组成部分：" + "、".join(missing))
            media = sorted(n for n in names if n.startswith("word/media/"))
            if media:
                errors.append("检测到图片媒体；草稿不得包含印章或签名图片")
            root = ET.fromstring(zf.read("word/document.xml"))
            settings = ET.fromstring(zf.read("word/settings.xml"))
            footer1 = ET.fromstring(zf.read("word/footer1.xml"))
            footer2 = ET.fromstring(zf.read("word/footer2.xml"))
            footer3 = ET.fromstring(zf.read("word/footer3.xml")) if "word/footer3.xml" in names else None
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        return [f"DOCX 或 XML 无效：{exc}"], warnings, {}

    full_text = text_of(root)
    paragraphs = p_texts(root)
    sect = root.find(".//" + W + "sectPr")
    meta = {"bytes": path.stat().st_size, "media_count": 0, "paragraphs": len(paragraphs), "validation_scope": "ooxml_structure", "visual_check": "not_performed", "font_availability": "not_verified", "full_compliance": "not_certified"}
    if sect is None:
        errors.append("缺少节属性")
    else:
        size, mar = sect.find(W + "pgSz"), sect.find(W + "pgMar")
        if size is None or size.get(W + "w") != "11906" or size.get(W + "h") != "16838":
            errors.append("页面不是 A4 纵向")
        doc_type = str(data.get("document_type") or "").strip()
        profile = str(data.get("layout_profile") or ({"命令（令）": "command", "函": "letter", "纪要": "minutes"}.get(doc_type, "standard")))
        expected = ({"top": "1617", "right": "1474", "bottom": "1134", "left": "1587", "footer": "1134"}
                    if profile == "letter" else
                    {"top": "2098", "right": "1474", "bottom": "1984", "left": "1587", "footer": "1360"})
        if mar is None:
            errors.append("缺少页边距")
        else:
            for key, value in expected.items():
                if mar.get(W + key) != value:
                    errors.append(f"{key} 页边距不符合基线")
        refs = {ref.get(W + "type") for ref in sect.findall(W + "footerReference")}
        if not {"default", "even"}.issubset(refs):
            errors.append("缺少奇偶页页脚引用")
        if profile == "letter":
            if "first" not in refs or sect.find(W + "titlePg") is None:
                errors.append("信函首页未设置独立无页码页脚")
            if footer3 is None:
                errors.append("信函首页缺少独立空白页脚")
            elif text_of(footer3).strip():
                errors.append("信函首页错误编排页码")
        elif bool(data.get("official_document", True)) and paragraphs:
            expected_mark_before = COMMAND_MARK_TOP_GAP if profile == "command" else STANDARD_MARK_TOP_GAP
            if spacing_value(paragraphs[0][0], "before") != str(expected_mark_before):
                errors.append("发文机关标志可见上边缘未按版心上边缘基准定位")
            if len(paragraphs) < 2 or spacing_value(paragraphs[1][0], "before") != str(HEADER_NUMBER_TOP_GAP):
                errors.append("发文字号未按发文机关标志下空二行的可见位置编排")
    if settings.find(W + "evenAndOddHeaders") is None:
        errors.append("未启用奇偶页不同")
    f1jcs = footer1.findall(".//" + W + "jc")
    f2jcs = footer2.findall(".//" + W + "jc")
    if not any(jc.get(W + "val") == "right" for jc in f1jcs):
        errors.append("奇数页页码未居右")
    if not any(jc.get(W + "val") == "left" for jc in f2jcs):
        errors.append("偶数页页码未居左")
    for footer in (footer1, footer2):
        for element in footer.iter(W + "r"):
            if text_of(element).strip():
                fonts = element.find("./" + W + "rPr/" + W + "rFonts")
                size = element.find("./" + W + "rPr/" + W + "sz")
                if fonts is None or any(fonts.get(W + k) != "宋体" for k in ("ascii", "hAnsi", "eastAsia")) or size is None or size.get(W + "val") != "28":
                    errors.append("页码数字及一字线须使用四号宋体，不能仅指定东亚字体")
    if not full_text.strip():
        errors.append("正文为空")
    for field in ('date', 'print_date'):
        issue = date_error(data.get(field))
        if issue:
            errors.append(field + '：' + issue)
    if data and data.get('official_document', True) is False:
        title = str(data.get('title') or '').strip()
        if not title or title not in full_text:
            errors.append('事务文书标题缺失')
        if title and (not paragraph_has_font(paragraphs, title, FONT_TITLE) or not paragraph_explicitly_not_bold(paragraphs, title)):
            errors.append('事务文书标题字体或非加粗设置不符')
        if path.name != f'{title}（草稿）.docx':
            errors.append('文件名与事务文书标题不一致')
        if any(marker in full_text for marker in ('〔发文机关署名由用户单位填写〕', '〔成文日期由用户单位填写〕', '签发人：')):
            errors.append('事务文书错误套用法定公文要素')
        if data.get('text_review_required'):
            result = review_text(data)
            errors.extend(item['message'] for item in result['issues']['blocking'])
            warnings.extend(item['message'] for level in ('important', 'optimization') for item in result['issues'][level])
        meta['document_category'] = '事务文书'
        return errors, warnings, meta
    doc_type = str(data.get("document_type") or "").strip()
    direction = str(data.get("direction") or "").strip()
    if data:
        if doc_type not in LEGAL_TYPES:
            errors.append("输入缺少有效法定文种")
        type_selection = data.get("type_selection")
        if type_selection is not None:
            if not isinstance(type_selection, dict):
                errors.append("type_selection 必须是对象")
            else:
                routed = select_document_type(type_selection)
                if routed["status"] != "ok":
                    errors.append("文种判断尚未解决：" + routed["reason"])
                else:
                    if routed["recommended_type"] != doc_type:
                        errors.append("文种与用途、行文关系不一致；推荐使用" + routed["recommended_type"])
                    if routed["direction"] != direction:
                        errors.append("行文方向与文种路由不一致；应为" + routed["direction"])
                    actual_profile = str(data.get("layout_profile") or ({"命令（令）": "command", "函": "letter", "纪要": "minutes"}.get(doc_type, "standard")))
                    if routed["layout_profile"] != actual_profile:
                        errors.append("版式与文种路由不一致；应为" + routed["layout_profile"])
                    routed_subtype = str(routed.get("recommended_subtype") or "").strip()
                    actual_subtype = str(data.get("document_subtype") or "").strip()
                    if routed_subtype and actual_subtype and routed_subtype != actual_subtype:
                        errors.append("文种子类型与路由不一致；应为" + routed_subtype)
        if data.get("content_validation_required") is True:
            content_result = validate_content(data)
            errors.extend("内容校验：" + item["message"] for item in content_result["issues"]["blocking"])
            warnings.extend("内容校验：" + item["message"] for level in ("important", "optimization") for item in content_result["issues"][level])
        if data.get("material_analysis_required") is True:
            material_result = analyze_materials(data)
            errors.extend("材料校验：" + message for message in material_result["blocking"])
            warnings.extend("材料校验：" + message for message in material_result["important"])
        if data.get("text_review_required") is True:
            text_result = review_text(data)
            errors.extend("文本审校：" + item["message"] for item in text_result["issues"]["blocking"])
            warnings.extend("文本审校：" + item["message"] for level in ("important", "optimization") for item in text_result["issues"][level])
        title = str(data.get("title") or "").strip()
        if title and doc_type != "命令（令）" and title not in full_text:
            errors.append("标题未写入文档")
        if title and doc_type != "命令（令）" and not paragraph_has_font(paragraphs, title, FONT_TITLE):
            errors.append("公文标题未使用方正小标宋简体")
        if title and doc_type != "命令（令）" and not paragraph_explicitly_not_bold(paragraphs, title):
            errors.append("公文标题不得加粗")
        adoption = str(data.get("adoption_line") or "").strip()
        if adoption:
            matches = [p for p, value in paragraphs if value == adoption]
            if not matches or not paragraph_has_font(paragraphs, adoption, FONT_BODY) or not paragraph_explicitly_not_bold(paragraphs, adoption):
                errors.append("会议通过信息应按默认规则用三号仿宋，不附加粗体")
            elif any(r.find('./'+W+'rPr/'+W+'sz') is None or r.find('./'+W+'rPr/'+W+'sz').get(W+'val') != '32' for p in matches for r in p.findall('./'+W+'r') if r.find('./'+W+'t') is not None):
                errors.append("会议通过信息字号应为三号")
        if doc_type == "命令（令）" and title in full_text:
            errors.append("命令（令）专用格式不应在令号后另排普通公文标题")
        if title and path.name != f"{title}（草稿）.docx":
            errors.append("文件名必须与公文标题逐字一致并以“（草稿）.docx”结尾")
        document_number = str(data.get("document_number") or "").strip()
        if document_number and document_number not in full_text:
            errors.append("发文字号或编号未写入文档")
        issuer_mark = str(data.get("issuer_mark") or "").strip()
        if doc_type == "函":
            displayed_issuer_mark = issuer_mark.replace("文件", "")
        elif doc_type == "纪要":
            displayed_issuer_mark = str(data.get("minutes_mark") or issuer_mark or "〔发文机关标志由用户单位填写〕").strip().replace("文件", "")
            if "纪要" not in displayed_issuer_mark:
                displayed_issuer_mark += "会议纪要"
        else:
            displayed_issuer_mark = issuer_mark
        if displayed_issuer_mark and not paragraph_has_font(paragraphs, displayed_issuer_mark, FONT_TITLE):
            errors.append("发文机关标志未使用方正小标宋简体")
        if paragraphs and not paragraph_explicitly_not_bold(paragraphs[:1], paragraphs[0][1]):
            errors.append("发文机关标志不得附加粗体（本技能版式约定）")
        block_fonts = {
            "body": FONT_BODY, "noindent": FONT_BODY, "center": FONT_BODY,
            "heading1": FONT_HEI, "heading2": FONT_KAI,
            "heading3": FONT_BODY, "heading4": FONT_BODY, "note": FONT_KAI,
        }
        for block in data.get("blocks") or []:
            block_text = str(block.get("text") or "").strip()
            block_type = str(block.get("type") or "body")
            expected_font = block_fonts.get(block_type, FONT_BODY)
            if block_text and not paragraph_has_font(paragraphs, block_text, expected_font):
                errors.append(f"正文层级字体错误：{block_type} 应使用 {expected_font}")
            if block_text and block_type in {"heading3", "heading4"} and not paragraph_explicitly_not_bold(paragraphs, block_text):
                errors.append("第三、四级标题应为仿宋体，不附加粗体")
        recipient = str(data.get("recipient") or "").strip()
        if recipient and recipient.rstrip("：") not in full_text:
            errors.append("主送机关未写入文档")
        if doc_type in RECIPIENT_USUALLY_OMITTED and recipient:
            warnings.append(f"{doc_type}通常不设置主送机关；请确认本次具体发布场景确需主送")
        signatory = str(data.get("signatory") or "").strip()
        has_signatory_label = "签发人：" in full_text
        if direction == "upward" and signatory and f"签发人：{signatory}" not in full_text:
            errors.append("上行文签发人未正确编排")
        if direction == "upward" and signatory:
            number_ps = [p for p, value in paragraphs if value == document_number+'签发人：'+signatory]
            stops = [] if not number_ps else number_ps[0].findall('./'+W+'pPr/'+W+'tabs/'+W+'tab')
            if [(s.get(W+'val'),s.get(W+'pos')) for s in stops] != [('left','320'),('right','8525')]:
                errors.append("上行文发文字号须左空一字")
        if profile in {'standard','minutes'} and bool(data.get('official_document', True)):
            number_ps = [p for p,value in paragraphs if value == document_number or value == document_number+'签发人：'+signatory]
            border = None if not number_ps else number_ps[0].find('./'+W+'pPr/'+W+'pBdr/'+W+'bottom')
            if border is None or border.get(W+'space') != '4' or border.get(W+'color') != 'FF0000':
                errors.append('版头红线间距参数不符；还须渲染核对其距发文字号下方约4mm')
        if direction != "upward" and has_signatory_label:
            errors.append("非上行文错误编排签发人")
        if doc_type in {"命令（令）", "议案"} and has_signatory_label:
            errors.append(f"{doc_type}不得使用上行文签发人标签")
        if doc_type == "命令（令）":
            if recipient:
                errors.append("命令（令）专用格式不设置主送机关")
            for field in ("signer_title", "signer_name"):
                value = str(data.get(field) or "").strip()
                if value and value not in full_text:
                    errors.append("命令签署要素缺失：" + field)
            title = str(data.get('signer_title') or '〔签署人职务由用户单位填写〕').strip()
            name = str(data.get('signer_name') or '〔签署人姓名由用户单位填写〕').strip()
            if not any(t == title+'　　'+name for p,t in paragraphs):
                errors.append('命令职务与签署姓名之间应空二字')
        if doc_type == "议案":
            for field in ("proposer_title", "proposer_name"):
                value = str(data.get(field) or "").strip()
                if value and value not in full_text:
                    errors.append("议案提出人要素缺失：" + field)
        if doc_type == "函" and str(data.get("layout_profile") or "letter") != "letter":
            errors.append("函未使用信函版式")
        if doc_type == "函" and any(str(data.get(k) or "").strip() for k in ("printing_authority", "print_date")):
            errors.append("信函格式版记不标印发机关、印发日期和分隔线")
        if doc_type == "纪要" and "纪要" not in full_text:
            errors.append("纪要专用标志缺失")
        date = normalize_cn_date(data.get("date") or "")
        if date and date not in full_text:
            errors.append("成文日期未写入文档")
        issuer = str(data.get("issuer") or "").strip()
        issuing_body = str(data.get("issuing_body") or "").strip()
        # These fields can legitimately use different agency wording when
        # the user explicitly supplies it.  Exact preservation is checked by
        # user_contract; do not replace it with a forced same-name rule.
        if "seal_requirement" not in data:
            errors.append("缺少 seal_requirement；必须明确为 required 或 not_required")
        seal_requirement = str(data.get("seal_requirement") or "").strip()
        if seal_requirement not in {"required", "not_required"}:
            errors.append("seal_requirement 必须为 required 或 not_required")
        expected_date_right = 1280
        if issuer and issuer not in full_text and doc_type not in {"命令（令）", "议案"}:
            errors.append("发文机关署名未写入文档")
        if issuer and doc_type not in {"命令（令）", "议案"}:
            issuer_ps = [p for p, t in paragraphs if t == issuer]
            if seal_requirement == "required":
                expected_date_right = 4 * CHAR_TWIPS
                expected_issuer_right = max(0, expected_date_right + (text_width_twips(date) - text_width_twips(issuer)) // 2)
            else:
                expected_issuer_right, expected_date_right = signature_indents(issuer, date)
            if not issuer_ps or not any(signature_position_matches(p, issuer, expected_issuer_right) for p in issuer_ps):
                errors.append("发文机关署名与成文日期未按长度联动对齐")
        if date:
            date_ps = [p for p, t in paragraphs if t == date]
            if doc_type in {"命令（令）", "议案"}:
                expected_date_right = 1280
            if not date_ps or not signature_position_matches(date_ps[-1], date, expected_date_right):
                errors.append("成文日期与发文机关署名未按规范对齐")
            if doc_type == '命令（令）' and date_ps:
                spacing = date_ps[-1].find('./'+W+'pPr/'+W+'spacing')
                if spacing is None or spacing.get(W+'before') != '560':
                    errors.append('命令成文日期应在专用签署下空一行编排')
        if doc_type == '纪要':
            first_roster = True
            signature_indexes = [i for i,(p,t) in enumerate(paragraphs) if t == issuer]
            for key,label in (('attendees','出席'),('absent_attendees','请假'),('nonvoting_attendees','列席')):
                value = str(data.get(key) or '').strip()
                if not value:
                    continue
                matches = [(i,p) for i,(p,t) in enumerate(paragraphs) if t==label+'：'+value]
                if not matches:
                    errors.append('纪要名单未写入：'+label)
                    continue
                i,p = matches[0]
                ind = p.find('./'+W+'pPr/'+W+'ind')
                spacing = p.find('./'+W+'pPr/'+W+'spacing')
                if ind is None or ind.get(W+'left')!='1600' or ind.get(W+'hanging')!='960':
                    errors.append('纪要名单回行未与冒号后首字对齐：'+label)
                if first_roster and (spacing is None or spacing.get(W+'before')!='560'):
                    errors.append('纪要名单应在正文或附件说明下空一行')
                if signature_indexes and i>=signature_indexes[-1]:
                    errors.append('纪要名单不得排在机关署名之后')
                first_roster = False
        attachments = data.get("attachments") or []
        attachments = [attachments] if isinstance(attachments, str) else attachments
        for index,item in enumerate(attachments,1):
            if str(item) not in full_text:
                errors.append("附件说明缺失：" + str(item))
            label = ('附件：' if index==1 else '') + (f'{index}. ' if len(attachments)>1 else '')
            expected = label+str(item).strip()
            matches = [p for p,t in paragraphs if t == expected]
            start = 640 if index==1 else 1600
            width = text_width_twips(label)
            ind = None if not matches else matches[0].find('./'+W+'pPr/'+W+'ind')
            spacing = None if not matches else matches[0].find('./'+W+'pPr/'+W+'spacing')
            if ind is None or ind.get(W+'left')!=str(start+width) or ind.get(W+'hanging')!=str(width):
                errors.append('附件说明回行未与名称首字对齐：'+str(index))
            if index==1 and (spacing is None or spacing.get(W+'before')!='560'):
                errors.append('附件说明应在正文下空一行')
        attachment_documents = data.get("attachment_documents") or []
        for index, item in enumerate(attachment_documents, 1):
            if isinstance(item, dict) and str(item.get("title") or "").strip() not in full_text:
                errors.append(f"第{index}个附件未另面写入")
        edition_requested = any(str(data.get(k) or "").strip() for k in ("copy_to", "printing_authority", "print_date")) or bool(data.get("recipient_in_edition"))
        edition_table = next((tbl for tbl in root.iter(W + "tbl") if tbl.find("./" + W + "tblPr/" + W + "tblpPr") is not None), None)
        floating = None if edition_table is None else edition_table.find("./" + W + "tblPr/" + W + "tblpPr")
        if edition_requested:
            edition_rows = edition_plan(data, 'letter' if doc_type == '函' else 'standard')['total_rows']
            expected_y = str((16838 - 1134 - (edition_rows+1) * 560) if doc_type == "函" else (BODY_BOTTOM - 560 * edition_rows))
            if floating is None or floating.get(W + "vertAnchor") != "page" or floating.get(W + "tblpY") != expected_y:
                errors.append("版记末条分隔线未与最后一面版心下边缘重合")
            if floating is not None and floating.get(W + "tblpYSpec"):
                errors.append("版记错误使用物理页底对齐，可能与页码重叠")
            borders = None if edition_table is None else edition_table.find("./" + W + "tblPr/" + W + "tblBorders")
            border_specs = {name: None if borders is None else borders.find(W + name) for name in ("top", "insideH", "bottom")}
            if doc_type == "函":
                if any(spec is None or spec.get(W + "val") not in {"nil", "none"} for spec in (border_specs["top"], border_specs["insideH"], border_specs["bottom"])):
                    errors.append("信函格式版记错误添加分隔线")
            elif (border_specs["top"] is None or border_specs["top"].get(W + "sz") != "8"
                  or border_specs["bottom"] is None or border_specs["bottom"].get(W + "sz") != "8"
                  or (edition_rows > 1 and (border_specs["insideH"] is None or border_specs["insideH"].get(W + "sz") != "6"))):
                errors.append("版记粗细分隔线不符合规范")
            if edition_table is not None:
                heights = edition_table.findall("./" + W + "tr/" + W + "trPr/" + W + "trHeight")
                expected_height = 560 * edition_rows
                actual_height = sum(int(h.get(W + "val") or 0) for h in heights)
                if actual_height != expected_height or any(h.get(W + "hRule") != "exact" for h in heights):
                    errors.append("版记行高不固定，无法保证末线与版心下边缘重合")
            for key in ("copy_to", "printing_authority", "print_date"):
                if doc_type == "函" and key in {"printing_authority", "print_date"}:
                    continue
                value = normalize_cn_date(data.get(key)) if key == "print_date" else str(data.get(key) or "").strip()
                acceptable = value in full_text or (key == "copy_to" and value.rstrip("。；;") in full_text)
                if value and not acceptable:
                    errors.append("版记要素缺失：" + key)
            if data.get("recipient_in_edition") and recipient.rstrip("：") not in full_text:
                errors.append("移入版记的主送机关缺失")
        if not data.get("policy_basis"):
            for phrase in FORBIDDEN_POLICY:
                if phrase in full_text:
                    errors.append("检测到无来源政策表述：" + phrase)
    elif not path.name.endswith("（草稿）.docx"):
        errors.append("文件名未以“（草稿）.docx”结尾")

    if "审批状态" in full_text:
        errors.append("正文含审批状态")
    return errors, warnings, meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument("--input")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors, warnings, meta = validate(args.docx, args.input)
    result = {"ok": not errors, "errors": errors, "warnings": warnings, "meta": meta}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
