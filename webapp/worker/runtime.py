"""Shared worker runtime: event output, command streaming, and OpenCode setup.

Skill-specific logic lives in ``worker/adapters/``; this module only carries
the pieces every adapter needs, so adapters can import it without a cycle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread
from time import monotonic

WORKSPACE = Path(os.environ.get("PPTMASTER_WORKSPACE", "/workspace/project"))
REPO_ROOT = Path("/app")
OPENCODE_CONFIG_SOURCE = Path("/opt/pptmaster/opencode-config")
OPENCODE_CONFIG_DESTINATION = Path("/home/pptmaster/.config/opencode")
OPENCODE_IDLE_TIMEOUT_EXIT_CODE = 124
DEFAULT_OPENCODE_IDLE_TIMEOUT_SECONDS = 600
OPENCODE_WAIT_NOTICE_SECONDS = 60


def emit(event_type: str, **payload: object) -> None:
    """Write one JSON line consumed by the trusted runner."""

    print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def run_command(command: list[str], *, idle_timeout_seconds: int | None = None) -> int:
    """Run a command, stream events, and stop it if OpenCode becomes silent."""

    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    if idle_timeout_seconds is None:
        for line in process.stdout:
            _emit_command_line(line.strip())
        return process.wait()

    output_queue: Queue[str | None] = Queue()

    def copy_output() -> None:
        """Forward blocking subprocess output into the timeout-aware loop."""

        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    Thread(target=copy_output, daemon=True).start()
    last_output_at = monotonic()
    last_wait_notice_at = 0
    while True:
        try:
            line = output_queue.get(timeout=1)
        except Empty:
            idle_seconds = int(monotonic() - last_output_at)
            if idle_seconds < idle_timeout_seconds:
                if idle_seconds - last_wait_notice_at >= OPENCODE_WAIT_NOTICE_SECONDS:
                    emit(
                        "log",
                        text=(
                            f"OpenCode 暂无新输出，已等待 {idle_seconds} 秒；"
                            "仍在等待模型响应。"
                        ),
                    )
                    last_wait_notice_at = idle_seconds
                continue
            emit(
                "error",
                message=(
                    f"OpenCode 连续 {idle_timeout_seconds} 秒未输出，已停止该任务；"
                    "请重新提交，或检查所选模型服务是否正常响应。"
                ),
            )
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return OPENCODE_IDLE_TIMEOUT_EXIT_CODE
        if line is None:
            break
        last_output_at = monotonic()
        last_wait_notice_at = 0
        _emit_command_line(line.strip())
    return process.wait()


def _emit_command_line(line: str) -> None:
    """Translate OpenCode JSONL into small, user-visible execution events."""

    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        emit("agent", text=line[:1000])
        return
    event_type = event.get("type")
    part = event.get("part") or {}
    if event_type == "text":
        text = _strip_ansi(str(part.get("text") or "").strip())
        if text:
            if "permission requested:" in text.lower():
                emit("permission", message=text[:1000])
                return
            emit("agent", text=text[:1000])
        return
    if event_type == "tool_use":
        state = part.get("state") or {}
        if state.get("status") != "completed":
            return
        tool = str(part.get("tool") or "tool")
        input_data = state.get("input") or {}
        detail = str(
            input_data.get("filePath")
            or input_data.get("file_path")
            or input_data.get("command")
            or ""
        )
        emit("tool", tool=tool, detail=detail[:240])
        return
    if event_type == "step_finish":
        tokens = part.get("tokens") or {}
        emit(
            "usage",
            tokens=tokens,
            total_tokens=tokens.get("total"),
            cost=part.get("cost"),
        )
        return
    emit("opencode", event=event_type or "unknown")


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    """Remove terminal control sequences before persisting execution events."""

    return _ANSI_RE.sub("", value)


def install_opencode_config() -> bool:
    """Copy the read-only provider config into this worker's writable Home directory."""

    generated = os.environ.get("PPTMASTER_OPENCODE_CONFIG_JSON", "")
    if generated:
        try:
            json.loads(generated)
            OPENCODE_CONFIG_DESTINATION.mkdir(parents=True, exist_ok=True)
            (OPENCODE_CONFIG_DESTINATION / "opencode.json").write_text(generated, encoding="utf-8")
            return True
        except (OSError, json.JSONDecodeError) as exc:
            emit("error", message=f"生成引擎配置装配失败：{exc}")
            return False
    if not OPENCODE_CONFIG_SOURCE.exists():
        return True
    source = next(
        (
            candidate
            for candidate in (
                OPENCODE_CONFIG_SOURCE / "opencode.jsonc",
                OPENCODE_CONFIG_SOURCE / "opencode.json",
            )
            if candidate.is_file()
        ),
        None,
    )
    if source is None:
        emit(
            "error",
            message="OpenCode 配置源中缺少 opencode.jsonc 或 opencode.json",
        )
        return False
    try:
        OPENCODE_CONFIG_DESTINATION.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, OPENCODE_CONFIG_DESTINATION / source.name)
    except OSError as exc:
        emit("error", message=f"生成引擎配置装配失败：{exc}")
        return False
    return True


def opencode_idle_timeout_seconds() -> int:
    """Read the bounded no-output timeout for one OpenCode invocation."""

    raw_value = os.environ.get("PPTMASTER_OPENCODE_IDLE_TIMEOUT_SECONDS", "")
    try:
        configured_value = int(raw_value) if raw_value else DEFAULT_OPENCODE_IDLE_TIMEOUT_SECONDS
    except ValueError:
        configured_value = DEFAULT_OPENCODE_IDLE_TIMEOUT_SECONDS
    return min(max(configured_value, 60), 1800)
