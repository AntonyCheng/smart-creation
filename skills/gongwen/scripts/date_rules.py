"""Calendar checks for supplied document dates; never invent a missing date."""
import re
from datetime import date


def normalize(value):
    text = str(value or '').strip()
    compact = re.sub(r'\s+', '', text)
    match = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', compact)
    if not match:
        return text
    year, month, day = map(int, match.groups())
    return f'{year:04d}年{month}月{day}日'


def error(value):
    text = normalize(value)
    if not text or (text.startswith('〔') and text.endswith('〕')):
        return None
    match = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not match:
        return '日期须使用完整阿拉伯数字年月日'
    try:
        date(*map(int, match.groups()))
    except ValueError:
        return '日期不存在，请核对年份、月份和日数'
    return None
