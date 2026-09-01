"""
ui / selection_page.py —— 候选选择页
=====================================
按标签分组折叠展示候选，用户勾选。
含自动补缺 + 容量校验的提示展示（业务逻辑在 selection）。
纯 UI。
"""
from __future__ import annotations
from typing import Dict, Any, List

import streamlit as st

from _config.config import recommendations_minutes
from selection.selection import group_by_tag, fill_shortfall, summarize_over_capacity

# 补缺估算用的平均时长（分钟），与 selection._DEFAULT_DURATION_MIN 一致
_AVG_DURATION_MIN = 90


def render_selection_page(candidates: Dict[str, List[Dict[str, Any]]],
                          days: int, pace: str, periods: List[str]) -> Dict[str, List[str]]:
    """渲染候选选择界面，返回 {标签: [已选店名]}。"""
    st.subheader("第二步 · 勾选你想去的景点")

    grouped = group_by_tag(candidates)
    selected: Dict[str, List[str]] = {}
    exclude_names: set = set()

    if not any(grouped.values()):
        st.error("当前城市没有检索到任何候选地点。原因：未配置高德地图 Key（.env 里的 AMAP_KEY），"
                 "内置演示数据仅覆盖杭州及主要城市的游玩类标签。请先到高德开放平台注册 Web 服务 Key 并填入 .env，"
                 "重启后即可按你输入的城市实时检索真实景点。")
        return {}

    for tag, pois in grouped.items():
        with st.expander(f"{tag}（{len(pois)} 个候选）", expanded=True):
            if not pois:
                st.caption("该标签暂无候选")
                continue
            names = [p.get("name", "") for p in pois]
            # 不默认勾选：让用户自主决定去哪、不去哪
            chosen = st.multiselect(f"从『{tag}』中选择（可多选）", options=names, default=[])
            st.caption(f"已选 {len(chosen)} / {len(names)} 个，剩下可点下拉框里的名字继续添加")
            selected[tag] = chosen
            exclude_names.update(chosen)

    # 容量提示（不再自动补——用户选的才排，排完空位才补）
    if st.button("确认选择，生成行程", type="primary"):
        # 清候选缓存，确保同城市+同标签的POI不受旧缓存影响
        from poi_pipeline.pipeline import _candidates_cache
        _candidates_cache.clear()
        # v1.6：直接返回用户勾选结果，不自动补
        filled: Dict[str, List[str]] = {k: list(v) for k, v in selected.items()}
        st.session_state["selected"] = filled
        over = summarize_over_capacity(filled, candidates, days, periods)
        for w in over:
            st.warning(w)
        return filled
    return {}