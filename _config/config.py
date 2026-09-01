"""
_config / config.py —— 集中配置（Key、环境、容量常量）
=====================================================
所有产品级常量集中在此，改业务规则只改这里。
"""
import os
from typing import List, Optional
from dotenv import load_dotenv

# 项目根目录绝对路径（本文件在 <root>/_config/ 下，向上一级即项目根）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 加载 .env（项目根下的 .env 文件）
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# =============== API Keys（一律走 .env，代码不写死） ===============
AMAP_KEY = os.getenv("AMAP_KEY", "")
TIANDITU_KEY = os.getenv("TIANDITU_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def has_valid_amap_key() -> bool:
    return bool(AMAP_KEY) and "your_amap_key" not in AMAP_KEY


def has_valid_tianditu_key() -> bool:
    return bool(TIANDITU_KEY) and "your_tianditu_key" not in TIANDITU_KEY


def has_valid_deepseek_key() -> bool:
    return bool(DEEPSEEK_KEY) and "your_deepseek_key" not in DEEPSEEK_KEY


# =============== API 端点 ===============
AMAP_PLACE_TEXT = "https://restapi.amap.com/v3/place/text"
AMAP_DISTANCE = "https://restapi.amap.com/v3/distance"
TIANDITU_VEC = "https://t{s}.tianditu.gov.cn/vec_w/wmts"  # 矢量底图（统一 HTTPS，避免 iframe 混合内容拦截）
TIANDITU_CVA = "https://t{s}.tianditu.gov.cn/cva_w/wmts"  # 注记层
TIANDITU_IMG = "https://t{s}.tianditu.gov.cn/img_w/wmts"  # 影像底图（备用）
TIANDITU_CIA = "https://t{s}.tianditu.gov.cn/cia_w/wmts"  # 影像注记
OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# OSM 在中国常超时，以下备用瓦片源均为 HTTPS 国内/稳定可访问
CARTODB_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
CARTODB_DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"

# =============== 规则引擎 / 容量常量 ===============
# 每个兴趣标签的候选最低数量（无 Key 演示模式也要给足候选供用户选择）
MIN_CANDIDATES_PER_TAG = 10
# 时段：morning / afternoon / evening（可选）
PERIODS = ["morning", "afternoon", "evening"]

# v1.6 固定时段区间：(下界, 上界, 默认起点, 硬上限)  单位:分钟
# 早段 08:00-12:00，午段 12:00-18:00，晚段 18:00-22:00
# 所有 POI 必须完全落在选中时段范围内，晚段最晚 22:00
PERIOD_WINDOWS = {
    "morning":   (8 * 60,  12 * 60, 8 * 60,  12 * 60),   # 08:00-12:00
    "afternoon": (12 * 60, 18 * 60, 12 * 60, 18 * 60),   # 12:00-18:00
    "evening":   (18 * 60, 22 * 60, 18 * 60, 22 * 60),   # 18:00-22:00 硬上限
}
# POI 间移动缓冲（分钟）
SLOT_BUFFER_MIN = 15

# 每时段时间预算（分钟），与 PERIOD_WINDOWS 硬上限一致
DAILY_BUDGET_PER_PERIOD = 240  # morning 4h
# afternoon 360min, evening 240min — 实际按 PERIOD_WINDOWS 硬上限计算


import re
from typing import Tuple, Optional

def parse_open_range(open_time: str) -> Optional[Tuple[int, int]]:
    """
    解析 "08:30-18:30" 这种开放时间字符串为 (open_min, close_min)。
    跨夜（close <= open）视为开放到 24:00。
    格式不对或为空返回 None，表示全天可排。
    """
    if not open_time or not open_time.strip():
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$", str(open_time).strip())
    if not m:
        return None
    oh, om, ch, cm = map(int, m.groups())
    open_min = oh * 60 + om
    close_min = ch * 60 + cm
    if close_min <= open_min:
        return (open_min, 24 * 60)
    return (open_min, close_min)


def recommendations_minutes(days: int, periods: Optional[List[str]] = None) -> int:
    """
    总时间预算（分钟）= 天数 × Σ(选中时段的硬上限 - 下界)。
    periods 为 None 时按全部 PERIODS。
    与 routing.cluster_days 的 daily_budget 计算保持一致。
    """
    ps = periods or PERIODS
    total_per_day = sum(PERIOD_WINDOWS[s][3] - PERIOD_WINDOWS[s][0] for s in ps)
    return max(1, days) * max(1, total_per_day)


# 其它容量约束（保留，供后续扩展）
MAX_DISTRICTS_PER_DAY = {"mixed": 1, "drive": 2}
MAX_MOVE_PER_DAY_KM = {"mixed": 12, "drive": 30}

# 时间窗口
LUNCH_BREAK = ("12:00", "14:00")
DINNER_BREAK = ("17:30", "20:30")
MEAL_DURATION_MIN = 75

# =============== 相似度阈值（改动点 5） ===============
# 两段式：
#   1) 关键词命中 → 直接判定为同一 POI
#   2) 未命中关键词 → 用归一化编辑距离，>= 阈值才判定为同一 POI
SIMILARITY_THRESHOLD = 0.60


# =============== 随机起点采样（改动点 3） ===============
# 贪心排序：随机起点 + 跑 2 次取总里程最短（最简单且防坏案例）
ROUTING_SAMPLE_TRIES = 2