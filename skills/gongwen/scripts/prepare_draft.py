#!/usr/bin/env python3
"""One call: content/type checks, build, structure check, receipt and candidate link.

No network or credentials. Actual transfer/HTTP check belongs to the host.
"""
import argparse
import hashlib
import json
import uuid
from pathlib import Path
from generate_docx import build
from validate_docx import validate
from runtime_support import config, file_link, font_status


def prepare(input_path, config_path=None):
    input_path = Path(input_path).resolve(strict=True)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if data.get('official_document', True) and (data.get('content_validation_required') is not True or not isinstance(data.get('type_selection'), dict)):
        raise ValueError('新起草法定公文必须启用内容校验并提供文种路由信息；不得关闭校验绕过阻断')
    settings = config(config_path)
    title = str(data.get("title") or "").strip()
    if not title or any(c in title for c in '/\\\x00\n\r') or len(title) > 120:
        raise ValueError("标题为空、过长或包含路径/控制字符")
    target_dir = Path(settings["output_root"]) / uuid.uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=False)
    path = target_dir / (title + "（草稿）.docx")
    build(data, path)
    errors, warnings, meta = validate(path, input_path)
    if errors:
        return {"ok": False, "stage": "structure", "errors": errors, "file_for_debug_only": str(path)}
    receipt = {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
               "structure_ok": True, "semantic_fact_check": "requires_source_review",
               "warnings": warnings, "font_environment": font_status(settings.get("fontconfig_file")), "visual_check": "not_performed",
               "download_check": "not_performed", "full_compliance": "not_certified", "meta": meta}
    receipt_path = target_dir / "validation-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "file": str(path), "receipt": str(receipt_path), "candidate_download_link": file_link(path, settings),
            "warnings": warnings, "font_environment": receipt["font_environment"],
            "visual_check": "not_performed", "download_check": "not_performed", "full_compliance": "not_certified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        result = prepare(args.input, args.config)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"ok": False, "stage": "prepare", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
