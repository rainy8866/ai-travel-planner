# -*- coding: utf-8 -*-
"""成都 5 标签用高德 POI 拉真实数据，观察实际返回与映射问题"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from poi_pipeline import amap
from _config.config_data import INTEREST_TAGS

CITY = "成都"

# 每个标签：搜索关键词（用高德热门类型码 + 本地地标词）
TAG_QUERIES = {
    "自然风光": ["天府公园", "龙潭水乡", "青龙湖湿地公园", "花舞人间", "石象湖"],
    "人文历史": ["武侯祠", "杜甫草堂", "宽窄巷子", "锦里", "金沙遗址", "大慈寺"],
    "主题乐园": ["国色天乡", "融创乐园", "欢乐谷", "极地海洋世界"],
    "购物商圈": ["春熙路", "远洋太古里", "成都IFS国金中心", "环球中心", "万象城"],
    "艺术展馆": ["成都博物馆", "四川博物院", "当代美术馆", "天府美术馆", "四川科技馆"],
}

def main():
    for tag, kws in TAG_QUERIES.items():
        seen = set()
        rows = []
        for kw in kws:
            pois = amap.search(kw, CITY, page_size=20)
            for p in pois:
                nm = p.get("name", "")
                if not nm or nm in seen:
                    continue
                seen.add(nm)
                rows.append((p.get("rating"), p.get("name"), p.get("type"), p.get("typecode"), p.get("open_time")))
        # 按评分排序，取前12
        rows.sort(key=lambda r: -(r[0] or 0) if r[0] is not None else 0)
        print(f"\n{'='*70}\n【{tag}】 共搜到 {len(rows)} 个，取前12：\n{'='*70}")
        for i, (rating, name, ptype, typecode, ot) in enumerate(rows[:12], 1):
            r = f"{rating:.1f}" if rating is not None else "-"
            print(f"{i:2d}. {name}  | 评分:{r}  | type:{ptype}  | 码:{typecode}  | 开放:{ot}")

if __name__ == "__main__":
    main()