"""
rules / rules_engine.py —— 规则引擎：开放时间备注
====================================================
v1.5：build_day_schedule / _pick_meals 已移除（死代码，主流程走
      cluster_days → order_day_optimized → render_itinerary → orchestrate_day → schedule_one_day）。
保留 open_time_note 作为开放时间备注展示工具。
"""
from __future__ import annotations
from typing import Dict, Any


_MODULE = "rules"


# ---------- 开放时间（改动点 2：仅展示） ----------

def open_time_note(p: Dict[str, Any]) -> str:
    """
    【改动点 2 A】开放时间只作为备注展示，不据此过滤景点。
    若高德返回了 open_time 就带上，否则给通用提示。
    """
    ot = p.get("open_time")
    if ot:
        return f"营业 {ot}（以现场为准）"
    return "开放时间以景区现场公告为准"
