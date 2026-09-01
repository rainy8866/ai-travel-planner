"""
poi_pipeline / llm.py —— Step 1 大模型生成候选店名（防幻觉起点）
===================================================================
- 调用 DeepSeek，按兴趣标签生成“景点店名”候选。
- 无 Key/超时/失败 -> 降级标记，返回 []，由 pipeline 走高德直接搜索兜底。
- 依赖 _config.log：出错时按埋点规范上报。
"""
from __future__ import annotations
from typing import List, Dict, Any
import json

import requests

from _config.config import (
    DEEPSEEK_KEY, DEEPSEEK_BASE_URL, has_valid_deepseek_key,
)
from _config.config_data import INTEREST_TAGS
from _config.log import log_error

_MODULE = "poi_pipeline"


def _build_prompt(city: str, tags: List[str]) -> str:
    """
    简洁提示词：只包含城市和用户偏好，每个标签列出具体场所类型。
    """
    # 每个标签列出具体场所类型
    tag_details = []
    for tg in tags:
        cfg = INTEREST_TAGS.get(tg, {})
        search_kw = cfg.get("search_keywords", [])
        tag_details.append(f"「{tg}」：{', '.join(search_kw)}")

    # 第一行：城市 + 偏好
    first_line = f"城市：{city}｜偏好：{', '.join(tags)}"

    # 要求部分
    tag_list = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(tag_details))

    lines = [
        first_line,
        "",
        "需求：",
        tag_list,
        "",
        "规则：",
        f"- 仅限{city}真实存在的场所，禁止编造、禁止跨城",
        "- 每个标签输出 12 个具体店名，覆盖不同区县",
        "- 只输出热门/有特色的景点，不要偏僻冷门",
        "- 注意区分相似名称（如：杭州乐园≠烂苹果乐园≠宋城）",
        "",
        "输出格式（严格JSON）：",
        "{\"标签名\": [\"店名1\", \"店名2\", ...]}",
    ]
    return "\n".join(lines)


def generate_candidates(city: str, tags: List[str]) -> Dict[str, List[str]]:
    """
    让 LLM 按用户选择的城市+偏好生成候选店名。
    返回 {标签: [店名, ...]}。无 Key 或失败时返回 {} 并记录降级。
    """
    if not has_valid_deepseek_key():
        log_error(_MODULE, "店名生成", "API", "无有效 DEEPSEEK_KEY，跳过 LLM 生成", degraded=True)
        return {}

    result: Dict[str, List[str]] = {}
    try:
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你只返回合法 JSON，不添加任何额外文字。"},
                {"role": "user", "content": _build_prompt(city, tags)},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # 容忍 markdown 代码块包裹
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        for tg in tags:
            got = data.get(tg) or []
            result[tg] = [str(x).strip() for x in got if str(x).strip()]
    except requests.RequestException as e:
        log_error(_MODULE, "店名生成", "API", f"DeepSeek 请求失败: {e}", degraded=True)
        return {}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log_error(_MODULE, "店名生成", "API", f"DeepSeek 响应解析失败: {e}", degraded=True)
        return {}
    return result


# ---------- 游玩时长估算（v1.4 新增） ----------

# 节奏英文 → 中文映射
_PACE_CN = {"relaxed": "悠闲", "normal": "正常", "compact": "紧凑"}


def _build_duration_prompt(city: str, pace: str, places: List[str]) -> str:
    """时长+开放时间估算提示词：城市 + 节奏 + 地点列表 → 每个地点的游玩时长与开放时间。"""
    pace_cn = _PACE_CN.get(pace, pace)
    places_str = "\n".join(f"{i+1}. {p}" for i, p in enumerate(places))

    lines = [
        f"你是【{city}】本地旅行顾问。用户计划去以下地点游玩，出行节奏为{pace_cn}。",
        "",
        "用户选择的地点：",
        places_str,
        "",
        "规则：",
        "1. 以用户尽可能多体验项目为前提，估算每个地点的游玩时间。",
        "2. 考虑地点类型（主题乐园/博物馆/公园/商圈/历史街区等）和规模。",
        "3. 游玩时间输出格式：",
        '   - < 4 小时：输出具体小时数，如 "2小时"、"3.5小时"',
        '   - 4~6 小时：输出 "半天"',
        '   - > 6 小时：输出 "全天"',
        "4. 同时返回该地点的日常开放时间，格式严格为 'HH:MM-HH:MM'，如 '09:00-22:00'。",
        "   - 若全天开放或 24 小时营业，输出 '00:00-24:00'。",
        "   - 若不确定，输出空字符串 \"\"。",
        "5. 只输出 JSON，不要任何解释文字。",
        "",
        "输出格式：",
        '{"地点名1": {"duration": "2小时", "open_time": "09:00-22:00"}, '
        '"地点名2": {"duration": "半天", "open_time": "10:00-18:00"}, '
        '"地点名3": {"duration": "全天", "open_time": ""}}',
    ]
    return "\n".join(lines)


def _parse_duration(raw) -> int:
    """
    把 LLM 返回的时长文本转为分钟数。
    "全天" → 480（8小时）
    "半天"/"一个时段" → 300（5小时，4~6的中值）
    "2小时" → 120
    "3.5小时" → 210
    """
    if not raw:
        return 90  # 兜底
    text = str(raw).strip()

    if "全天" in text:
        return 480
    if "半天" in text or "一个时段" in text:
        return 300

    # 解析 "X小时" 或 "X.Y小时"
    import re
    m = re.match(r"(\d+(?:\.\d+)?)\s*小时?", text)
    if m:
        hours = float(m.group(1))
        return int(hours * 60)

    return 90  # 兜底


def _parse_open_time(raw) -> str:
    """
    解析 LLM 返回的开放时间，规范为 'HH:MM-HH:MM'。
    - '全天'/'24小时'/'00:00-24:00' → 置空（视为全时段可排，由编排兜底处理）
    - 非法格式 → 置空
    """
    if not raw:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # 全天类
    if any(kw in text for kw in ("全天", "24小时", "24h")):
        return ""
    # 规范 HH:MM-HH:MM
    import re
    m = re.search(r"(\d{1,2}:\d{2})\s*[-—~]\s*(\d{1,2}:\d{2})", text)
    if not m:
        return ""
    def _fmt(t: str) -> str:
        h, mi = t.split(":")
        return f"{int(h):02d}:{int(mi):02d}"
    return f"{_fmt(m.group(1))}-{_fmt(m.group(2))}"


def estimate_durations(city: str, pace: str, places: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    调用 DeepSeek 估算每个地点的游玩时长（分钟）与开放时间。
    返回 {地点名: {"duration_min": int, "open_time": str}}。
    无 Key 或失败时返回 {} 并记录降级。
    """
    if not has_valid_deepseek_key():
        log_error(_MODULE, "时长估算", "API", "无有效 DEEPSEEK_KEY，跳过时长估算", degraded=True)
        return {}
    if not places:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    try:
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "只返回合法 JSON，不添加任何额外文字。"},
                {"role": "user", "content": _build_duration_prompt(city, pace, places)},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        for name, val in data.items():
            if isinstance(val, dict):
                dur = _parse_duration(val.get("duration"))
                ot = _parse_open_time(val.get("open_time"))
            else:
                # 兼容旧格式（纯字符串）
                dur = _parse_duration(val)
                ot = ""
            result[name] = {"duration_min": dur, "open_time": ot}
    except requests.RequestException as e:
        log_error(_MODULE, "时长估算", "API", f"DeepSeek 请求失败: {e}", degraded=True)
        return {}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log_error(_MODULE, "时长估算", "API", f"DeepSeek 响应解析失败: {e}", degraded=True)
        return {}
    return result


def _build_open_time_prompt(places: List[str]) -> str:
    """开放时间查询提示词：仅查开放时间，不查时长。"""
    lines = [
        "以下是用户选择的景点列表，请查询每个景点的日常开放时间。",
        "输出格式：HH:MM-HH:MM。如果全天开放输出 00:00-24:00，不确定或无固定开放时间输出空字符串。",
        "只输出 JSON，不要任何解释文字。",
        "",
        "景点列表：",
    ]
    for i, p in enumerate(places, 1):
        lines.append(f"{i}. {p}")
    lines.extend([
        "",
        "输出格式：",
        '{"景点名1": "09:00-22:00", "景点名2": "00:00-24:00", "景点名3": ""}',
    ])
    return "\n".join(lines)


def query_open_times(places: List[str]) -> Dict[str, str]:
    """
    用 V4 Flash 批量查询景点开放时间。
    返回 {景点名: "HH:MM-HH:MM"} 或 {景点名: ""}。
    无 Key/失败返回 {}。
    """
    if not has_valid_deepseek_key():
        log_error(_MODULE, "开放时间查询", "API", "无有效 DEEPSEEK_KEY，跳过", degraded=True)
        return {}
    if not places:
        return {}

    result: Dict[str, str] = {}
    try:
        payload = {
            "model": "deepseek-chat",  # V4 Flash 兼容，默认用 flash
            "messages": [
                {"role": "system", "content": "只返回合法 JSON，不添加任何额外文字。"},
                {"role": "user", "content": _build_open_time_prompt(places)},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        for name, raw in data.items():
            result[name] = _parse_open_time(raw)
    except requests.RequestException as e:
        log_error(_MODULE, "开放时间查询", "API", f"DeepSeek 请求失败: {e}", degraded=True)
        return {}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log_error(_MODULE, "开放时间查询", "API", f"DeepSeek 响应解析失败: {e}", degraded=True)
        return {}
    return result