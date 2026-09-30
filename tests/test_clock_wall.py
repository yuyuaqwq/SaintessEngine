#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""挂钟门禁：可注入钟 / 日历时区 / 跨天边界 / 单一出口。

跑法：python tests/test_clock_wall.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **跨天边界**：假钟推过本地午夜 → `day_key()` 必须跟着变（不许缓存 / 不许用 UTC 算日历日）
  ② **不静默退 UTC**：坏时区必须抛可读错（退回 UTC = 每天的刷新在错误的时刻发生，最难查）
  ③ **单一出口**：引擎里除挂钟模块外不得直接 `datetime.now()` / `date.today()` /
     `time.time()`（假钟穿不过去 → 测试与真机行为分叉；`time.time()` 的逐处豁免
     登记见 `_WALL_CALL_EXEMPT`）
"""
import datetime as dt
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.clock import wall  # noqa: E402

passed = 0
failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ============================================================ ① 默认 = 系统钟
def t1_default_system_clock():
    print("\n-- ① 不注入 = 系统钟（不配置也能跑）")
    wall.reset()
    import time
    delta = abs(wall.now() - time.time())
    check("now() 与 time.time() 同口径（差 < 2s）", delta < 2.0, f"差 {delta:.3f}s")
    check("无 provider 时 has_provider() 为 False", wall.has_provider() is False)
    check("默认时区是 UTC", wall.zone_name() == "UTC" and wall.zone() == dt.timezone.utc)
    check("now_utc() 带时区（不带 tz 的 datetime 是 bug 温床）",
          wall.now_utc().tzinfo is not None)
    check("now() 返回 float", isinstance(wall.now(), float))


# ============================================================ ② 注入假钟
def t2_injection():
    print("\n-- ② 注入假钟：所有出口都跟着它走")
    wall.reset()
    ts = 1_757_750_000.0            # 2025-09-13 前后（UTC）
    wall.set_provider(lambda: ts)
    check("now() 逐字等于注入值", wall.now() == ts)
    check("now_utc() = 注入时刻（UTC）",
          wall.now_utc() == dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc))
    check("has_provider() 为 True", wall.has_provider() is True)
    wall.set_zone("UTC+8")
    check("now_local() 按注入时区偏移 +8h",
          wall.now_local().utcoffset() == dt.timedelta(hours=8))
    check("today() 是带时区的日历日", wall.today() == wall.now_local().date())
    check("day_key() 是 'YYYY-MM-DD'", re.fullmatch(r"\d{4}-\d{2}-\d{2}", wall.day_key()) is not None,
          wall.day_key())
    check("stamp() 按注入钟格式化", wall.stamp("%Y-%m-%d") == wall.day_key())
    wall.reset()


# ============================================================ ③ 跨天边界（反证）
def t3_day_boundary():
    print("\n-- ③ 跨天边界：本地午夜前后必须换日历日（反证「算错成 UTC 日」）")
    wall.reset()
    wall.set_zone("UTC+8")
    # 本地 2026-01-02 23:59:59 == UTC 2026-01-02 15:59:59
    before = dt.datetime(2026, 1, 2, 15, 59, 59, tzinfo=dt.timezone.utc).timestamp()
    after = before + 2
    wall.set_provider(lambda: before)
    k1 = wall.day_key()
    wall.set_provider(lambda: after)
    k2 = wall.day_key()
    check("午夜前是 01-02", k1 == "2026-01-02", k1)
    check("午夜后是 01-03（+2 秒就跨天）", k2 == "2026-01-03", k2)
    check("同一时刻算 UTC 日会得到不同的日子（证明用了本地时区）",
          wall.now_utc().date().strftime("%Y-%m-%d") != k2)
    # provider 不被缓存
    wall.set_provider(lambda: before)
    check("换回旧钟 day_key 立刻回旧值（无缓存）", wall.day_key() == k1)
    wall.reset()


# ============================================================ ④ 时区三种写法
def t4_zones():
    print("\n-- ④ 时区三种写法 + 坏输入不静默")
    wall.reset()
    z1 = wall.parse_zone("Asia/Shanghai")
    z2 = wall.parse_zone("UTC+8")
    z3 = wall.parse_zone(dt.timezone(dt.timedelta(hours=8)))
    ts = 1_757_750_000.0
    keys = {z: dt.datetime.fromtimestamp(ts, tz=z).strftime("%Y-%m-%d") for z in (z1, z2, z3)}
    check("Asia/Shanghai = UTC+8 = tzinfo(8h)（同一日历日）", len(set(keys.values())) == 1, keys)
    check("Asia/Shanghai 走 zoneinfo（有 key）", getattr(z1, "key", "") == "Asia/Shanghai")
    check("'Z' / 'UTC' 都是 UTC", wall.parse_zone("Z") == dt.timezone.utc
          and wall.parse_zone("UTC") == dt.timezone.utc)
    check("UTC-3.5 支持小数偏移",
          wall.parse_zone("UTC-3.5").utcoffset(None) == dt.timedelta(hours=-3.5))
    bad = 0
    for bogus in ("Asia/Nowhere", "UTC+啊", "Nope/Nope"):
        try:
            wall.parse_zone(bogus)
        except (ValueError, TypeError):
            bad += 1
    check("坏时区名一律抛错（不静默退 UTC）", bad == 3, f"只抛了 {bad}/3")
    try:
        wall.set_provider("不是函数")
        check("非可调用钟源 → TypeError", False)
    except TypeError:
        check("非可调用钟源 → TypeError", True)
    wall.reset()


# ============================================================ ⑤ reset 干净
def t5_reset():
    print("\n-- ⑤ reset() 逐项还原（测试之间不许互相污染）")
    wall.set_zone("Asia/Shanghai")
    wall.set_provider(lambda: 0.0)
    wall.reset()
    check("provider 清掉", wall.has_provider() is False)
    check("时区回 UTC", wall.zone_name() == "UTC")
    import time
    check("读出口回系统钟", abs(wall.now() - time.time()) < 2.0)


#: 直调 `time.time(` 的**逐处豁免登记**（不许整文件豁免 —— 与 `test_no_silent_fallback`
#: 的白名单口径同族；登记项 0 命中 ⇒ 报红，防「过期挡箭牌」）。扫描口径：除挂钟本尊
#: `clock/wall.py` 外，任何 `time.time(` 都要么改走挂钟（`wall.now()` / 可注入钟），
#: 要么在此登记「它为什么不是旁路」的理由。
_WALL_CALL_EXEMPT = {
    ("saintess_engine/clock/timer.py",
     r"self\._clock\s*=\s*clock\s+or\s+\(lambda: int\(time\.time\(\)\)\)"):
        "可注入默认：`clock` 参数优先，系统钟只是缺省值（下方 ⑥ 形状检查同钉）",
    ("saintess_engine/host/runtime.py",
     r'"clock":\s*"time\.time\(\)"'):
        "DEFAULTS_HINTS 展示串（描述缺省钟源的说明文字），不是调用",
}


def _scan_wall_outlets(root):
    """扫 `root/saintess_engine`：返回 `(datetime 直调, 未豁免的 time.time 直调, 用到的豁免项)`。

    `datetime` 三项与 `time.time` 走同一张豁免表（当前表里没有 datetime 项）。
    """
    dt_hits, wall_hits, used = [], [], set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "saintess_engine")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel == "saintess_engine/clock/wall.py":
                continue
            src = open(p, encoding="utf-8").read()
            for m in re.finditer(r"datetime\.now\(|date\.today\(|utcnow\(", src):
                dt_hits.append("%s:%d" % (rel, src[:m.start()].count(chr(10)) + 1))
            src_lines = src.splitlines()
            for m in re.finditer(r"time\.time\(", src):
                ln = src[:m.start()].count(chr(10))
                line = src_lines[ln] if ln < len(src_lines) else ""
                for (ex_rel, ex_pat), _why in _WALL_CALL_EXEMPT.items():
                    if ex_rel == rel and re.search(ex_pat, line):
                        used.add((ex_rel, ex_pat))
                        break
                else:
                    wall_hits.append("%s:%d" % (rel, ln + 1))
    return dt_hits, wall_hits, used


# ============================================================ ⑥ 单一出口（扫源码）
def t6_single_outlet():
    print("\n-- ⑥ 引擎里「墙上时间」只有一个出口")
    dt_hits, wall_hits, used = _scan_wall_outlets(ROOT)
    check("除挂钟外没有直接 datetime.now()/date.today()/utcnow()", dt_hits == [], dt_hits[:6])
    check("★ 除挂钟外没有未登记的 time.time() 直调（豁免表 _WALL_CALL_EXEMPT，逐处登记）",
          wall_hits == [], wall_hits[:6])
    stale = sorted(set(_WALL_CALL_EXEMPT) - used)
    check("★ 豁免登记项全部真命中（0 命中的登记 = 过期挡箭牌，须清）", stale == [], stale)
    # 反证（有牙）：临时假仓根里造一个 `time.time()` 直调 ⇒ 扫描器必须抓到
    tmp_root = os.path.join(ROOT, "tests", "_wall_scan_negative_tmp")
    tmp_pkg = os.path.join(tmp_root, "saintess_engine")
    os.makedirs(tmp_pkg, exist_ok=True)
    tmp = os.path.join(tmp_pkg, "zz_tmp_wallcall.py")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("import time\n\n\ndef f():\n    return time.time()\n")
        _d2, _w2, _u2 = _scan_wall_outlets(tmp_root)
        check("反证：新造 time.time() 直调会被扫出（有牙）", len(_w2) == 1, _w2)
        check("反证：它与任一豁免都不匹配（豁免不吞新点）", _u2 == set(), _u2)
    finally:
        os.remove(tmp)
        os.rmdir(tmp_pkg)
        os.rmdir(tmp_root)
    # 惰性计时器的默认钟：只能是「可注入默认」，不许是唯一来源
    tsrc = open(os.path.join(ROOT, "saintess_engine", "clock", "timer.py"), encoding="utf-8").read()
    ok = re.search(r"self\._clock\s*=\s*clock\s+or\s+", tsrc) is not None
    check("timer 的系统钟只是「可注入默认」（clock 参数优先）", ok)
    check("timer 真接受注入的 clock 参数（形状在）",
          "def __init__(self" in tsrc and "clock" in tsrc)


def main():
    print("== 挂钟门禁：注入 / 时区 / 跨天 / 单一出口 ==")
    t1_default_system_clock()
    t2_injection()
    t3_day_boundary()
    t4_zones()
    t5_reset()
    t6_single_outlet()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
