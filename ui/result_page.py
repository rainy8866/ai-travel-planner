"""
ui / result_page.py —— 结果页
===============================
- 展示每天的时间轴（景点 + 午餐 + 晚餐，含具体钟点）
- 展示行程地图（天地图/OSM）
- 展示埋点日志（哪个模块出错/降级）
纯 UI。
"""
from __future__ import annotations
from typing import Dict, Any, List
import re
from collections import OrderedDict

import streamlit as st
import folium

from map_view.map_view import render_map
from _config.log import read_logs


_LINE_RE = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*module=(?P<mod>\S+)\s+step=(?P<step>\S+)\s+type=(?P<t>\S+)\s+"
    r"degraded=(?P<deg>\d)\s*:\s*(?P<msg>.*)$"
)


def _parse_log_line(line: str) -> Dict[str, Any] | None:
    line = line.rstrip("\n")
    m = _LINE_RE.match(line)
    if not m:
        return None
    return {
        "raw": line,
        "ts": m.group("ts"),
        "module": m.group("mod"),
        "step": m.group("step"),
        "type": m.group("t"),
        "degraded": (m.group("deg") == "1"),
        "msg": m.group("msg"),
    }


def _group_logs(lines: List[str]) -> "OrderedDict[tuple, List[Dict[str, Any]]]":
    groups: "OrderedDict[tuple, List[Dict[str, Any]]]" = OrderedDict()
    for ln in lines:
        entry = _parse_log_line(ln)
        if not entry:
            continue
        key = (entry["module"], entry["step"], entry["type"], entry["degraded"])
        groups.setdefault(key, []).append(entry)
    return groups


_PERIOD_LABELS = {
    "morning": "☀️ 上午",
    "afternoon": "🌤 下午",
    "evening": "🌙 晚上",
}


def _render_day(day: Dict[str, Any], idx: int, periods: List[str]):
    st.markdown(f"### 第 {day.get('day', idx + 1)} 天")
    if day.get("warning"):
        warn = day["warning"]
        lines = warn.split('\n')
        filtered = [l for l in lines if '补充' in l or '推荐' in l]
        if filtered:
            st.warning('\n'.join(filtered))
    items = day.get("items", [])

    # 按时段分组
    by_slot: Dict[str, List[Dict[str, Any]]] = {s: [] for s in periods}
    for it in items:
        if it.get("kind") == "meal":
            continue
        slot = it.get("slot") or "morning"
        by_slot.setdefault(slot, []).append(it)

    # 检测全天POI：如果POI在当前时段的结束时间 > 时段soft_cap，视为跨时段
    # 被跨时段POI覆盖的后续时段不显示"(空闲)"
    covered_slots = set()
    for it in items:
        slot = it.get("slot") or "morning"
        if slot not in by_slot or not by_slot[slot]:
            continue
        # 获取该POI的time_range，检查是否跨时段
        tr = it.get("time_range", "")
        if "-" in tr:
            end_time = tr.split("-")[1]
            # 时段soft_cap（分钟）
            from _config.config import PERIOD_WINDOWS
            slot_order = ["morning", "afternoon", "evening"]
            si = slot_order.index(slot) if slot in slot_order else -1
            if si >= 0:
                # 检查结束时间是否超过当前时段soft_cap
                sc = PERIOD_WINDOWS[slot][3]
                end_h, end_m = int(end_time[:2]), int(end_time[3:5])
                end_min = end_h * 60 + end_m
                if end_min > sc:
                    # 跨时段：标记后续时段为"被占用"
                    for j in range(si + 1, len(slot_order)):
                        if slot_order[j] in by_slot and not by_slot[slot_order[j]]:
                            covered_slots.add(slot_order[j])

    # 时段栏
    cols = st.columns(len(periods))
    for i, slot in enumerate(periods):
        with cols[i]:
            label = _PERIOD_LABELS.get(slot, slot)
            pois = by_slot.get(slot, [])
            st.markdown(f"**{label}**")
            if not pois:
                if slot in covered_slots:
                    st.caption("⬅")
                else:
                    st.caption("（空闲）")
            for p in pois:
                tr = p.get('time_range', '')
                st.markdown(f"- 📍 {p.get('name')} _{tr}_")


def render_result_page(result: Dict[str, Any], periods: List[str] | None = None):
    """result: {"mode":"rules","days":[{"day","items","dropped","warning"}]}"""
    st.subheader("第三步 · 你的行程")
    if periods is None:
        periods = ["morning", "afternoon"]

    mode = result.get("mode", "rules")

    for i, day in enumerate(result.get("days", [])):
        _render_day(day, i, periods)

    # 汇总所有天的dropped（在最后一天后统一显示）
    all_dropped: List[Dict[str, Any]] = []
    for day in result.get("days", []):
        for p in day.get("dropped", []):
            all_dropped.append(p)
    if all_dropped:
        # 去重
        seen = set()
        unique_dropped = []
        for p in all_dropped:
            nm = p.get("name", "")
            if nm and nm not in seen:
                unique_dropped.append(p)
                seen.add(nm)
        st.markdown("---")
        with st.expander(f"⚠️ 共 {len(unique_dropped)} 个景点未排入（可返回选择页删除）"):
            names = "、".join(p.get("name", "") for p in unique_dropped)
            st.markdown(f"未排入：{names}")
            st.caption("原因：时间预算不足 / 开放时间不匹配 / 时段已满。"
                       "可点下方『← 返回选择』手动删除后重新生成。")

    # 地图
    st.markdown("### 路线地图")
    days_data = result.get("days", [])
    n_days = len(days_data)
    active_day = 1
    if n_days > 1:
        day_options = {d.get("day", i + 1): f"第 {d.get('day', i + 1)} 天" for i, d in enumerate(days_data)}
        selected_day = st.selectbox("选择查看第几天", options=list(day_options.keys()),
                                    format_func=lambda x: day_options[x],
                                    index=0, key="day_selector")
        active_day = selected_day
    try:
        m = render_map(days_data, active_day=active_day)
        st.components.v1.html(m._repr_html_(), height=560)
    except Exception as e:
        st.error(f"地图渲染失败：{e}")

    # 运行状态（开发者调试信息，默认折叠）
    with st.expander("🛠 运行状态（调试信息）", expanded=False):
        logs = read_logs(n=200)
        if not logs:
            st.success("本次行程生成无错误或降级 ✅")
        else:
            groups = _group_logs(logs)
            total_errors = sum(1 for (_, _, _, deg), _ in groups.items() if not deg)
            total_degraded = sum(1 for (_, _, _, deg), _ in groups.items() if deg)
            st.caption(
                f"错误 {total_errors} 项 · 降级 {total_degraded} 项 · 共 {len(groups)} 类（同模块同步骤同类问题已合并）"
            )
            for (mod, step, t, deg), entries in groups.items():
                label = "⚠️ 降级" if deg else "❌ 错误"
                with st.expander(
                    f"{label}  module={mod}  step={step}  type={t}  × {len(entries)}"
                ):
                    last = entries[-1]
                    st.markdown(f"**最新信息**：{last['msg']}")
                    st.markdown(f"**首次时间**：{entries[0]['ts']}｜**最近时间**：{last['ts']}")
                    if len(entries) > 1:
                        st.caption("原始日志（最后 3 条）：")
                        st.code("\n".join(e["raw"] for e in entries[-3:]), language="text")
                    else:
                        st.code(last["raw"], language="text")