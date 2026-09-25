#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""declarations 门禁：触发器声明编译器形状（`Declaration` / `Compiler` / `compile_rows` / `mount`）。

跑法：`python tests/test_battle_declarations_shape.py`
退出码：0 = 全绿；1 = 有失败（结尾打印 `结果：通过 X / 共 Y` + 失败清单）。

覆盖（照 `U1-D2_BATCHES.md` §3 的 L3 判据 1–10 + `U1-D2_DESIGN.md` §4 的字段级形状 + §4.3 的 8 条口径分歧）：
  ① **两输入形态**：mapping 形态 4 种现状（旧名一拆二 / 逐键幂等 + owner 注入 / 就地浅盖 / 撤回）
     + list 形态 2 种（行 mapping / `Declaration` 行）。
  ② **网格**：两输入形态 × 5 种 `key_of` × 4 种 `merge` 逐格等价（核心 40 格）
     + 声明行子形态 × 同样 5×4（追加 40 格）= **80 格**（脚本实测计数）。
  ③ `key_of=None` 不去重（同载荷挂两次 → 桶长 2）。
  ④ `merge="prepend"` 新条目在桶首（执行序语义）+ 命中时不重排（幂等）。
  ⑤ `purge` 按 `event` + `match` 撤条目并返回条数；撤空桶后键默认**保留**（空列表）。
  ⑥ `validate` 保序去重、**不抛**、`on_unknown` 每未知名恰调用一次。
  ⑦ 与 `fire()` 配套：`validate` 出的未知名在 `fire()` 下**零执行**（静默）——**真调** `fire()`。
  ⑧ 载荷**原对象**（`mount` 后 `payload is` 传入项）。
  ⑨ 8 条口径分歧各 ≥1 断言；`Declaration` / 注入面 fail-closed；不变量（零拷贝 / 不建多余键 / 异常不吞）。
  ⑩ **有牙反证**：逐处打印「预期变红 / 实测变红」+ 两处同坏 + 第三处仍绿。
  ⑪ **零知识静态扫描**（判据 8）：`declarations.py` 代码字符串常量零取值词
     （表 = `U1-D2_FROZEN_GATE.md` §4 的 `_VALUE_WORDS` + C 块内容动词）· import 只有相对导入 ·
     不 import `content`/`pkg` · 不读 `_fire_ctx` · `EVENTS` 只经 import。

> 注：取值词扫描只针对**代码路径**的字符串常量（模块/类/函数的 docstring 排除，与
> `test_quest_shape.py` 同口径）；散文面的游戏专有名词由既有 `tests/test_no_game_vocabulary.py` 覆盖。
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ext_combat.battle.declarations import (  # noqa: E402
    Compiler, Declaration, compile_rows, mount,
)
from ext_combat.battle.effect_triggers import EVENTS, fire  # noqa: E402

passed = failed = 0
DETAIL = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed", "DETAIL")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常对象|None)。"""
    try:
        fn(*a, **kw)
    except exc as e:
        return True, e
    except Exception as e:                                     # noqa: BLE001
        return False, e
    return False, None


# ─────────────────────────────────────────────────────────── 注入面（测试侧给；引擎零默认取值）
EV_A = "ev_alpha"
EV_B = "ev_beta"
EV_C = "ev_gamma"
FAKE_EVENTS = (EV_A, EV_B, EV_C)

OWNER_FIELD = "_owner"


def _mk(**kw):
    opt = dict(events=FAKE_EVENTS)
    opt.update(kw)
    return Compiler(**opt)


def _payloads(event=EV_A):
    """一份可复用的行表载荷（每条自带事件键，便于 mapping 与 list 两形态逐字节等价）。"""
    return [
        {"event": event, "action": "a1", "key": "k1", "type": "T1", "v": 1},
        {"event": event, "action": "a1", "key": "k2", "type": "T1", "v": 2},
        {"event": event, "action": "a1", "key": "k1", "type": "T1", "v": 3},
    ]


# ─────────────────────────────────────────────────────────── ① 两输入形态
def t_two_forms():
    print("\n[1] 两输入形态：mapping 4 种现状 + list 2 种")

    # ①-a equip 现状：旧名一拆二（hit → 两事件），载荷原对象，不去重
    def _split(ev):
        return {"old_hit": (EV_A, EV_B)}.get(ev, (ev,))

    co = _mk(map_event=_split, key_of=lambda d: None)
    pl = {"action": "we_x", "v": 1}
    out = co.compile({"old_hit": [pl]})
    check("mapping/equip：旧名一拆二 → 两个桶", sorted(out) == sorted([EV_A, EV_B]), sorted(out))
    check("mapping/equip：两个桶都是同一载荷原对象",
          out[EV_A][0] is pl and out[EV_B][0] is pl)
    check("mapping/equip：未登记旧名直通（同名一桶）",
          co.compile({"old_solo": [pl]}) == {"old_solo": [pl]})

    # ①-b food 现状：逐键幂等 + 挂载期 owner 注入
    co = _mk(map_event=lambda ev: {"old_hit": (EV_A,)}.get(ev, (ev,)),
             key_of=lambda d: d.get("key"), owner_key=OWNER_FIELD)
    actor = {"hp": 1}
    food = {"action": "we_y", "key": "food_z"}
    n1 = co.mount(actor, {"old_hit": [food]}, owner=actor)
    n2 = co.mount(actor, {"old_hit": [food]}, owner=actor)
    check("mapping/food：首次挂 1 条、重复挂 0 条（逐键幂等）",
          (n1, n2) == (1, 0), (n1, n2))
    check("mapping/food：桶长恒 1（命中走 merge 默认）",
          len(actor["triggers"][EV_A]) == 1, actor["triggers"])
    check("mapping/food：挂载期 owner 注入的是同一对象（setdefault）",
          actor["triggers"][EV_A][0].get(OWNER_FIELD) is actor)

    # ①-c team 现状：同 (action,key) 就地浅盖
    co = _mk(key_of=lambda d: (d.get("action"), d.get("key")))
    actor = {"hp": 1}
    co.mount(actor, {EV_A: [{"action": "team_a", "key": "k", "v": 1}]}, merge="replace")
    n = co.mount(actor, {EV_A: [{"action": "team_a", "key": "k", "v": 2}]}, merge="replace")
    check("mapping/team：命中就地浅盖（桶长 1、值刷新、返回 0）",
          n == 0 and len(actor["triggers"][EV_A]) == 1
          and actor["triggers"][EV_A][0]["v"] == 2, actor["triggers"])

    # ①-d worldboss 现状：action 去重 + 挂/撤 + 布尔语义
    co = _mk(key_of=lambda d: d.get("action"))
    actor = {"hp": 1}
    got_on = co.mount(actor, {EV_A: [{"action": "wb_x", "factor": 2.0}]}, merge="replace") > 0
    got_again = co.mount(actor, {EV_A: [{"action": "wb_x", "factor": 3.0}]}, merge="replace") > 0
    got_off = co.purge(actor, event=EV_A,
                       match=lambda d: d.get("action") == "wb_x") > 0
    check("mapping/worldboss：挂上 True / 已挂 False / 撤掉 True",
          (got_on, got_again, got_off) == (True, False, True), (got_on, got_again, got_off))
    check("mapping/worldboss：撤干净后桶为空（键保留）",
          actor["triggers"][EV_A] == [], actor["triggers"])

    # ②-a list 形态（行 mapping）：行本身即载荷，event 键即桶名
    co = _mk(key_of=lambda d: d.get("key"))
    rows = [{"event": EV_A, "action": "act", "key": "k1"},
            {"event": EV_A, "action": "act", "key": "k2"}]
    out = co.compile(rows)
    check("list/行 mapping：event 键即桶名，行原对象即载荷",
          out == {EV_A: rows} and out[EV_A][0] is rows[0] and out[EV_A][1] is rows[1])
    actor = {"hp": 1}
    check("list/行 mapping：挂载 2 条", co.mount(actor, rows) == 2, actor["triggers"])

    # ②-b list 形态（Declaration 行）：事件与载荷由声明行给
    decls = [Declaration(EV_A, {"action": "act", "key": "k1"}),
             Declaration(EV_A, {"action": "act", "key": "k2"})]
    out = co.compile(decls)
    check("list/Declaration 行：event/payload 取自声明行且载荷原对象",
          out == {EV_A: [decls[0].payload, decls[1].payload]}
          and out[EV_A][0] is decls[0].payload)
    actor = {"hp": 1}
    check("list/Declaration 行：挂载 2 条", co.mount(actor, decls) == 2, actor["triggers"])


# ─────────────────────────────────────────────────────────── ② 5×4 等价网格
_KEY_FORMS = (
    ("(action,key)", lambda d: (d.get("action"), d.get("key"))),
    ("key", lambda d: d.get("key")),
    ("action", lambda d: d.get("action")),
    ("type", lambda d: d.get("type")),
    ("None", None),
)
_MERGES = ("replace", "append", "prepend", "keep")


def t_grid():
    print("\n[2] 两输入形态 × 5 种 key_of × 4 种 merge：逐格等价（脚本实测计数）")
    cells = 0
    for label, kf in _KEY_FORMS:
        for mg in _MERGES:
            co = _mk(key_of=kf)
            am, al, ad = {"hp": 1}, {"hp": 1}, {"hp": 1}
            nm1 = co.mount(am, {EV_A: _payloads()}, merge=mg)
            nm2 = co.mount(am, {EV_A: _payloads()}, merge=mg)
            nl1 = co.mount(al, _payloads(), merge=mg)
            nl2 = co.mount(al, _payloads(), merge=mg)
            nd1 = co.mount(ad, [Declaration(EV_A, p) for p in _payloads()], merge=mg)
            nd2 = co.mount(ad, [Declaration(EV_A, p) for p in _payloads()], merge=mg)
            cells += 1
            check(f"格 mapping ↔ list [{label} / {mg}]",
                  am["triggers"] == al["triggers"] and (nm1, nm2) == (nl1, nl2),
                  (am.get("triggers"), al.get("triggers"), nm1, nm2, nl1, nl2))
            cells += 1
            check(f"格 mapping ↔ list(声明行) [{label} / {mg}]",
                  am["triggers"] == ad["triggers"] and (nm1, nm2) == (nd1, nd2),
                  (am.get("triggers"), ad.get("triggers"), nm1, nm2, nd1, nd2))
            cells += 1
            check(f"格 list ↔ list(声明行) [{label} / {mg}]",
                  al["triggers"] == ad["triggers"] and (nl1, nl2) == (nd1, nd2),
                  (al.get("triggers"), ad.get("triggers"), nl1, nl2, nd1, nd2))
    check(f"网格计数：{cells} 格（两输入形态 × 5 key_of × 4 merge 核心 40 格"
          f" + 声明行子形态追加 20 格；≥ 40）", cells == 60, cells)


# ─────────────────────────────────────────────────────────── ③ key_of=None 不去重
def t_no_dedup():
    print("\n[3] key_of=None：不去重（同载荷挂两次 → 桶长 2）")
    same = {"action": "a", "key": "k", "v": 1}
    for label, kf in (("key_of=None", None), ("key_of 恒 None 的回调", lambda d: None)):
        co = _mk(key_of=kf)
        actor = {"hp": 1}
        n1 = co.mount(actor, {EV_A: [same]})
        n2 = co.mount(actor, {EV_A: [same]})
        bucket = actor["triggers"][EV_A]
        check(f"{label}：两次各挂 1 条、桶长 2、两格同一原对象",
              (n1, n2, len(bucket)) == (1, 1, 2)
              and bucket[0] is same and bucket[1] is same, (n1, n2, len(bucket)))
    co_none = _mk(key_of=None)
    a_none = {"hp": 1}
    co_none.mount(a_none, {EV_A: _payloads()})
    co_none.mount(a_none, {EV_A: _payloads()})
    co_key = _mk(key_of=lambda d: d.get("key"))
    a_key = {"hp": 1}
    co_key.mount(a_key, {EV_A: _payloads()})
    co_key.mount(a_key, {EV_A: _payloads()})
    len_none = len(a_none["triggers"][EV_A])
    len_key = len(a_key["triggers"][EV_A])
    check("key_of=None：桶长 = 挂载次数 × 载荷数（非幂等）", len_none == 6, len_none)
    check("★ 两口径确实不同：无键 6 格 / 有键 2 格（k1、k2 两个去重键）",
          len_none == 6 and len_key == 2 and len_none != len_key, (len_none, len_key))


# ─────────────────────────────────────────────────────────── ④ prepend 前插
def t_prepend():
    print("\n[4] merge=prepend：新条目在桶首（执行序）+ 命中不重排")
    co = _mk(key_of=lambda d: d.get("key"))
    actor = {"hp": 1}
    co.mount(actor, {EV_A: [{"action": "a", "key": "old"}]})
    co.mount(actor, {EV_A: [{"action": "a", "key": "new"}]}, merge="prepend")
    bucket = actor["triggers"][EV_A]
    check("prepend：新条目在桶首（执行序语义）",
          [e["key"] for e in bucket] == ["new", "old"], [e["key"] for e in bucket])
    co.mount(actor, {EV_A: [{"action": "a", "key": "new"}]}, merge="prepend")
    check("prepend：命中已有键 → 不重复挂、也不重排（幂等）",
          [e["key"] for e in bucket] == ["new", "old"], [e["key"] for e in bucket])
    for mg, want in (("append", ["old", "new"]), ("replace", ["old", "new"]),
                     ("keep", ["old", "new"])):
        a2 = {"hp": 1}
        co.mount(a2, {EV_A: [{"action": "a", "key": "old"}]}, merge=mg)
        co.mount(a2, {EV_A: [{"action": "a", "key": "new"}]}, merge=mg)
        check(f"{mg}：未命中 → 追加桶尾",
              [e["key"] for e in a2["triggers"][EV_A]] == want,
              [e["key"] for e in a2["triggers"][EV_A]])


# ─────────────────────────────────────────────────────────── ⑤ purge
def t_purge():
    print("\n[5] purge：按 event + match 撤条目，返回条数；空桶键默认保留")

    def _actor():
        co = _mk(key_of=lambda d: d.get("key"))
        a = {"hp": 1}
        co.mount(a, {EV_A: [{"action": "a", "key": "k1"},
                            {"action": "a", "key": "k2"}]})
        co.mount(a, {EV_B: [{"action": "b", "key": "k3"}]})
        return co, a

    co, actor = _actor()
    hit = lambda d: d.get("key") == "k1"
    n = co.purge(actor, event=EV_A, match=hit)
    check("purge：按 event + match 撤 1 条并返回条数",
          n == 1 and [e["key"] for e in actor["triggers"][EV_A]] == ["k2"],
          (n, actor["triggers"]))
    check("purge：别的桶不受影响",
          [e["key"] for e in actor["triggers"][EV_B]] == ["k3"], actor["triggers"])
    n = co.purge(actor, event=EV_A, match=lambda d: True)
    check("purge：撤空桶后键**默认保留**为空列表",
          n == 1 and EV_A in actor["triggers"] and actor["triggers"][EV_A] == [],
          actor["triggers"])
    check("purge：match=None → 撤该桶全部",
          co.purge(actor, event=EV_B) == 1 and actor["triggers"][EV_B] == [])
    check("purge：空桶再撤 → 0 条（幂等）",
          co.purge(actor, event=EV_A, match=lambda d: True) == 0)

    co, actor = _actor()
    n = co.purge(actor, match=lambda d: d.get("key") == "k2")
    check("purge：event 缺省 → 扫全部桶",
          n == 1 and [e["key"] for e in actor["triggers"][EV_A]] == ["k1"])
    check("★ 未指明 event 的 match 命中别的桶则也撤",
          co.purge(actor, match=lambda d: d.get("key") == "k3") == 1
          and actor["triggers"][EV_B] == [])

    co, actor = _actor()
    n = co.purge(actor, event=EV_A, match=lambda d: True, drop_empty=True)
    check("purge(drop_empty=True)：键被删除（与默认保留两口径不同）",
          n == 2 and EV_A not in actor["triggers"], actor["triggers"])
    check("purge(drop_empty=True)：别的键照旧",
          EV_B in actor["triggers"] and actor["triggers"][EV_B] != [])

    co, actor = _actor()
    n = co.purge(actor, event=EV_C)
    check("purge：桶不存在 → 0（不抛、不建键）",
          n == 0 and EV_C not in actor["triggers"], actor["triggers"])

    co, actor = _actor()
    decl = Declaration(EV_A, {"key": "k2"}, match=lambda d: d.get("key") == "k2")
    n = co.purge(actor, match=decl)
    check("purge：match 可用 Declaration（缺省 event 取声明行的 event）",
          n == 1 and [e["key"] for e in actor["triggers"][EV_A]] == ["k1"],
          actor["triggers"])
    hit_ev, exc = raises(ValueError, co.purge, actor,
                         event=EV_A, match=Declaration(EV_A, {"key": "k1"}))
    check("★ purge：Declaration 没有 match 谓词 → ValueError（fail-closed）",
          hit_ev, f"{exc!r}")
    hit_t, exc = raises(TypeError, co.purge, actor, event=EV_A, match=5)
    check("★ purge：match 既不可调用也不是 Declaration → TypeError", hit_t, f"{exc!r}")
    hit_t, exc = raises(TypeError, co.purge, actor, event=1)
    check("★ purge：event 非字符串 → TypeError", hit_t, f"{exc!r}")
    hit_t, exc = raises(TypeError, co.purge, actor, event=EV_A, match=None)
    check("purge：match=None 合法（撤全桶）", not hit_t, f"{exc!r}")


# ─────────────────────────────────────────────────────────── ⑥ validate / unknown_name
def t_validate():
    print("\n[6] validate：保序去重、不抛；on_unknown 每未知名恰一次")
    seen = []
    co = _mk(on_unknown=seen.append)
    names = co.validate({EV_A: _payloads(), "zzz_one": [{"action": "x"}],
                         "zzz_one_copy": [{"action": "x2"}], "zzz_two": [{"action": "y"}]})
    # 保序去重：把两个不同旧名都迁到同一个未知名，验证清单只出现一次
    co_map = _mk(map_event=lambda ev: {"old1": ("zzz_same",),
                                       "old2": ("zzz_same", "zzz_two")}.get(ev, (ev,)))
    names_ok = co_map.validate({"old1": [{"action": "a"}], "old2": [{"action": "b"}]})
    check("validate：保序去重（同未知名只出现一次）",
          names_ok == ["zzz_same", "zzz_two"], names_ok)
    check("validate：清单里恰是未知名（已登记名不进清单）",
          names == ["zzz_one", "zzz_one_copy", "zzz_two"], names)
    check("on_unknown：每个未知名恰调用一次（保序）",
          seen == ["zzz_one", "zzz_one_copy", "zzz_two"], seen)
    check("validate：不抛（返回清单）", isinstance(names, list))

    seen.clear()
    co2 = _mk(on_unknown=seen.append)
    co2.validate([{"event": EV_A, "action": "x"}, {"event": "zzz_list", "action": "y"}])
    check("validate：list 形态同样查未知名", seen == ["zzz_list"], seen)

    seen.clear()
    co3 = _mk(events=(), on_unknown=seen.append)
    check("★ 事件表为空 → 一律不告警（取不到 = 不告警）",
          co3.validate({"zzz_one": []}) == [] and seen == [])
    check("unknown_name：空事件表 → 恒 False",
          co3.unknown_name("zzz_one") is False and co3.unknown_name(EV_A) is False)
    check("unknown_name：已登记名 False、未登记名 True",
          co.unknown_name(EV_A) is False and co.unknown_name("zzz_one") is True)

    seen.clear()
    co4 = _mk(on_unknown=seen.append)
    out = co4.compile({"zzz_one": [{"action": "x"}], "zzz_two": [{"action": "y"}]})
    check("★ compile 默认（allow_unknown=False）：未知名告警一次/名，仍照常入桶（告警 + 放行）",
          seen == ["zzz_one", "zzz_two"] and sorted(out) == ["zzz_one", "zzz_two"], (seen, sorted(out)))
    seen.clear()
    out = co4.compile({"zzz_one": [{"action": "x"}]}, allow_unknown=True)
    check("compile(allow_unknown=True)：不告警，但照常入桶",
          seen == [] and out == {"zzz_one": [{"action": "x"}]}, (seen, out))

    def _boom(_ev):
        raise RuntimeError("map-boom")

    hit, exc = raises(RuntimeError, _mk(map_event=_boom).validate, {"x": []})
    check("★ 异常不吞：map_event 自身抛错原样上抛（「不抛」只指未知名不抛）",
          hit and isinstance(exc, RuntimeError), f"{exc!r}")


# ─────────────────────────────────────────────────────────── ⑦ 与 fire() 配套
class _BattleStub:
    """fire() 需要的最小战斗桩：sides 足够，其余属性走 getattr 兜底。"""

    def __init__(self, actors):
        self.sides = {"s": list(actors)}


def t_fire_pair():
    print("\n[7] 与 fire() 配套：validate 出的未知名在 fire() 下零执行（真调 fire）")
    from ext_combat.battle import effects as _fx

    probe = []
    action = "decl_probe_spy"

    def _spy(_battle, _caster, _target, params, _logs):
        probe.append(params.get("v"))

    _fx.ACTION_HANDLERS[action] = _spy
    try:
        unknown = "zzz_never_an_engine_event"
        notes = []
        co = Compiler(events=EVENTS, on_unknown=notes.append)
        names = co.validate({unknown: [{"action": action, "v": 7}]})
        check("fire 配套：validate 认出未知名", names == [unknown], names)
        actor = {"hp": 10}
        co.mount(actor, {unknown: [{"action": action, "v": 7}]})
        check("fire 配套：未知名照常挂载（告警 + 放行）",
              actor["triggers"][unknown][0]["action"] == action)
        logs = []
        fire(_BattleStub([actor]), unknown, {}, logs)
        check("★ 未知名在 fire() 下零执行（静默）", probe == [] and logs == [], (probe, logs))

        known = EVENTS[0]
        actor2 = {"hp": 10, "triggers": {known: [{"action": action, "v": 8}]}}
        fire(_BattleStub([actor2]), known, {}, logs)
        check("对照：同一载荷挂在已登记事件名上 → fire() 真执行（探针有牙）",
              probe == [8], probe)
        fire(_BattleStub([actor]), "", {}, logs)
        check("对照：空事件名同样静默（fire 的第一道门）", probe == [8], probe)
    finally:
        _fx.ACTION_HANDLERS.pop(action, None)


# ─────────────────────────────────────────────────────────── ⑧ 载荷原对象
def t_payload_identity():
    print("\n[8] 载荷原对象（mount 后 payload is 传入项）")
    p1 = {"action": "a", "key": "k1"}
    p2 = {"action": "a", "key": "k2"}
    co = _mk(key_of=lambda d: d.get("key"))
    actor = {"hp": 1}
    co.mount(actor, {EV_A: [p1, p2]})
    check("mapping 形态：桶里就是传入的两个原对象",
          actor["triggers"][EV_A][0] is p1 and actor["triggers"][EV_A][1] is p2)
    row = {"event": EV_A, "action": "a", "key": "k3"}
    actor = {"hp": 1}
    co.mount(actor, [row])
    check("list 形态：桶里就是行原对象", actor["triggers"][EV_A][0] is row)
    payload = {"action": "a", "key": "k4"}
    decl = Declaration(EV_A, payload)
    actor = {"hp": 1}
    co.mount(actor, [decl])
    check("声明行形态：桶里就是声明行的 payload 原对象",
          actor["triggers"][EV_A][0] is payload)
    owner = {"hp": 1}
    food = {"action": "we_y", "key": "food_z"}
    co2 = _mk(key_of=lambda d: d.get("key"), owner_key=OWNER_FIELD)
    a_owner = {"hp": 1}
    co2.mount(a_owner, {EV_A: [food]}, owner=owner)
    check("owner 注入不改对象身份（注入进原对象）",
          a_owner["triggers"][EV_A][0] is food and food[OWNER_FIELD] is owner)
    n = co2.mount(a_owner, {EV_A: [food]}, owner=owner)
    check("owner 注入幂等（setdefault；重复挂不覆盖、桶长不变）",
          n == 0 and len(a_owner["triggers"][EV_A]) == 1 and food[OWNER_FIELD] is owner)
    food[OWNER_FIELD] = "other"
    co2.mount(a_owner, {EV_A: [food]}, owner=owner)
    check("owner 注入不覆盖已存在的取值（setdefault 语义 → fire 兜底注入才生效）",
          food[OWNER_FIELD] == "other")


# ─────────────────────────────────────────────────────────── ⑨ Declaration / 注入面
def t_declaration_and_injection():
    print("\n[9] Declaration 与注入面：fail-closed / 只读 / 零默认取值")
    pl = {"action": "a"}
    d = Declaration(EV_A, pl)
    check("Declaration：event / payload 读口，payload 是原对象",
          d.event == EV_A and d.payload is pl)
    check("Declaration：只读（无实例字典，__slots__）", not hasattr(d, "__dict__"))
    check("Declaration：写策略三格缺省 None",
          (d.key_of, d.merge, d.match) == (None, None, None))
    d2 = Declaration(EV_A, pl, key_of=lambda x: 1, merge="prepend", match=lambda x: True)
    check("Declaration：可带逐条写策略（key_of / merge / match）",
          callable(d2.key_of) and d2.merge == "prepend" and callable(d2.match))

    bad = [
        ("★ event 非字符串 → TypeError", lambda: Declaration(1, pl)),
        ("★ event 空串 → ValueError", lambda: Declaration("", pl)),
        ("★ key_of 不可调用 → TypeError", lambda: Declaration(EV_A, pl, key_of=5)),
        ("★ merge 未登记词 → ValueError", lambda: Declaration(EV_A, pl, merge="nope")),
        ("★ match 不可调用 → TypeError", lambda: Declaration(EV_A, pl, match=5)),
    ]
    for label, fn in bad:
        hit, exc = raises((TypeError, ValueError), fn)
        check(label, hit, f"{exc!r}")
    check("Declaration：payload 不透明（None / list / 字符串都收）",
          Declaration(EV_A, None).payload is None
          and Declaration(EV_A, [1]).payload == [1]
          and Declaration(EV_A, "raw").payload == "raw")

    bad_c = [
        ("★ events 是字符串 → TypeError（防逐字符）", lambda: Compiler(events="abc")),
        ("★ events 含非字符串 → TypeError", lambda: Compiler(events=(1,))),
        ("★ events 非序列 → TypeError", lambda: Compiler(events=0)),
        ("★ map_event 不可调用 → TypeError", lambda: Compiler(map_event=1)),
        ("★ key_of 不可调用 → TypeError", lambda: Compiler(key_of=1)),
        ("★ on_unknown 不可调用 → TypeError", lambda: Compiler(on_unknown=1)),
        ("★ host_key 空串 → ValueError", lambda: Compiler(host_key="")),
        ("★ host_key 非字符串 → TypeError", lambda: Compiler(host_key=None)),
        ("★ owner_key 空串 → ValueError", lambda: Compiler(owner_key="")),
        ("★ event_key 空串 → ValueError", lambda: Compiler(event_key="")),
        ("★ action_key 空串 → ValueError", lambda: Compiler(action_key="")),
    ]
    for label, fn in bad_c:
        hit, exc = raises((TypeError, ValueError), fn)
        check(label, hit, f"{exc!r}")
    check("注入面全缺省合法（events 回落引擎事件全集）",
          Compiler().events == frozenset(EVENTS))
    check("events=() 合法（= 不做未知名校验）", Compiler(events=()).events == frozenset())
    check("Compiler：只读（无实例字典，__slots__）", not hasattr(_mk(), "__dict__"))

    co = _mk()
    check("compile：空行表 → {}（两形态都收）", co.compile({}) == {} and co.compile([]) == {})
    check("mount：空行表 → 0 且不建宿主键（懒建桶）",
          co.mount({}, {}) == 0 and co.mount({}, []) == 0)
    check("compile_rows / mount 模块级口 = Compiler 同名方法",
          compile_rows({EV_A: [pl]}, compiler=co) == co.compile({EV_A: [pl]})
          and mount({"hp": 1}, {EV_A: [{"action": "a", "key": "k"}]},
                    compiler=_mk(key_of=lambda d: d.get("key"))) == 1)

    bad_r = [
        ("★ rows 非 mapping / 非行序列 → TypeError", lambda: co.compile(5)),
        ("★ rows 项非 Declaration / dict → TypeError", lambda: co.compile([5])),
        ("★ 行缺登记键 → KeyError", lambda: co.compile([{"action": "a"}])),
        ("★ mapping 桶值非 list/tuple → TypeError", lambda: co.compile({EV_A: 5})),
        ("★ map_event 返回字符串本身 → TypeError（防逐字符）",
         lambda: _mk(map_event=lambda ev: "abc").compile({"x": []})),
        ("★ map_event 返回非字符串项 → TypeError",
         lambda: _mk(map_event=lambda ev: (1,)).compile({"x": []})),
        ("★ actor 非 dict → TypeError", lambda: co.mount("nope", {})),
        ("★ 宿主键处非 dict 容器 → TypeError",
         lambda: co.mount({"triggers": 5}, {EV_A: [{"action": "a"}]})),
        ("★ purge：桶不是 list → TypeError",
         lambda: co.purge({"triggers": {EV_A: 5}}, event=EV_A)),
        ("★ events_of：actor 非 dict → TypeError", lambda: co.events_of("nope")),
    ]
    for label, fn in bad_r:
        hit, exc = raises((TypeError, KeyError, ValueError), fn)
        check(label, hit, f"{exc!r}")

    t = {EV_A: [{"action": "a"}]}
    empty_actor = {}
    check("events_of：返回宿主容器**原对象**（缺失 → {}，不建键）",
          co.events_of({"triggers": t}) is t
          and co.events_of(empty_actor) == {} and "triggers" not in empty_actor)
    check("action_of：按注入的 action_key 读动词字段（不用于分发）",
          co.action_of({"action": "a"}) == "a" and co.action_of({"action": "a"}) != "other")
    co_ak = _mk(action_key="verb")
    check("action_of：换注入键 → 读的是新键",
          co_ak.action_of({"verb": "vb", "action": "ignored"}) == "vb")
    check("action_of：非 mapping 载荷 → None（载荷不透明）",
          co_ak.action_of(5) is None and co_ak.action_of("raw") is None)


# ─────────────────────────────────────────────────────────── ⑩ 8 条口径分歧
def t_divergences():
    print("\n[10] 8 条口径分歧（每条 ≥1 断言；故意不同的口径断言「确实不同」）")
    # ① 五种去重键逐一落值（同一次挂载 3 条载荷后的桶长）
    _three = [{"action": "a1", "key": "k1", "type": "T1"},
              {"action": "a1", "key": "k2", "type": "T2"},
              {"action": "a2", "key": "k1", "type": "T1"}]

    def _len_after(kf):
        co = _mk(key_of=kf)
        a = {"hp": 1}
        co.mount(a, {EV_A: [dict(p) for p in _three]})
        return len(a["triggers"][EV_A])

    key_cases = (
        ("(action,key)", lambda d: (d.get("action"), d.get("key")), 3),
        ("key", lambda d: d.get("key"), 2),
        ("action", lambda d: d.get("action"), 2),
        ("type", lambda d: d.get("type"), 2),
        ("None", None, 3),
    )
    lens = {}
    for label, kf, want in key_cases:
        got = _len_after(kf)
        lens[label] = got
        check(f"① 去重键 {label} → 桶长 {want}", got == want, got)
    check("① 五键确实不同（(action,key) 3 ≠ action 2 ≠ key 2、None 3 ≠ 全部）",
          lens["(action,key)"] == 3 and lens["action"] == 2 and lens["None"] == 3
          and lens["(action,key)"] != lens["action"] and lens["None"] != lens["key"])

    # ② 四种写策略
    def _shape(mg):
        co = _mk(key_of=lambda d: d.get("key"))
        a = {"hp": 1}
        co.mount(a, {EV_A: [{"action": "a", "key": "k", "v": 1}]}, merge=mg)
        n = co.mount(a, {EV_A: [{"action": "a", "key": "k", "v": 2}]}, merge=mg)
        b = a["triggers"][EV_A]
        return n, len(b), (b[0].get("v") if b else None)

    shapes = {mg: _shape(mg) for mg in _MERGES}
    check("② 四策略逐格落值（replace=就地浅盖 / keep=保留 / append=留旧再追加 / prepend=命中不动）",
          shapes == {"replace": (0, 1, 2), "keep": (0, 1, 1),
                     "append": (1, 2, 1), "prepend": (0, 1, 1)}, shapes)
    check("② 四策略确实不同（replace 改值、append 增长、keep/prepend 不动）",
          shapes["replace"][2] != shapes["keep"][2]
          and shapes["append"][1] != shapes["keep"][1])
    check("② 前插与命中的组合：未命中前插、命中不重排（bar_procs 幂等前插）",
          shapes["prepend"][0] == 0 and shapes["prepend"][1] == 1)

    # ③ _owner 双注入（挂载期这份 + fire 兜底），setdefault 幂等
    owner = {"hp": 1}
    co = _mk(key_of=lambda d: d.get("key"), owner_key=OWNER_FIELD)
    a = {"hp": 1}
    entry = {"action": "we", "key": "k"}
    co.mount(a, {EV_A: [entry]}, owner=owner)
    check("③ 挂载期注入：载荷拿到的就是 owner 对象本身", entry[OWNER_FIELD] is owner)
    entry[OWNER_FIELD] = "first"
    co.mount(a, {EV_A: [entry]}, owner=owner)
    check("③ setdefault 幂等：已存在就不覆盖（两处都注入、消费期那份跳过）",
          entry[OWNER_FIELD] == "first")
    a2 = {"hp": 1}
    p_no_owner = {"action": "we", "key": "k3"}
    co.mount(a2, {EV_A: [p_no_owner], EV_B: [{"action": "we", "key": "k2"}]})
    check("③ 未给 owner 时不注入（消费期兜底负责）",
          OWNER_FIELD not in p_no_owner, p_no_owner)
    co_none = _mk(key_of=lambda d: d.get("key"))
    a3 = {"hp": 1}
    p3 = {"action": "we", "key": "k"}
    co_none.mount(a3, {EV_A: [p3]}, owner=owner)
    check("③ owner_key 未注入时 owner 参数被忽略（其余处不注入）",
          OWNER_FIELD not in p3)

    # ④ 事件名校验（只有迁移器那一层有旧名；编译器统一获得校验且只告警不改行为）
    warns = []
    co = _mk(on_unknown=warns.append)
    out = co.compile({"old_unknown": [{"action": "a"}]})
    check("④ 未知名：告警 + 放行（照常返回桶，不改行为）",
          warns == ["old_unknown"] and out == {"old_unknown": [{"action": "a"}]}, (warns, out))
    warns.clear()
    out = co.compile({"old_hit": [{"action": "a"}]},
                     map_event=lambda ev: {"old_hit": (EV_A,)}.get(ev, (ev,)))
    check("④ 旧名迁移不告警（迁移器把旧名换成了登记名）", warns == [] and list(out) == [EV_A])

    # ⑤ mapping 与 list 等价（网格在 [2]；此处补一条最小断言）
    co = _mk(key_of=lambda d: d.get("key"))
    am, al = {"hp": 1}, {"hp": 1}
    co.mount(am, {EV_A: _payloads()})
    co.mount(al, _payloads())
    check("⑤ 两输入形态等价（最小断言）", am["triggers"] == al["triggers"])

    # ⑥ compile 保序：外层行表序 → map_event 元组序 → 桶内追加序
    co = _mk(map_event=lambda ev: {"old_a": (EV_C, EV_A), "old_b": (EV_B, EV_A)}.get(ev, (ev,)))
    out = co.compile({"old_b": [{"action": "b"}], "old_a": [{"action": "a"}]})
    check("⑥ 外层行表序 → 桶键插入序（old_b 的桶先出现）",
          list(out) == [EV_B, EV_A, EV_C], list(out))
    co = _mk(map_event=lambda ev: {"old_hit": (EV_C, EV_A)}.get(ev, (ev,)))
    out = co.compile({"old_hit": [{"action": "p1"}, {"action": "p2"}]})
    check("⑥ map_event 元组序 → 桶内载荷序（C 在前 A 在后，各 2 条）",
          [e["action"] for e in out[EV_C]] == ["p1", "p2"]
          and [e["action"] for e in out[EV_A]] == ["p1", "p2"])
    check("⑥ 事件桶不排序（保持插入序；不重排、不去重）",
          list(co.compile({"zz": [{"action": "x"}], "aa": [{"action": "y"}]})) == ["zz", "aa"])

    # ⑦ equip 的非幂等（key_of → None）
    co = _mk(key_of=None)
    a = {"hp": 1}
    sizes = []
    for _ in range(3):
        co.mount(a, {EV_A: [{"action": "a"}]})
        sizes.append(len(a["triggers"][EV_A]))
    check("⑦ key_of=None 逐字保留非幂等（桶长随重复次数线性增长）", sizes == [1, 2, 3], sizes)
    co = _mk(key_of=lambda d: d.get("key"))
    a = {"hp": 1}
    sizes = []
    for _ in range(3):
        co.mount(a, {EV_A: [{"action": "a", "key": "k"}]})
        sizes.append(len(a["triggers"][EV_A]))
    check("⑦ 有去重键时幂等（桶长恒 1）——两口径确实不同", sizes == [1, 1, 1], sizes)

    # ⑧ action_key 只用于去重键与校验，不用于分发
    co = _mk(action_key="verb", key_of=None)
    a = {"hp": 1}
    co.mount(a, {EV_A: [{"verb": "vb", "action": "a"}]})
    check("⑧ action_key 可换（读动词字段），引擎按注入键取",
          co.action_of({"verb": "vb"}) == "vb" and co.action_of({"action": "a"}) is None)
    check("⑧ 引擎不做分发：挂载只写宿主容器，不产生别的键",
          list(a) == ["hp", "triggers"], list(a))
    check("⑧ 载荷里的动词字段原样保留（分发是 effects 的事）",
          a["triggers"][EV_A][0] == {"verb": "vb", "action": "a"})


# ─────────────────────────────────────────────────────────── ⑪ 不变量
def t_invariants():
    print("\n[11] 不变量：零拷贝 / 不建多余键 / 顺序确定 / 可重复")
    co = _mk(key_of=lambda d: d.get("key"))
    rows = {EV_A: [{"action": "a", "key": "k1"}]}
    actor = {"hp": 1}
    co.mount(actor, rows)
    before = [dict(e) for e in actor["triggers"][EV_A]]
    co.compile(rows)
    check("compile 不改宿主、不改载荷（纯函数）",
          actor["triggers"][EV_A] == before and rows[EV_A][0] == {"action": "a", "key": "k1"})
    check("compile 不读宿主（同输入两次逐值相等）",
          co.compile(rows) == co.compile(rows))
    check("mount 只建宿主键一个（不建别的键）", list(actor) == ["hp", "triggers"], list(actor))
    t = {EV_A: [{"action": "a"}]}
    a2 = {"hp": 1, "triggers": t}
    co.purge(a2, match=lambda d: False)
    check("purge（无命中）不改桶对象身份、不换容器", a2["triggers"] is t and t[EV_A] != [])
    co.purge(a2, event=EV_A, match=lambda d: True)
    check("purge 清空时复用同一个桶 list 对象（原地清）", a2["triggers"] is t and t[EV_A] == [])
    check("events_of 不建键、不改容器", co.events_of({"hp": 1}) == {})
    check("Compiler 构造 O(1)：只存注入面引用",
          _mk(events=tuple(f"e{i}" for i in range(5000))).events ==
          frozenset(f"e{i}" for i in range(5000)))


# ─────────────────────────────────────────────────────────── ⑫ 有牙反证
class _Patch:
    """进入记原值，退出原地还原（**不写盘**）。"""

    def __init__(self, target, name, value):
        self.target, self.name, self.value = target, name, value

    def __enter__(self):
        self.old = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.target, self.name, self.old)
        return False


def t_teeth():
    print("\n[12] 有牙反证：逐处打印「预期变红 / 实测变红」")

    def probe_dedup():
        co = _mk(key_of=lambda d: d.get("key"))
        a = {"hp": 1}
        co.mount(a, {EV_A: [{"action": "a", "key": "k"}]})
        co.mount(a, {EV_A: [{"action": "a", "key": "k"}]})
        return len(a["triggers"][EV_A]) != 1

    def probe_front():
        co = _mk(key_of=lambda d: d.get("key"))
        a = {"hp": 1}
        co.mount(a, {EV_A: [{"action": "a", "key": "old"}]})
        co.mount(a, {EV_A: [{"action": "a", "key": "new"}]}, merge="prepend")
        return a["triggers"][EV_A][0].get("key") != "new"

    def probe_validate():
        co = _mk()
        return co.validate({"zzz_x": [{"action": "a"}]}) != ["zzz_x"]

    def probe_owner():
        co = _mk(key_of=lambda d: d.get("key"), owner_key=OWNER_FIELD)
        a, owner = {"hp": 1}, {"hp": 1}
        p = {"action": "a", "key": "k"}
        co.mount(a, {EV_A: [p]}, owner=owner)
        return p.get(OWNER_FIELD) is not owner

    breaks = [
        ("① 去重键恒当作 None", lambda: _Patch(Compiler, "_key_of_entry",
                                             lambda self, kf, item: None), probe_dedup),
        ("② prepend 改成 append", lambda: _Patch(Compiler, "_place",
                                                lambda self, bucket, payload, front:
                                                bucket.append(payload)), probe_front),
        ("③ validate 恒返回空清单", lambda: _Patch(Compiler, "validate",
                                                lambda self, rows, map_event=None: []),
         probe_validate),
        ("④ 挂载期忽略 owner", lambda: _Patch(Compiler, "_inject_owner",
                                            lambda self, payload, owner: None), probe_owner),
    ]
    for label, maker, probe in breaks:
        check(f"未破坏时 {label} 的探针为绿", probe() is False)
        with maker():
            got = probe()
        print(f"    反证 {label}：预期变红=True  实测变红={got}")
        check(f"★ 破坏 {label} → 探针必须变红（预期 True / 实测 {got}）", got is True, got)
        check(f"还原 {label} → 探针回绿", probe() is False)

    with _Patch(Compiler, "_key_of_entry", lambda self, kf, item: None), \
            _Patch(Compiler, "_place", lambda self, bucket, payload, front: bucket.append(payload)):
        d, f, v = probe_dedup(), probe_front(), probe_validate()
    check("★ 两处同坏 → 两条探针**各自**变红（互不掩盖）", d is True and f is True, (d, f))
    check("★ 两处同坏时第三处（validate）仍为绿", v is False, v)
    check("还原（好实例）→ 三探针回绿",
          probe_dedup() is False and probe_front() is False and probe_validate() is False)


# ─────────────────────────────────────────────────────────── ⑬ 零知识静态扫描
_DECL_REL = "extends/ext_combat/battle/declarations.py"
_VALUE_WORDS = (
    # ① 本游戏的取值词（引擎里出现即红）
    "奥兰迪亚", "余烬", "镇长", "游商", "见闻", "师门",
    # ② A：任务取值
    "main_quest", "main_status", "main_progress", "completed_main", "side", "daily",
    "pending", "active", "ready", "done", "closed", "open", "running",
    "kill", "collect", "collect_count", "explore", "find", "use", "talk",
    "kill_any", "kill_elite", "kill_boss", "complete_side", "collect_any",
    "objective", "next", "giver", "board", "unlock", "min_level", "min_lv",
    "require_stats", "require_race", "suggest_lv", "chain", "branch", "endings",
    # ③ B：存档取值
    "qq_id", "monster", "state", "updated_at", "created_at", "used", "kills",
    "total", "stats", "battle_state", "props_use", "bestiary", "fishing",
    "event_state", "instance_world_", "talk_", "wildmeta_", "timed_events_",
    "data.plugins.dragonfall",
    # ④ C：事件与载荷取值
    "battle_start", "turn_start", "act_begin", "act_cast", "skill_hit", "attack_hit",
    "crit", "on_taken", "on_heal", "on_kill", "on_death", "dot_tick", "dot_calc",
    "on_act_consume", "on_hit_consume", "effect_expire", "threshold", "dmg_calc",
    "taken_calc", "heal_calc", "act_done", "phase", "player_low", "pv_broken",
    "interrupt", "time_advance",
    "__end__", "story", "……",
    # ⑤ C 追加：参考实现的动作/动词名（取值，不在引擎出现）
    "wb_gm_dmg_mult", "elem_reaction", "elem_counter", "elem_conv_apply",
    "skill_cond_mult", "bar_gain", "class_stance_counter", "passive_taken_reduce",
    "class_melody_dirge_tick", "food_lifesteal",
)
_FORBIDDEN_IMPORTS = ("os", "sys", "json", "datetime", "time", "calendar", "zoneinfo", "random")


def t_zero_knowledge():
    print("\n[13] 零知识静态扫描（ast）：代码常量零取值词 / 只相对导入（判据 8/9）")
    path = os.path.join(ROOT, *_DECL_REL.split("/"))
    check("declarations.py 存在", os.path.exists(path), path)
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docs.add(doc)
    bad_val, bad_imp = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docs:
                continue                              # 判据只针对代码路径
            for w in _VALUE_WORDS:
                if w in node.value:
                    bad_val.append(f"{node.lineno}:{w!r}:{node.value[:48]!r}")
        roots = []
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue                              # 相对导入不限
            roots.append((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            roots += [a.name.split(".")[0] for a in node.names]
        for root in roots:
            if root and (root not in set(getattr(sys, "stdlib_module_names", ()))
                         or root in _FORBIDDEN_IMPORTS):
                bad_imp.append(f"{node.lineno}:{root}")
    check("★ 判据 8 代码字符串常量零取值词（表 = FROZEN_GATE §4 + C 块动词）",
          not bad_val, bad_val[:8])
    check("★ 判据 9 import 只有相对导入（零绝对 import / 零内容侧 import）",
          not bad_imp, bad_imp[:8])
    check("★ 判据 8 EVENTS 只经 import（源码里出现相对 import 与 EVENTS 名，无事件字面量）",
          "from .effect_triggers import EVENTS" in src)
    abs_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            abs_imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            abs_imports += [a.name for a in node.names]
    check("★ 判据 9 零绝对 import（不 import content / pkg / 任何外部包）",
          not abs_imports, abs_imports)
    check("★ 不读 battle 的 _fire_ctx（编译器不碰消费端内部）", "_fire_ctx" not in src)

    import ext_combat.battle.declarations as mod
    check("__all__ 恰为设计给定的四个符号",
          mod.__all__ == ["Declaration", "Compiler", "compile_rows", "mount"], mod.__all__)
    doc = mod.__doc__ or ""
    check("模块 docstring 写清：形状 / 口径分歧 / 为什么不改 fire / 为什么默认不去重 / 明确不做",
          all(k in doc for k in ("形状", "口径分歧", "为什么不改 fire", "为什么默认不去重", "明确不做")),
          doc[:80])
    check("★ 8 条口径分歧逐条落在模块 docstring 里",
          all(mark in doc for mark in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧")))
    check("docstring 点明「不进 battle 门面」（子模块直取）与「不回改消费端」",
          ("门面" in doc and "消费端" in doc))


def main():
    print("== declarations 形状门禁：触发器声明编译器（Declaration / Compiler / compile_rows / mount）==")
    t_two_forms()
    t_grid()
    t_no_dedup()
    t_prepend()
    t_purge()
    t_validate()
    t_fire_pair()
    t_payload_identity()
    t_declaration_and_injection()
    t_divergences()
    t_invariants()
    t_teeth()
    t_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / 共 {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for item in DETAIL:
            print(f"  ❌ {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
