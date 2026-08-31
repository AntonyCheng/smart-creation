#!/usr/bin/env python3
"""Generate standards-oriented Chinese official DOCX files with stdlib only."""

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from select_document_type import select_document_type
from analyze_materials import analyze_materials
from review_text import review_text
from validate_content import validate_content
from edition_layout import plan as edition_plan
from date_rules import normalize as normalize_cn_date, error as date_error

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RED, BLACK = "FF0000", "000000"
FONT_BODY, FONT_TITLE = "仿宋_GB2312", "方正小标宋简体"
FONT_HEI, FONT_KAI, FONT_SONG = "黑体", "楷体_GB2312", "宋体"
LEGAL_TYPES = {"决议", "决定", "命令（令）", "公报", "公告", "通告", "意见", "通知", "通报", "报告", "请示", "批复", "议案", "函", "纪要"}
USER_CONTRACT_FIELDS = (
    "document_type", "document_subtype", "direction", "issuer_mark",
    "document_number", "title", "recipient", "blocks", "attachments",
    "issuing_body", "issuer", "date", "seal_requirement", "signatory",
    "signer_title", "signer_name", "proposer_title", "proposer_name",
    "copy_to", "printing_authority", "print_date",
)
UPWARD_DEFAULT = {"报告", "请示"}
PAGE_HEIGHT = 16838
BODY_BOTTOM = PAGE_HEIGHT - 1984
CHAR_TWIPS = 320
LINE_TWIPS = 560
TEXT_WIDTH = 8845
# Paragraph spacing reaches the line box, while GB/T 9704 measures to the
# visible upper edge of the issuer mark. These calibrated values compensate
# for the font ascent so the rendered glyph edge lands at 35 mm (ordinary and
# minutes) or 20 mm (command) below the upper edge of the text area.
STANDARD_MARK_TOP_GAP = 1890
COMMAND_MARK_TOP_GAP = 1040
# “标志下空二行” is a visual position. Two complete paragraph-spacing lines
# after the mark's own exact-height line box push the number and red rule low.
HEADER_NUMBER_TOP_GAP = 840
LETTER_LINE_WIDTH = 9638      # 170 mm


def x(value):
    return escape(str(value or ""), quote=False)


def text_width_twips(text):
    """Approximate advance width at 16 pt for signature-line alignment."""
    units = 0.0
    for ch in str(text or ""):
        units += 1.0 if unicodedata.east_asian_width(ch) in {"W", "F", "A"} else 0.5
    return round(units * CHAR_TWIPS)


def signature_indents(issuer, date):
    """GB/T 9704—2012 7.3.5.2 alignment for unsigned single-agency documents."""
    issuer_width = text_width_twips(issuer)
    date_width = text_width_twips(date)
    if date_width <= issuer_width:
        return 2 * CHAR_TWIPS, max(0, issuer_width - date_width)
    return 4 * CHAR_TWIPS + date_width - issuer_width, 2 * CHAR_TWIPS


def run(text, font=FONT_BODY, size=32, bold=False, color=BLACK):
    return ('<w:r><w:rPr>'
            f'<w:rFonts w:ascii="{x(font)}" w:hAnsi="{x(font)}" w:eastAsia="{x(font)}" w:cs="{x(font)}"/>'
            '<w:lang w:val="zh-CN" w:eastAsia="zh-CN" w:bidi="zh-CN"/>'
            f'<w:color w:val="{color}"/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
            + ('<w:b/><w:bCs/>' if bold else '<w:b w:val="0"/><w:bCs w:val="0"/>')
            + f'</w:rPr><w:t xml:space="preserve">{x(text)}</w:t></w:r>')


def paragraph(text="", *, font=FONT_BODY, size=32, bold=False, color=BLACK,
              align="both", first_line=640, left=0, right=0, hanging=0,
              before=0, after=0, line=560, keep_next=False,
              border_bottom=None, border_top=None, page_break_before=False,
              raw_runs=None):
    props = [f'<w:jc w:val="{align}"/>']
    # Word/WPS can otherwise insert extra spacing between Latin/digits and Han
    # characters, invalidating the two-character signature/date alignment.
    props.extend(['<w:autoSpaceDE w:val="0"/>', '<w:autoSpaceDN w:val="0"/>'])
    ind = []
    if first_line:
        ind.append(f'w:firstLine="{first_line}"')
    if left:
        ind.append(f'w:left="{left}"')
    if right:
        ind.append(f'w:right="{right}"')
    if hanging:
        ind.append(f'w:hanging="{hanging}"')
    if ind:
        props.append('<w:ind ' + ' '.join(ind) + '/>')
    props.append(f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="exact"/>')
    props.append('<w:widowControl/>')
    if keep_next:
        props.append('<w:keepNext/>')
    if page_break_before:
        props.append('<w:pageBreakBefore/>')
    borders = []
    if border_top:
        val = border_top[3] if len(border_top) > 3 else "single"
        borders.append(f'<w:top w:val="{val}" w:sz="{border_top[0]}" w:space="{border_top[1]}" w:color="{border_top[2]}"/>')
    if border_bottom:
        val = border_bottom[3] if len(border_bottom) > 3 else "single"
        borders.append(f'<w:bottom w:val="{val}" w:sz="{border_bottom[0]}" w:space="{border_bottom[1]}" w:color="{border_bottom[2]}"/>')
    if borders:
        props.append('<w:pBdr>' + ''.join(borders) + '</w:pBdr>')
    order = ['keepNext', 'pageBreakBefore', 'widowControl', 'pBdr', 'autoSpaceDE', 'autoSpaceDN', 'snapToGrid', 'spacing', 'ind', 'jc']
    props.sort(key=lambda value: order.index(re.match(r'<w:(\w+)', value).group(1)))
    content = raw_runs if raw_runs is not None else run(text, font, size, bold, color)
    return f'<w:p><w:pPr>{"".join(props)}</w:pPr>{content}</w:p>'


def positioned_signature_line(text, right, *, before=0, keep_next=False):
    """Use editable right tabs to preserve mixed-script signature geometry.

    Some DOCX importers ignore autoSpaceDE/DN. Script-group tab stops express
    the intended positions without changing glyphs, fonts, or visible text.
    Do not combine this with a paragraph right indent: renderer rounding at
    that boundary can wrap the last character. The final stop is the inset.
    """
    segments = re.findall(r'[\x20-\x7e]+|[^\x20-\x7e]+', text)
    cursor = TEXT_WIDTH - right - text_width_twips(text)
    if cursor < 0 or right < 0:
        raise ValueError('署名或日期超出版心，请确认简称或采用专门排版')
    stops, runs = [], []
    for part in segments:
        cursor += text_width_twips(part)
        stops.append(f'<w:tab w:val="right" w:pos="{cursor}"/>')
        runs.append(run('').replace('<w:t xml:space="preserve"></w:t>', '<w:tab/>') + run(part))
    # A date as long as the issuer can end at the body edge under 7.3.5.2.
    # Give the line box 0.5 pt of rounding slack, without moving any tab stop,
    # so a renderer's sub-point tab advances cannot wrap the final character.
    guard = -10 if right == 0 else 0
    result = paragraph('', align='left', first_line=0, right=guard, before=before,
                       keep_next=keep_next, raw_runs=''.join(runs))
    return result.replace('<w:autoSpaceDE', '<w:tabs>' + ''.join(stops) + '</w:tabs><w:autoSpaceDE', 1)


def cell(text, width, *, align="left", font=FONT_BODY, size=32, bold=False, color=BLACK,
         left=0, right=0, borders="none", top_border=None, bottom_border=None,
         raw_runs=None, grid_span=1, hanging=0, valign='top'):
    p = paragraph(text, font=font, size=size, bold=bold, color=color,
                  align=align, first_line=0, left=left, right=right, hanging=hanging, line=560,
                  raw_runs=raw_runs)
    def border(side, override):
        if not override:
            return f'<w:{side} w:val="{borders}"/>'
        val, size_value, space_value, border_color = override
        return (f'<w:{side} w:val="{val}" w:sz="{size_value}" '
                f'w:space="{space_value}" w:color="{border_color}"/>')
    tc_borders = ('<w:tcBorders>'
                  + border("top", top_border)
                  + '<w:left w:val="none"/>'
                  + border("bottom", bottom_border)
                  + '<w:right w:val="none"/><w:insideH w:val="none"/><w:insideV w:val="none"/>'
                  + '</w:tcBorders>')
    span = f'<w:gridSpan w:val="{grid_span}"/>' if grid_span > 1 else ''
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{span}'
            '<w:tcMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
            '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tcMar>'
            f'{tc_borders}<w:vAlign w:val="{valign}"/></w:tcPr>{p}</w:tc>')


def header_number_table(document_number, signatory):
    # Keep the legacy function name for callers, but use one paragraph: table
    # border spacing is ignored by some importers and put the red rule too close.
    if text_width_twips(document_number + '签发人：' + signatory) + 3*CHAR_TWIPS > TEXT_WIDTH:
        raise ValueError('文号与签发人超出单行版头容量，请采用经核验的多签发人专门排版')
    tab_run = run('').replace('<w:t xml:space="preserve"></w:t>', '<w:tab/>')
    result = paragraph('', align='left', first_line=0, left=320,
                       before=HEADER_NUMBER_TOP_GAP, keep_next=True,
                       border_bottom=(8, 4, RED),
                       raw_runs=run(document_number)+tab_run+run('签发人：')+run(signatory,FONT_KAI))
    # Border extends to the full text area; the text indent is expressed by a
    # leading tab instead so the red line is not shortened on the left.
    result = result.replace('<w:ind w:left="320"/>', '')
    result = result.replace('</w:pPr>', '</w:pPr>'+tab_run, 1)
    return result.replace('<w:autoSpaceDE', '<w:tabs><w:tab w:val="left" w:pos="320"/><w:tab w:val="right" w:pos="8525"/></w:tabs><w:autoSpaceDE', 1)


def footer_xml(align, letter_rule=False):
    indent = 'w:right="280"' if align == "right" else 'w:left="280"'
    rule = ''
    if letter_rule:
        rule = paragraph('', align='center', first_line=0, left=-397, right=-397, line=1,
                         border_top=(12, 0, RED, 'thinThickSmallGap'))
    def field(contents):
        return run('', FONT_SONG, 28).replace('<w:t xml:space="preserve"></w:t>', contents)
    page_field = ''.join(field(v) for v in (
        '<w:fldChar w:fldCharType="begin"/>',
        '<w:instrText xml:space="preserve"> PAGE </w:instrText>',
        '<w:fldChar w:fldCharType="separate"/>')) + run('1', FONT_SONG, 28) + field('<w:fldChar w:fldCharType="end"/>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W}" xmlns:r="{R}">{rule}<w:p><w:pPr><w:jc w:val="{align}"/><w:ind {indent}/><w:spacing w:before="0" w:after="0"/></w:pPr>
{run('— ', FONT_SONG, 28)}{page_field}{run(' —', FONT_SONG, 28)}</w:p></w:ftr>'''


def first_footer_xml(profile):
    rule = ''
    if profile == 'letter':
        rule = paragraph('', align='center', first_line=0, left=-397, right=-397, line=1,
                         border_top=(12, 0, RED, 'thinThickSmallGap'))
    # A trailing empty paragraph inherits the document's 28 pt line height
    # and raises the preceding rule by a whole body line. The rule paragraph
    # already satisfies the footer's block-content requirement.
    content = rule or paragraph('', first_line=0, line=1)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W}" xmlns:r="{R}">{content}</w:ftr>'''


def layout_for(data):
    doc_type = str(data.get("document_type") or "").strip()
    explicit = str(data.get("layout_profile") or "").strip()
    if explicit:
        return explicit
    return {"命令（令）": "command", "函": "letter", "纪要": "minutes"}.get(doc_type, "standard")


def issuer_from_mark(value):
    """Return the single-agency name represented by an ordinary issuer mark."""
    text = str(value or "").strip()
    for suffix in ("会议纪要", "纪要", "命令", "令", "文件"):
        if text.endswith(suffix):
            return text[:-len(suffix)].strip()
    return text


def body_blocks(data, keep_last_with_next=False):
    parts = []
    for item in data.get("blocks") or []:
        kind, text = str(item.get("type") or "body"), str(item.get("text") or "").strip()
        if not text:
            continue
        if kind == "heading1":
            parts.append(paragraph(text, font=FONT_HEI, align="left", first_line=0, keep_next=True))
        elif kind == "heading2":
            parts.append(paragraph(text, font=FONT_KAI, first_line=640, keep_next=True))
        elif kind == "heading3":
            parts.append(paragraph(text, font=FONT_BODY, first_line=640, keep_next=True))
        elif kind == "heading4":
            parts.append(paragraph(text, font=FONT_BODY, first_line=640, keep_next=True))
        elif kind == "noindent":
            parts.append(paragraph(text, align="left", first_line=0))
        elif kind == "center":
            parts.append(paragraph(text, align="center", first_line=0))
        elif kind == "note":
            parts.append(paragraph(text, font=FONT_KAI, first_line=640))
        else:
            parts.append(paragraph(text))
    if parts and keep_last_with_next and '<w:keepNext' not in parts[-1]:
        parts[-1] = parts[-1].replace('<w:pPr>', '<w:pPr><w:keepNext/>', 1)
    return parts


def title_runs(data):
    title = str(data.get("title") or "").strip()
    lines = data.get("title_lines")
    if lines is None:
        if text_width_twips(title) * 22 / 16 > TEXT_WIDTH:
            raise ValueError("长标题必须提供title_lines，按词意分行，不得在词内自动折行")
        return None
    if not isinstance(lines, list) or not lines or any(not isinstance(v, str) or not v for v in lines):
        raise ValueError("title_lines must be a nonempty array of strings")
    if ''.join(lines) != title:
        raise ValueError("title_lines must concatenate exactly to title")
    if any(text_width_twips(v) * 22 / 16 > TEXT_WIDTH for v in lines):
        raise ValueError("title_lines contains an overwide line at 22pt")
    separator = run('', FONT_TITLE, 44).replace('</w:r>', '<w:br/></w:r>')
    return separator.join(run(v, FONT_TITLE, 44) for v in lines)


def attachments_block(data):
    raw = data.get("attachments") or []
    raw = [raw] if isinstance(raw, str) else raw
    items = [str(v).strip() for v in raw if str(v).strip()]
    if not items:
        return []
    result = []
    for index, item in enumerate(items, 1):
        label = ('附件：' if index == 1 else '') + (f'{index}. ' if len(items)>1 else '')
        start = 640 if index == 1 else 1600
        label_width = text_width_twips(label)
        result.append(paragraph(label+item, align='left', first_line=0,
                                left=start+label_width, hanging=label_width,
                                before=560 if index == 1 else 0, keep_next=True))
    return result


def attachment_pages(data):
    """Render supplied attachment bodies on separate pages before the edition note."""
    result = []
    for index, item in enumerate(data.get("attachment_documents") or [], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        label = "附件" if len(data.get("attachment_documents") or []) == 1 else f"附件{index}"
        result.append(paragraph(label, font=FONT_HEI, align="left", first_line=0,
                                page_break_before=True, keep_next=True))
        result.append(paragraph(title, font=FONT_TITLE, size=44, align="center",
                                first_line=0, before=560, after=560, line=640,
                                keep_next=True))
        for block in item.get("blocks") or []:
            kind = str(block.get("type") or "body")
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            if kind == "heading1":
                result.append(paragraph(text, font=FONT_HEI, align="left", first_line=0, keep_next=True))
            elif kind == "heading2":
                result.append(paragraph(text, font=FONT_KAI, align="left", first_line=640, keep_next=True))
            else:
                result.append(paragraph(text))
    return result


def signature_block(data, profile):
    if data.get('official_document', True) is False:
        # Speeches and work summaries do not acquire statutory placeholders.
        return [paragraph(str(data[key]), align='right', first_line=0, right=640,
                          before=560 if key == 'issuer' else 0)
                for key in ('issuer', 'date') if data.get(key)]
    issuer = str(data.get("issuer") or "〔发文机关署名由用户单位填写〕").strip()
    date = normalize_cn_date(data.get("date") or "〔成文日期由用户单位填写〕")
    result = []
    if profile == "command":
        signer_title = str(data.get("signer_title") or "〔签署人职务由用户单位填写〕").strip()
        signer_name = str(data.get("signer_name") or "〔签署人姓名由用户单位填写〕").strip()
        result.append(paragraph('', align="right", first_line=0, right=1280,
                                before=1120, keep_next=True,
                                raw_runs=run(signer_title, FONT_BODY) + run('　　') + run(signer_name, FONT_KAI)))
        result.append(positioned_signature_line(date, 1280, before=560))
    elif str(data.get("document_type") or "") == "议案":
        title = str(data.get("proposer_title") or "〔提出人职务由用户单位填写〕").strip()
        name = str(data.get("proposer_name") or "〔提出人姓名由用户单位填写〕").strip()
        result.append(paragraph(f"{title}  {name}", align="right", first_line=0, right=640, before=560, keep_next=True))
        result.append(positioned_signature_line(date, 1280))
    else:
        if data.get("seal_requirement") == "required":
            date_right = 4 * CHAR_TWIPS
            issuer_right = max(0, date_right + (text_width_twips(date) - text_width_twips(issuer)) // 2)
        else:
            issuer_right, date_right = signature_indents(issuer, date)
        result.append(positioned_signature_line(issuer, issuer_right, before=560, keep_next=True))
        result.append(positioned_signature_line(date, date_right))
    note = str(data.get("note") or "").strip()
    if note:
        note = note if note.startswith("（") and note.endswith("）") else f"（{note}）"
        result.append(paragraph(note, align="left", first_line=0, left=640))
    return result


def edition_note_table(data, profile):
    """Plan wrapped lines first, then anchor the indivisible block above the bottom rule."""
    layout = edition_plan(data, profile)
    if not layout['total_rows']:
        return ''
    br = run('', FONT_BODY, 28).replace('</w:r>', '<w:br/></w:r>')
    def lines_runs(lines):
        return br.join(run(line, FONT_BODY, 28) for line in lines)
    rows = []
    letter = profile == 'letter'
    if layout['leading_rows']:
        # Separate paragraphs ensure each label has a three-character hanging indent.
        paragraphs = ''.join(paragraph('', align='left', first_line=0, left=1120, right=280,
                            hanging=840, keep_next=True, raw_runs=lines_runs(lines))
                             for lines in layout['leading'])
        tc = cell('', 8845, font=FONT_BODY, size=28, grid_span=2,
                  top_border=None if letter else ('single',8,0,BLACK),
                  bottom_border=None if letter else ('single',6,0,BLACK))
        tc = tc[:tc.index('<w:p>')] + paragraphs + '</w:tc>'
        rows.append(f'<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{560*layout["leading_rows"]}" w:hRule="exact"/></w:trPr>' + tc + '</w:tr>')
    if layout['final']:
        top = ('single', 6 if layout['leading_rows'] else 8, 0, BLACK)
        bottom = ('single',8,0,BLACK)
        rows.append(f'<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{560*layout["final_rows"]}" w:hRule="exact"/></w:trPr>'
                    + cell('',5200,align='left',font=FONT_BODY,size=28,left=280,top_border=top,bottom_border=bottom,raw_runs=lines_runs(layout['final'][0]),valign='bottom')
                    + cell('',3645,align='right',font=FONT_BODY,size=28,right=280,top_border=top,bottom_border=bottom,raw_runs=lines_runs(layout['final'][1]),valign='bottom') + '</w:tr>')
    table_y = (PAGE_HEIGHT-1134-560*(layout['total_rows']+1)) if letter else BODY_BOTTOM-560*layout['total_rows']
    borders = ''.join(f'<w:{side} w:val="none"/>' for side in ('top','left','bottom','right','insideH','insideV')) if letter else ('<w:top w:val="single" w:sz="8" w:color="000000"/><w:left w:val="none"/><w:right w:val="none"/><w:bottom w:val="single" w:sz="8" w:color="000000"/><w:insideH w:val="single" w:sz="6" w:color="000000"/><w:insideV w:val="none"/>')
    return ('<w:tbl><w:tblPr>'
            f'<w:tblpPr w:vertAnchor="page" w:horzAnchor="margin" w:tblpY="{table_y}" w:tblpXSpec="center" w:leftFromText="0" w:rightFromText="0" w:topFromText="0" w:bottomFromText="0"/>'
            '<w:tblW w:w="8845" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
            f'<w:tblBorders>{borders}</w:tblBorders></w:tblPr><w:tblGrid><w:gridCol w:w="5200"/><w:gridCol w:w="3645"/></w:tblGrid>' + ''.join(rows) + '</w:tbl>')




def header_block(data, profile):
    issuer_mark = str(data.get("issuer_mark") or "〔发文机关标志由用户单位填写〕").strip()
    document_number = str(data.get("document_number") or "发文字号：〔由用户单位填写〕").strip()
    signatory = str(data.get("signatory") or "").strip()
    direction = str(data.get("direction") or "").strip()
    parts = []
    if profile == "command":
        mark = issuer_mark if issuer_mark.endswith("令") else issuer_mark.replace("文件", "") + "令"
        parts.append(paragraph(mark, font=FONT_TITLE, size=64, bold=False, color=RED,
                               align="center", first_line=0, before=COMMAND_MARK_TOP_GAP,
                               line=800, keep_next=True))
        parts.append(paragraph(document_number, align="center", first_line=0,
                               before=HEADER_NUMBER_TOP_GAP, line=560, keep_next=True))
    elif profile == "letter":
        parts.append(paragraph(issuer_mark.replace("文件", ""), font=FONT_TITLE, size=56,
                               bold=False, color=RED, align="center", first_line=0,
                               left=-397, right=-397, line=720, keep_next=True,
                               border_bottom=(12, 6, RED, "thickThinSmallGap")))
        parts.append(paragraph(document_number, align="right", first_line=0,
                               before=420, line=560, keep_next=True))
    elif profile == "minutes":
        mark = str(data.get("minutes_mark") or issuer_mark).strip().replace("文件", "")
        mark = mark if "纪要" in mark else mark + "会议纪要"
        parts.append(paragraph(mark, font=FONT_TITLE, size=56, bold=False, color=RED,
                               align="center", first_line=0, before=STANDARD_MARK_TOP_GAP,
                               line=720, keep_next=True))
        parts.append(paragraph(document_number, align="center", first_line=0,
                               before=HEADER_NUMBER_TOP_GAP, line=560, keep_next=True,
                               border_bottom=(8, 4, RED)))
    else:
        size = 72 if len(issuer_mark) <= 14 else (64 if len(issuer_mark) <= 20 else 56)
        parts.append(paragraph(issuer_mark, font=FONT_TITLE, size=size, bold=False, color=RED,
                               align="center", first_line=0, before=STANDARD_MARK_TOP_GAP,
                               line=880, keep_next=True))
        if direction == "upward" and signatory:
            parts.append(header_number_table(document_number, signatory))
        else:
            parts.append(paragraph(document_number, align="center", first_line=0,
                                   before=HEADER_NUMBER_TOP_GAP, line=560, keep_next=True,
                                   border_bottom=(8, 4, RED)))
    return parts


def document_xml(data, default_footer_id, even_footer_id, first_footer_id):
    official = bool(data.get("official_document", True))
    title = str(data.get("title") or "").strip()
    doc_type = str(data.get("document_type") or "").strip()
    if not title:
        raise ValueError("title is required")
    if official and doc_type not in LEGAL_TYPES:
        raise ValueError("document_type must be one of the 15 statutory types")
    profile = layout_for(data)
    parts = header_block(data, profile) if official else []
    if profile == "command":
        parts.append(paragraph('', align="left", first_line=0, before=1120, line=1))
    else:
        parts.append(paragraph(title, font=FONT_TITLE, size=44, align="center", first_line=0,
                               before=1120 if official else 0, after=560,
                               line=640, keep_next=True, raw_runs=title_runs(data)))
    adoption = str(data.get("adoption_line") or "").strip()
    if adoption:
        parts.append(paragraph(adoption, font=FONT_BODY, align="center", first_line=0, after=280, keep_next=True))
    recipient = "" if data.get("recipient_in_edition") else str(data.get("recipient") or "").strip()
    if recipient:
        parts.append(paragraph(recipient if recipient.endswith("：") else recipient + "：", align="left", first_line=0, keep_next=True))
    signature = signature_block(data, profile)
    # Keep the last substantive paragraph/closing with attachment descriptions
    # and signature, avoiding a signature-only next page. Visual QA remains
    # required for unusually long paragraphs and complex layouts.
    parts.extend(body_blocks(data, keep_last_with_next=bool(signature)))
    parts.extend(attachments_block(data))
    if profile == "minutes":
        first_roster = True
        for key, label in (("attendees", "出席"), ("absent_attendees", "请假"), ("nonvoting_attendees", "列席")):
            value = str(data.get(key) or "").strip()
            if value:
                parts.append(paragraph('', align="left", first_line=0, left=1600, hanging=960,
                                       before=560 if first_roster else 0, keep_next=True,
                                       raw_runs=run(f'{label}：', FONT_HEI) + run(value, FONT_BODY)))
                first_roster = False
    parts.extend(signature)
    parts.extend(attachment_pages(data))
    edition = edition_note_table(data, profile)
    if edition:
        parts.append(edition)
    # Letter: line box starts above the 30 mm visible glyph edge to account
    # for the specified small-title-Song font's ascent (not a 30 mm margin).
    top_margin = 1617 if profile == "letter" else 2098
    bottom_margin = 1134 if profile == "letter" else 1984
    # With the required 14 pt SimSun and 28 pt footer line box, this footer
    # offset places the visible one-character rule 7 mm below the body edge.
    # pgMar/footer locates the line box, not the rule's visible ink.
    footer_margin = 1134 if profile == "letter" else 1360
    first_ref = f'<w:footerReference w:type="first" r:id="{x(first_footer_id)}"/><w:titlePg/>' if profile == "letter" else ''
    sect = f'''<w:sectPr><w:footerReference w:type="default" r:id="{x(default_footer_id)}"/><w:footerReference w:type="even" r:id="{x(even_footer_id)}"/>{first_ref}<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="{top_margin}" w:right="1474" w:bottom="{bottom_margin}" w:left="1587" w:header="851" w:footer="{footer_margin}" w:gutter="0"/><w:cols w:space="425"/><w:docGrid w:type="lines" w:linePitch="560"/></w:sectPr>'''
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{''.join(parts)}{sect}</w:body></w:document>'''


def styles_xml():
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="{FONT_BODY}" w:cs="Times New Roman"/><w:lang w:val="zh-CN" w:eastAsia="zh-CN" w:bidi="zh-CN"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0" w:line="560" w:lineRule="exact"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style></w:styles>'''


def font_table_xml():
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts xmlns:w="{W}">
<w:font w:name="Times New Roman"><w:family w:val="roman"/><w:pitch w:val="variable"/></w:font>
<w:font w:name="{FONT_BODY}"><w:altName w:val="仿宋"/><w:family w:val="roman"/><w:charset w:val="86"/></w:font>
<w:font w:name="{FONT_TITLE}"><w:altName w:val="小标宋"/><w:family w:val="roman"/><w:charset w:val="86"/></w:font>
<w:font w:name="{FONT_HEI}"><w:family w:val="swiss"/><w:charset w:val="86"/></w:font>
<w:font w:name="{FONT_KAI}"><w:altName w:val="楷体"/><w:family w:val="roman"/><w:charset w:val="86"/></w:font>
<w:font w:name="{FONT_SONG}"><w:family w:val="roman"/><w:charset w:val="86"/></w:font>
</w:fonts>'''


def normalized_settings(raw):
    text = raw.decode("utf-8")
    return text if "<w:evenAndOddHeaders" in text else text.replace("</w:settings>", "<w:evenAndOddHeaders/></w:settings>")


def ensure_footer3_relationship(raw):
    text = raw.decode("utf-8")
    match = re.search(r'<Relationship\b[^>]*\bId="([^"]+)"[^>]*\bTarget="footer3\.xml"', text)
    if match:
        return raw, match.group(1)
    used = set(re.findall(r'\bId="(rId\d+)"', text))
    number = 11
    while f"rId{number}" in used:
        number += 1
    rel_id = f"rId{number}"
    element = (f'<Relationship Id="{rel_id}" '
               'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
               'Target="footer3.xml"/>')
    return text.replace("</Relationships>", element + "</Relationships>").encode("utf-8"), rel_id


def ensure_footer3_content_type(raw):
    text = raw.decode("utf-8")
    if 'PartName="/word/footer3.xml"' not in text:
        element = ('<Override PartName="/word/footer3.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
        text = text.replace("</Types>", element + "</Types>")
    return text.encode("utf-8")


def validate_input(data):
    official = bool(data.get('official_document', True))
    if not official:
        if data.get('layout_profile') not in {None, '', 'standard'}:
            raise ValueError('事务文书不套用命令、信函或纪要专用版头')
        if any(data.get(key) for key in ('issuer_mark', 'document_number', 'signatory', 'copy_to', 'printing_authority', 'print_date')):
            raise ValueError('事务文书不自动套用红头、签发人或法定公文版记，请先确认文书用途')
        data.setdefault('seal_requirement', 'not_required')
    if "seal" in data:
        legacy_seal = data.pop("seal")
        mapping = {
            True: "required", False: "not_required",
            "required": "required", "not_required": "not_required",
            "需要": "required", "需要加盖公章": "required",
            "不需要": "not_required", "不加盖公章": "not_required",
        }
        if not isinstance(legacy_seal, (bool, str)) or legacy_seal not in mapping:
            raise ValueError("seal may only be a simple stamping requirement; seal media is forbidden")
        data.setdefault("seal_requirement", mapping[legacy_seal])
    doc_type = str(data.get("document_type") or "").strip()
    if data.get("official_document") and data.get("content_validation_required"):
        contract = data.get("user_contract")
        if not isinstance(contract, dict):
            raise ValueError("new official drafts require user_contract copied from the user's explicit fields")
        missing_contract = [key for key in USER_CONTRACT_FIELDS if key not in contract]
        if missing_contract:
            raise ValueError("user_contract missing fields: " + ", ".join(missing_contract))
        mismatched = [key for key in USER_CONTRACT_FIELDS if data.get(key, "") != contract.get(key, "")]
        if mismatched:
            raise ValueError("input differs from user_contract: " + ", ".join(mismatched))
        if "postscript" in data:
            raise ValueError("legacy postscript is forbidden; use attachments for attachment descriptions")
    direction = str(data.get("direction") or ("upward" if doc_type in UPWARD_DEFAULT else "downward")).strip()
    data["direction"], data["layout_profile"] = direction, layout_for(data)
    type_selection = data.get("type_selection")
    if type_selection is not None:
        if not isinstance(type_selection, dict):
            raise ValueError("type_selection must be an object")
        routed = select_document_type(type_selection)
        if routed["status"] != "ok":
            raise ValueError("document type selection is not resolved: " + routed["reason"])
        if routed["recommended_type"] != doc_type:
            raise ValueError(f"document_type must match routed type: {routed['recommended_type']}")
        if routed["direction"] != direction:
            raise ValueError(f"direction must match routed direction: {routed['direction']}")
        if routed["layout_profile"] != data["layout_profile"]:
            raise ValueError(f"layout_profile must match routed profile: {routed['layout_profile']}")
        routed_subtype = str(routed.get("recommended_subtype") or "").strip()
        actual_subtype = str(data.get("document_subtype") or "").strip()
        if routed_subtype and actual_subtype and routed_subtype != actual_subtype:
            raise ValueError(f"document_subtype must match routed subtype: {routed_subtype}")
    if official and data.get("content_validation_required") is True:
        content_result = validate_content(data)
        if not content_result["ok"]:
            messages = [item["message"] for item in content_result["issues"]["blocking"]]
            raise ValueError("content validation failed: " + "；".join(messages))
    if data.get("material_analysis_required") is True:
        material_result = analyze_materials(data)
        if not material_result["ok"]:
            raise ValueError("material analysis failed: " + "；".join(material_result["blocking"]))
    if data.get("text_review_required") is True:
        text_result = review_text(data)
        if not text_result["ok"]:
            messages = [item["message"] for item in text_result["issues"]["blocking"]]
            raise ValueError("text review failed: " + "；".join(messages))
    if direction != "upward" and data.get("signatory"):
        raise ValueError("signatory is only allowed for upward documents")
    if doc_type in {"命令（令）", "议案"} and data.get("signatory"):
        raise ValueError("commands and proposals use special signer fields, not signatory")
    if doc_type == "函" and direction != "parallel":
        raise ValueError("函 must use parallel direction")
    if doc_type == "命令（令）" and data.get("recipient"):
        raise ValueError("命令（令）专用格式不设置主送机关")
    if data.get("recipient_in_edition") and not data.get("recipient"):
        raise ValueError("recipient_in_edition requires recipient")
    if data.get("recipient_in_edition") not in {None, True, False}:
        raise ValueError("recipient_in_edition must be boolean")
    date = normalize_cn_date(data.get("date") or "")
    data["date"] = date
    if data.get("print_date"):
        data["print_date"] = normalize_cn_date(data.get("print_date"))
    issuing_body = str(data.get("issuing_body") or "").strip()
    issuer = str(data.get("issuer") or "").strip()
    # The title's agency wording, issuer mark, issuing-body metadata and
    # signature are independent user-controlled fields.  Do not force them
    # to be identical: an office may issue/sign a document whose supplied
    # title uses the parent unit's wording.  user_contract is the enforcement
    # layer that prevents silent substitution of any explicit value.
    for date_field in ('date', 'print_date'):
        issue = date_error(data.get(date_field))
        if issue:
            raise ValueError(date_field + '：' + issue)
    forbidden = {"stamp", "seal", "signature_image", "approval_status"} & set(data)
    if forbidden:
        raise ValueError("forbidden input fields: " + ", ".join(sorted(forbidden)))
    if "seal_requirement" not in data:
        raise ValueError("seal_requirement is required: use required or not_required; do not infer or omit it")
    seal_requirement = str(data.get("seal_requirement") or "").strip()
    if seal_requirement not in {"required", "not_required"}:
        raise ValueError("seal_requirement must be required or not_required")
    data["seal_requirement"] = seal_requirement


def build(data, output):
    validate_input(data)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    base = Path(__file__).resolve().parent.parent / "assets" / "base.docx"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(base, "r") as source:
        rels = ET.fromstring(source.read("word/_rels/document.xml.rels"))
        footer_ids = {Path(rel.get("Target", "")).name: rel.get("Id") for rel in rels.findall(f"{{{rel_ns}}}Relationship") if rel.get("Type", "").endswith("/footer")}
        default_footer_id, even_footer_id = footer_ids.get("footer1.xml"), footer_ids.get("footer2.xml")
        if not default_footer_id or not even_footer_id:
            raise ValueError("base.docx must contain odd and even footers")
        profile = layout_for(data)
        if profile == "letter":
            rels_xml, first_footer_id = ensure_footer3_relationship(source.read("word/_rels/document.xml.rels"))
            content_types_xml = ensure_footer3_content_type(source.read("[Content_Types].xml"))
        else:
            rels_xml = source.read("word/_rels/document.xml.rels")
            content_types_xml = source.read("[Content_Types].xml")
            first_footer_id = ""
        replacements = {
            "[Content_Types].xml": content_types_xml,
            "word/_rels/document.xml.rels": rels_xml,
            "word/document.xml": document_xml(data, default_footer_id, even_footer_id, first_footer_id).encode("utf-8"),
            "word/styles.xml": styles_xml().encode("utf-8"),
            "word/fontTable.xml": font_table_xml().encode("utf-8"),
            "word/footer1.xml": footer_xml("right", profile == "letter").encode("utf-8"),
            "word/footer2.xml": footer_xml("left", profile == "letter").encode("utf-8"),
            "word/settings.xml": normalized_settings(source.read("word/settings.xml")).encode("utf-8"),
            "docProps/core.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{x(data.get('title'))}（草稿）</dc:title><dc:creator></dc:creator><cp:lastModifiedBy></cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>'''.encode("utf-8")}
        with ZipFile(output, "w", ZIP_DEFLATED) as target:
            for item in source.infolist():
                target.writestr(item, replacements.get(item.filename, source.read(item.filename)))
            if profile == "letter":
                target.writestr("word/footer3.xml", first_footer_xml(profile).encode("utf-8"))


def generate(data, output):
    """Compatibility entry point for tool callers; delegates to the validated builder."""
    return build(data, output)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_docx.py input.json output.docx")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    build(data, sys.argv[2])
    print(Path(sys.argv[2]).resolve())


if __name__ == "__main__":
    main()
