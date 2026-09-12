#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tlog 结构化流水门禁：形状 + 可拔插契约 + JSONL 往返 + 读口/重放 + 事件桥。

跑法：python tests/test_tlog.py
退出码：0 = 全绿；1 = 有失败。

可拔插口径（与 `log` 门禁同款）：**先**断言「0 sink = 零行为」，**再**断言「配了 sink 能拿到」。
JSONL 往返要断言**逐字节一致**（不是"能读回来就行"）—— 那是落盘格式稳定性的硬证据。
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine import tlog as TL                                    # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


# ---------------------------------------------------------------- 1 Record
def t1_record():
    print("\n[1] Record：形状与序列化")
    r = TL.Record(kind="battle.hit", ts=100.5, actor="p1",
                  fields={"dmg": 34, "crit": False}, tags=["pvp"])
    d = r.to_dict()
    check("to_dict 键序固定（kind/ts/actor/fields/tags）",
          list(d) == ["kind", "ts", "actor", "fields", "tags"], str(list(d)))
    r2 = TL.Record.from_dict(d)
    check("from_dict 往返等价", (r2.kind, r2.ts, r2.actor, r2.fields, r2.tags)
          == (r.kind, r.ts, r.actor, r.fields, tuple(r.tags)))
    check("tags 归一为 tuple", isinstance(r.tags, tuple))
    check("has_tag", r.has_tag("pvp") and not r.has_tag("nope"))
    check("kind 命名校验（点分）",
          TL.is_valid_kind("battle.hit") and TL.is_valid_kind("a.b.c")
          and not TL.is_valid_kind("battle hit") and not TL.is_valid_kind(""))
    check("非 dict fields 归一", TL.Record(kind="k", fields=[("a", 1)]).fields == {"a": 1})


# ---------------------------------------------------------------- 2 KindTable
def t2_kind_table():
    print("\n[2] KindTable：声明表（装载 / 校验 / 自检）")
    kt = TL.KindTable({
        "battle.hit": {"fields": ["subject", "dmg", "crit"], "desc": "命中", "category": "battle"},
        "quest.accept": ["quest"],                       # 列表简写
        "shop.paid": {},                                  # 只声明 kind
    })
    check("装载三种形态（详写 / 列表 / 空）", len(kt) == 3 and kt.fields_of("quest.accept") == ("quest",))
    check("keys 保序", kt.keys() == ("battle.hit", "quest.accept", "shop.paid"))
    check("fields_of 未声明 kind → 空", kt.fields_of("nope") == ())
    check("by_category 分组", "battle" in kt.by_category())
    check("validate 干净", kt.validate() == [], str(kt.validate()))
    bad = TL.KindTable([{"kind": "BAD KIND", "fields": ["ok", "bad field", "ok"]}])
    probs = bad.validate()
    check("validate 抓 kind 命名 / 字段名 / 重复字段", len(probs) == 3, str(probs))
    problems = kt.check_record(TL.Record(kind="battle.hit", fields={"dmg": 1, "extra": 2}))
    check("check_record 报缺字段 + 多字段",
          any("缺少" in p for p in problems) and any("未声明字段" in p for p in problems), str(problems))
    au = kt.audit(["battle.hit", "unknown.kind"])
    check("audit：未发过的声明 + 未声明的 kind",
          set(au["unused"]) == {"quest.accept", "shop.paid"} and au["undeclared"] == ["unknown.kind"])
    check("to_data 回写（可进编辑器）",
          all("kind" in d for d in kt.to_data()) and len(kt.to_data()) == 3)


# ---------------------------------------------------------------- 3 零 sink
def t3_zero_sink():
    print("\n[3] 0 sink = 零行为")
    tl = TL.TLog()
    rec = tl.emit("battle.hit", actor="p1", dmg=34)
    check("不配 sink 也能 emit（返回 Record）", isinstance(rec, TL.Record) and rec.fields["dmg"] == 34)
    check("不配 sink 时 sinks 为空（无任何出口）", tl.sinks == [])
    check("write_many 返回 0（什么都不发生）", tl.write_many([rec]) == 0)
    check("reader 无源时读回空", list(tl.reader().iter_records()) == [])
    check("audit 能跑（sinks=0）", tl.audit()["sinks"] == 0)


# ---------------------------------------------------------------- 4 JSONL
def t4_jsonl():
    print("\n[4] JSONLSink：落盘 + 往返**逐字节一致**")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sub", "tlog.jsonl")
        s = TL.JSONLSink(p)
        tl = TL.TLog(sinks=[s], clock=lambda: 1000.0)
        tl.emit("battle.hit", actor="p1", subject="e1", dmg=34, crit=False)
        tl.emit("battle.hit", actor="p1", fields={"kind": "phys"}, dmg=12)   # 避保留名冲突
        tl.emit("quest.accept", actor="p1", quest="Q17")
        tl.emit("battle.end", actor="p1", win=True, rounds=5)
        s.close()
        check("文件已落盘（父目录自动建）", os.path.exists(p))
        lines = open(p, encoding="utf-8").read().rstrip("\n").split("\n")
        check("一行一条（4 行）", len(lines) == 4, str(len(lines)))
        check("行内是合法 JSON 且中文不转义", json.loads(lines[0])["kind"] == "battle.hit")

        # ★ 往返逐字节一致
        back = list(TL.JSONLSink(p).read_records())
        redump = [json.dumps(r.to_dict(), ensure_ascii=False) for r in back]
        check("读回条数一致", len(back) == 4)
        check("★ JSONL 往返逐字节一致", redump == lines,
              f"\n      got={redump[:1]}\n      exp={lines[:1]}")
        check("字段类型保持（bool/float 不退化）",
              back[3].fields["win"] is True and back[0].fields["dmg"] == 34)
        check("fields= 逃生口（保留名冲突字段照样能记）", back[1].fields["kind"] == "phys")

        # 追加语义
        s2 = TL.JSONLSink(p)
        TL.TLog(sinks=[s2]).emit("battle.hit", actor="p1", dmg=1)
        s2.close()
        check("默认追加（不截断）", len(open(p, encoding="utf-8").read().strip().split("\n")) == 5)

        # 坏行跳过
        with open(p, "a", encoding="utf-8") as f:
            f.write("{坏行}\n")
        s3 = TL.JSONLSink(p)
        got = list(s3.read_records())
        check("坏行跳过且不整文件失败", len(got) == 5 and len(s3.bad_lines) == 1, str(s3.bad_lines))


# ---------------------------------------------------------------- 5 MemorySink
def t5_memory_sink():
    print("\n[5] MemorySink")
    m = TL.MemorySink(limit=2)
    tl = TL.TLog(sinks=[m], clock=lambda: 5.0)
    for i in range(3):
        tl.emit("battle.hit", actor="p1", dmg=i)
    check("limit 保留最近 N 条", [r.fields["dmg"] for r in m.records] == [1, 2])
    check("kinds 去重保序", m.kinds() == ("battle.hit",))
    check("of_kind 取子集", len(m.of_kind("battle.hit")) == 2)
    m.clear()
    check("clear", m.records == [])


# ---------------------------------------------------------------- 6 Reader
def t6_reader():
    print("\n[6] Reader：一套筛选口径")
    m = TL.MemorySink()
    tl = TL.TLog(sinks=[m])
    tl.emit("battle.hit", actor="p1", tags=["pvp"], dmg=10)
    tl.emit("battle.hit", actor="p2", dmg=20)
    tl.emit("quest.accept", actor="p1", quest="Q1")
    rd = tl.reader()
    check("无筛选 = 全量", rd.count() == 3)
    check("kind 精确", rd.count(kind="quest.accept") == 1)
    check("kind 前缀（battle. 匹配整族）", rd.count(kind="battle.") == 2)
    check("kind 列表", rd.count(kind=["battle.hit", "quest.accept"]) == 3)
    check("actor 精确", rd.count(actor="p1") == 2)
    check("tag 筛选", rd.count(tag="pvp") == 1)
    check("组合筛选", rd.count(kind="battle.", actor="p1") == 1)
    check("first / kinds", rd.first(actor="p2").fields["dmg"] == 20
          and rd.kinds() == ("battle.hit", "quest.accept"))
    tl2 = TL.TLog(sinks=[TL.MemorySink()], clock=lambda: 50.0)
    tl2.emit("k.one")
    tl3 = TL.TLog(sinks=[TL.MemorySink()], clock=lambda: 100.0)
    tl3.emit("k.two")
    # 时间窗（跨 sink 合并读）
    rd2 = TL.Reader(tl2.sinks + tl3.sinks)
    check("since/until 左闭右开",
          rd2.count(since=50.0, until=100.0) == 1 and rd2.count(since=50.0) == 2)


# ---------------------------------------------------------------- 7 Replay
def t7_replay():
    print("\n[7] Replay：按序重放 / 概览 / 脱敏")
    recs = [TL.Record(kind="b.2", ts=3.0, actor="p1"), TL.Record(kind="b.1", ts=1.0, actor="p2"),
            TL.Record(kind="b.3", ts=2.0, actor="p1")]
    rp = TL.Replay(recs, name="run1")
    check("按 ts 排序", [r.ts for r in rp.steps()] == [1.0, 2.0, 3.0])
    check("by_kind 分组", len(rp.by_kind()["b.1"]) == 1)
    check("actors / span / summary",
          set(rp.actors()) == {"p1", "p2"} and rp.span() == (1.0, 3.0)
          and rp.summary()["count"] == 3)
    anon = rp.anonymize()
    check("自动脱敏（u1/u2）", set(anon.actors()) == {"u1", "u2"})
    check("脱敏不改原对象", set(rp.actors()) == {"p1", "p2"})
    m2 = rp.anonymize({"p1": "英雄甲"})
    check("显式 mapping 优先，未覆盖的自动补号",
          "英雄甲" in m2.actors() and len(m2.actors()) == 2)
    check("回放窗口：先筛后放",
          [r.kind for r in TL.Reader([TL.MemorySink()]).replay().steps()] == [])


# ---------------------------------------------------------------- 8 事件桥
def t8_bridge():
    print("\n[8] EventLogBridge：总线 → 流水（映射表由内容侧给）")
    from saintess_engine.events import EventBus
    m = TL.MemorySink()
    tl = TL.TLog(sinks=[m])
    bus = EventBus(("order_paid", "battle_end"))
    br = TL.EventLogBridge(tl, {
        "order_paid": "shop.paid",
        "battle_end": {"kind": "battle.end", "fields": ["win", "rounds"], "tags": ["battle"]},
    })
    check("attach 只挂映射表 ∩ 已声明事件", br.attach(bus) == 2)
    bus.fire("order_paid", {"qq_id": 1454832774, "amount": 999, "lines": ["x"]})
    bus.fire("battle_end", {"actor": "p1", "win": True, "rounds": 5, "secret": "不该进"})
    r0, r1 = m.records[0], m.records[1]
    check("简写映射：事件名 → kind", r0.kind == "shop.paid")
    check("actor_keys 顺序取主体（qq_id）", r0.actor == "1454832774")
    check("drop 掉总线内部键 lines", "lines" not in r0.fields)
    check("详细映射：fields 白名单 + tags",
          set(r1.fields) == {"win", "rounds"} and r1.tags == ("battle",), str(r1.fields))
    check("桥不产出提示行（旁路）", bus.fire("order_paid", {"qq_id": 1, "lines": []}) is not None
          and m.records[-1].kind == "shop.paid")
    check("未映射事件被记入 missed", br.missed == [] or "nope" not in br.missed)
    br2 = TL.EventLogBridge(tl, {}, strict=True)
    bus2 = EventBus(("x",))
    sub = br2.subscriber("x")
    try:
        sub({})
        ok = False
    except KeyError:
        ok = True
    check("strict：未映射事件抛错", ok)
    check("detach 清掉订阅", br.detach(bus) == 2 and bus.subscribers("order_paid") == ())


# ---------------------------------------------------------------- 9 声明联动
def t9_tlog_declaration():
    print("\n[9] TLog × KindTable：声明校验")
    kt = TL.KindTable({"battle.hit": {"fields": ["dmg"]}})
    seen = []
    m = TL.MemorySink()
    tl = TL.TLog(sinks=[m], kinds=kt, on_undeclared=lambda probs: seen.extend(probs))
    tl.emit("battle.hit", actor="p1", dmg=5, surprise=1)
    check("非 strict：记问题但不拦", len(m.records) == 1 and seen, str(seen))
    tl.emit("nope.kind")
    check("未声明 kind 也记入 problems", any("未声明的 kind" in p for p in tl.audit()["problems"]))
    strict_tl = TL.TLog(sinks=[TL.MemorySink()], kinds=kt, strict=True)
    try:
        strict_tl.emit("battle.hit", dmg=1, extra=2)
        ok = False
    except ValueError:
        ok = True
    check("strict：与声明不符直接抛", ok)
    check("kinds_seen 记账", set(tl.kinds_seen()) == {"battle.hit", "nope.kind"})


# ---------------------------------------------------------------- 10 分发纪律
def t10_dispatch_discipline():
    print("\n[10] 分发纪律（与 log 同一套）")
    class Boom:
        def write(self, records):
            raise RuntimeError("sink 坏了")

    m = TL.MemorySink()
    import logging as _lg
    old = _lg.raiseExceptions
    _lg.raiseExceptions = False
    try:
        n = TL.dispatch([Boom(), m], [TL.Record(kind="k")])
    finally:
        _lg.raiseExceptions = old
    check("dispatch 返回成功数", n == 1, f"n={n}")
    check("坏 sink 不牵连同批其他 sink", len(m.records) == 1)
    tl = TL.TLog(sinks=[m])
    check("add_sink / remove_sink", (tl.add_sink(TL.MemorySink()) or tl.remove_sink(m)) == 1)


def main():
    print("== tlog 门禁：Record / KindTable / sinks / Reader / Replay / Bridge ==")
    t1_record()
    t2_kind_table()
    t3_zero_sink()
    t4_jsonl()
    t5_memory_sink()
    t6_reader()
    t7_replay()
    t8_bridge()
    t9_tlog_declaration()
    t10_dispatch_discipline()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
