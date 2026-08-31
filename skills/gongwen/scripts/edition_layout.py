"""Measured line plans for four-point-size (14pt) edition-note text."""
import unicodedata

CHAR = 280  # one 14pt Han character in twips
WIDTH = 8845


def width(text):
    return sum(CHAR if unicodedata.east_asian_width(c) in {'W', 'F', 'A'} else CHAR/2 for c in text)


def wrap(text, first_width, next_width=None):
    next_width = next_width or first_width
    lines, current = [], ''
    for char in text:
        capacity = first_width if not lines else next_width
        if current and width(current + char) > capacity:
            lines.append(current)
            current = ''
        current += char
    if current or not lines:
        lines.append(current)
    return lines


def plan(data, profile):
    leading = []
    for key, label, enabled in [('recipient', '主送：', data.get('recipient_in_edition')), ('copy_to', '抄送：', True)]:
        value = str(data.get(key) or '').strip().rstrip('：。；;') if enabled else ''
        if value:
            leading.append(wrap(label + value + '。', WIDTH-2*CHAR, WIDTH-5*CHAR))
    if profile == 'letter':
        final = None
    elif leading or data.get('printing_authority') or data.get('print_date'):
        left = str(data.get('printing_authority') or '〔印发机关由用户单位填写〕').strip()
        date = ''.join(str(data.get('print_date') or '').split())
        right = date + '印发' if date else '〔印发日期由用户单位填写〕'
        final = [wrap(left, 5200-CHAR), wrap(right, 3645-CHAR)]
    else:
        final = None
    leading_rows = sum(map(len, leading))
    final_rows = max(map(len, final)) if final else 0
    total_rows = leading_rows + final_rows
    if total_rows > 18:
        raise ValueError('版记超过18行，需人工分页编排，不能压缩字体或裁切')
    return {'leading':leading, 'final':final, 'leading_rows':leading_rows, 'final_rows':final_rows, 'total_rows':total_rows}
