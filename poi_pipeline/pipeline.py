"""
poi_pipeline / pipeline.py —— 候选景点生成与验证（防幻觉核心编排）
=====================================================================
Step0  校验输入 / 准备
Step1  大模型生成店名（llm.generate_candidates）
Step2  高德反查验证（amap.search + is_same_poi 两段式相似度）
Step3  四层去重 + 黑名单硬过滤 -> 候选池

降级（分模块）：
- LLM 失败 -> 用标签关键词直接高德搜索生成候选
- 高德失败 -> 用 fallback 的假数据候选
- 输出统一结构，供 selection 分组展示。
"""
from __future__ import annotations
from typing import List, Dict, Any

from _config.config import (
    has_valid_amap_key, has_valid_deepseek_key, MIN_CANDIDATES_PER_TAG,
)
from _config.config_data import INTEREST_TAGS, SAFE_POI_LIBRARY, CITY_SAFE_POI_LIBRARY
from _config.log import log_error

from . import llm, amap
from fallback.fallback import fake_candidates

_MODULE = "poi_pipeline"

import re

# 子地点/附属设施黑名单：名字包含任一关键词的 POI 视为"大景点内的小设施"，直接过滤
# 如"杭州乐园-游客中心"、"宋城检票口"、"西湖景区东门" 等
_SUB_PLACE_KEYWORDS = [
    "游客中心", "服务中心", "检票口", "检票", "售票处", "售票",
    "出口", "入口", "大门", "正门", "北门", "南门", "东门", "西门",
    "停车场", "停车", "更衣室", "卫生间", "厕所", "洗手间",
    "医务室", "警务室", "咨询台", "接待", "前台",
    "租赁", "租借", "站点", "停靠点", "观光车", "电瓶车",
    "商业街", "美食街", "小吃街", "购物街",
    # 建筑/楼栋类
    "号楼", "号楼栋", "栋号",
    # 园区内部子景点标识
    "欢乐剧场", "水世界", "水上乐园", "游乐设施",
    "环岛漂流", "漂流", "摩天轮",
    # 地标内部分区
    "文物区", "园林区", "展区", "展示区", "体验区", "体验店",
    # 社区/街区（附属区域）
    "社区", "街区",
    # 公交/地铁站
    "公交站", "公交", "地铁站", "地铁", "车站",
    # 品牌分店/子门店（购物商圈垃圾POI）
    "爱回收", "泰兰尼斯", "LILY", "lily",
    "泡泡玛特", "POPMART", "访客大堂", "访客中心",
    "小卖部", "便利店", "快闪店", "快闪",
    "旗舰店", "形象店", "体验店", "概念店",
    "美容店", "美发店", "美甲店", "化妆店",
    # 医疗/卫生
    "诊所", "医务室",
    # 期数/分区（明确是子phase）
    "二期", "三期", "四期", "五期",
    # 商场内部区域
    "中庭", "大厅", "大堂", "泊客区", "泊客",
    # 子街/子区域（需配合前缀匹配，这里只做兜底）
    "锦街",
    # 广场子区域
    "东广场", "西广场", "南广场", "北广场",
]

# 方位词：含东西南北+后缀 → 子地点（如"春熙路东段"、"大慈寺社区"）
# 注意：纯方位词（如"南"单独）不过滤，需要跟后缀
_DIRECTION_SUFFIX_RE = re.compile(r'[东西南北][街道路段道社区区段楼栋]')

# 子地点检测：只过滤 abcdABCD 这8个字母 + 数字（用户指定）
# 如 "A馆"、"IN99"、"1号楼"、"C栋" 等
# 其他字母（如 IFS、Apple）不过滤
_HAS_ABCD_OR_DIGIT_RE = re.compile(r'[abcdABCD0-9]')

# 额外子地点模式（正则）

# 品牌分店模式：品牌名(地标名店) 或 品牌名(地标名inXX店)
# 如 "钟书阁(成都银泰中心in99店)"、"伊藤洋华堂(成都锦华万达广场店)"
_STORE_BRANCH_RE = re.compile(
    r'^.+?\(.+(店|分店|旗舰店)\)$'
)

# 品牌+店 模式（无括号）：品牌名直接+店
# 如 "万象城店"、"大悦城店"、"太古里店"
_BRAND_STORE_RE = re.compile(
    r'^(万象城|大悦城|太古里|ifs|IFS|银泰|龙湖|万达|凯德|来福士|春熙路).*店$'
)

# 公交站/地铁站模式：地名(公交站) / 地名(地铁站)
_STATION_RE = re.compile(
    r'.+\((公交站|地铁站|公交|地铁)\)$'
)

# 纯字母+数字楼栋：IFS A栋 / IFS L楼 / 银泰中心B座
# 不含中文数字（中文数字靠关键词匹配）
_LETTER_BUILDING_RE = re.compile(
    r'[A-Z][栋楼房座]'
)

# 建筑编号正则：匹配 "名+数字+楼/栋/号/单元/室" 模式
_BUILDING_RE = re.compile(
    r'[\d]+[-\s]*[\w]*[楼栋号单元室]'
)

# 园区内部子景点模式
_SUB_ATTRACTION_RE = re.compile(
    r'[-\s]?(水世界|飞行岛|天府蜀韵|欢乐剧场|游乐设施|体验区|体验店|水上乐园)'
)
_SUB_ATTRACTION_SUFFIX = re.compile(
    r'(欢乐谷|乐园|景区|公园|乐园城|主题乐园)(水世界|飞行岛|天府蜀韵|欢乐剧场|游乐设施)$'
)

# 子地点后缀特征：用于父子包含检测时判断"多出的部分是否为子地点"
_SUB_SUFFIX_RE = re.compile(
    r'[栋楼房座单元室号]|公交站|地铁站|文物区|园林区|展区|店|分店|旗舰店|南(站|区)|北(站|区)|东(站|区)|西(站|区)|摩天轮|幸福|欢乐|梦幻|乐园|景区|公园'
)

# 已知子地点插入词：用于从"主地名+插入词+后缀"中提取核心名
# 如 "国色天乡陆地乐园" 去掉 "陆地" → "国色天乡乐园"
_SUB_INSERT_WORDS = [
    "陆地", "嘉年华", "日本馆", "原始林", "湄河滩",
    "碧鸡园", "菁华", "川西", "观演广场", "文化广场",
    "A栋", "L楼", "1号楼", "文物区", "园林区",
    "乐园", "景区", "公园",
    "摩天轮", "幸福摩天轮", "幸福", "欢乐", "梦幻",
]

# 城市区域前缀：城市+区域+地标 → 剥离区域
# 如 "成都天府大悦城" → 去掉"天府" → "成都大悦城"
_CITY_DISTRICT_RE = re.compile(
    r'^(成都|西安|杭州|北京|上海|广州|深圳|重庆|苏州|南京|武汉|长沙|青岛|厦门|大理|丽江|香格里拉)'
    r'(天府|锦华|高新|锦江|武侯|青羊|成华|金牛|龙泉驿|双流|新都|温江|郫都|都江堰|彭州|崇州|金堂|大邑|蒲江|新津)'
)

# 品牌前缀剥离：已知品牌 + 地点 格式
# 如 "Apple 成都太古里" → "成都太古里"
_BRAND_PREFIX_RE = re.compile(
    r'^(Apple|华为|小米|极氪|蔚来|理想|小鹏|比亚迪|特斯拉|星巴克|麦当劳|肯德基|'
    r'钟书阁|西西弗|方所|言几又|Page One|诚品|方所|'
    r'伊藤洋华堂|伊势丹|仁和|茂业|万象城|龙湖|万达|银泰|IFS|太古|大悦城|'
    r'Chrome Hearts|Dyson|戴森|LAMY|三立方|港久|泡泡玛特)'
)


def _possible_parent_names(name: str) -> set:
    """
    从 POI 名生成可能的父名集合（用于模糊去重）。
    例："国色天乡乐园-嘉年华A" → {"国色天乡乐园-嘉年华A", "国色天乡乐园"}
    """
    parents = {name}
    n = name

    # 1. 剥离括号后缀：xxx(yyy) / xxx（yyy）
    stripped = re.sub(r'\s*[（(].*?[)）]\s*$', '', n)
    if stripped != n:
        parents.add(stripped.strip())
        n = stripped.strip()

    # 2. 剥离 | 前缀：品牌 | 地点 → 地点
    stripped = re.sub(r'^[^|｜]+[|｜]\s*', '', n)
    if stripped != n:
        parents.add(stripped.strip())
        n = stripped.strip()

    # 3. 剥离 - 后缀：地点-子地名 → 地点
    stripped = re.sub(r'\s*[-—]\s*[^\s-]+$', '', n)
    if stripped != n:
        parents.add(stripped.strip())
        n = stripped.strip()

    # 4. 剥离城市+区域前缀：城市+区域+地标 → 剥离区域
    # 如 "成都天府大悦城" → 去掉"天府" → "成都大悦城"
    m = _CITY_DISTRICT_RE.match(n)
    if m:
        stripped = n[:m.start(2)] + n[m.end():]
        if len(stripped) >= 4:
            parents.add(stripped)
            n = stripped

    # 5. 剥离品牌前缀：品牌 地点 → 地点
    m = _BRAND_PREFIX_RE.match(n)
    if m:
        stripped = n[m.end():].strip()
        if len(stripped) >= 3:
            parents.add(stripped)
            n = stripped

    # 6. 剥离已知插入词：主地名+插入词+后缀 → 主地名+后缀
    for word in _SUB_INSERT_WORDS:
        if word in n:
            stripped = n.replace(word, '').strip()
            if len(stripped) >= 4:
                parents.add(stripped)

    # 7. 尝试剥离 "乐园/景区/公园" 后缀的前后变体
    #    "国色天乡陆地乐园" → 去掉"陆地" → "国色天乡乐园"（已在步骤6处理）

    return parents


def _dedup_by_core_name(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    核心名去重：如果两个 POI 共享某个"可能的父名"，则视为重复，
    保留原始名称最短的那个。
    例："国色天乡乐园" vs "国色天乡陆地乐园" → 共享父名"国色天乡乐园" → 保留前者
    """
    remove_ids: set = set()
    # 预计算每个 POI 的可能父名
    for i, p in enumerate(pois):
        p['_parents'] = _possible_parent_names(p.get('name', ''))

    for i, p1 in enumerate(pois):
        if id(p1) in remove_ids:
            continue
        parents1 = p1.get('_parents', set())
        n1 = p1.get('name', '')
        for j, p2 in enumerate(pois):
            if i >= j or id(p2) in remove_ids:
                continue
            parents2 = p2.get('_parents', set())
            # 如果两个 POI 有共同的父名 → 重复
            common = parents1 & parents2
            # 或父名互为子串（如 "国色天乡乐园" 是 "国色天乡陆地乐园" 的子串）
            if not common:
                for pa in parents1:
                    for pb in parents2:
                        if pa in pb or pb in pa:
                            common = {pa}
                            break
                    if common:
                        break
            if common:
                n2 = p2.get('name', '')
                # 保留短名
                if len(n1) <= len(n2):
                    remove_ids.add(id(p2))
                else:
                    remove_ids.add(id(p1))
                    break  # p1 已标记移除，跳出内层循环

    # 清理临时字段
    for p in pois:
        p.pop('_parents', None)

    return [p for p in pois if id(p) not in remove_ids]


def _is_sub_place(name: str) -> bool:
    """判断 POI 名字是否是大景点的附属设施/建筑编号/园区内子景点/分店。"""
    # 0. 含abcdABCD或数字 → 过滤（用户指定规则）
    if _HAS_ABCD_OR_DIGIT_RE.search(name):
        return True
    # 0.5 含方位词+后缀 → 过滤（如"春熙路东段"、"大慈寺社区"）
    if _DIRECTION_SUFFIX_RE.search(name):
        return True
    # 1. 关键词匹配
    if any(kw in name for kw in _SUB_PLACE_KEYWORDS):
        return True
    # 2. 品牌分店模式：品牌(地标店)
    if _STORE_BRANCH_RE.search(name):
        return True
    # 2.5 品牌+店 模式（无括号）
    if _BRAND_STORE_RE.search(name):
        return True
    # 3. 公交站/地铁站（长名才触发，避免误杀短名如"公交新村"）
    if len(name) > 6 and _STATION_RE.search(name):
        return True
    # 4. 字母+楼栋（如 IFS A栋）
    if len(name) > 5 and _LETTER_BUILDING_RE.search(name):
        return True
    # 5. 建筑编号（数字+楼/栋/单元等）
    if len(name) > 5 and _BUILDING_RE.search(name):
        return True
    # 6. 园区内部子景点
    if _SUB_ATTRACTION_RE.search(name):
        return True
    if _SUB_ATTRACTION_SUFFIX.search(name):
        return True
    return False


def _filter_by_parent_child(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    父子包含检测：如果 POI A 的名字是 POI B 的子串，
    且 B 多出的部分包含子地点特征（栋/楼/公交站/区等），则过滤 B。
    例："IFS国际金融中心" 是 "IFS国际金融中心A栋" 的子串 → 过滤后者。
    """
    # 按名字长度排序，短名（父）在前
    sorted_pois = sorted(pois, key=lambda p: len(p.get("name", "")))
    filtered = set()
    for i, p1 in enumerate(sorted_pois):
        n1 = p1.get("name", "")
        if not n1:
            continue
        for j in range(i + 1, len(sorted_pois)):
            p2 = sorted_pois[j]
            n2 = p2.get("name", "")
            if not n2:
                continue
            # n1 是 n2 的子串 → n2 可能是子地点
            if n1 in n2 and n1 != n2:
                # 提取 n2 比 n1 多出的部分
                extra = n2.replace(n1, "", 1).strip()
                # 如果多出的部分包含子地点特征 → 过滤 n2
                if extra and _SUB_SUFFIX_RE.search(extra):
                    filtered.add(id(p2))
    return [p for p in pois if id(p) not in filtered]


# POI 别名映射：将常见简称/别名归一化为标准名
# 用于去重（如"IFS国金中心" = "IFS国际金融中心"）
_POI_ALIAS_MAP = {
    "ifs国金中心": "IFS国际金融中心",
    "ifs国际金融中心": "IFS国际金融中心",
    "成都ifs": "IFS国际金融中心",
}

def _dedupe(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    候选池去重（同标签内）：
    A 子地点过滤：名字含"游客中心/检票口/出口"等子设施关键词的直接剔除
    B 精确名去重
    C 坐标去重（同一坐标点只保留一次）
    D 父子包含检测：POI 名是另一 POI 名的子串且含子地点特征 → 剔除
    注：不再做跨标签去重，允许同一 POI 出现在多个标签下。
    注：不再做相似度去重（原 0.60 阈值误杀严重，改由 confirm_keywords 白名单把关）。
    """
    # 0. 别名归一化
    for p in pois:
        nm = p.get("name", "")
        canonical = _POI_ALIAS_MAP.get(nm.lower())
        if canonical:
            p["name"] = canonical

    # A/B/C 基础过滤
    result: List[Dict[str, Any]] = []
    seen_exact: set = set()
    seen_coord: set = set()
    for p in pois:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        # A 子地点过滤
        if _is_sub_place(name):
            continue
        if name in seen_exact:
            continue
        # B/C 精确名 + 坐标
        key = (round(p.get("lng", 0), 5), round(p.get("lat", 0), 5))
        if key in seen_coord:
            continue
        seen_exact.add(name)
        seen_coord.add(key)
        result.append(p)
    # D 父子包含检测
    result = _filter_by_parent_child(result)
    # E 核心名去重（模糊匹配：共享父名 → 保留最短）
    result = _dedup_by_core_name(result)
    # F 每标签限22个（按评分降序，保留前22个）
    result.sort(key=lambda p: -float(p.get("rating") or 0))
    result = result[:22]
    return result


def _tagged(pois: List[Dict[str, Any]], tag: str,
            generated_names: List[str]) -> List[Dict[str, Any]]:
    """给 POI 打上标签。若名称与 LLM 生成名相似也标注确认。"""
    for p in pois:
        tags = set(p.get("tags") or [])
        tags.add(tag)
        names = generated_names or []
        if any(amap.is_same_poi(p.get("name", ""), gn) for gn in names):
            tags.add("LLM确认")
        p["tags"] = list(tags)
    return pois


def _inject_safe_library(city: str, tags: List[str]) -> List[Dict[str, Any]]:
    """注入已知安全 POI 库（按城市匹配 + 杭州通用 SAFE_POI_LIBRARY），保证关键地标不丢。"""
    out: List[Dict[str, Any]] = []

    def _extend(items: List[Dict[str, Any]], tg: str):
        for item in items:
            out.append({**item, "tags": [tg, "安全库"], "open_time": item.get("open_time", "")})

    # 1) 通用库：仅杭州（避免把杭州示例注入到成都/上海等城市）
    hangzhou = ("杭州" in city) or ("Hangzhou" in city)
    for tg in tags:
        if hangzhou:
            _extend(SAFE_POI_LIBRARY.get(tg, []), tg)

    # 2) 城市专属库：城市名即 key（任意子串命中）
    for city_key, lib in CITY_SAFE_POI_LIBRARY.items():
        if city_key in city:
            for tg in tags:
                _extend(lib.get(tg, []), tg)
    return out


def _tag_confirms(pois: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    标签确认层：若 INTEREST_TAGS[标签].confirm_keywords 定义了白名单，
    则只保留"名字或 type 字段"命中至少一个关键词的 POI。
    但若 POI 已通过高德反查验证（有 typecode），则不过滤——高德已确认真实存在。
    仅对无 typecode 的候选（LLM 纯生成名未反查成功）做白名单过滤。
    """
    keywords = cfg.get("confirm_keywords") or []
    if not keywords:
        return pois
    keep: List[Dict[str, Any]] = []
    kw_lower = [k.lower() for k in keywords]
    for p in pois:
        # 有 typecode → 高德已确认真实存在，直接保留
        if p.get("typecode"):
            keep.append(p)
            continue
        text = f"{p.get('name') or ''}|{p.get('type') or ''}".lower()
        if any(kw and kw in text for kw in kw_lower):
            keep.append(p)
    return keep


# 候选池缓存：同输入直接复用，保证确定性
_candidates_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}


def build_candidates(ui: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    主入口。返回 {标签: [POI,...]} 候选池。
    方案 A：ui(city/days/pace/tags) 整包传入 Step1，让 LLM 按总量/节奏/标签/城市口味出候选。
    任何降级只影响对应环节，不中断整条链路。
    同输入直接复用缓存，保证确定性。
    """
    city = str(ui.get("city", "")).strip()
    tags: List[str] = list(ui.get("tags") or [])
    days = int(ui.get("days", 1) or 1)
    pace = str(ui.get("pace", "normal") or "normal")
    periods: List[str] = list(ui.get("periods") or ["morning", "afternoon", "evening"])

    # 缓存 key：城市+标签+天数+节奏
    cache_key = f"{city}|{','.join(sorted(tags))}|{days}|{pace}"
    if cache_key in _candidates_cache:
        return _candidates_cache[cache_key]

    result: Dict[str, List[Dict[str, Any]]] = {tg: [] for tg in tags}

    # Step1 大模型生成店名
    llm_names: Dict[str, List[str]] = {}
    llm_ok = has_valid_deepseek_key()
    if llm_ok:
        llm_names = llm.generate_candidates(city, tags)
        if not llm_names:
            log_error(_MODULE, "Step1生成", "API", "LLM 未产出候选，走关键词兜底", degraded=True)

    # Step3 用所有可能来源收集 POI
    gathered: Dict[str, List[Dict[str, Any]]] = {tg: [] for tg in tags}

    # 来源A：安全库注入
    for tg in tags:
        gathered[tg].extend(_inject_safe_library(city, [tg]))

    # 来源A2：安全库POI开放时间补全（高德API查询）
    if has_valid_amap_key():
        for tg in tags:
            for p in gathered[tg]:
                if "安全库" in p.get("tags", []) and not p.get("open_time"):
                    name = p.get("name", "")
                    got = amap.search(name, city, page_size=10)
                    # 遍历所有结果，找最佳匹配（有open_time的优先）
                    best = None
                    for r in got:
                        if amap.is_same_poi(name, r.get("name", "")):
                            if r.get("open_time"):
                                best = r
                                break  # 找到有open_time的就停
                            if best is None:
                                best = r  # 没有open_time但匹配的也暂存
                    if best:
                        ot = best.get("open_time", "")
                        if ot:
                            p["open_time"] = ot
                        if best.get("typecode") and not p.get("typecode"):
                            p["typecode"] = best.get("typecode")
                        if best.get("rating") and not p.get("rating"):
                            p["rating"] = best.get("rating")

    for tg in tags:
        cfg = INTEREST_TAGS.get(tg, {})
        # 来源B：LLM 生成的店名逐一高德反查（仅按名字+城市验证真实存在，不做类型码过滤）
        names = llm_names.get(tg, [])
        if has_valid_amap_key():
            for gn in names[:8]:
                got = amap.search(gn, city, page_size=10)
                hit = [p for p in got if amap.is_same_poi(gn, p.get("name", ""))]
                gathered[tg].extend(_tagged(hit, tg, [gn]))

        # 标签确认（confirm_keywords 白名单过滤）——
        # 对二次元等设置了 confirm_keywords 的标签，剔掉“纯普通咖啡店/服装店”之类不命中的噪声。
        gathered[tg] = _tag_confirms(gathered[tg], cfg)

        # 四层去重
        result[tg] = _dedupe(gathered[tg])

        # 不再注入假 POI：候选不足只记日志，用真实数据为准
        if len(result[tg]) < 3:
            log_error(_MODULE, "候选池", "LIMIT",
                      f"城市『{city}』标签『{tg}』候选较少（仅 {len(result[tg])} 个）",
                      degraded=True)

    # Step4 跨标签去重：同一 POI 出现在多个标签时，只保留在第一个标签里
    # 使用模糊匹配：精确名 + 去城市前缀后相同
    _CITY_PREFIXES = ["成都", "杭州", "北京", "上海", "广州", "深圳", "重庆", "武汉", "西安", "南京", "苏州", "长沙", "青岛", "厦门", "大理", "丽江", "香格里拉"]
    seen_global: dict = {}  # {规范化名: 原始名}
    def _normalize(name: str) -> str:
        n = name.strip()
        for cp in _CITY_PREFIXES:
            if n.startswith(cp):
                n = n[len(cp):]
                break
        return n
    for tg in tags:
        filtered: list = []
        for p in result.get(tg, []):
            nm = (p.get("name") or "").strip()
            if not nm:
                filtered.append(p)
                continue
            norm = _normalize(nm)
            if norm in seen_global:
                # 同一POI已在其他标签保留，跳过
                continue
            seen_global[norm] = nm
            filtered.append(p)
        result[tg] = filtered

    # Step5 LLM 游玩时长+开放时间估算（v1.5）
    # 收集所有候选 POI 的名字（去重），调 LLM 估算时长与开放时间
    # 安全库已有 duration_min 的 POI 不覆盖时长；高德已返回非空 open_time 的不覆盖开放时间
    all_names: list[str] = []
    seen_names: set = set()
    for tg in tags:
        for p in result.get(tg, []):
            nm = (p.get("name") or "").strip()
            if nm and nm not in seen_names and not p.get("duration_min"):
                all_names.append(nm)
                seen_names.add(nm)

    if all_names and has_valid_deepseek_key():
        durations = llm.estimate_durations(city, pace, all_names)
        if durations:
            for tg in tags:
                for p in result.get(tg, []):
                    nm = (p.get("name") or "").strip()
                    if nm in durations:
                        info = durations[nm]
                        # 时长：已有不覆盖
                        if not p.get("duration_min"):
                            p["duration_min"] = info.get("duration_min", 90)
                        # 开放时间：高德已返回非空的不覆盖
                        if not p.get("open_time"):
                            p["open_time"] = info.get("open_time", "")
        else:
            log_error(_MODULE, "时长估算", "API", "LLM 未返回时长，沿用默认 90min", degraded=True)
    elif all_names:
        log_error(_MODULE, "时长估算", "API", "无 DEEPSEEK_KEY，候选 POI 时长默认 90min", degraded=True)

    # 写入缓存（深拷贝，避免后续修改污染缓存）
    import copy
    _candidates_cache[cache_key] = copy.deepcopy(result)

    return result