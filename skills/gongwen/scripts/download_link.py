#!/usr/bin/env python3
"""Link only an unchanged validated DOCX using this host's configuration."""

import argparse
import json
import hashlib
from pathlib import Path
from runtime_support import config, file_link


def checked_link(receipt_path, config_path=None):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    path = Path(receipt["file"])
    if receipt.get("structure_ok") is not True or receipt.get("source_coverage_ok") is not True:
        raise ValueError("未通过结构和来源覆盖检查")
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get("sha256"):
        raise ValueError("DOCX在校验后发生改变，禁止回传旧校验结果")
    return file_link(path, config(config_path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--config")
    args = parser.parse_args()
    link = checked_link(args.receipt, args.config)
    if link is None:
        raise SystemExit("local模式无浏览器下载URL，请使用宿主文件附件工具，不输出伪造链接")
    print(link)


if __name__ == "__main__":
    main()
