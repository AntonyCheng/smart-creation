"""Host configuration without credentials or hard-coded employee IDs."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

REQUIRED_FONTS = {"方正小标宋简体", "仿宋_GB2312", "黑体", "楷体_GB2312", "宋体"}


def config(path=None):
    path = Path(path or os.environ.get("GONGWEN_RUNTIME_CONFIG") or Path(__file__).resolve().parent.parent / "runtime.json")
    if not path.is_file():
        raise ValueError("缺少runtime.json；请由安装者配置当前员工ID、输出目录和交付方式，不能猜测")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("delivery_mode") not in {"platform", "local"}:
        raise ValueError("delivery_mode须为platform或local")
    root = Path(str(data.get("output_root") or ""))
    if not root.is_absolute():
        raise ValueError("output_root必须是当前宿主已确认的绝对路径")
    data["output_root"] = str(root.resolve())
    if data.get("fontconfig_file"):
        fontconfig = Path(str(data["fontconfig_file"]))
        if not fontconfig.is_absolute() or not fontconfig.is_file():
            raise ValueError("fontconfig_file必须为安装者配置的真实绝对文件路径")
        data["fontconfig_file"] = str(fontconfig.resolve())
    if data["delivery_mode"] == "platform":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(data.get("agent_id") or "")):
            raise ValueError("platform模式须配置当前员工agent_id；不得沿用他人的ID")
        prefix = str(data.get("api_path_prefix") or "").strip("/")
        if not prefix or any(v in prefix.split("/") for v in ("..", ".", "")) or "?" in prefix or "#" in prefix:
            raise ValueError("api_path_prefix无效")
        data["api_path_prefix"] = prefix
    return data


def file_link(path, settings):
    path = Path(path).resolve(strict=True)
    relative = path.relative_to(Path(settings["output_root"]).resolve())
    if path.suffix.lower() != ".docx" or not path.is_file() or path.stat().st_size == 0:
        raise ValueError("非有效DOCX文件")
    if settings["delivery_mode"] == "local":
        return None
    api_path = settings["api_path_prefix"] + "/" + relative.as_posix()
    label = path.name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{label}](/api/agents/{settings['agent_id']}/files/download?path={quote(api_path, safe='/')})"


def font_status(fontconfig_file=None):
    # OOXML font names do not prove that the renderer has the font installed.
    exe = shutil.which("fc-list")
    if not exe:
        return {"status": "unknown", "reason": "宿主无fc-list；需在实际Word/WPS或渲染器中确认字体", "visual_check": "not_performed"}
    try:
        env = None
        if fontconfig_file:
            env = {"FONTCONFIG_FILE": str(fontconfig_file), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        proc = subprocess.run([exe, ":", "family"], capture_output=True, text=True, timeout=8, env=env)
        if proc.returncode:
            raise ValueError("字体枚举失败")
        families = {s.strip() for line in proc.stdout.splitlines() for s in line.split(",")}
        missing = sorted(REQUIRED_FONTS - families)
        return {"status": "missing" if missing else "available", "missing": missing, "visual_check": "not_performed"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unknown", "reason": "无法验证实际字体", "visual_check": "not_performed"}
