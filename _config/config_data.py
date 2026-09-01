"""
_config / config_data.py —— 静态数据：兴趣标签、时长基准、别名表
==================================================================
- INTEREST_TAGS：用户能勾选的兴趣标签 -> 提示词 + 高德搜索关键词
- BASE_DURATIONS：游玩时长基准库（改动点 6：统一从此取值，LLM 不改时长）
- NAME_ALIASES：名称别名表（防幻觉：高德反查判定用）
"""
from __future__ import annotations

# =============== 兴趣标签（PRD §8 / 二次元等） ===============
# 每个标签：search_keywords（高德兜底搜索用）、prompt_hint（喂给 LLM）、amap_types（类型码限制）
INTEREST_TAGS = {
    "自然风光": {
        "search_keywords": ["西湖", "西溪湿地", "森林公园", "公园", "风景区"],
        "prompt_hint": "综合公园、河流湖泊、山、森林等自然景观类景点",
        "amap_types": "110200|110202|110203",
        "confirm_keywords": [
            "公园", "湿地", "湖", "山", "峰", "森林", "风景区", "风景名胜",
            "植物园", "森林公园", "湿地公园", "湖泊", "江", "河", "峡谷",
            "瀑布", "草原", "水库", "国家公园", "地质公园", "遗址公园",
            "自然", "景观", "生态园", "花海", "田园", "茶园",
        ],
    },
    "人文历史": {
        "search_keywords": ["博物馆", "历史街区", "古迹", "名人故居", "寺庙"],
        "prompt_hint": "博物馆、历史街区、古迹、名人故居、寺庙等人文历史类",
        "amap_types": "140100|140202|110103",
        "confirm_keywords": [
            "博物馆", "历史街区", "故居", "寺", "塔", "阁", "祠", "庙",
            "碑", "遗址", "纪念馆", "书院", "古城", "御街", "文物",
            "陵", "墓", "牌坊", "古迹", "非遗", "石窟", "城墙",
            "历史", "文化", "纪念堂", "艺术馆", "名人",
        ],
    },
    "主题乐园": {
        "search_keywords": ["主题乐园", "游乐园", "游乐场", "乐园", "海洋公园", "水上乐园", "欢乐谷", "方特", "宋城", "迪士尼"],
        "prompt_hint": "大型主题乐园、游乐园、游乐场、水上乐园、海洋公园等娱乐场所",
        "amap_types": "080302|080306|080307",
        "confirm_keywords": [
            "主题乐园", "游乐园", "游乐场", "乐园", "海洋公园", "水上乐园",
            "欢乐谷", "方特", "宋城", "迪士尼", "长隆", "海昌", "融创",
            "主题公园", "主题乐园", "梦幻王国", "欢乐世界",
        ],
    },
    "购物商圈": {
        "search_keywords": ["商业街", "购物中心", "商圈", "步行街"],
        "prompt_hint": "大型购物中心、步行街、地标商圈",
        "amap_types": "060100|060400|060500",
        "confirm_keywords": [
            "购物中心", "商场", "百货", "步行街", "商业街", "银泰", "万象",
            "大悦城", "来福士", "嘉里", "天街", "宝龙", "国大", "in77",
            "国金", "IFS", "太古", "恒隆", "环球", "印象城", "奥特莱斯",
        ],
    },
    "艺术展馆": {
        "search_keywords": ["美术馆", "艺术馆", "展览馆", "剧院", "演出厅"],
        "prompt_hint": "美术馆、艺术馆、展览馆、剧院等艺术文化场所",
        "amap_types": "140200|140300|140104",
        "confirm_keywords": [
            "美术馆", "艺术馆", "展览馆", "剧院", "音乐厅", "画廊",
            "画院", "展览中心", "博览馆", "会展", "剧场", "文化馆",
            "图书馆", "设计", "工艺", "书画院", "大剧院", "艺术",
            "展览", "演出", "音乐", "文化",
        ],
    },
}

# 已知安全 POI 库（防幻觉：这些是确定的真实点位，必需点位强制收录）
# 每个兴趣标签至少收录 10 个真实点位，保证无 Key（演示模式）时每个标签也有充足候选可选。
# name: 中奖点位，供候选池直接注入，避免检索漏掉关键地标
SAFE_POI_LIBRARY = {
    "自然风光": [
        {"name": "西湖风景名胜区", "district": "西湖区", "lat": 30.2466, "lng": 120.1510,
         "type": "风景名胜", "typecode": "110102", "cost": 0, "duration_min": 150},
        {"name": "西溪国家湿地公园", "district": "西湖区", "lat": 30.2686, "lng": 120.0570,
         "type": "风景名胜", "typecode": "110200", "cost": 80, "duration_min": 180},
        {"name": "湘湖", "district": "萧山区", "lat": 30.1570, "lng": 120.2350,
         "type": "风景名胜", "typecode": "110200", "cost": 0, "duration_min": 120},
        {"name": "杭州植物园", "district": "西湖区", "lat": 30.2440, "lng": 120.1200,
         "type": "公园", "typecode": "110203", "cost": 10, "duration_min": 120},
        {"name": "九溪烟树", "district": "西湖区", "lat": 30.2070, "lng": 120.1110,
         "type": "风景名胜", "typecode": "110102", "cost": 0, "duration_min": 120},
        {"name": "太子湾公园", "district": "西湖区", "lat": 30.2310, "lng": 120.1420,
         "type": "公园", "typecode": "110203", "cost": 0, "duration_min": 90},
        {"name": "满陇桂雨", "district": "西湖区", "lat": 30.2180, "lng": 120.1080,
         "type": "风景名胜", "typecode": "110102", "cost": 0, "duration_min": 90},
        {"name": "云栖竹径", "district": "西湖区", "lat": 30.1870, "lng": 120.0910,
         "type": "风景名胜", "typecode": "110102", "cost": 8, "duration_min": 120},
        {"name": "良渚古城遗址公园", "district": "余杭区", "lat": 30.3860, "lng": 120.0030,
         "type": "风景名胜", "typecode": "110100", "cost": 60, "duration_min": 150},
        {"name": "京杭大运河（杭州段）", "district": "拱墅区", "lat": 30.3140, "lng": 120.1530,
         "type": "河流", "typecode": "110100", "cost": 0, "duration_min": 90},
        {"name": "青山湖国家森林公园", "district": "临安区", "lat": 30.2280, "lng": 119.7960,
         "type": "风景名胜", "typecode": "110200", "cost": 40, "duration_min": 150},
        {"name": "超山风景区", "district": "余杭区", "lat": 30.4120, "lng": 120.2070,
         "type": "风景名胜", "typecode": "110102", "cost": 20, "duration_min": 120},
    ],
    "人文历史": [
        {"name": "浙江省博物馆（孤山馆）", "district": "西湖区", "lat": 30.2560, "lng": 120.1550,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 120},
        {"name": "灵隐寺", "district": "西湖区", "lat": 30.2400, "lng": 120.1040,
         "type": "寺庙", "typecode": "110103", "cost": 75, "duration_min": 120},
        {"name": "河坊街", "district": "上城区", "lat": 30.2350, "lng": 120.1770,
         "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 90},
        {"name": "雷峰塔", "district": "西湖区", "lat": 30.2310, "lng": 120.1470,
         "type": "文物古迹", "typecode": "110103", "cost": 40, "duration_min": 90},
        {"name": "岳飞庙", "district": "西湖区", "lat": 30.2550, "lng": 120.1490,
         "type": "文物古迹", "typecode": "110103", "cost": 25, "duration_min": 60},
        {"name": "胡雪岩故居", "district": "上城区", "lat": 30.2350, "lng": 120.1790,
         "type": "名人故居", "typecode": "140100", "cost": 20, "duration_min": 60},
        {"name": "南宋御街", "district": "上城区", "lat": 30.2330, "lng": 120.1790,
         "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 90},
        {"name": "六和塔", "district": "西湖区", "lat": 30.1980, "lng": 120.1200,
         "type": "文物古迹", "typecode": "110103", "cost": 20, "duration_min": 60},
        {"name": "中国丝绸博物馆", "district": "上城区", "lat": 30.2360, "lng": 120.1500,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 90},
        {"name": "杭州博物馆", "district": "上城区", "lat": 30.2450, "lng": 120.1500,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 90},
        {"name": "良渚博物院", "district": "余杭区", "lat": 30.4000, "lng": 120.0300,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 120},
        {"name": "拱宸桥", "district": "拱墅区", "lat": 30.3240, "lng": 120.1410,
         "type": "文物古迹", "typecode": "110103", "cost": 0, "duration_min": 60},
    ],
    "主题乐园": [
        {"name": "杭州宋城", "district": "西湖区", "lat": 30.1860, "lng": 120.0970,
         "type": "主题公园", "typecode": "080302", "cost": 320, "duration_min": 240},
        {"name": "杭州乐园", "district": "萧山区", "lat": 30.1560, "lng": 120.2380,
         "type": "主题公园", "typecode": "080302", "cost": 200, "duration_min": 240},
        {"name": "杭州长乔极地海洋公园", "district": "萧山区", "lat": 30.1550, "lng": 120.2380,
         "type": "海洋公园", "typecode": "080307", "cost": 300, "duration_min": 240},
        {"name": "烂苹果乐园", "district": "萧山区", "lat": 30.1580, "lng": 120.2380,
         "type": "主题公园", "typecode": "080302", "cost": 200, "duration_min": 240},
        {"name": "湘湖开元森泊度假乐园", "district": "萧山区", "lat": 30.1600, "lng": 120.2400,
         "type": "主题乐园", "typecode": "080302", "cost": 280, "duration_min": 240},
        {"name": "杭州湾融创乐园", "district": "萧山区", "lat": 30.1570, "lng": 120.2390,
         "type": "主题公园", "typecode": "080302", "cost": 200, "duration_min": 240},
        {"name": "西溪欢乐城", "district": "余杭区", "lat": 30.2780, "lng": 120.0100,
         "type": "游乐场", "typecode": "080306", "cost": 120, "duration_min": 180},
        {"name": "临安青山湖水上乐园", "district": "临安区", "lat": 30.2280, "lng": 119.7960,
         "type": "水上乐园", "typecode": "080307", "cost": 180, "duration_min": 240},
        {"name": "千岛湖乐园", "district": "淳安县", "lat": 29.6080, "lng": 119.0200,
         "type": "主题乐园", "typecode": "080302", "cost": 200, "duration_min": 300},
        {"name": "浙江广厦欢乐世界", "district": "东阳市", "lat": 29.1360, "lng": 120.2850,
         "type": "主题乐园", "typecode": "080302", "cost": 180, "duration_min": 240},
    ],
    "购物商圈": [
        {"name": "湖滨银泰 in77", "district": "上城区", "lat": 30.2536, "lng": 120.1642,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "杭州万象城", "district": "上城区", "lat": 30.2300, "lng": 120.2300,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "杭州大厦购物城", "district": "拱墅区", "lat": 30.2700, "lng": 120.1600,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "武林银泰", "district": "拱墅区", "lat": 30.2660, "lng": 120.1600,
         "type": "百货商场", "typecode": "060400", "cost": 0, "duration_min": 120},
        {"name": "杭州嘉里中心", "district": "拱墅区", "lat": 30.2590, "lng": 120.1630,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "杭州湖滨步行街", "district": "上城区", "lat": 30.2550, "lng": 120.1660,
         "type": "步行街", "typecode": "060500", "cost": 0, "duration_min": 90},
        {"name": "延安路商业街", "district": "上城区", "lat": 30.2600, "lng": 120.1600,
         "type": "商业街", "typecode": "060500", "cost": 0, "duration_min": 90},
        {"name": "杭州来福士中心", "district": "上城区", "lat": 30.2320, "lng": 120.2240,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "国大城市广场", "district": "拱墅区", "lat": 30.2690, "lng": 120.1610,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "杭州银泰百货（庆春店）", "district": "上城区", "lat": 30.2540, "lng": 120.1730,
         "type": "百货商场", "typecode": "060400", "cost": 0, "duration_min": 120},
        {"name": "龙湖杭州金沙天街", "district": "钱塘区", "lat": 30.3330, "lng": 120.3100,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        {"name": "滨江宝龙城", "district": "滨江区", "lat": 30.2080, "lng": 120.2160,
         "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
    ],
    "艺术展馆": [
        {"name": "中国美术学院美术馆", "district": "上城区", "lat": 30.2400, "lng": 120.1500,
         "type": "美术馆", "typecode": "140200", "cost": 0, "duration_min": 90},
        {"name": "浙江美术馆", "district": "上城区", "lat": 30.2350, "lng": 120.1550,
         "type": "美术馆", "typecode": "140200", "cost": 0, "duration_min": 90},
        {"name": "杭州大剧院", "district": "上城区", "lat": 30.2470, "lng": 120.2180,
         "type": "剧院", "typecode": "140300", "cost": 0, "duration_min": 120},
        {"name": "浙江省展览馆", "district": "拱墅区", "lat": 30.2670, "lng": 120.1640,
         "type": "展览馆", "typecode": "140104", "cost": 0, "duration_min": 90},
        {"name": "中国茶叶博物馆", "district": "西湖区", "lat": 30.2210, "lng": 120.1200,
         "type": "博物馆", "typecode": "140100", "cost": 0, "duration_min": 90},
        {"name": "浙江自然博物院", "district": "拱墅区", "lat": 30.2620, "lng": 120.1670,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 120},
        {"name": "南宋官窑博物馆", "district": "上城区", "lat": 30.2400, "lng": 120.1630,
         "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 90},
        {"name": "杭州工艺美术博物馆", "district": "拱墅区", "lat": 30.3260, "lng": 120.1400,
         "type": "美术馆", "typecode": "140200", "cost": 0, "duration_min": 90},
        {"name": "中国国际设计博物馆", "district": "上城区", "lat": 30.2460, "lng": 120.1460,
         "type": "美术馆", "typecode": "140200", "cost": 0, "duration_min": 90},
        {"name": "浙江图书馆", "district": "西湖区", "lat": 30.2500, "lng": 120.1550,
         "type": "图书馆", "typecode": "140104", "cost": 0, "duration_min": 90},
        {"name": "浙江音乐厅", "district": "上城区", "lat": 30.2430, "lng": 120.1510,
         "type": "剧院", "typecode": "140300", "cost": 0, "duration_min": 120},
        {"name": "中国杭州工艺美术馆", "district": "拱墅区", "lat": 30.1400, "lng": 120.1420,
         "type": "美术馆", "typecode": "140200", "cost": 0, "duration_min": 90},
    ],
}

# =============== 游玩时长基准库（改动点 6：唯一时长来源） ===============
# typecode 前缀 -> (min, max) 分钟。LLM 只排版不改时长。
BASE_DURATIONS = {
    # 公园 / 自然
    "110200": (60, 120),   # 风景名胜-公园
    "110202": (60, 120),
    "110203": (60, 120),
    "110100": (90, 180),   # 风景
    "110101": (90, 180),
    "110102": (90, 180),
    # 科教文化
    "140100": (90, 150),   # 博物馆
    "140101": (90, 150),
    "140104": (60, 120),   # 展览馆
    "140200": (90, 150),   # 美术馆
    "140202": (90, 150),   # 文化
    "140300": (60, 120),   # 剧院
    "141300": (60, 120),   # 科教
    # 购物
    "060000": (90, 150),
    "060100": (90, 150),
    "060400": (90, 150),   # 商场
    "060500": (60, 120),   # 步行街
    # 休闲
    "080302": (120, 180),  # 主题公园/乐园
    "080306": (90, 150),   # 游乐场
    # 美食（不作为景点长期停留，仅供演示）
    "050000": (45, 75),
    # 默认
    "__default__": (60, 120),
}

# 类型码前缀 -> 是否“游玩点位”（过滤酒店/住宅/写字楼等非景点用）
NON_VISIT_TYPE_PREFIX = ("060600", "120100", "120200", "120300", "120301", "141200")
# 名字黑名单（含这些词的 POI 不进候选池）
EXCLUDE_NAME_KEYWORDS = (
    "酒店", "宾馆", "民宿", "客栈", "旅馆", "公寓", "住宅", "小区", "楼盘",
    "停车场", "写字楼", "房地产", "售楼", "建材", "物流", "超市", "市客",
    "山姆", "会员商店", "卖场", "仓储", "批发", "研究所", "研究院", "科学院",
    "学校", "大学", "科技园", "办公",
)

# 名字白名单前缀（即便含黑名单词，以这些前缀开头的仍然算景点/可去）
WHITE_VISIT_PREFIX = ("西湖", "杭州", "灵隐", "西溪", "湘湖", "运河", "良渚")

# =============== 名称别名表（防幻觉：高德反查判定用） ===============
# 大模型推的店名 / 高德返回名，取别名做“关键词命中”归一。
NAME_ALIASES = {
    "湖滨银泰 in77": ["in77", "湖滨银泰", "杭州湖滨银泰"],
    "BilibiliGoods": ["bilibiligoods", "哔哩哔哩", "b站"],
    "西湖": ["西湖风景名胜区"],
    "西溪湿地": ["西溪国家湿地公园"],
    "灵隐寺": ["灵隐"],
    "天府红": ["天府红购物中心"],
    "天府国际动漫城": ["天府国际动漫城", "动漫城"],
}

# =============== 城市专属安全库（按城市名匹配注入，保证非杭州城市也能有各标签关键地标） ===============
# 结构：{ 城市名(任意子串命中即可) : { 标签名 : [POI,...] } }
CITY_SAFE_POI_LIBRARY = {
    "成都": {
        "自然风光": [
            {"name": "成都大熊猫繁育研究基地", "district": "成华区", "lat": 30.7330, "lng": 104.1470,
             "type": "动物园", "typecode": "110102", "cost": 55, "duration_min": 240},
            {"name": "武侯祠博物馆", "district": "武侯区", "lat": 30.6410, "lng": 104.0420,
             "type": "博物馆", "typecode": "140101", "cost": 50, "duration_min": 120},
            {"name": "锦里古街", "district": "武侯区", "lat": 30.6430, "lng": 104.0430,
             "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 120},
            {"name": "都江堰景区", "district": "都江堰市", "lat": 30.9990, "lng": 103.6230,
             "type": "风景名胜", "typecode": "110202", "cost": 80, "duration_min": 300},
            {"name": "青城山风景区", "district": "都江堰市", "lat": 30.9030, "lng": 103.5680,
             "type": "风景名胜", "typecode": "110202", "cost": 80, "duration_min": 360},
            {"name": "西岭雪山", "district": "大邑县", "lat": 30.8190, "lng": 103.1750,
             "type": "风景名胜", "typecode": "110202", "cost": 120, "duration_min": 480},
            {"name": "宽窄巷子", "district": "青羊区", "lat": 30.6730, "lng": 104.0610,
             "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 90},
            {"name": "浣花溪公园", "district": "青羊区", "lat": 30.6620, "lng": 104.0430,
             "type": "公园", "typecode": "110201", "cost": 0, "duration_min": 120},
            {"name": "杜甫草堂博物馆", "district": "青羊区", "lat": 30.6640, "lng": 104.0170,
             "type": "博物馆", "typecode": "140101", "cost": 50, "duration_min": 120},
            {"name": "望江楼公园", "district": "锦江区", "lat": 30.6330, "lng": 104.0970,
             "type": "公园", "typecode": "110201", "cost": 20, "duration_min": 90},
            {"name": "青龙湖湿地公园", "district": "龙泉驿区", "lat": 30.6640, "lng": 104.2990,
             "type": "湿地公园", "typecode": "110203", "cost": 0, "duration_min": 240},
            {"name": "龙泉山城市森林公园", "district": "龙泉驿区", "lat": 30.5830, "lng": 104.3330,
             "type": "森林公园", "typecode": "110202", "cost": 0, "duration_min": 300},
        ],
        "人文历史": [
            {"name": "武侯祠博物馆", "district": "武侯区", "lat": 30.6410, "lng": 104.0420,
             "type": "博物馆", "typecode": "140101", "cost": 50, "duration_min": 120},
            {"name": "杜甫草堂博物馆", "district": "青羊区", "lat": 30.6640, "lng": 104.0170,
             "type": "博物馆", "typecode": "140101", "cost": 50, "duration_min": 120},
            {"name": "锦里古街", "district": "武侯区", "lat": 30.6430, "lng": 104.0430,
             "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 120},
            {"name": "宽窄巷子", "district": "青羊区", "lat": 30.6730, "lng": 104.0610,
             "type": "历史街区", "typecode": "140202", "cost": 0, "duration_min": 90},
            {"name": "都江堰景区", "district": "都江堰市", "lat": 30.9990, "lng": 103.6230,
             "type": "文物古迹", "typecode": "110103", "cost": 80, "duration_min": 300},
            {"name": "青城山风景区", "district": "都江堰市", "lat": 30.9030, "lng": 103.5680,
             "type": "文物古迹", "typecode": "110103", "cost": 80, "duration_min": 360},
            {"name": "永陵博物馆", "district": "金牛区", "lat": 30.6840, "lng": 104.0400,
             "type": "博物馆", "typecode": "140101", "cost": 20, "duration_min": 90},
            {"name": "成都博物馆", "district": "青羊区", "lat": 30.6650, "lng": 104.0610,
             "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 180},
            {"name": "金沙遗址博物馆", "district": "青羊区", "lat": 30.6810, "lng": 104.0270,
             "type": "博物馆", "typecode": "140101", "cost": 80, "duration_min": 180},
            {"name": "水井坊博物馆", "district": "锦江区", "lat": 30.6580, "lng": 104.0920,
             "type": "博物馆", "typecode": "140101", "cost": 20, "duration_min": 90},
            {"name": "成都画院", "district": "锦江区", "lat": 30.6610, "lng": 104.0810,
             "type": "艺术馆", "typecode": "140102", "cost": 0, "duration_min": 90},
        ],
        "主题乐园": [
            {"name": "成都欢乐谷", "district": "金牛区", "lat": 30.7390, "lng": 104.0570,
             "type": "主题公园", "typecode": "080302", "cost": 230, "duration_min": 480},
            {"name": "国色天乡乐园", "district": "温江区", "lat": 30.7830, "lng": 103.8330,
             "type": "主题乐园", "typecode": "080302", "cost": 100, "duration_min": 360},
            {"name": "成都海昌极地海洋公园", "district": "双流区", "lat": 30.4300, "lng": 103.9800,
             "type": "海洋公园", "typecode": "080307", "cost": 180, "duration_min": 360},
            {"name": "成都融创乐园", "district": "都江堰市", "lat": 30.9480, "lng": 103.5620,
             "type": "主题乐园", "typecode": "080302", "cost": 180, "duration_min": 480},
            {"name": "时光印记摩天轮", "district": "锦江区", "lat": 30.6560, "lng": 104.0840,
             "type": "游乐场", "typecode": "080306", "cost": 60, "duration_min": 120},
        ],
        "购物商圈": [
            {"name": "成都太古里", "district": "锦江区", "lat": 30.6570, "lng": 104.0810,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 180},
            {"name": "成都大悦城", "district": "武侯区", "lat": 30.6470, "lng": 104.0370,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
            {"name": "成都IFS国际金融中心", "district": "锦江区", "lat": 30.6580, "lng": 104.0820,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
            {"name": "春熙路步行街", "district": "锦江区", "lat": 30.6540, "lng": 104.0820,
             "type": "步行街", "typecode": "060500", "cost": 0, "duration_min": 120},
            {"name": "成都银泰中心", "district": "高新区", "lat": 30.5720, "lng": 104.0740,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
            {"name": "成都来福士广场", "district": "武侯区", "lat": 30.6420, "lng": 104.0440,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
            {"name": "环球中心", "district": "高新区", "lat": 30.5720, "lng": 104.0660,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 180},
            {"name": "成都万象城", "district": "成华区", "lat": 30.6810, "lng": 104.1020,
             "type": "购物中心", "typecode": "060100", "cost": 0, "duration_min": 120},
        ],
        "艺术展馆": [
            {"name": "成都博物馆", "district": "青羊区", "lat": 30.6650, "lng": 104.0610,
             "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 180},
            {"name": "四川博物院", "district": "青羊区", "lat": 30.6650, "lng": 104.0560,
             "type": "博物馆", "typecode": "140101", "cost": 0, "duration_min": 180},
            {"name": "金沙遗址博物馆", "district": "青羊区", "lat": 30.6810, "lng": 104.0270,
             "type": "博物馆", "typecode": "140101", "cost": 80, "duration_min": 180},
            {"name": "水井坊博物馆", "district": "锦江区", "lat": 30.6580, "lng": 104.0920,
             "type": "博物馆", "typecode": "140101", "cost": 20, "duration_min": 90},
            {"name": "成都画院", "district": "锦江区", "lat": 30.6610, "lng": 104.0810,
             "type": "艺术馆", "typecode": "140102", "cost": 0, "duration_min": 90},
            {"name": "四川省图书馆", "district": "青羊区", "lat": 30.6660, "lng": 104.0570,
             "type": "图书馆", "typecode": "140104", "cost": 0, "duration_min": 90},
            {"name": "成都当代美术馆", "district": "高新区", "lat": 30.5720, "lng": 104.0750,
             "type": "美术馆", "typecode": "140102", "cost": 0, "duration_min": 120},
            {"name": "东郊记忆", "district": "成华区", "lat": 30.6700, "lng": 104.1170,
             "type": "艺术馆", "typecode": "140102", "cost": 0, "duration_min": 120},
        ],
    },
    "上海": {
    },
    "北京": {
    },
    "广州": {
    },
    "深圳": {
    },
    "重庆": {
    },
    "武汉": {
    },
    "西安": {
    },
}