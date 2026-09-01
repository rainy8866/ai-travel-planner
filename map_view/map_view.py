"""
map_view / map_view.py —— 天地图 / folium 路线图
====================================================
- 有天地图 Key：矢量底图(vec) + 注记层(cva)，两层叠在 folium TileLayer
- 无 Key/失效：降级到 CartoDB Light（HTTPS 全球稳定，国内可访问，OSM 国内常超时）
- 按天分色 Marker + PolyLine 连主路线
返回 folium.Map 对象，供 ui 用 st.components.v1.html 或 folium_static 展示。

关键修复记录（为什么这样写）：
1) Leaflet 瓦片 URL 里的 {z}/{x}/{y} 是前端占位符，绝不能被 Python str.format() 吞掉；
   因此构造时用双花括号 {{z}}/{{x}}/{{y}} 转义，或直接拼接不经过 .format()。
2) folium.Map(tiles=None)：默认 "OpenStreetMap" 的 CDN 国内常超时，导致用户侧灰色空白；
   改为 tiles=None，手动按优先级叠图层：天地图 → CartoDB 兜底。
3) "Key 存在但 _add_tianditu 返回 False" 的分支必须也兜底加一个底图（以前漏了，直接空白）。
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional

import folium

from _config.config import (
    TIANDITU_KEY, has_valid_tianditu_key,
    TIANDITU_VEC, TIANDITU_CVA,
    OSM_TILE, CARTODB_LIGHT,
)
from _config.log import log_error

_MODULE = "map_view"

_DAY_COLORS = ["#d9534f", "#337ab7", "#3a9d4e", "#9b59b6", "#e8903a"]  # 十六进制色，直接用于 DivIcon CSS


def _day_color(i: int) -> str:
    return _DAY_COLORS[i % len(_DAY_COLORS)]


def _div_icon_html(number: int, color: str, size: int = 28) -> str:
    """生成 DivIcon 的 HTML：圆形背景 + 白色数字居中。"""
    gray = "#999"
    bg = color if color != "gray" else gray
    return (
        f'<div style="'
        f'background-color:{bg};'
        f'color:white;'
        f'width:{size}px;height:{size}px;'
        f'border-radius:50%;'
        f'border:2px solid white;'
        f'box-shadow:0 1px 4px rgba(0,0,0,0.3);'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:13px;font-weight:bold;'
        f'font-family:Arial,sans-serif;'
        f'">'
        f'{number}'
        f'</div>'
    )


def _tianditu_tile_url(base_tpl: str, layer: str, tk: str) -> str:
    """
    构造天地图 WMTS 瓦片 URL。
    关键点：Leaflet 需要的 {z}/{x}/{y} 用双花括号保留，避免被 Python format 吞掉；
    s=子域名固定写 0~7 中的某一个（天地图允许）。
    """
    base = base_tpl.format(s=0)  # 子域名只实例化 {s}，其余占位符不动
    return (
        f"{base}?tk={tk}"
        f"&service=wmts&request=GetTile&version=1.0.0"
        f"&layer={layer}&style=default&tilematrixset=w&format=tiles"
        f"&tilematrix={{z}}&tilerow={{y}}&tilecol={{x}}"
    )


def _add_tianditu(m: folium.Map) -> bool:
    """添加天地图矢量底图 + 注记层。成功返回 True，失败记录日志并返回 False。"""
    if not has_valid_tianditu_key():
        return False
    try:
        vec_url = _tianditu_tile_url(TIANDITU_VEC, "vec", TIANDITU_KEY)
        folium.TileLayer(
            tiles=vec_url,
            attr="天地图",
            name="天地图矢量底图",
            max_zoom=18,
            overlay=False,
            control=True,
        ).add_to(m)

        cva_url = _tianditu_tile_url(TIANDITU_CVA, "cva", TIANDITU_KEY)
        folium.TileLayer(
            tiles=cva_url,
            attr="天地图注记",
            name="天地图注记",
            max_zoom=18,
            overlay=True,
            control=True,
        ).add_to(m)
        return True
    except Exception as e:
        log_error(_MODULE, "天地图加载", "API", f"{e}", degraded=True)
        return False


def _add_fallback_base(m: folium.Map, reason: str) -> None:
    """
    兜底底图：CartoDB Light（OSM 国内超时严重，这里优先 CartoDB；
    若 CartoDB 也失败，folium 会自动不渲染，用户仍能看到 Marker/连线）。
    """
    log_error(_MODULE, "底图", "API",
              f"{reason}，底图降级为 CartoDB Light", degraded=True)
    try:
        folium.TileLayer(
            tiles=CARTODB_LIGHT,
            attr="© CartoDB © OpenStreetMap contributors",
            name="CartoDB Light（兜底）",
            max_zoom=19,
            subdomains="abcd",
        ).add_to(m)
    except Exception as e:
        log_error(_MODULE, "CartoDB兜底", "API", f"{e}", degraded=True)
        # 最后一道防线：folium 自带的 OSM 命名瓦片（虽然国内也容易超时，但比没有强）
        try:
            folium.TileLayer(
                tiles=OSM_TILE,
                attr="© OpenStreetMap",
                name="OSM（最终兜底）",
                max_zoom=19,
            ).add_to(m)
        except Exception as e2:
            log_error(_MODULE, "OSM最终兜底", "API", f"{e2}", degraded=True)


def render_map(
    days: List[Dict[str, Any]],
    center: Optional[tuple] = None,
    active_day: Optional[int] = None,
) -> folium.Map:
    """
    days: [{ "day":1, "items":[{"name","kind","lat","lng",...}] }]
    或 [{ "day":1, "pois":[{"name","lat","lng","tags"}] , "path_index":[...] }]
    center: (lat, lng) 缺省取第一个点。
    active_day: 当前选中的天序号（1-based）。该天路线 opacity=1、marker 原色；
                其他天路线 opacity=0.15、marker 变灰，实现"按天切换高亮"。
    地点名通过 Tooltip(permanent=True) 常驻显示在 marker 旁，无需点击。
    返回带分色标点 + 主连线的 folium.Map。
    """
    all_locs: List[tuple] = []
    for d in days:
        for it in d.get("pois", d.get("items", [])):
            if it.get("lat") is not None and it.get("lng") is not None:
                all_locs.append((it["lat"], it["lng"]))

    if not all_locs:
        c = center or (30.2741, 120.1551)
        # tiles=None：不使用任何默认命名瓦片（避免 OSM 超时导致容器灰）
        m = folium.Map(location=c, zoom_start=12, tiles=None)
    else:
        c = center or (sum(x for x, _ in all_locs) / len(all_locs),
                       sum(y for _, y in all_locs) / len(all_locs))
        m = folium.Map(location=c, zoom_start=13, tiles=None)

    # ===== 底图优先级链路（保证任何情况至少有一层可见底图）=====
    has_key = has_valid_tianditu_key()
    used_tianditu = _add_tianditu(m)

    if has_key and not used_tianditu:
        # 分支 A：用户配了 Key，但天地图图层添加异常 → 兜底
        _add_fallback_base(m, "已配置 TIANDITU_KEY 但天地图图层加载失败")
    elif not has_key:
        # 分支 B：用户根本没配 Key → 直接兜底
        _add_fallback_base(m, "未配置 TIANDITU_KEY")
    # else：天地图加载成功，无需兜底

    # ===== 注入 CSS 美化常驻 Tooltip（方案A）=====
    # 半透明背景 + 边框 + 小字号 + 偏移不盖 marker；当天文字彩色，其他天文字灰色
    _inject_tooltip_css(m)

    # ===== 按天绘制 Marker + 连线（带数字序号）=====
    for di, d in enumerate(days):
        day_no = d.get("day", di + 1)
        color = _day_color(day_no - 1)
        is_active = (active_day is None) or (day_no == active_day)
        pois = d.get("pois", d.get("items", []))
        line_points: List[tuple] = []
        for idx, it in enumerate(pois, start=1):
            if it.get("lat") is None or it.get("lng") is None:
                continue
            pt = (it["lat"], it["lng"])
            line_points.append(pt)
            label = it.get("name", "")
            kind = it.get("kind", "poi")
            # 当天：彩色数字标记；其他天：灰色数字标记
            if is_active:
                icon_color = color
            else:
                icon_color = "gray"
            # 地名常驻：当天用天色文字，其他天用灰色文字
            if is_active:
                tip_html = f'<span class="mv-lbl" style="color:{color}">{label}</span>'
            else:
                tip_html = f'<span class="mv-lbl" style="color:#999">{label}</span>'
            folium.Marker(
                location=pt,
                icon=folium.DivIcon(
                    html=_div_icon_html(idx, icon_color),
                    icon_size=(28, 28),
                    icon_anchor=(14, 14),
                ),
                popup=folium.Popup(f"<b>{idx}. {label}</b><br>{kind}<br>第{day_no}天", max_width=220),
                tooltip=folium.Tooltip(
                    tip_html, permanent=True, direction="right",
                    sticky=False, offset=[18, 0],
                ),
            ).add_to(m)
        if len(line_points) > 1:
            # 当天路线正常显示，其他天淡化
            line_opacity = 1.0 if is_active else 0.15
            line_weight = 5 if is_active else 3
            folium.PolyLine(
                line_points, color=color, weight=line_weight, opacity=line_opacity,
            ).add_to(m)

    folium.LayerControl().add_to(m)
    return m


def _inject_tooltip_css(m: folium.Map) -> None:
    """注入 CSS：美化常驻 Tooltip（半透明背景、边框、小字号、去箭头、右偏不盖 marker）。"""
    css = """
    <style>
    .leaflet-tooltip.leaflet-tooltip-permanent,
    .leaflet-tooltip .mv-lbl {
        font-size: 11px;
        font-weight: 600;
    }
    .leaflet-tooltip.leaflet-tooltip-permanent {
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.18);
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
        padding: 1px 6px;
        white-space: nowrap;
    }
    .leaflet-tooltip.leaflet-tooltip-permanent::before { display: none; }
    </style>
    """
    m.get_root().html.add_child(folium.Element(css))



