"""
_config / log.py —— 方案 A 统一错误通道（埋点规范）
===============================================
所有模块出错/降级时调用 log_error，带模块标识，便于日志检索定位“哪个模块出错了”。
- 写日志：<root>/log/errors.log（追加一行）
- 同时打到 stderr
"""
from __future__ import annotations
import os
import sys
import traceback
from datetime import datetime

from .config import ROOT_DIR

_LOG_DIR = os.path.join(ROOT_DIR, "log")
_LOG_FILE = os.path.join(_LOG_DIR, "errors.log")


def _ensure_dir() -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)


def log_error(module: str, step: str, error_type: str, msg: str, degraded: bool = False) -> None:
    """
    统一错误上报。

    参数（字段约定来自开发计划 §4.1）：
      module    所属模块，必须与文件夹名一致，如 'poi_pipeline'
      step      该模块内的小步骤，如 '高德反查'
      error_type 错误类型（约定枚举），如 API / TIMEOUT / LIMIT / OVERFLOW
      msg       一句话描述
      degraded  是否为降级（False=真错误，True=降级兜底）
    """
    _ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"[{ts}] module={module} step={step} type={error_type} "
        f"degraded={int(degraded)} : {msg}"
    )
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # 日志写入失败不能中断主流程
        print(f"[log_error] 写日志失败: {e}", file=sys.stderr)
    print(line, file=sys.stderr)


def log_exception(module: str, step: str, exc: BaseException, degraded: bool = False) -> None:
    """异常带堆栈的上报。"""
    msg = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()}"
    log_error(module, step, "EXCEPTION", msg, degraded=degraded)


def read_logs(module: str | None = None, n: int = 50) -> list[str]:
    """读取日志（便于页面展示/调试）。可按模块过滤。"""
    if not os.path.exists(_LOG_FILE):
        return []
    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if module:
        lines = [ln for ln in lines if f"module={module}" in ln]
    return lines[-n:]


def reset_logs() -> None:
    """清空日志，确保结果页“运行状态”只展示本次请求产生的错误/降级。"""
    _ensure_dir()
    try:
        with open(_LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass