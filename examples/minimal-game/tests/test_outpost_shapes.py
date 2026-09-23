# -*- coding: utf-8 -*-
"""《铆炉回声》据点勘探 —— 闭环门禁 + 形态自检（**自跑风格**，不用 pytest）。

跑法：python examples/minimal-game/tests/test_outpost_shapes.py   （exit 0 全绿）

覆盖：
  1) 引擎形状真的用上了：records / store.declare / produce.Jobs / wire.Wire / bonus.Bonus
  2) ★ 闭环：派队员 → 时钟推后 → 到点收取 → 访问次数 +1 → 据点加成生效 → 落库可读
  3) 有牙：未到点不收且作业原样不动 / 槽还被占 / 未知据点不静默 / 资料表顺序声明有守卫
  4) ★ 形态：content/outpost.py ≤100 行，且零「通用机制」字样（读表 / 建表 / 取件 / 队列）
"""
import ast
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLE = os.path.dirname(_HERE)                                   # examples/minimal-game
_REPO = os.path.dirname(os.path.dirname(_EXAMPLE))                  # 框架根
sys.path.insert(0, _EXAMPLE)
sys.path.insert(0, _REPO)

from saintess_engine.bonus import Bonus                                # noqa: E402
from saintess_engine.clock import wall                                 # noqa: E402
from saintess_engine.log import get_logger                            # noqa: E402
from ext_economy.produce import AlreadyBusy, Jobs                 # noqa: E402
from saintess_engine.records import Records, RecordsOrderMismatch     # noqa: E402
from saintess_engine.store import Database, DeclaredRepository        # noqa: E402
from saintess_engine.wire import Wire, WireMissing                    # noqa: E402
from content.outpost import DAY, SITE_ORDER, VISIT_SPEC, Outpost      # noqa: E402

#: 判据 2 的形态统计（与 BRIEF §3.2 的 grep 同口径）
FORM_BAN = re.compile(r"import json|CREATE TABLE|SELECT |INSERT |UPDATE |sqlite3"
                      r"|_HOST_PKG|_resolve_host|os\.environ")
#: 五个引擎形状必须出现在 outpost.py 的 import 面里
SHAPES = ("saintess_engine.records", "saintess_engine.store", "ext_economy.produce",
          "saintess_engine.wire", "saintess_engine.bonus")
T0 = 1700000000                                       # 假钟起点（UTC 2023-11-14）

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


class Clock:
    """注入的假钟（**整数秒**，与 produce 的口径一致）；推时间 = 改一个数。"""

    def __init__(self, t):
        self.t = int(t)

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += int(secs)
        return self.t


def make_outpost(db_path, clock, *, jobs=None, handles=("db", "clock", "jobs", "log")):
    """按 wire 口径装配 Outpost：句柄名由调用方定，取不到就 WireMissing（不静默）。"""
    wire = Wire()
    wire.bind(db=Database(db_path), clock=clock, jobs={} if jobs is None else jobs,
              log=get_logger("minimal-game.outpost"))
    return Outpost(_EXAMPLE, wire), wire


def run_once(op, clock, member, site_id):
    """派 → 推时钟到点 → 收取（三步都是内容侧的业务编排）。"""
    op.dispatch(member, site_id)
    clock.advance(int(op.site(site_id)["days"]) * DAY)
    return op.collect(member)


# ---------------------------------------------------------------- 1 资料表
def t1_records():
    print("\n[1] records：读 content/data/sites.json（键型 / 顺序自己声明）")
    tmp = tempfile.mkdtemp(prefix="outpost_records_")
    try:
        clock = Clock(T0)
        wall.set_provider(lambda: float(clock()))
        op, _wire = make_outpost(os.path.join(tmp, "a.db"), clock)
        check("sites 是 engine 的 Records（不是自己读文件）", isinstance(op.sites, Records))
        check("资料表读到了（missing=False / problems 空）",
              op.sites.missing is False and op.sites.problems == [], op.sites.problems)
        check("声明序 = SITE_ORDER（不是 JSON 字典序）",
              list(op.sites.all()) == list(SITE_ORDER), list(op.sites.all()))
        check("按 id 查一条（get）", op.site("tide_mill")["name"] == "潮磨坊")
        check("单字段索引（by name）也在引擎里",
              (op.sites.by("name", "盐脉井") or {}).get("bonus_domain") == "cap")
        bad = None
        try:
            Records(_EXAMPLE, "sites", sub="content/data",
                    key_type=str, order=("tide_mill",)).load()
        except RecordsOrderMismatch as exc:
            bad = str(exc)
        check("★ 顺序声明有守卫：与域键集不符 → RecordsOrderMismatch（不静默改序）",
              bool(bad) and "不一致" in bad, bad)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 2 闭环
def t2_closed_loop():
    print("\n[2] ★ 闭环：派 → 时钟推后 → 收取 → 访问 +1 → 加成生效 → 落库")
    tmp = tempfile.mkdtemp(prefix="outpost_loop_")
    try:
        db = os.path.join(tmp, "outpost.db")
        clock = Clock(T0)
        wall.set_provider(lambda: float(clock()))
        op, _wire = make_outpost(db, clock)
        check("访问记录表由 store.declare 装配（DeclaredRepository）",
              isinstance(op.visits, DeclaredRepository) and op.visits.table == VISIT_SPEC.name)
        check("计时作业由引擎 produce.Jobs 给（Jobs）", isinstance(op.jobs, Jobs))
        check("加成容器由引擎 bonus.Bonus 给（Bonus）", isinstance(op.bonus, Bonus))

        info = op.dispatch("m1", "tide_mill")
        check("派得出去：开了一条 1 天的作业（remaining == DAY）",
              info["remaining"] == DAY and info["ends_at"] == T0 + DAY, info)

        day0 = wall.day_key()
        check("未到点：collect 返回 None", op.collect("m1") is None)
        check("未到点：作业原样不动（还在队列里，没被清槽）", len(op.jobs.all_of("m1")) == 1)
        check("未到点：一条访问记录都没写", op.record("m1", "tide_mill") is None)

        clock.advance(DAY)
        got = op.collect("m1")
        day1 = wall.day_key()
        check("到点收取成功（有结算结果）", bool(got), got)
        check("访问次数 +1", got and got["visits"] == 1, got)
        check("记录日期 = 引擎 clock.wall 的当天（推钟后从 day0 跨到 day1）",
              got and got["day"] == day1 and day1 != day0, (got, day0, day1))
        check("★ 据点加成生效：tide_mill 每次 +3（panel）",
              got and got["bonus"] == 3 and op.bonus.resolve("panel") == 3, got)
        check("收取后槽释放（队列空了）", op.jobs.all_of("m1") == [])

        row = op.record("m1", "tide_mill")
        check("访问记录落库可读（visits / last_day）",
              row == {"member": "m1", "site_id": "tide_mill", "visits": 1, "last_day": day1}, row)

        clock.advance(DAY * 2)
        got2 = run_once(op, clock, "m1", "tide_mill")
        check("第二次勘探：次数 1→2、日期跟着钟走",
              got2["visits"] == 2 and got2["day"] == wall.day_key() != day1, got2)
        check("按来源幂等回写：加成 3 → 6（同一据点只留一条来源，不叠成两条）",
              got2["bonus"] == 6 and op.bonus.sources("panel") == ["site:tide_mill"],
              (got2["bonus"], op.bonus.sources("panel")))

        fresh, _w = make_outpost(db, clock)          # 同一只库、新实例：记录还在
        check("重开实例仍读得到记录（真落库，不是内存假闭环）",
              (fresh.record("m1", "tide_mill") or {}).get("visits") == 2)

        op.dispatch("m2", "kiln_wreck")
        clock.advance(DAY * 3)
        due = op.jobs.due()
        check("★ 到点未收取不丢：due() 一直点名它（结算方拿得到原始载荷）",
              len(due) == 1 and due[0][1].payload == {"site_id": "kiln_wreck"}, due)
        check("补收：到点的那条能收掉", op.collect("m2")["visits"] == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 3 有牙
def t3_teeth():
    print("\n[3] 有牙：不静默 / 不顶掉 / 取不到就报错")
    tmp = tempfile.mkdtemp(prefix="outpost_teeth_")
    try:
        db = os.path.join(tmp, "outpost.db")
        clock = Clock(T0)
        wall.set_provider(lambda: float(clock()))
        op, wire = make_outpost(db, clock)

        hit = None
        try:
            op.dispatch("m9", "no_such_site")
        except KeyError as exc:
            hit = str(exc)
        check("未知据点 → KeyError（不静默派去空据点）", bool(hit) and "no_such_site" in hit, hit)
        check("派失败的队员没有留下作业", op.jobs.current("m9") is None)

        op.dispatch("m1", "salt_vein")
        hit = None
        try:
            op.dispatch("m1", "tide_mill")           # 同一队员槽满（max_slots=1）
        except AlreadyBusy as exc:
            hit = str(exc)
        check("槽已满 → 引擎 AlreadyBusy（绝不静默顶掉旧作业）", bool(hit), hit)
        check("被拒后旧作业还在（原样不动）",
              op.jobs.current("m1").payload == {"site_id": "salt_vein"})
        check("被拒后没写第二条记录", op.record("m1", "tide_mill") is None)

        clock.advance(DAY * 2)
        check("到点可收（salt_vein 每次 +1 cap）", op.collect("m1")["bonus"] == 1)
        check("收完槽就释放，可以再派", bool(op.dispatch("m1", "salt_vein")))

        hit = None
        try:
            wire2 = Wire()
            wire2.bind(clock=clock, log=op.log)      # 故意不 bind db
            Outpost(_EXAMPLE, wire2)
        except WireMissing as exc:
            hit = str(exc)
        check("wire 缺句柄 → WireMissing 且点名（不写取件样板、不静默兜底）",
              bool(hit) and "db" in hit and "取件面缺少" in hit, hit)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 4 加成
def t4_bonus():
    print("\n[4] bonus：跨据点合并 / 档域分开 / 上限截断")
    tmp = tempfile.mkdtemp(prefix="outpost_bonus_")
    try:
        db = os.path.join(tmp, "outpost.db")
        clock = Clock(T0)
        wall.set_provider(lambda: float(clock()))
        op, _wire = make_outpost(db, clock)
        for _ in range(4):                           # tide_mill：每次 +3，上限按 3 次算
            run_once(op, clock, "m1", "tide_mill")
        check("★ 到上限后不再涨（min(visits, bonus_max_visits) 在内容侧算）",
              op.bonus.resolve("panel") == 9, op.bonus.resolve("panel"))
        run_once(op, clock, "m1", "salt_vein")       # 另一档域：cap +1
        check("跨据点合并：panel 9 与 cap 1 各归各域",
              op.bonus.resolve("panel") == 9 and op.bonus.resolve("cap") == 1)
        check("空档域 = 0（不是 None）", op.bonus.resolve("cost") == 0)
        check("来源标签 = 据点（可按据点数点）",
              sorted(op.bonus.sources()) == ["site:salt_vein", "site:tide_mill"],
              op.bonus.sources())
        check("sources('panel') 只列本域来源", op.bonus.sources("panel") == ["site:tide_mill"])
        check("snapshot 三档域齐全", op.bonus.snapshot() == {"panel": 9, "cap": 1, "cost": 0},
              op.bonus.snapshot())
        check("访问记录与加成对得上（tide_mill 去了 4 次）",
              op.record("m1", "tide_mill")["visits"] == 4)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 5 形态
def t5_form():
    print("\n[5] ★ 形态：outpost.py ≤100 行 + 零通用机制字样")
    path = os.path.join(_EXAMPLE, "content", "outpost.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    n = len(text.splitlines())
    check(f"content/outpost.py ≤ 100 行（实测 {n} 行）", n <= 100, f"n={n}")
    hits = [f"{i}:{ln.strip()}" for i, ln in enumerate(text.splitlines(), 1)
            if FORM_BAN.search(ln)]
    check("★ 零命中：读表 / 建表 / 取件 / 队列 / 环境变量一行都没写", not hits, hits)

    mods, bad = set(), []
    for node in ast.walk(ast.parse(text, filename=path)):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
    check("五个引擎形状都在 import 面里（不是嘴说用上了）",
          set(SHAPES) <= mods, sorted(mods))
    for m in sorted(mods):
        if m == "game" or m.startswith("game.") or m in ("json", "sqlite3"):
            bad.append(m)
    check("不 import 其他游戏包 / 不 import json / 不 import sqlite3", not bad, bad)
    check("只用引擎通用件 + 扩展包 + 标准库（__future__ / 自己）",
          all(m.startswith("saintess_engine") or m.startswith("ext_") or m == "__future__"
              for m in mods), sorted(mods))


def main():
    print("== 《铆炉回声》据点勘探：闭环 + 引擎形状 ==")
    try:
        for fn in (t1_records, t2_closed_loop, t3_teeth, t4_bonus, t5_form):
            fn()
    finally:
        wall.reset()
    print(f"\n===== 结果：通过 {passed} / 失败 {failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
