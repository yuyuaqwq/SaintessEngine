# -*- coding: utf-8 -*-
"""墙上时间（可注入挂钟）—— 「现在几点 / 今天是哪天」的统一出口。

为什么要有它
------------
同目录的 `timer.LazyTimers` 管的是**时长**（「多久之后过期」），用的是相对秒数；
而「今天」「本周」这类玩法（每日刷新、限购、签到、轮换、天气）要的是**日历日**。
两者混用一个隐式 `now()` 是静默失效的温床：

* 测试里想「跨一天」只能真的等 24 小时，于是没人测跨天边界；
* 玩法代码直接 `datetime.now()` → 假钟穿不过去，测试与真机行为分叉；
* 服务器换时区 / 宿主想快进时间，玩法层零适配点。

形状（引擎只定接口，钟源由宿主注入）
------------------------------------
* `set_provider(fn)` —— `fn() -> float`（epoch 秒，UTC，与 `time.time()` 同口径）
* `set_zone(tz)`     —— 日历换算用的时区；三种写法都认（见下）
* 读出口：`now()` / `now_utc()` / `now_local()` / `today()` / `day_key()` / `stamp()`

时区三种写法（离线环境也能用）
------------------------------
    set_zone("Asia/Shanghai")      # 名字（走 zoneinfo；需要 tzdata，缺了会抛可读错）
    set_zone("UTC+8") / "UTC-3"    # 固定偏移字符串（零依赖，永远可用）
    set_zone(timezone(timedelta(hours=8)))   # 直接给 tzinfo

铁律
----
1. **只有这一个出口**：玩法/流程代码不得直接 `datetime.now()`（否则假钟失效）；
   门禁 `tests/test_clock_wall.py` 会扫源码抓这个（带白名单：本模块自身）。
2. 注入是**进程级**的，`reset()` 必须能逐项还原（否则测试之间互相污染）。
3. 没 provider 时用系统钟 —— 不配置也能跑，配了才换（宿主晚接一步也不会炸）。

用法::

    from saintess_engine.clock import wall

    wall.set_zone("Asia/Shanghai")
    wall.day_key()                       # '2026-09-13'（本地日历日）
    wall.stamp("%H:%M")                  # '16:31'（本地时刻，strftime）

    wall.set_provider(lambda: 1757750000.0)   # 测试注入假钟
    wall.day_key()                       # 由假钟算出的日历日
    wall.reset()                         # 还原系统钟 + UTC
"""
from __future__ import annotations

import datetime as _dt
import time as _time

__all__ = [
    "set_provider", "reset", "has_provider",
    "set_zone", "zone", "zone_name",
    "now", "now_utc", "now_local", "today", "day_key", "stamp",
    "parse_zone",
]

_PROVIDER = None          # Optional[Callable[[], float]]
_ZONE = _dt.timezone.utc  # tzinfo
_ZONE_NAME = "UTC"


# ============================================================ 钟源（可注入）
def set_provider(fn):
    """注入钟源：`fn() -> float`（epoch 秒）。传 `None` = 还原系统钟。"""
    global _PROVIDER
    if fn is not None and not callable(fn):
        raise TypeError("钟源必须是可调用对象（fn() -> epoch 秒）")
    _PROVIDER = fn
    return fn


def has_provider() -> bool:
    """当前是否用了注入钟（测试/诊断用；宿主一般不需要看）。"""
    return _PROVIDER is not None


def now() -> float:
    """当前墙上时间（epoch 秒，UTC 口径）。注入钟优先，否则系统钟。"""
    if _PROVIDER is not None:
        return float(_PROVIDER())
    return _time.time()


def now_utc() -> _dt.datetime:
    """当前时刻（**带时区**的 UTC datetime）。不带 tz 的 datetime 是 bug 温床，这里不给。"""
    return _dt.datetime.fromtimestamp(now(), tz=_dt.timezone.utc)


def now_local() -> _dt.datetime:
    """当前时刻（带时区，换算到 `set_zone` 指定的时区）。"""
    return now_utc().astimezone(_ZONE)


def today() -> _dt.date:
    """本地日历日（跨天边界用这个，不要用 `now()` 自己算）。"""
    return now_local().date()


def day_key(fmt: str = "%Y-%m-%d") -> str:
    """本地日历日的稳定字符串键（做每日刷新的 key 就用它）。"""
    return today().strftime(fmt)


def stamp(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """本地时刻的格式化串（展示用）。"""
    return now_local().strftime(fmt)


# ============================================================ 时区
def parse_zone(tz):
    """把三种写法统一成 `tzinfo`（失败 → 抛可读错，不静默退回 UTC）。

    * `tzinfo` 实例 → 原样
    * `"UTC"` / `"UTC+8"` / `"UTC-3.5"` → 固定偏移（零依赖）
    * 其他字符串 → `zoneinfo.ZoneInfo(name)`（需要 tzdata；缺了给可读提示）
    """
    if tz is None:
        return _dt.timezone.utc
    if isinstance(tz, _dt.tzinfo):
        return tz
    if not isinstance(tz, str):
        raise TypeError("时区要 tzinfo / 字符串 / 固定偏移，收到 %r" % (type(tz).__name__,))
    name = tz.strip()
    up = name.upper()
    if up == "UTC" or up == "Z":
        return _dt.timezone.utc
    if up.startswith("UTC+") or up.startswith("UTC-"):
        body = name[3:]          # 保留符号：UTC+8 → "+8"，UTC-3.5 → "-3.5"
        try:
            hours = float(body)
        except ValueError:
            raise ValueError("固定偏移写法应为 UTC+8 / UTC-3.5，收到 %r" % (tz,))
        return _dt.timezone(_dt.timedelta(hours=hours))
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover - 3.9 以下
        raise ValueError("本机 Python 无 zoneinfo，请用 'UTC+8' 这类固定偏移写法：%r" % (tz,))
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(
            "解析不了时区 %r（%s）。离线环境请用固定偏移写法 'UTC+8'，"
            "或安装 tzdata 后重试。" % (tz, type(exc).__name__))


def set_zone(tz):
    """设日历时区（见 `parse_zone` 的三种写法）。"""
    global _ZONE, _ZONE_NAME
    z = parse_zone(tz)
    _ZONE = z
    _ZONE_NAME = getattr(z, "key", None) or str(z)
    return z


def zone():
    """当前 tzinfo。"""
    return _ZONE


def zone_name() -> str:
    """当前时区名（诊断/展示用）。"""
    return _ZONE_NAME


# ============================================================ 还原
def reset():
    """还原到「系统钟 + UTC」（测试 teardown 用，避免互相污染）。"""
    global _PROVIDER, _ZONE, _ZONE_NAME
    _PROVIDER = None
    _ZONE = _dt.timezone.utc
    _ZONE_NAME = "UTC"
