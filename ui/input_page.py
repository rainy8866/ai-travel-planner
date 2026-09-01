"""
ui / input_page.py —— 输入页
=============================
负责收集用户输入：城市 / 天数 / 节奏 / 出游时间段 / 兴趣标签。
纯 UI，业务逻辑在 poi_pipeline / selection。
"""
from __future__ import annotations
from typing import Dict, Any, List

import streamlit as st

from _config.config_data import INTEREST_TAGS
from _config.config import recommendations_minutes, PERIODS

_PERIOD_LABELS = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}
_PERIOD_START = {"morning": 9, "afternoon": 14, "evening": 19}  # 各时段默认起止（供 render 用）


def render_input_page() -> Dict[str, Any]:
    """渲染输入表单，返回用户选择 dict。"""
    st.subheader("第一步 · 告诉我你的旅行偏好")

    # 强制清理旧 session state（此前 default=["morning","afternoon"] 被 Streamlit 缓存，
    # 即使代码改为 default=[] 也会沿用旧值；这里主动 pop 掉，确保空默认值生效。
    for _k in list(st.session_state.keys()):
        if "出游时间段" in _k or "时间段" in _k:
            st.session_state.pop(_k, None)

    city = st.text_input("城市", value="", placeholder="如：杭州 / 成都 / 上海")
    days = st.number_input("出行天数", min_value=1, max_value=7, value=1, step=1)

    pace = st.selectbox(
        "出行节奏",
        options=["relaxed", "normal", "compact"],
        index=1,  # 默认"正常"（原默认是"悠闲"，现改为不预选偏好）
        format_func=lambda x: {"relaxed": "悠闲", "normal": "正常", "compact": "紧凑"}[x],
    )

    periods = st.multiselect(
        "出游时间段（可多选，至少选 1 个）",
        options=list(PERIODS),
        default=[],  # 不预选任何时段，由用户自行选择
        format_func=lambda x: _PERIOD_LABELS[x],
    )
    st.caption("💡 选择后点击框外空白处可收起下拉列表。")

    tags = st.multiselect(
        "兴趣标签（可多选）",
        options=list(INTEREST_TAGS.keys()),
        default=[],  # 不预选标签，由用户自己决定
    )

    # 提交校验：城市 / 时段 / 标签 任一为空都拦截
    if st.button("生成候选景点", type="primary"):
        if not city.strip():
            st.warning("请填写城市")
            return {}
        if not periods:
            st.warning("请至少选择一个出游时间段")
            return {}
        if not tags:
            st.warning("请至少选择一个兴趣标签")
            return {}
        return {
            "city": city.strip(),
            "days": int(days),
            "pace": pace,
            "periods": list(periods),
            "tags": tags,
        }
    return {}
