"""
fallback / fallback.py —— 异常兜底 / 降级链路 / 演示假数据
=============================================================
提供演示模式假数据（无 API Key 时也能跑通全流程）：
- fake_candidates: 按标签给出一批真实存在的杭州地点假数据
- 供 poi_pipeline 高德失败时兜底
所有假数据带 tags，便于后续正常流程（排序/聚类/编排）不变。
"""
from __future__ import annotations
from typing import List, Dict, Any

from _config.config_data import SAFE_POI_LIBRARY, CITY_SAFE_POI_LIBRARY
from _config.log import log_error

_MODULE = "fallback"


def fake_candidates(city: str, tags: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    兜底候选池。按"城市 ↔ 哪个安全库"映射，绝不用别的城市假数据冒充：
    - 杭州 → 取 SAFE_POI_LIBRARY（原杭州通用库）
    - CITY_SAFE_POI_LIBRARY.keys() 中命中的城市（成都/上海/北京…）→ 取对应城市专属库
    - 其他城市 → 返回空（调用方应记录日志降级，避免拿杭州示例冒充）
    """
    hangzhou = ("杭州" in city) or ("Hangzhou" in city)
    city_key = next((ck for ck in CITY_SAFE_POI_LIBRARY.keys() if ck in city), None)

    out: Dict[str, List[Dict[str, Any]]] = {}
    for tg in tags:
        items: List[Dict[str, Any]] = []
        if hangzhou:
            src = SAFE_POI_LIBRARY.get(tg, [])
        elif city_key:
            src = CITY_SAFE_POI_LIBRARY[city_key].get(tg, [])
        else:
            src = []
        for p in src:
            po = dict(p)
            po.setdefault("tags", [tg])
            po.setdefault("open_time", "")
            items.append(po)
        out[tg] = items
    if not any(out.get(tg) for tg in tags):
        log_error(_MODULE, "假数据", "LIMIT",
                  f"城市『{city}』标签 {tags} 无演示数据/城市专属库，请配置高德 Key 或扩充 CITY_SAFE_POI_LIBRARY",
                  degraded=True)
    return out