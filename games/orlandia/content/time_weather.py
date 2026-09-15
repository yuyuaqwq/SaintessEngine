# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/time_weather.py`
# 搬运改动面**只有「宿主取件」**一类：无（本文件零宿主取件，逐字原样搬入）
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年 核心 - time_weather.py（18 章时间季节系统，2026-08-06）

现实时间映射（QQ 机器人天然有现实时钟）：
- 时间段：清晨 05-08 / 白天 08-18 / 黄昏 18-20 / 夜晚 20-05
- 季节：春 3-5 / 夏 6-8 / 秋 9-11 / 冬 12-2
- 天气：日期哈希伪随机（每天固定、全服一致，可查）；雪只在冬季、雾只在特定地图
"""
import datetime
import random

# 时间段定义
PERIODS = [
    ("night", 0, 5),     # 00:00-05:00 夜晚
    ("morning", 5, 8),   # 05:00-08:00 清晨
    ("day", 8, 18),      # 08:00-18:00 白天
    ("evening", 18, 20), # 18:00-20:00 黄昏
    ("night", 20, 24),   # 20:00-24:00 夜晚
]

PERIOD_CN = {
    "morning": "🌅 清晨", "day": "☀️ 白天", "evening": "🌇 黄昏", "night": "🌙 夜晚",
}
SEASON_CN = {
    "spring": "🌸 春", "summer": "☀️ 夏", "autumn": "🍂 秋", "winter": "❄️ 冬",
}
WEATHER_CN = {
    "sunny": "☀️ 晴", "cloudy": "🌤️ 多云", "rain": "🌧️ 雨",
    "storm": "⛈️ 暴雨", "snow": "❄️ 雪", "fog": "🌫️ 雾",
}

# 雾天特定地图（18 章 1.4：雾·特定地图）
FOG_MAPS = {"misty_swamp", "old_battlefield", "ancient_battlefield", "shipwreck_graveyard", "fog_moor"}


def current_period(now: datetime.datetime | None = None) -> str:
    """当前时间段：morning/day/evening/night"""
    now = now or datetime.datetime.now()
    h = now.hour
    for name, start, end in PERIODS:
        if start <= h < end:
            return name
    return "night"


def current_season(now: datetime.datetime | None = None) -> str:
    """当前季节：spring/summer/autumn/winter(按现实月份)"""
    now = now or datetime.datetime.now()
    m = now.month
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    if m in (9, 10, 11):
        return "autumn"
    return "winter"


def _day_hash(seed: int, salt: str = "") -> int:
    """日期哈希：全服一致、可查(roam/cycle/天气共用)"""
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def today_weather(map_id: str | None = None, now: datetime.date | None = None) -> str:
    """当天天气：日期哈希伪随机。晴50/多云20/雨15/暴雨5/雪(冬)15/雾(特定地图)10。
    雪只在冬季；雾只在 FOG_MAPS 地图（其余地图雾会转多云）。"""
    now = now or datetime.date.today()
    seed = now.toordinal()
    season = current_season(datetime.datetime.combine(now, datetime.time(12)))
    r = _day_hash(seed, map_id or "") % 100
    if map_id in FOG_MAPS:
        # 雾天特定地图：晴45/多云20/雨15/暴雨5/雾10/雪(冬)5 → 简化：r<45晴 45-65多云 65-80雨 80-85暴雨 85-95雾 95+雪(冬)
        if r < 45:
            return "sunny"
        if r < 65:
            return "cloudy"
        if r < 80:
            return "rain"
        if r < 85:
            return "storm"
        if r < 95:
            return "fog"
        return "snow" if season == "winter" else "sunny"
    # 普通地图：晴50/多云20/雨15/暴雨5/雪(冬)15（雾地图外无雾）
    if r < 50:
        return "sunny"
    if r < 70:
        return "cloudy"
    if r < 85:
        return "rain"
    if r < 90:
        return "storm"
    return "snow" if season == "winter" else "sunny"


def time_weather_summary(map_id: str | None = None, now: datetime.datetime | None = None) -> str:
    """『时间』指令面板：时刻/时间段/季节/天气（v95.30 加具体几点几分）"""
    now = now or datetime.datetime.now()
    return (
        f"{now.hour:02d}:{now.minute:02d} · {PERIOD_CN[current_period(now)]} · "
        f"{SEASON_CN[current_season(now)]} · "
        f"{WEATHER_CN[today_weather(map_id, now.date())]}"
    )
