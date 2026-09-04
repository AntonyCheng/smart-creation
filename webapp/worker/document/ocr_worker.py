#!/usr/bin/env python3
"""Long-lived local PaddleOCR worker for Chinese source materials.

Runs inside its own virtualenv (``/opt/ocr-venv``); it must not import
anything from the application. Ported from the kLeagl ``document-runtime``.

Protocol: one JSON object per stdin line, one JSON response per stdout line.
The worker never accepts shell commands and writes only to the output path
selected by the trusted caller.

    {"id": "...", "inputPath": "...", "outputPath": "...", "profile": "mobile"}
      -> {"id": "...", "ok": true, "pageCount": N, "characterCount": N,
          "averageConfidence": 0.0-1.0 | null, "warnings": [...]}
      -> {"id": "...", "ok": false, "code": "OCR_FAILED", "error": "..."}
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result_data(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", None)
    if callable(value):
        value = value()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return {}
    nested = value.get("res")
    return nested if isinstance(nested, dict) else value


def polygon_position(polygon: Any) -> tuple[float, float]:
    try:
        points = list(polygon)
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return min(ys), min(xs)
    except (TypeError, ValueError, IndexError):
        return 0.0, 0.0


class OcrRuntime:
    def __init__(self) -> None:
        self._engines: dict[str, Any] = {}

    def engine(self, profile: str) -> Any:
        if profile in self._engines:
            return self._engines[profile]

        from paddleocr import PaddleOCR

        model_kind = "server" if profile == "server" else "mobile"
        kwargs = {
            "lang": "ch",
            "ocr_version": "PP-OCRv5",
            "text_detection_model_name": f"PP-OCRv5_{model_kind}_det",
            "text_recognition_model_name": f"PP-OCRv5_{model_kind}_rec",
            "use_doc_orientation_classify": True,
            "use_doc_unwarping": False,
            "use_textline_orientation": True,
        }
        self._engines[profile] = PaddleOCR(**kwargs)
        return self._engines[profile]

    def extract(self, input_path: Path, output_path: Path, profile: str) -> dict[str, Any]:
        engine = self.engine(profile)
        pages: list[str] = []
        scores: list[float] = []

        for page_number, result in enumerate(engine.predict(input=str(input_path)), start=1):
            data = result_data(result)
            texts = [str(value).strip() for value in (data.get("rec_texts") or [])]
            raw_scores = list(data.get("rec_scores") or [])
            polygons = list(data.get("rec_polys") or data.get("dt_polys") or [])

            rows: list[tuple[float, float, str, float | None]] = []
            for index, text in enumerate(texts):
                if not text:
                    continue
                y, x = polygon_position(polygons[index] if index < len(polygons) else None)
                confidence = None
                if index < len(raw_scores):
                    try:
                        confidence = float(raw_scores[index])
                        scores.append(confidence)
                    except (TypeError, ValueError):
                        confidence = None
                rows.append((y, x, text, confidence))
            rows.sort(key=lambda row: (round(row[0] / 12), row[1]))
            page_text = "\n".join(row[2] for row in rows)
            pages.append(f"<!-- page: {page_number} -->\n\n{page_text}".strip())

        markdown = "\n\n".join(pages).strip()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown + "\n", encoding="utf-8")
        return {
            "pageCount": len(pages) or None,
            "characterCount": len(markdown),
            "averageConfidence": (sum(scores) / len(scores)) if scores else None,
            "warnings": [],
        }


def main() -> None:
    runtime = OcrRuntime()
    for line in sys.stdin:
        job_id = None
        try:
            request = json.loads(line)
            job_id = request.get("id")
            input_path = Path(str(request["inputPath"])).resolve(strict=True)
            output_path = Path(str(request["outputPath"])).resolve()
            profile = "server" if request.get("profile") == "server" else "mobile"
            result = runtime.extract(input_path, output_path, profile)
            emit({"id": job_id, "ok": True, **result})
        except ModuleNotFoundError as error:
            emit({
                "id": job_id,
                "ok": False,
                "code": "OCR_DEPENDENCY_MISSING",
                "error": f"OCR 依赖未安装：{error.name}",
            })
        except Exception as error:  # Worker boundary: always return a structured failure.
            if os.environ.get("DOCUMENT_OCR_DEBUG") == "1":
                traceback.print_exc(file=sys.stderr)
            emit({"id": job_id, "ok": False, "code": "OCR_FAILED", "error": str(error)[:800]})


if __name__ == "__main__":
    main()
