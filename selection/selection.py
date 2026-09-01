"""
selection / selection.py —— 候选筛选 / 已选计数 / 自动补缺
==============================================================
业务逻辑层（不含 UI，UI 在 ../ui/selection_page.py）。
v1.4：容量校验改为时间预算制（与 routing.cluster_days 同源）。
- 自动补缺：优先补，补不满就如实提示“缺口未填满 N 个”，不硬凑、不跨标签造假
- 排不下 -> 明确提示（按时间预算，而非个数）
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional

from _config.config import recommendations_minutes
from _config.log import log_error

_MODULE = "selection"

# 时长缺失时的兜底默认值（与 routing._dur / rules._duration 一致）
_DEFAULT_DURATION_MIN = 90


def _poi_duration(p: Dict[str, Any]) -> int:
    """取 POI 时长，缺失按 90 分钟兜底。"""
    return int(p.get("duration_min") or _DEFAULT_DURATION_MIN)


def group_by_tag(candidates: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """按标签分组（候选池已按标签组织，这里规范化 + 按评分排序）。"""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for tag, pois in candidates.items():
        sorted_pois = sorted(pois, key=lambda p: -(p.get("rating") or 0))
        grouped[tag] = sorted_pois
    return grouped


def fill_shortfall(
    selected: Dict[str, List[str]],
    candidates: Dict[str, List[Dict[str, Any]]],
    target_per_tag: int,
    allowed_tags: List[str],
    exclude_names: set,
) -> Dict[str, List[str]]:
    """
    自动补缺。
    - 在每个允许标签下，按评分序补足到 target_per_tag
    - 若某标签候选不足/已全选，补多少算多少
    - 并返回一份“缺口未填满”的说明（不静默）
    返回 (filled_selected, shortfall_msg)
    """
    filled: Dict[str, List[str]] = {k: list(v) for k, v in selected.items()}
    shortfall = []
    for tag in allowed_tags:
        need = target_per_tag - len(filled.get(tag, []))
        if need <= 0:
            continue
        pool = candidates.get(tag, [])
        # 候选先去重（排除已选、排除全局 exclude_names）
        fresh = [p for p in pool
                 if p.get("name") not in exclude_names
                 and p.get("name") not in filled.get(tag, [])]
        can_add = fresh[:need]
        for p in can_add:
            filled.setdefault(tag, []).append(p.get("name"))
            exclude_names.add(p.get("name"))
        if len(can_add) < need:
            shortfall.append(
                f"『{tag}』需补 {need} 个，但候选仅余 {len(can_add)} 个，缺口 {need - len(can_add)} 个未填满"
            )
            log_error(_MODULE, "自动补缺", "LIMIT", shortfall[-1], degraded=True)
    return filled, shortfall


def summarize_over_capacity(
    selected: Dict[str, List[str]],
    candidates: Dict[str, List[Dict[str, Any]]],
    days: int,
    periods: Optional[List[str]] = None,
) -> List[str]:
    """
    v1.4 时间预算制：把已选 POI 的时长求和，与总时间预算对比。
    - 总预算 = recommendations_minutes(days, periods)
    - 已选时长 = 各标签下已选 POI 的 duration_min 之和（缺失按 90 兜底）
    - 超出则提示“超出 X 小时”，不静默丢弃。
    periods 为 None 时按全部 PERIODS（兼容旧调用）。
    """
    total_budget = recommendations_minutes(days, periods)
    total_sel_min = 0
    sel_count = 0
    for tag, names in selected.items():
        pool = {p.get("name"): p for p in candidates.get(tag, [])}
        for name in names:
            p = pool.get(name)
            if p is None:
                # 跨标签去重时可能在别的 tag 下，全局兜底按默认时长计
                total_sel_min += _DEFAULT_DURATION_MIN
            else:
                total_sel_min += _poi_duration(p)
            sel_count += 1

    warns = []
    if total_sel_min > total_budget:
        over_min = total_sel_min - total_budget
        warns.append(
            f"已选 {sel_count} 个景点（预计 {total_sel_min // 60} 小时），"
            f"超出 {days} 天行程时间预算（{total_budget // 60} 小时）约 {over_min // 60} 小时，"
            f"系统将自动紧凑安排，建议取舍。"
        )
        log_error(_MODULE, "容量校验", "OVERFLOW", warns[-1], degraded=False)
    return warns
