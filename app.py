"""
app.py —— Streamlit 入口
=========================
三页流程：输入 -> 候选选择 -> 结果（时间轴 + 地图 + 运行状态）。
只做薄串接；业务在 poi_pipeline / selection / routing / rules / render / map_view / fallback。
v1.6: 选择后插 LLM 开放时间查询，固定时段，open_time 空时随便排。
"""
from __future__ import annotations
from typing import Dict, Any, List

import streamlit as st

st.set_page_config(page_title="旅行规划助手", page_icon="🗺", layout="wide")

# ---------- 模块 ----------
from poi_pipeline.pipeline import build_candidates
from poi_pipeline.llm import query_open_times
from routing.routing import cluster_days, order_day_optimized
from render.render import render_itinerary
from ui.input_page import render_input_page
from ui.selection_page import render_selection_page
from ui.result_page import render_result_page
from _config.config import PERIOD_WINDOWS
from _config.log import reset_logs

st.title("🗺 旅行规划助手")

# 页面状态：step = input | select | result
if "step" not in st.session_state:
    st.session_state["step"] = "input"
if "candidates" not in st.session_state:
    st.session_state["candidates"] = {}


# ---------- 第一步：输入 ----------
if st.session_state["step"] == "input":
    ui = render_input_page()
    if ui:
        with st.spinner("正在为你生成候选景点…"):
            st.session_state["ui"] = ui
            st.session_state["candidates"] = build_candidates(ui)
        st.session_state["step"] = "select"
        st.rerun()

# ---------- 第二步：选择候选 ----------
elif st.session_state["step"] == "select":
    ui = st.session_state["ui"]
    st.caption(f"城市 {ui['city']} · {ui['days']} 天 · 节奏 {ui['pace']}")
    sel = render_selection_page(st.session_state["candidates"], ui["days"], ui["pace"], ui.get("periods", ["morning", "afternoon"]))
    if sel:
        st.session_state["selected"] = sel
        st.session_state["step"] = "result"
        st.rerun()
    if st.button("← 返回修改输入"):
        st.session_state["step"] = "input"
        st.rerun()

# ---------- 第三步：结果 ----------
else:
    ui = st.session_state["ui"]
    reset_logs()
    selected: Dict[str, List[str]] = st.session_state.get("selected", {})
    candidates: Dict[str, List[Dict[str, Any]]] = st.session_state.get("candidates", {})

    # 把已选店名还原为 POI 对象
    chosen_pois: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for tag, names in selected.items():
        for p in candidates.get(tag, []):
            if p.get("name") in names and p.get("name") not in by_name:
                chosen_pois.append(p)
                by_name[p["name"]] = p

    # Q2-A: 用户选完后，LLM 批量查询开放时间
    chosen_names = [p["name"] for p in chosen_pois]
    with st.spinner("正在查询景点开放时间…"):
        open_times = query_open_times(chosen_names)
        if open_times:
            for p in chosen_pois:
                if p["name"] in open_times:
                    # 覆盖之前的 open_time（用户选完后查的更精准）
                    p["open_time"] = open_times[p["name"]]

    # 时间预算计算（按固定时段硬上限）
    periods = ui.get("periods") or ["morning", "afternoon"]
    daily_budget = sum(PERIOD_WINDOWS[s][3] - PERIOD_WINDOWS[s][0] for s in periods)
    total_budget = daily_budget * ui["days"]
    total_poi_time = sum(int(p.get("duration_min") or 90) for p in chosen_pois)
    over_count = total_poi_time - total_budget

    if over_count > 0:
        st.warning(
            f"⚠️ 你选了 {len(chosen_pois)} 个景点（预计 {total_poi_time // 60} 小时），"
            f"超出 {ui['days']} 天行程时间预算（{total_budget // 60} 小时）。"
            f"系统将自动调整，部分景点可能安排较紧凑。"
            f"建议返回减少景点，或增加天数。"
        )

    day_groups = cluster_days(chosen_pois, periods=periods, max_days=ui["days"])
    ordered_days = [order_day_optimized(g) for g in day_groups if g]

    # 断言：编排前所有 POI 必须来自用户选择
    chosen_names_set = {p.get("name") for p in chosen_pois}
    for day in ordered_days:
        for p in day:
            if p.get("name") not in chosen_names_set:
                raise RuntimeError(f"编排异常：POI『{p.get('name')}』不在用户选择列表中")

    result = render_itinerary(ordered_days, ui["days"], ui["pace"], ui, candidates=candidates)

    render_result_page(result, periods=periods)

    if st.button("← 返回选择"):
        st.session_state["step"] = "select"
        st.rerun()