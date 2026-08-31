#!/usr/bin/env python3
"""Configure a local installation; no network, fonts or account credentials."""
import argparse,json
from xml.sax.saxutils import escape
from pathlib import Path

def setup(output, config_path=None):
    root=Path(output).expanduser()
    if not root.is_absolute():
        raise ValueError('输出目录必须是使用方指定的绝对路径')
    target=Path(config_path) if config_path else Path(__file__).resolve().parent.parent/'runtime.json'
    root=root.resolve()
    root.mkdir(parents=True,exist_ok=True)
    font_dir=Path(__file__).resolve().parent.parent/'assets/fonts'
    font_config=root/'gongwen-fonts.conf'
    settings={'delivery_mode':'local','output_root':str(root)}
    if target.exists():
        raise FileExistsError('配置已存在，不覆盖：'+str(target))
    if font_dir.is_dir():
        with font_config.open('x',encoding='utf-8') as handle:
            handle.write('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>'+escape(str(font_dir))+'</dir><cachedir>'+escape(str(root/'font-cache'))+'</cachedir></fontconfig>')
        settings['fontconfig_file']=str(font_config.resolve())
    # Never overwrite an existing host configuration.
    with target.open('x',encoding='utf-8') as handle:
        json.dump(settings,handle,ensure_ascii=False,indent=2)
    return {'config':str(target.resolve()),'output_root':str(root),'fonts':'使用方须另行确认已安装指定字体'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--config')
    args=parser.parse_args()
    try:
        print(json.dumps(setup(args.output,args.config),ensure_ascii=False))
    except (ValueError,OSError) as exc:
        parser.exit(1,str(exc)+'\n')
