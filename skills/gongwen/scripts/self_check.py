#!/usr/bin/env python3
"""Offline package/environment checks, without claiming visual compliance."""
import json,sys,zipfile
from pathlib import Path
from runtime_support import config,font_status
ROOT=Path(__file__).resolve().parent.parent

def check():
    errors=[]
    if sys.version_info<(3,9): errors.append('Python版本低于3.9')
    for p in (ROOT/'scripts').glob('*.py'):
        try: compile(p.read_text(encoding='utf-8'),str(p),'exec')
        except SyntaxError as exc: errors.append(str(exc))
    try:
        with zipfile.ZipFile(ROOT/'assets/base.docx') as z:
            if z.testzip(): errors.append('DOCX基础容器损坏')
    except (OSError,zipfile.BadZipFile) as exc: errors.append(str(exc))
    try:
        settings=config()
        output=Path(settings['output_root'])
        if not output.is_dir(): errors.append('输出目录不存在')
        status=font_status(settings.get('fontconfig_file'))
    except (OSError,ValueError) as exc:
        errors.append(str(exc)); status={'status':'unknown'}
    if len(list((ROOT/'assets/fonts').glob('*.ttf')))+len(list((ROOT/'assets/fonts').glob('*.TTF')))+len(list((ROOT/'assets/fonts').glob('*.ttc')))!=5:
        errors.append('随包字体文件数量不符')
    return {'ok':not errors,'errors':errors,'font_environment':status,'visual_check':'not_performed'}

if __name__=='__main__':
    result=check(); print(json.dumps(result,ensure_ascii=False,indent=2)); sys.exit(0 if result['ok'] else 1)
