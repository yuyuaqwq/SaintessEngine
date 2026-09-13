# 挂钟形状（可注入墙上时间）

> 模块：`saintess_engine.clock.wall` —— `set_provider` / `set_zone` / `now` / `now_local` /
> `today` / `day_key` / `stamp` / `reset`。
> 一句话：**「现在几点 / 今天是哪天」只有这一个出口，钟源和时区都由宿主注入。**

## 为什么有它

同目录的 `timer.LazyTimers` 管的是**时长**（「多久后过期」，相对秒数）；
而参考实现里另一类需求要的是**日历日**（每日刷新 / 限购 / 签到 / 轮换 / 天气）。
两者混在一个隐式 `now()` 上，症状在参考实现里是三类：

| # | 现象 | 后果 |
|---|---|---|
| 1 | 玩法代码直接 `datetime.now()` / `date.today()`（宿主 `core/time_weather.py` 等） | 假钟穿不过去 → 跨天边界**只能真的等到明天**才测得到，于是没人测；测试与真机行为分叉 |
| 2 | 用 UTC 算「今天」 | 每日刷新在**错误的时刻**发生（本地 08:00 而不是 00:00），且只在特定时段复现 |
| 3 | 换时区 / 想快进时间 | 玩法层零适配点 —— 要么改代码，要么放弃测试 |

判据（本仓通用）：把「几点/哪天」的**取值**拿掉，剩下的形状在任何游戏里都成立
→ 这是引擎的东西，不是内容的东西。

## 形状

```python
from saintess_engine.clock import wall

wall.set_zone("Asia/Shanghai")     # 名字 / "UTC+8" 固定偏移 / tzinfo 实例，三种都认
wall.day_key()                     # '2026-09-13'（本地日历日，做每日刷新的 key）

wall.set_provider(lambda: 1_757_750_000.0)   # 宿主传系统钟；测试传假钟
wall.now()          # epoch 秒（UTC 口径，与 time.time() 同口径）
wall.now_utc()      # 带时区的 UTC datetime（不带 tz 的 datetime 是 bug 温床，故不提供）
wall.now_local()    # 换算到时区
wall.today()        # 本地 date
wall.stamp("%H:%M") # 本地格式化串（展示用）
wall.reset()        # 还原「系统钟 + UTC」（测试 teardown，防互相污染）
```

## 铁律

1. **单一出口**：玩法/流程代码不得直接 `datetime.now()` / `date.today()` / `utcnow()`
   —— 门禁扫源码（`tests/test_clock_wall.py` ⑥）。
2. **时区三种写法**：`"Asia/Shanghai"`（走 `zoneinfo`，需 tzdata）·`"UTC+8"`（零依赖固定偏移，离线环境用）·
   `tzinfo` 实例。解析失败**抛可读错，不静默退 UTC**（退回 UTC = 刷新在错误时刻发生，最难查）。
3. **不配置也能跑**：无 provider = 系统钟；`set_zone` 不调 = UTC。宿主晚接一步不会炸。
4. **注入是进程级的**，`reset()` 必须逐项还原（门禁 ⑤）。
5. 惰性计时器的系统钟只是**可注入默认**（`clock` 参数优先），不是第二真源（门禁 ⑥）。

## 门禁

`tests/test_clock_wall.py` —— 28 条断言：默认系统钟 / 注入后全出口跟随 / **跨天边界（本地午夜 +2 秒必须换日）** /
三种时区写法等价 / 坏时区与坏 provider 一律抛 / `reset()` 干净 / 引擎内单一出口扫源码。
