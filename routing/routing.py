"""
routing / routing.py —— 距离计算 + 贪心排序 + 地理聚类分天（v1.4 时间预算版）
====================================================================
- haversine_km: 两点直线距离（Haversine）
- order_day_optimized: 单日贪心排序（随机起点×2 取最短）
- cluster_days: 时间预算 + 评分种子 + 前天终点最近 + 地理贪心
"""
from __future__ import annotations
import math
import random
from typing import List, Dict, Any, Optional

from _config.config import ROUTING_SAMPLE_TRIES, PERIODS, PERIOD_WINDOWS, parse_open_range
from _config.log import log_error

_MODULE = "routing"


def haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点直线距离（公里）。"""
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _route_length(order: List[Dict[str, Any]]) -> float:
    """给定顺序，计算首尾相接总直线里程。"""
    total = 0.0
    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]
        total += haversine_km(a.get("lng", 0), a.get("lat", 0), b.get("lng", 0), b.get("lat", 0))
    return total


def _greedy_from(points: List[Dict[str, Any]], start_idx: int) -> List[Dict[str, Any]]:
    """从 start_idx 出发的贪心最近邻排序（每个点只访问一次）。"""
    n = len(points)
    visited = [False] * n
    order = [points[start_idx]]
    visited[start_idx] = True
    cur = start_idx
    for _ in range(n - 1):
        best = -1
        best_d = float("inf")
        for j in range(n):
            if visited[j]:
                continue
            d = haversine_km(points[cur]["lng"], points[cur]["lat"],
                             points[j]["lng"], points[j]["lat"])
            if d < best_d:
                best_d = d
                best = j
        visited[best] = True
        order.append(points[best])
        cur = best
    return order


def order_day_optimized(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    单日贪心排序：固定从最高分 POI 开始（确定性）。
    """
    if len(points) <= 1:
        return list(points)
    # 固定从评分最高的 POI 开始（确定性输出）
    best_idx = max(range(len(points)), key=lambda i: float(points[i].get("rating") or 0))
    cand = _greedy_from(points, best_idx)
    return cand


def cluster_days(
    pois: List[Dict[str, Any]],
    periods: List[str],
    max_days: int = 3,
    dist_km: float = 8.0,
) -> List[List[Dict[str, Any]]]:
    """
    v1.6 聚类分天：固定时段时间预算 + 评分种子 + 前天终点最近 + 地理贪心。

    规则：
    1. 每天时间预算 = Σ(选中时段的硬上限 - 下界)，按 PERIOD_WINDOWS 计算
       morning=4h, afternoon=6h, evening=4h → 全天14h
    2. 第一天种子 = 评分最高的 POI
    3. 后续天种子 = 离前一天最后一个 POI 最近的未分配 POI
    4. 贪心填充：找最近未分配 POI，累加 duration_min <= 日预算
    5. 全天 POI（>=480min）自然独占一天
    """
    if not pois:
        return []

    from _config.config import PERIOD_WINDOWS
    daily_budget = max(1, sum(PERIOD_WINDOWS[s][3] - PERIOD_WINDOWS[s][0] for s in periods))

    def _dur(p: Dict[str, Any]) -> int:
        return int(p.get("duration_min") or 90)

    def _rating(p: Dict[str, Any]) -> float:
        return float(p.get("rating") or 0)

    used = [False] * len(pois)
    day_groups: List[List[Dict[str, Any]]] = []
    last_end_poi: Optional[Dict[str, Any]] = None  # 前一天的最后一个 POI

    for day_idx in range(max_days):
        if all(used):
            break

        rest_idx = [i for i in range(len(pois)) if not used[i]]

        # 选种子
        if day_idx == 0 or last_end_poi is None:
            # 第一天：评分最高
            seed_idx = max(rest_idx, key=lambda i: _rating(pois[i]))
        else:
            # 后续天：离前一天终点最近
            seed_idx = min(rest_idx, key=lambda i: haversine_km(
                last_end_poi.get("lng", 0), last_end_poi.get("lat", 0),
                pois[i].get("lng", 0), pois[i].get("lat", 0),
            ))

        current: List[Dict[str, Any]] = [pois[seed_idx]]
        used[seed_idx] = True
        cur_time = _dur(pois[seed_idx])

        # 如果种子是全天级POI（>=480min），独占一天，不再填充
        if cur_time >= 480:
            day_groups.append(current)
            last_end_poi = current[-1]
            continue

        # 贪心填充
        # 已覆盖的时段
        def _covered_slots(day_pois):
            slots = set()
            for p in day_pois:
                ot = parse_open_range(p.get("open_time") or "")
                if ot:
                    for s in periods:
                        lo, hi, _, sc = PERIOD_WINDOWS[s]
                        if ot[0] <= sc and ot[1] >= lo:
                            slots.add(s)
                else:
                    slots.update(periods)
            return slots

        covered = _covered_slots(current)
        uncovered = set(periods) - covered

        while cur_time < daily_budget:
            best_i, best_d = None, float("inf")
            best_cover = -1

            for i in range(len(pois)):
                if used[i]:
                    continue
                d = min(
                    haversine_km(c.get("lng", 0), c.get("lat", 0),
                                 pois[i].get("lng", 0), pois[i].get("lat", 0))
                    for c in current
                )
                p_slots = set()
                ot = parse_open_range(pois[i].get("open_time") or "")
                if ot:
                    for s in periods:
                        lo, hi, _, sc = PERIOD_WINDOWS[s]
                        if ot[0] <= sc and ot[1] >= lo:
                            p_slots.add(s)
                else:
                    p_slots = set(periods)
                new_cover = len(p_slots & uncovered)
                if new_cover > best_cover:
                    best_cover = new_cover
                    best_i = i
                    best_d = d
                elif new_cover == best_cover and d < best_d:
                    best_d = d
                    best_i = i

            if best_i is None:
                break
            if cur_time + _dur(pois[best_i]) > daily_budget:
                break
            if len(current) >= 3 and best_d > dist_km * 1.5:
                break
            current.append(pois[best_i])
            used[best_i] = True
            cur_time += _dur(pois[best_i])
            new_slots = _covered_slots(current)
            uncovered = set(periods) - new_slots

        # 每天内部按贪心最近邻排序，确保访问顺序最优
        current = order_day_optimized(current)

        day_groups.append(current)
        # 记录排好序后的最后一个POI，作为下一天起点的参考锚点
        last_end_poi = current[-1] if current else None

    # 兜底：未分配的 POI 塞进总时长最短的天（不打降级日志，由 Phase 1.5 再处理）
    for i in range(len(pois)):
        if used[i]:
            continue
        if day_groups:
            target_g = min(day_groups, key=lambda g: sum(_dur(p) for p in g))
            target_g.append(pois[i])
            used[i] = True
        else:
            log_error(_MODULE, "聚类分天", "LIMIT",
                      f"POI『{pois[i].get('name')}』无可用天可放置", degraded=False)

    return day_groups


def assign_period_weights(days: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """
    给每天每个 POI 标注建议时段占比（morning/afternoon/evening）。
    按 rating 从高到低往 morning 优先分配，供 rules 做时段分配参考。
    """
    w = {"morning": 1.0, "afternoon": 0.8, "evening": 0.6}
    for day in days:
        ranked = sorted(day, key=lambda p: (p.get("rating") or 0), reverse=True)
        for i, p in enumerate(ranked):
            period = PERIODS[min(i, len(PERIODS) - 1)]
            p["period_hint"] = period
            p["period_weight"] = w[period]
    return days
