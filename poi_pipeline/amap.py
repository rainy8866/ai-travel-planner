"""
poi_pipeline / amap.py —— Step 2 高德反查验证 + 距离矩阵
===========================================================
- search: 用关键词/店名在高德 place/text 反查真实 POI（防幻觉的“验真”闸门）
  - 验证通过（相似度 >= 阈值）才保留
  - 过滤黑名单词 / 非游玩类型码
  - 无 Key / 失败 -> 降级，返回 []，由 fallback 提供假数据
- distance_matrix: 调用高德 /v3/distance 计算两点间耗时
  - 无 Key / 失败 -> 降级 -> None，调用方用直线估算
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import re

import requests

from _config.config import (
    AMAP_KEY, AMAP_PLACE_TEXT, AMAP_DISTANCE, has_valid_amap_key,
    SIMILARITY_THRESHOLD,
)
from _config.config_data import (
    EXCLUDE_NAME_KEYWORDS, WHITE_VISIT_PREFIX,
    NAME_ALIASES, NON_VISIT_TYPE_PREFIX,
)
from _config.log import log_error

_MODULE = "poi_pipeline"


# ---------- 工具 ----------

def _norm(s: str) -> str:
    """规范化名称：去空格、去空白、小写，用于比对。"""
    return "".join(str(s or "").split()).lower()


def _key_overlap(name_a: str, name_b: str) -> bool:
    """关键词命中判定：任一别名或关键词出现在对方名字里。"""
    a, b = _norm(name_a), _norm(name_b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    # 别名表命中：双方都提及同一别名才算同一地标（避免"西湖"等泛词误伤）
    for canon, aliases in NAME_ALIASES.items():
        for al in [canon, *aliases]:
            al = _norm(al)
            if al and (al in a and al in b):
                return True
    return False


def _edit_distance(a: str, b: str) -> int:
    """编辑距离（归一化用）。"""
    a, b = _norm(a), _norm(b)
    dp = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, len(b) + 1):
            tmp = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = tmp
    return dp[-1]


def similarity(name_a: str, name_b: str) -> float:
    """改动点 5 两段式相似度：
    1) 关键词命中 -> 1.0
    2) 否则 -> 1 - 归一化编辑距离
    """
    if _key_overlap(name_a, name_b):
        return 1.0
    a, b = _norm(name_a), _norm(name_b)
    if not a or not b:
        return 0.0
    d = _edit_distance(a, b)
    return 1.0 - d / max(len(a), len(b))


def is_same_poi(generated_name: str, amap_name: str) -> bool:
    """改动点 5：相似度是否达到阈值（>= SIMILARITY_THRESHOLD）。"""
    return similarity(generated_name, amap_name) >= SIMILARITY_THRESHOLD


def _parse_open_time(p: Dict[str, Any]) -> str:
    """从高德返回值解析营业时间，形如 '10:00-22:00'。"""
    biz_ext = (p.get("biz_ext") or {}) or {}
    cand = biz_ext.get("open_time") or p.get("businessTime") or ""
    m = re.search(r"\d{2}:\d{2}\s*[-—-]\s*\d{2}:\d{2}", str(cand))
    return m.group(0).replace(" ", "") if m else ""


# ---------- POI 搜索 ----------

def search(keyword: str, city: str, types: str = "", page_size: int = 20) -> List[Dict[str, Any]]:
    """
    高德 place/text 反查。
    返回规范化的真实 POI 列表（已过滤黑名单/非游玩类型码）。
    失败或无 Key -> 记录降级并返回 []。
    """
    if not has_valid_amap_key():
        log_error(_MODULE, "高德反查", "API", "无有效 AMAP_KEY，反查降级为假数据", degraded=True)
        return []

    params = {
        "key": AMAP_KEY,
        "keywords": keyword,
        "city": city,
        "citylimit": "true",
        "offset": page_size,
        "page": 1,
        "extensions": "all",
    }
    if types:
        params["types"] = types

    try:
        resp = requests.get(AMAP_PLACE_TEXT, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log_error(_MODULE, "高德反查", "API", f"place/query 失败: {e}", degraded=True)
        return []

    if str(data.get("status")) != "1":
        log_error(_MODULE, "高德反查", "API", f"高德返回非 1 状态: {str(data)[:200]}", degraded=True)
        return []

    pois = data.get("pois") or []
    result: List[Dict[str, Any]] = []
    for p in pois:
        loc = p.get("location") or ""
        try:
            lng_s, lat_s = loc.split(",")
            lng, lat = float(lng_s), float(lat_s)
        except Exception:
            continue
        name = p.get("name") or ""
        if not _is_visit_poi(name, p.get("type") or "", p.get("typecode") or ""):
            continue
        biz_ext = p.get("biz_ext") or {}
        rating = None
        try:
            r = biz_ext.get("rating")
            if r not in (None, "", [], {}):
                rating = float(r)
        except Exception:
            rating = None
        result.append({
            "name": name,
            "lng": lng,
            "lat": lat,
            "type": p.get("type") or "",
            "typecode": p.get("typecode") or "",
            "address": p.get("address") or "",
            "district": p.get("pname") or p.get("adname") or "",
            "rating": rating,
            "cost": _estimate_cost(p),
            "open_time": _parse_open_time(p),
            "tags": [],
        })
    return result


def _is_visit_poi(name: str, poi_type: str, typecode: str) -> bool:
    """过滤非游玩点位：黑名单词 + 非游玩类型码。白名单前缀可豁免。"""
    if not name:
        return False
    if any(w in _norm(name) for w in EXCLUDE_NAME_KEYWORDS):
        # 白名单前缀（如“西湖xxx酒店”其实是想去的湖区）可豁免
        if not _norm(name).startswith(tuple(_norm(wp) for wp in WHITE_VISIT_PREFIX)):
            return False
    if typecode:
        for pref in NON_VISIT_TYPE_PREFIX:
            if typecode.startswith(pref):
                return False
    return True


def _estimate_cost(p: Dict[str, Any]) -> float:
    """缺失 cost 时的简单估算（演示用，非精确）。"""
    t = p.get("type") or ""
    code = str(p.get("typecode") or "")
    if "博物馆" in t or code.startswith("140"):
        return 0
    if "公园" in t or code.startswith("110"):
        return 0
    if "餐厅" in t or "餐饮" in t or code.startswith("05"):
        return 80
    if "风景" in t or "景点" in t or code.startswith("1101"):
        return 40
    return 0


# ---------- 距离矩阵 ----------

def distance_matrix(points: List[Tuple[float, float]]) -> Optional[List[List[float]]]:
    """
    计算 points 两两之间的车程/直线耗时（分钟）矩阵。
    - 高德可用：调 /v3/distance（真实）；
    - 高德不可用/失败：返回 None，调用方用 Haversine 直线兜底。
    返回 n*n 矩阵，元素为耗时分钟数。
    """
    n = len(points)
    if n <= 1:
        return [[0.0]]
    if not has_valid_amap_key():
        log_error("routing", "距离矩阵", "API", "无 AMAP_KEY，改用直线估算", degraded=True)
        return None

    origins = "|".join(f"{lng},{lat}" for lng, lat in points)
    matrix: List[List[float]] = []
    try:
        for j, (d_lng, d_lat) in enumerate(points):
            params = {
                "key": AMAP_KEY,
                "origins": origins,
                "destination": f"{d_lng},{d_lat}",  # 单数 destination（高德要求）
                "type": 1,  # 1=驾车
            }
            resp = requests.get(AMAP_DISTANCE, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if str(data.get("status")) != "1":
                log_error("routing", "距离矩阵", "API",
                          f"distance 返回非1: {str(data)[:200]}", degraded=True)
                return None
            results = data.get("results") or []
            col: List[float] = [0.0] * n
            for r in results:
                try:
                    i = int(r.get("origin_id", "0") or 0)
                    col[i] = float(r.get("duration", 0) or 0) / 60.0  # 秒->分钟
                except Exception:
                    pass
            matrix.append(col)
        # 转成 row-major: matrix[i][j] = i->j 的耗时
        row_major = [[0.0] * n for _ in range(n)]
        for j, col in enumerate(matrix):
            for i, v in enumerate(col):
                row_major[i][j] = v
        return row_major
    except requests.RequestException as e:
        log_error("routing", "距离矩阵", "API", f"高德 distance 失败: {e}", degraded=True)
        return None