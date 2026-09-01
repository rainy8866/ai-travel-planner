"""
render / render.py —— 规则引擎编排 + 钟点排定（v1.6）
================================================================
v1.6：固定时段（早8-12/午12-18/晚18-22），open_time空时随便排。
- 开放时间硬过滤（有open_time才过滤，没有则随便排）
- 固定时段区间 + 22h 硬上限
- 评分降序贪心填充 + duration_min 时间预算
- 塞不下进 dropped
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple

from _config.config import (
    PERIODS, PERIOD_WINDOWS, SLOT_BUFFER_MIN,
    parse_open_range,
)
from _config.log import log_error
from routing.routing import haversine_km

_MODULE = "render"

_PERIOD_LABELS_CN = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}


# ---------- 开放时间解析已移至 _config/config.py ----------


def _has_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    """两个闭区间是否有交集（端点接触不算，如 [9,18] 与 [18,24] 不重叠）。"""
    return a[0] < b[1] and b[0] < a[1]


def _allowed_periods(p: Dict[str, Any], periods: List[str]) -> List[str]:
    """
    计算某 POI 可排的时段清单。
    - 有 open_time 且合法：硬过滤，开放区间与时段区间有重叠才可排
    - open_time 为空：随便排，全时段可排
    """
    ot = p.get("open_time") or ""
    rng = parse_open_range(ot)
    allowed = []
    for slot in periods:
        lo, hi, _, soft_cap = PERIOD_WINDOWS[slot]
        slot_window = (lo, soft_cap)
        if rng is None:
            # 无固定开放时间 → 随便排，全时段可排
            allowed.append(slot)
        else:
            # 硬过滤：开放区间与时段区间有交集
            if _has_overlap(rng, slot_window):
                allowed.append(slot)
    return allowed


# ---------- 规则引擎编排 ----------

def _dur(p: Dict[str, Any]) -> int:
    """取 POI 时长，缺失按 90 兜底。"""
    return int(p.get("duration_min") or 90)


def _rating(p: Dict[str, Any]) -> float:
    return float(p.get("rating") or 0)


def orchestrate_day(
    day_pois: List[Dict[str, Any]],
    periods: List[str],
) -> Dict[str, Any]:
    """
    v1.7 纯规则编排：只排用户选的 POI，按评分降序分配到各时段。
    补空位逻辑由 render_itinerary 在全部天排完后统一调用 fill_extras。
    返回 {slot: [POI...], "dropped": [...], "evening_empty": bool, "_slot_cursor": {...}}
    """
    def _advance_cursor(slot, end_time):
        """把 cursor 推到 end_time + buffer，但不超过 soft_cap。"""
        _, _, _, sc = PERIOD_WINDOWS[slot]
        slot_cursor[slot] = min(end_time + SLOT_BUFFER_MIN, sc)

    # 1. 预解析每个 POI 的开放时间
    for p in day_pois:
        p["_ot_rng"] = parse_open_range(p.get("open_time") or "")

    # 2. 分类：full_day（>=480，独占）/ normal
    full_day = [p for p in day_pois if _dur(p) >= 480]
    normal = [p for p in day_pois if _dur(p) < 480]

    # 3. normal 按地理近邻聚类 + 评分兜底：
    # 核心思路：聚成地理簇，同簇POI尽量塞在连续时段，避免跨区跑
    normal.sort(key=lambda p: -_rating(p))

    # 3.1 地理聚类：把 <=1.5km 的POI聚成同一簇（同一建筑群/街区）
    GEO_CLUSTER_KM = 1.5
    clusters: List[List[Dict[str, Any]]] = []
    used_in_cluster: set = set()

    for seed_p in normal:
        if seed_p.get("name") in used_in_cluster:
            continue
        cluster = [seed_p]
        used_in_cluster.add(seed_p.get("name"))
        for p in normal:
            if p.get("name") in used_in_cluster:
                continue
            avg_lng = sum(c.get("lng", 0) for c in cluster) / len(cluster)
            avg_lat = sum(c.get("lat", 0) for c in cluster) / len(cluster)
            d = haversine_km(avg_lng, avg_lat, p.get("lng", 0), p.get("lat", 0))
            if d <= GEO_CLUSTER_KM:
                cluster.append(p)
                used_in_cluster.add(p.get("name"))
        clusters.append(cluster)

    # 3.2 簇按簇内最高评分降序；簇内用TSP-nearest-neighbor地理排序
    clusters.sort(key=lambda c: max(_rating(p) for p in c), reverse=True)
    geo_ordered: List[Dict[str, Any]] = []
    for cluster in clusters:
        # 簇内地理排序：最近邻贪心
        cluster.sort(key=lambda p: -_rating(p))
        cluster_ordered: List[Dict[str, Any]] = [cluster[0]]
        remaining_in_cluster = cluster[1:]
        while remaining_in_cluster:
            last = cluster_ordered[-1]
            best_idx = min(
                range(len(remaining_in_cluster)),
                key=lambda i: haversine_km(
                    last.get("lng", 0), last.get("lat", 0),
                    remaining_in_cluster[i].get("lng", 0), remaining_in_cluster[i].get("lat", 0)
                )
            )
            cluster_ordered.append(remaining_in_cluster.pop(best_idx))
        geo_ordered.extend(cluster_ordered)

    normal = geo_ordered

    # 4. 初始化各时段 POI 列表 + cursor
    slot_pois: Dict[str, List[Dict[str, Any]]] = {s: [] for s in periods}
    slot_cursor: Dict[str, int] = {}
    for s in periods:
        _, _, default_start, _ = PERIOD_WINDOWS[s]
        slot_cursor[s] = default_start

    dropped: List[Dict[str, Any]] = []

    # 5. 全天 POI 优先占位（仅标记占用时段，不阻塞其他时段）
    if full_day:
        full_day.sort(key=lambda p: -_rating(p))
        chosen = full_day[0]
        ot_rng = chosen["_ot_rng"]
        target_slot = None
        for s in periods:
            lo, _, _, soft_cap = PERIOD_WINDOWS[s]
            actual_start = max(slot_cursor[s], ot_rng[0] if ot_rng else lo)
            actual_end = actual_start + _dur(chosen)
            if actual_end <= soft_cap:
                target_slot = s
                break
        if target_slot:
            slot_pois[target_slot].append(chosen)
            lo, _, _, soft_cap = PERIOD_WINDOWS[target_slot]
            slot_cursor[target_slot] = soft_cap
        else:
            # 单个时段塞不下 → 跨连续时段放
            chosen_dur = _dur(chosen)
            for start_idx in range(len(periods)):
                total_avail = 0
                covered_slots = []
                for si in range(start_idx, len(periods)):
                    s = periods[si]
                    _, _, _, sc = PERIOD_WINDOWS[s]
                    cs = slot_cursor[s]
                    avail = max(0, sc - max(cs, PERIOD_WINDOWS[s][0]))
                    total_avail += avail
                    covered_slots.append(s)
                    if total_avail >= chosen_dur:
                        break
                if total_avail >= chosen_dur and len(covered_slots) >= 1:
                    first_slot = covered_slots[0]
                    slot_pois[first_slot].append(chosen)
                    _, _, _, sc = PERIOD_WINDOWS[first_slot]
                    slot_cursor[first_slot] = sc
                    for s in covered_slots[1:]:
                        _, _, _, sc = PERIOD_WINDOWS[s]
                        slot_cursor[s] = sc
                    break
        for p in full_day[1:]:
            dropped.append(p)

    # 6. 按簇顺序排POI：同簇POI连续时段排列
    for cluster in clusters:
        # 记录簇内上一个POI所在时段，后续POI优先尝试该时段或下一个
        last_cluster_slot_idx = -1
        for p in cluster:
            ot_rng = p["_ot_rng"]
            placed = False

            # 构造时段尝试顺序：优先簇内上一个POI的时段及其相邻时段
            if last_cluster_slot_idx >= 0:
                preferred_slots = [periods[last_cluster_slot_idx]]
                if last_cluster_slot_idx + 1 < len(periods):
                    preferred_slots.append(periods[last_cluster_slot_idx + 1])
                if last_cluster_slot_idx - 1 >= 0:
                    preferred_slots.append(periods[last_cluster_slot_idx - 1])
                for s in periods:
                    if s not in preferred_slots:
                        preferred_slots.append(s)
            else:
                preferred_slots = list(periods)

            for slot in preferred_slots:
                lo, hi, _, soft_cap = PERIOD_WINDOWS[slot]
                actual_start = max(slot_cursor[slot], ot_rng[0] if ot_rng else lo)
                actual_end = actual_start + _dur(p)
                if actual_start >= lo and actual_end <= soft_cap:
                    if ot_rng is None or actual_end <= ot_rng[1]:
                        slot_pois[slot].append(p)
                        _advance_cursor(slot, actual_end)
                        placed = True
                        last_cluster_slot_idx = periods.index(slot)
                        break
                    else:
                        if ot_rng[0] > slot_cursor[slot] and ot_rng[0] >= lo:
                            actual_start2 = ot_rng[0]
                            actual_end2 = actual_start2 + _dur(p)
                            if actual_end2 <= soft_cap and actual_end2 <= ot_rng[1]:
                                slot_pois[slot].append(p)
                                _advance_cursor(slot, actual_end2)
                                placed = True
                                last_cluster_slot_idx = periods.index(slot)
                                break
            if not placed:
                # 兜底：检查 open_time 约束（不能排到不开放的时段）
                for slot in periods:
                    lo, hi, _, soft_cap = PERIOD_WINDOWS[slot]
                    actual_start = max(slot_cursor[slot], lo)
                    actual_end = actual_start + _dur(p)
                    if actual_start >= lo and actual_end <= soft_cap:
                        if ot_rng is not None and actual_end > ot_rng[1]:
                            continue
                        slot_pois[slot].append(p)
                        _advance_cursor(slot, actual_end)
                        placed = True
                        last_cluster_slot_idx = periods.index(slot)
                        break
            if not placed:
                dropped.append(p)

    evening_empty = "evening" in periods and slot_cursor.get("evening", 0) < PERIOD_WINDOWS["evening"][3]

    return {
        **slot_pois,
        "dropped": dropped,
        "full_day_exclusive": False,
        "evening_empty": evening_empty,
        "_slot_cursor": slot_cursor,
    }


def fill_extras(
    orchestrated: Dict[str, Any],
    extra_pool: List[Dict[str, Any]],
    global_used: set,
    periods: List[str],
) -> List[Dict[str, Any]]:
    """
    v1.7 补空位：在已排完用户POI的orchestrated基础上，从extra_pool补空位。
    - global_used 跨天全局去重（同一POI不能在不同天重复出现）
    - 按评分降序尝试塞入有时段空位的POI
    返回补入的POI列表，同时更新 global_used 和 orchestrated。
    """
    slot_cursor: Dict[str, int] = orchestrated.get("_slot_cursor", {})

    # 预解析开放时间
    for p in extra_pool:
        if "_ot_rng" not in p:
            p["_ot_rng"] = parse_open_range(p.get("open_time") or "")

    filled: List[Dict[str, Any]] = []
    extras = sorted(
        [p for p in extra_pool if p.get("name") not in global_used],
        key=lambda p: -_rating(p)
    )
    for p in extras:
        ot_rng = p["_ot_rng"]
        placed = False
        for slot in periods:
            lo, hi, _, soft_cap = PERIOD_WINDOWS[slot]
            actual_start = max(slot_cursor.get(slot, lo), ot_rng[0] if ot_rng else lo)
            actual_end = actual_start + _dur(p)
            if actual_start >= lo and actual_end <= soft_cap:
                if ot_rng is None or actual_end <= ot_rng[1]:
                    orchestrated.setdefault(slot, []).append(p)
                    _, _, _, sc = PERIOD_WINDOWS[slot]
                    slot_cursor[slot] = min(actual_end + SLOT_BUFFER_MIN, sc)
                    global_used.add(p.get("name"))
                    filled.append(p)
                    placed = True
                    break
        # 补空位不做兜底（忽略open_time），因为这是推荐补的，不是用户选的
    orchestrated["_slot_cursor"] = slot_cursor
    return filled


# ---------- 钟点排定 ----------

def _min_to_time(x: int) -> str:
    x = max(0, int(x))
    h = x // 60
    m = x % 60
    if h >= 24:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def schedule_one_day(
    orchestrated: Dict[str, Any],
    poi_by_name: Dict[str, Dict[str, Any]],
    periods: List[str],
) -> List[Dict[str, Any]]:
    """
    把 orchestrate_day 的产出转为带 time_range 的 items。
    24h 上限已在 orchestrate_day 保证。
    """
    items: List[Dict[str, Any]] = []

    def _poi_item(nm: str, start: int, dur: int, slot: str) -> Dict[str, Any]:
        p = poi_by_name.get(nm, {}) or {}
        return {
            "kind": "poi", "name": nm, "tags": p.get("tags", []),
            "time_range": f"{_min_to_time(start)}-{_min_to_time(start + dur)}",
            "lat": p.get("lat"), "lng": p.get("lng"),
            "note": open_note_from(p),
            "slot": slot,
        }

    for slot in periods:
        pois = orchestrated.get(slot) or []
        lo, hi, default_start, soft_cap = PERIOD_WINDOWS[slot]
        cursor = default_start
        for p in pois:
            nm = p.get("name", "")
            dur = _dur(p)
            ot_rng = parse_open_range(p.get("open_time") or "")
            actual_start = max(cursor, ot_rng[0] if ot_rng else lo)
            actual_end = actual_start + dur
            if actual_start >= lo:
                # 允许跨时段：如果超出soft_cap，用min(soft_cap, ot_end)截断显示
                display_end = min(actual_end, soft_cap)
                if ot_rng:
                    display_end = min(display_end, ot_rng[1])
                # 至少显示到当前slot的结束时间
                display_end = max(display_end, lo)
                items.append(_poi_item(nm, actual_start, dur, slot))
                cursor = actual_end + SLOT_BUFFER_MIN

    return items


def open_note_from(p: Dict[str, Any]) -> str:
    """开放时间备注。"""
    ot = p.get("open_time")
    return f"营业 {ot}（以现场为准）" if ot else "开放时间以景区现场公告为准"


# ---------- 主入口 ----------

def render_itinerary(
    ordered_days: List[List[Dict[str, Any]]],
    days: int,
    pace: str,
    ui: Dict[str, Any],
    candidates: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    主入口（v1.6）：纯规则引擎编排，固定时段，open_time空时随便排。
    - 先排用户选的 POI（ordered_days 输入）
    - 如果时段还有空位，从 candidates 里补（优先级低）
    返回 {"mode": "rules", "days": [{"day": idx, "items": [...], "dropped": [...], "warning": str}]}
    """
    periods: List[str] = list(ui.get("periods") or list(PERIODS))

    # 规范化：城市前缀剥离 + 通用别名
    _CITY_PREFIXES = ["成都", "杭州", "北京", "上海", "广州", "深圳", "重庆", "武汉", "西安", "南京", "苏州", "长沙", "青岛", "厦门", "大理", "丽江", "香格里拉"]
    _ALIAS_MAP = {
        "ifs国金中心": "IFS国际金融中心",
        "ifs国际金融中心": "IFS国际金融中心",
        "ifs": "IFS国际金融中心",
        "远洋太古里": "太古里",
        "成都远洋太古里": "太古里",
        "成都太古里": "太古里",
    }
    def _norm(nm: str) -> str:
        n = nm.strip()
        if n.lower() in _ALIAS_MAP:
            return _ALIAS_MAP[n.lower()]
        for cp in _CITY_PREFIXES:
            if n.startswith(cp):
                n = n[len(cp):]
                break
        if n.lower() in _ALIAS_MAP:
            return _ALIAS_MAP[n.lower()]
        return n

    user_names_raw = {p.get("name") for day in ordered_days for p in day if p.get("name")}
    user_names_norm = {_norm(n) for n in user_names_raw}

    # 构造补池：candidates 中所有 POI，排除用户已选的（含别名/前缀匹配）
    extra_pool: List[Dict[str, Any]] = []
    if candidates:
        seen_extra_norm = set()
        for tag, pois in candidates.items():
            for p in pois:
                nm = p.get("name", "")
                if not nm:
                    continue
                n_norm = _norm(nm)
                # 和用户选的重名（规范化后）就跳过：不能补用户已选的
                if n_norm in user_names_norm:
                    continue
                if n_norm in seen_extra_norm:
                    continue
                extra_pool.append(p)
                seen_extra_norm.add(n_norm)

    # poi_by_name 同时包含用户和补的
    poi_by_name: Dict[str, Dict[str, Any]] = {}
    for day in ordered_days:
        for p in day:
            if p.get("name"):
                poi_by_name[p["name"]] = p
    for p in extra_pool:
        if p.get("name") and p["name"] not in poi_by_name:
            poi_by_name[p["name"]] = p

    result_days: List[Dict[str, Any]] = []

    # Phase 1: 先排全部天的用户 POI（不补任何推荐）
    all_orchestrated: List[Dict[str, Any]] = []
    global_used: set = set()  # 跨天去重：已排入的 POI 名（含用户选的）
    for idx, day_pois in enumerate(ordered_days, start=1):
        orchestrated = orchestrate_day(day_pois, periods)
        all_orchestrated.append(orchestrated)
        for slot in periods:
            for p in orchestrated.get(slot, []):
                global_used.add(p.get("name"))

    # Phase 1.5: 重新分配 — 收集所有天的 dropped，
    # 用"最空的天+最空闲的时段"调用 orchestrate_day 重排，保证硬约束一致
    all_dropped: List[Dict[str, Any]] = []
    for orchestrated in all_orchestrated:
        all_dropped.extend(orchestrated.get("dropped", []))
        orchestrated["dropped"] = []  # 先清空，等会再装回真·排不下的

    # 逐 dropped POI：找能装进去的天，用 orchestrate_day 的完整规则（而不是手写半套）
    remaining_dropped: List[Dict[str, Any]] = []
    for p in all_dropped:
        if p.get("name") in global_used:
            continue
        placed = False
        # 候选天：按"总空闲时间最多"倒序遍历
        day_ranked = sorted(
            range(len(all_orchestrated)),
            key=lambda j: sum(
                max(0, PERIOD_WINDOWS[s][3] - all_orchestrated[j].get("_slot_cursor", {}).get(s, PERIOD_WINDOWS[s][0]))
                for s in periods
            ),
            reverse=True,
        )
        for j in day_ranked:
            # 把 j 天的已排 POI + 当前 p 合起来重做编排
            existing: List[Dict[str, Any]] = []
            for s in periods:
                existing.extend(all_orchestrated[j].get(s, []))
            trial_input = existing + [p]
            trial_out = orchestrate_day(trial_input, periods)
            # 如果新 p 出现在 trial_out 某时段，说明这次排进去了
            new_placed_names = set()
            for s in periods:
                for tp in trial_out.get(s, []):
                    new_placed_names.add(tp.get("name"))
            if p.get("name") in new_placed_names:
                # 接受：用 trial_out 替换 all_orchestrated[j]
                for s in periods:
                    all_orchestrated[j][s] = trial_out.get(s, [])
                all_orchestrated[j]["_slot_cursor"] = trial_out.get("_slot_cursor", {})
                all_orchestrated[j]["evening_empty"] = trial_out.get("evening_empty", False)
                # dropped 用 trial_out 的（但过滤掉原 existing 中的名字，它们一定排进去了；只保留 trial_out 真·排不下的新POI）
                existing_names = {q.get("name") for q in existing}
                extra_drop = [tp for tp in trial_out.get("dropped", []) if tp.get("name") not in existing_names]
                # 先不管 extra_drop，本轮先处理当前 p
                global_used.add(p.get("name"))
                placed = True
                break
        if not placed:
            remaining_dropped.append(p)

    # 把 remaining_dropped 装回第 1 天的 dropped 字段（统一汇总，UI会在最后展示）
    if remaining_dropped and all_orchestrated:
        all_orchestrated[0]["dropped"] = remaining_dropped

    # Phase 2: 只有全部天的用户 POI 都排完（无 dropped）才补空位
    # 有任何 dropped → 不补，尊重用户选择
    has_any_drop = any(
        orchestrated.get("dropped", []) for orchestrated in all_orchestrated
    )

    for idx, orchestrated in enumerate(all_orchestrated, start=1):
        if has_any_drop:
            # 有用户 POI 排不下 → 不补推荐
            filled_extra = []
        else:
            filled_extra = fill_extras(orchestrated, extra_pool, global_used, periods)

        # 断言校验
        valid_names = set(poi_by_name.keys())
        for slot in periods:
            slot_list = orchestrated.get(slot, [])
            for p in slot_list:
                if p.get("name") not in valid_names:
                    raise RuntimeError(f"编排异常：POI『{p.get('name')}』不在有效列表中")
        for p in orchestrated.get("dropped", []):
            if p.get("name") not in user_names_raw:
                raise RuntimeError(f"编排异常：dropped POI『{p.get('name')}』非用户选择")

        items = schedule_one_day(orchestrated, poi_by_name, periods)
        dropped = orchestrated.get("dropped") or []

        warning_parts: List[str] = []
        if dropped:
            names = "、".join(p.get("name", "") for p in dropped)
            warning_parts.append(f"当天 {len(dropped)} 个景点排不下（时间预算/开放时间限制）：{names}。建议返回选择页调整。")
        if filled_extra:
            names = "、".join(p.get("name", "") for p in filled_extra)
            warning_parts.append(f"当天已为你补充 {len(filled_extra)} 个推荐景点：{names}（空位自动填充，可返回选择页调整）")

        warning = "\n".join(warning_parts)
        result_days.append({
            "day": idx,
            "items": items,
            "dropped": dropped,
            "filled_extra": filled_extra,
            "warning": warning,
        })

    return {"mode": "rules", "days": result_days}
