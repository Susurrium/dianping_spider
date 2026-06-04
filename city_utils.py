# -*- coding:utf-8 -*-
"""City parsing helpers for the multi-city Domino's store sheet."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict


ROOT_DIR = Path(__file__).resolve().parent
LOCATION_DOC = ROOT_DIR / "docs" / "location.md"

CITY_ALIASES = {
    "北京市": "北京",
    "上海市": "上海",
    "天津市": "天津",
    "重庆市": "重庆",
}

KNOWN_CITY_PREFIXES = [
    "北京",
    "上海",
    "天津",
    "重庆",
    "石家庄",
    "张家口",
    "沈阳",
    "大连",
    "长春",
    "哈尔滨",
    "南京",
    "苏州",
    "无锡",
    "南通",
    "杭州",
    "宁波",
    "温州",
    "嘉兴",
    "绍兴",
    "台州",
    "金华",
    "福州",
    "厦门",
    "泉州",
    "漳州",
    "济南",
    "青岛",
    "烟台",
    "潍坊",
    "郑州",
    "武汉",
    "长沙",
    "广州",
    "深圳",
    "东莞",
    "佛山",
    "中山",
    "珠海",
    "江门",
    "惠州",
    "湛江",
    "南宁",
    "成都",
    "西安",
    "太原",
    "唐山",
    "合肥",
    "芜湖",
    "贵阳",
    "昆明",
    "兰州",
]


def canonical_city(name: str) -> str:
    name = str(name or "").strip()
    name = re.sub(r"(市|地区|自治州|盟)$", "", name)
    return CITY_ALIASES.get(name, name)


def city_from_address(address: str) -> str:
    address = str(address or "").strip()
    for city in sorted(KNOWN_CITY_PREFIXES, key=len, reverse=True):
        if address.startswith(city):
            return canonical_city(city)
    match = re.match(r"^([\u4e00-\u9fff]{2,6}?)(?:市|地区|自治州|盟)", address)
    if match:
        return canonical_city(match.group(1))
    return canonical_city(address[:2])


def load_city_id_map(path: Path = LOCATION_DOC) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*-\s*([^：:]+)[：:]\s*(\d+)\s*$", line)
        if match:
            mapping[canonical_city(match.group(1))] = match.group(2)
    return mapping


def expected_city_ids(address: str) -> set[str]:
    city = city_from_address(address)
    city_id = load_city_id_map().get(city)
    return {city_id} if city_id else set()
