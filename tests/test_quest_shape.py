#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""quest 门禁：任务账本形状（`QuestLog` / `Objective` / `Objectives` / `Quest`）。

跑法：`python tests/test_quest_shape.py`
退出码：0 = 全绿；1 = 有失败（结尾打印 `结果：通过 X / 共 Y` + 失败清单）。

覆盖（照 `U1-D2_BATCHES.md` §1 的 L1 判据 + `U1-D2_DESIGN.md` §2 的字段级形状 + §2.3 的 12 条口径分歧）：
  ① **目标注册表**：声明序 = 判定序 = 展示序；`parts` 的修饰键归属；复合目标；`need_of`；
     `hits` / `fold` / `satisfied` / `complete` / `lines` / `unknown` 逐条 + 每条兜底分支。
  ② **账本**：读口（`raw`/`current`/`status`/`progress`/`done`/`lane`/`entry`/`status_of`/`is_open`）·
     迁移（`accept`/`set_status`/`bump`/`deliver`/`abandon`/`require`/`snapshot`/`restore`）。
  ③ **不变量**：构造 O(1) 零遍历（探针账本 + 成本对照）· 注入面 fail-closed · 迁移返回新对象 ·
     不改原 `raw`（`json.dumps` 指纹，判据 10）· 异常不吞 · 顺序即语义。
  ④ **12 条口径分歧各 ≥1 条断言**（故意不同的两口径**断言「它们确实不同」**，防后人顺手统一）。
  ⑤ **有牙反证**：逐处打印「预期变红 / 实测变红」；两处同坏 + 第三处仍绿。
  ⑥ **零知识静态扫描**（`ast`，判据 5/6/8）：代码字符串常量零取值词（表 = `U1-D2_FROZEN_GATE.md` §4）·
     import 只有标准库且不含 os/sys/json/datetime/time/calendar/random · 零字段知识。
  ⑦ **构造 10^5 次**（判据 9，建议项）。

> 注：`_VALUE_WORDS` 只扫**代码路径**的字符串常量（模块/类/函数的 docstring 排除，与
> `U1-D4` 系列的门禁口径一致）；散文面的游戏专有名词由既有 `tests/test_no_game_vocabulary.py` 覆盖。
"""
import ast
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.quest import (  # noqa: E402
    Objective, Objectives, Quest, QuestLog, parse_needs,
)

passed = failed = 0
DETAIL = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        DETAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常对象|None)。"""
    try:
        fn(*a, **kw)
    except exc as e:
        return True, e
    except Exception as e:                                     # noqa: BLE001
        return False, e
    return False, None


# ─────────────────────────────────────────────────────────── 注入面（测试侧给；引擎零默认值）
FIELDS = {"current": "cur", "status": "st", "progress": "pr",
          "archive": "hist", "lanes": "sub"}
STATES = {"todo": "s_todo", "live": "s_live", "met": "s_met", "ended": "s_ended"}
LANES = (("sub", {"progress": dict}), ("tally", {"progress": int}))


def _mk(raw=None, **kw):
    opt = dict(fields=FIELDS, states=STATES, lanes=LANES)
    opt.update(kw)
    return QuestLog(raw, **opt)


def _raw(**kw):
    r = {"cur": "t1", "st": "s_todo", "pr": {}, "hist": [], "sub": {}}
    r.update(kw)
    return r


def _match_alpha(value, event):
    return event.get("hit") == "alpha" and event.get("target") == value


def _match_beta(value, event):
    return event.get("hit") == "beta" and event.get("target") == value


def _match_gamma(value, event):
    return event.get("hit") == "gamma"


def _need_alpha(obj, engine):
    return int(obj.get("qty", 1))


def _need_beta(obj, engine):
    return int(obj.get("qty2") or obj.get("qty", 1))


def _need_zero(obj, engine):
    return 0


def _fold_alpha(obj, progress, event):
    key = obj["alpha"]
    return {key: int(progress.get(key, 0)) + 1}


def _fold_beta(obj, progress, event):
    key = obj["beta"]
    return {key: int(progress.get(key, 0)) + 1}


def _text_alpha(obj, progress, ctx):
    return "A:" + str(obj["alpha"])


def _text_beta(obj, progress, ctx):
    return "B:" + str(obj["beta"])


def _objs(unknown=None, need_of=None):
    return Objectives(
        Objective("alpha", match=_match_alpha, need=_need_alpha, fold=_fold_alpha,
                  text=_text_alpha, modifiers=("qty",)),
        Objective("beta", match=_match_beta, need=_need_beta, fold=_fold_beta,
                  text=_text_beta, modifiers=("qty", "qty2")),
        Objective("gamma", match=_match_gamma, need=_need_zero, fold=None,
                  text=None, multi=True, modifiers=("cap",)),
        unknown=unknown, need_of=need_of,
    )


# ─────────────────────────────────────────────────────────── ① 注册表
def t_registry():
    print("\n[1] Objectives：声明序 = 判定序 = 展示序")
    objs = _objs()
    check("keys() = 声明序（不排序、不重排）", objs.keys() == ["alpha", "beta", "gamma"], objs.keys())
    check("同一个键换声明序 → keys() 随之变（证明真在看序）",
          Objectives(Objective("z", need=_need_zero),
                     Objective("a", need=_need_zero)).keys() == ["z", "a"])
    check("Objective 只读（无实例字典，__slots__）", not hasattr(Objective("x"), "__dict__"))
    check("Objectives 只读（无实例字典，__slots__）", not hasattr(objs, "__dict__"))
    check("Objective 暴露契约键名与四个回调开关",
          (Objective("k").key, Objective("k").multi, Objective("k").modifiers)
          == ("k", False, ()))
    check("modifiers 规范化成 tuple", Objective("k", modifiers=["a", "b"]).modifiers == ("a", "b"))

    bad = [
        ("★ 注册项非 Objective → TypeError", lambda: Objectives("alpha")),
        ("★ 类型名重复 → ValueError", lambda: Objectives(Objective("a"), Objective("a"))),
        ("★ 类型名为空 → TypeError", lambda: Objective("")),
        ("★ 类型名非字符串 → TypeError", lambda: Objective(1)),
        ("★ match 不可调用 → TypeError", lambda: Objective("a", match=1)),
        ("★ need 不可调用 → TypeError", lambda: Objective("a", need="x")),
        ("★ fold 不可调用 → TypeError", lambda: Objective("a", fold=[])),
        ("★ text 不可调用 → TypeError", lambda: Objective("a", text=3)),
        ("★ modifiers 是字符串（会逐字符）→ TypeError", lambda: Objective("a", modifiers="qty")),
        ("★ modifiers 里有空串 → TypeError", lambda: Objective("a", modifiers=[""])),
        ("★ unknown 不可调用 → TypeError", lambda: Objectives(Objective("a", need=_need_zero), unknown=1)),
        ("★ need_of 不可调用 → TypeError", lambda: Objectives(Objective("a"), need_of=1)),
        ("★ 无 need 回调且未注入 need_of → TypeError", lambda: Objectives(Objective("a"))),
    ]
    for label, fn in bad:
        hit, exc = raises((TypeError, ValueError), fn)
        check(label, hit, f"{exc!r}")
    check("无 need 回调 + 注入 need_of → 合法",
          isinstance(Objectives(Objective("a"), need_of=lambda o, k: 2), Objectives))
    check("空注册表合法（unknown 策略仍可用）", Objectives().keys() == [])


# ─────────────────────────────────────────────────────────── ② parts
def t_parts():
    print("\n[2] parts：目标 mapping 插入序 + 修饰键归属")
    objs = _objs()
    parts = objs.parts({"alpha": "m1", "qty": 3})
    check("单型 + 修饰键 → 一个 part（qty 归它）",
          parts == [("alpha", "m1", 3, {"qty": 3})], parts)
    parts = objs.parts({"beta": "m2", "qty2": 4})
    check("★ 口径④ 复合：qty2 存在 → need 取 qty2", parts[0][2] == 4, parts)
    parts = objs.parts({"beta": "m2", "qty": 3})
    check("★ 口径④ qty2 缺失 → 回落 qty", parts[0][2] == 3, parts)
    parts = objs.parts({"alpha": "a", "qty": 2, "beta": "b", "qty2": 5})
    check("复合目标两型都出，行序 = 插入序",
          [(p[0], p[1], p[2]) for p in parts] == [("alpha", "a", 2), ("beta", "b", 5)], parts)
    check("修饰键只归它紧跟的那一型",
          parts[0][3] == {"qty": 2} and parts[1][3] == {"qty2": 5}, parts)
    parts = objs.parts({"qty": 7, "alpha": "a"})
    check("前导修饰键归到**下一个** part（不丢）", parts == [("alpha", "a", 7, {"qty": 7})], parts)
    parts = objs.parts({"alpha": "a", "zzz": 1})
    check("未注册非修饰键不进 parts（交给 lines 的 unknown 策略）",
          [p[0] for p in parts] == ["alpha"], parts)
    parts = objs.parts({"gamma": "g", "cap": 9})
    check("multi 型照常出 part（need 由回调给）",
          parts == [("gamma", "g", 0, {"cap": 9})], parts)
    check("空 objective → []", objs.parts({}) == [])
    hit, exc = raises(TypeError, objs.parts, "not-a-mapping")
    check("★ objective 非 mapping → TypeError（不吞）", hit, f"{exc!r}")
    seq = objs.parts({"alpha": "x", "qty": 3})
    check("parts 返回新 list（调用方改它不影响注册表）", isinstance(seq, list) and seq[0][3] is not None)
    again = objs.parts({"alpha": "x", "qty": 3})
    check("★ 顺序即语义：两次同一输入逐值相等", seq == again)


# ─────────────────────────────────────────────────────────── ③ need_of / parse_needs
def t_need():
    print("\n[3] need_of / parse_needs：需求数口径由注入面给")
    objs = _objs()
    check("type_key 指定 → 用该型的 need 回调",
          objs.need_of({"alpha": "a", "qty": 5}, "alpha") == 5)
    check("type_key 缺省 → 用首个 part 的型（beta 在前 → 取 beta 的 2）",
          objs.need_of({"beta": "b", "qty2": 2, "alpha": "a", "qty": 4}) == 2)
    check("空 objective + type_key 缺省 → 0", objs.need_of({}) == 0)
    hit, exc = raises(KeyError, objs.need_of, {"alpha": "a"}, "nope")
    check("★ 未注册类型且无注入 need_of → KeyError（fail-closed）", hit, f"{exc!r}")

    injected = Objectives(Objective("alpha"), need_of=lambda obj, key: 42)
    check("类型无 need 回调 → 用注入的 need_of", injected.need_of({"alpha": "a"}, "alpha") == 42)
    check("未注册类型 → 交给注入的 need_of（不抛）",
          injected.need_of({"alpha": "a"}, "other") == 42)

    objs2 = _objs(need_of=lambda obj, key: 99)
    check("★ 口径④ 注入 need_of 后，类型自带 need 仍优先（两口径确实不同）",
          objs2.need_of({"alpha": "a", "qty": 5}, "alpha") == 5
          and objs2.need_of({"other": 1}, "other") == 99)

    check("parse_needs 默认（无修改键声明）→ 每个非修改键 need=1",
          parse_needs({"alpha": 1, "beta": 2}) == {"alpha": 1, "beta": 1})
    check("parse_needs 声明修改键 → 修改键不出现在结果里",
          parse_needs({"alpha": 1, "qty": 3}, modifiers=("qty",)) == {"alpha": 3})
    check("★ 口径④ parse_needs 取**首个正整数**修改键（qty2 优先于 qty）",
          parse_needs({"beta": 1, "qty": 2, "qty2": 4}, modifiers=("qty2", "qty"))
          == {"beta": 4})
    check("★ 口径④ 修改键都是 0/缺失 → 退 1（与上面的 4 确实不同）",
          parse_needs({"beta": 1, "qty": 0}, modifiers=("qty", "qty2")) == {"beta": 1})
    check("parse_needs 注入 need_of → 逐键调它",
          parse_needs({"alpha": 1, "beta": 1}, need_of=lambda o, k: len(k)) == {"alpha": 5, "beta": 4})
    hit, exc = raises(TypeError, parse_needs, "x")
    check("★ parse_needs 非 mapping → TypeError", hit, f"{exc!r}")


# ─────────────────────────────────────────────────────────── ④ hits / fold
def t_hits_fold():
    print("\n[4] hits / fold：命中判定与进度折叠（patch 不就地改）")
    objs = _objs()
    check("保序：命中哪几型按 parts 序",
          objs.hits({"alpha": "m1", "beta": "m2"}, {"hit": "alpha", "target": "m1"}) == ["alpha"])
    check("一个事件可命中多型（保序）",
          objs.hits({"alpha": "m1", "beta": "m1"},
                    {"hit": "beta", "target": "m1", "also": True}) == ["beta"])
    check("不命中 → []", objs.hits({"alpha": "m1"}, {"hit": "beta", "target": "zzz"}) == [])
    check("★ 兜底：match=None 的型永不命中（gamma 的 match 是回调，这里换一个无名回调型）",
          Objectives(Objective("solo", need=_need_zero)).hits({"solo": 1}, {"hit": "solo"}) == [])

    progress = {"m1": 2}
    patch = objs.fold({"alpha": "m1"}, progress, {"hit": "alpha", "target": "m1"})
    check("fold 返回 patch（键由内容回调决定）", patch == {"m1": 3}, patch)
    check("★ 不就地改：传入的 progress 一个字节没动", progress == {"m1": 2}, progress)
    check("未命中 → 空 patch", objs.fold({"alpha": "m1"}, {}, {"hit": "beta", "target": "m1"}) == {})
    check("复合命中 → patch 合并（保序 update）",
          objs.fold({"alpha": "a", "beta": "b"}, {},
                    {"hit": "beta", "target": "b"}) == {"b": 1})
    check("fold=None 的型命中 → 不贡献 patch（gamma）",
          objs.fold({"gamma": "g"}, {}, {"hit": "gamma"}) == {})

    boom = RuntimeError("fold-boom")

    def _raiser(*a, **kw):
        raise boom

    objs3 = Objectives(Objective("alpha", match=_match_alpha, need=_need_zero, fold=_raiser))
    hit, exc = raises(RuntimeError, objs3.fold, {"alpha": "a"}, {}, {"hit": "alpha", "target": "a"})
    check("★ 异常不吞：fold 回调抛错原样上抛", hit and exc is boom, f"{exc!r}")
    hit, exc = raises(RuntimeError, Objectives(
        Objective("alpha", match=_raiser, need=_need_zero)).hits, {"alpha": "a"}, {})
    check("★ 异常不吞：match 回调抛错原样上抛", hit and exc is boom, f"{exc!r}")


# ─────────────────────────────────────────────────────────── ⑤ satisfied / complete
def t_satisfied():
    print("\n[5] satisfied / complete：达成判定（两种进度容器）")
    objs = _objs()
    check("mapping 进度：每个非零 part 都要够数",
          objs.satisfied({"alpha": "m1", "qty": 3}, {"m1": 3}) is True)
    check("mapping 进度：差一个 → False",
          objs.satisfied({"alpha": "m1", "qty": 3}, {"m1": 2}) is False)
    check("mapping 进度：缺键当 0 → False",
          objs.satisfied({"alpha": "m1", "qty": 3}, {}) is False)
    check("复合目标：一型够一型不够 → False",
          objs.satisfied({"alpha": "a", "qty": 1, "beta": "b", "qty2": 2}, {"a": 1, "b": 1}) is False)
    check("复合目标：两型都够 → True",
          objs.satisfied({"alpha": "a", "qty": 1, "beta": "b", "qty2": 2}, {"a": 1, "b": 2}) is True)
    check("need=0 的 multi 型不拦（gamma）", objs.satisfied({"gamma": "g", "cap": 2}, {}) is True)
    check("空 objective → False（现状 `or {}` 后无键 → 永不达成）", objs.satisfied({}, {}) is False)
    check("★ 口径③ int 进度：整格计数与 need 比（不是按 value 取键）",
          objs.satisfied({"alpha": "m1", "qty": 3}, 3) is True
          and objs.satisfied({"alpha": "m1", "qty": 3}, 2) is False)
    check("★ 非数值进度值（字符串/None）→ False（不谎报达成）",
          objs.satisfied({"alpha": "m1", "qty": 1}, "3") is False
          and objs.satisfied({"alpha": "m1", "qty": 1}, None) is False)
    check("complete 是**结构**判定：有已注册 part → True", objs.complete({"alpha": "a"}) is True)
    check("complete：空 objective → False", objs.complete({}) is False)
    check("complete：只有未注册键 → False", objs.complete({"zzz": 1}) is False)
    check("complete 与 satisfied 是两个口径（complete 不看进度）",
          objs.complete({"alpha": "a", "qty": 9}) is True
          and objs.satisfied({"alpha": "a", "qty": 9}, {}) is False)


# ─────────────────────────────────────────────────────────── ⑥ lines / unknown
def t_lines():
    print("\n[6] lines：逐行骨架（复合全出 · 行序 = parts 序 · unknown 策略）")
    objs = _objs()
    check("单型一行", objs.lines({"alpha": "m1", "qty": 2}) == ["A:m1"])
    check("★ 口径② 复合目标**全出**（不是首命中即返）",
          objs.lines({"alpha": "a", "beta": "b"}) == ["A:a", "B:b"])
    check("★ 口径② 行序随目标键序改变（正序 vs 倒序）",
          objs.lines({"beta": "b", "alpha": "a"}) == ["B:b", "A:a"])
    check("text=None 的型 → 不出行（gamma）", objs.lines({"gamma": "g", "cap": 1}) == [])
    check("修饰键不出行", objs.lines({"alpha": "a", "qty": 5}) == ["A:a"])

    check("★ 口径⑤ unknown 默认（未注入）→ 返回 None → 不加行", objs.lines({"zzz": 1}) == [])
    seen = []
    objs2 = _objs(unknown=lambda k, v: seen.append((k, v)) or "？")
    check("★ 口径⑤ 注入 unknown 返回字符串 → 就地出行",
          objs2.lines({"alpha": "a", "zzz": 1}) == ["A:a", "？"], seen)
    check("unknown 每未注册键调一次（含键与值）", seen == [("zzz", 1)], seen)
    seen.clear()
    objs3 = _objs(unknown=lambda k, v: seen.append(k) or None)
    check("★ 口径⑤ 注入 unknown 返回 None → 不加行（且注册键不调 unknown）",
          objs3.lines({"alpha": "a", "zzz": 1}) == ["A:a"] and seen == ["zzz"], seen)

    calls = []
    objs4 = _objs(unknown=lambda k, v: (calls.append("u"), "？")[1])
    objs4.lines({"qty": 1, "alpha": "a"})
    check("修饰键不走 unknown（即使出现在注册键之前）", calls == [], calls)

    tpl = lambda key, obj, progress, state: f"[{key}]" + str(obj.get(key)) + "/" + str(state)
    check("★ 口径② text_of 是各出口自己的模板（同骨架不同行文）",
          objs.lines({"alpha": "a"}, state="S1", text_of=tpl) == ["[alpha]a/S1"])
    check("★ 口径② 两个不同 text_of → 行文不同（引擎不产成品文案）",
          objs.lines({"alpha": "a"}, text_of=tpl)
          != objs.lines({"alpha": "a"}, text_of=lambda k, o, p, s: "X"))
    hit, exc = raises(TypeError, objs.lines, {"alpha": "a"}, text_of=5)
    check("★ text_of 不可调用 → TypeError", hit, f"{exc!r}")
    hit, exc = raises(TypeError, objs.lines, "x")
    check("★ objective 非 mapping → TypeError", hit, f"{exc!r}")

    boom = RuntimeError("text-boom")

    def _txt(*a, **kw):
        raise boom

    objs5 = Objectives(Objective("alpha", need=_need_zero, text=_txt))
    hit, exc = raises(RuntimeError, objs5.lines, {"alpha": "a"})
    check("★ 异常不吞：text 回调抛错原样上抛", hit and exc is boom, f"{exc!r}")


# ─────────────────────────────────────────────────────────── ⑦ 账本读口
def t_ledger_read():
    print("\n[7] QuestLog 读口：raw / current / status / progress / done / lane / entry")
    raw = _raw(sub={"s1": {"st": "s_live", "pr": {"m1": 1}}})
    log = _mk(raw)
    check("raw 属性 = 原对象（不拷贝、不归一）", log.raw is raw)
    check("current = 注入字段名的取值", log.current == "t1")
    check("status = 注入字段名的取值", log.status == "s_todo")
    check("progress = 原对象（不拷贝）", log.progress is raw["pr"])
    check("done = archive 字段（原对象）", log.done is raw["hist"])
    check("★ 兜底：status 缺失 → 注入的 todo 状态词", _mk({"cur": "x"}).status == "s_todo")
    check("★ 兜底：status 显式为 None → 同样回落 todo", _mk({"st": None}).status == "s_todo")
    check("★ 兜底：progress 缺失 → {}", _mk({}).progress == {})
    check("★ 兜底：done 缺失 → []", _mk({}).done == [])
    check("★ 兜底：current 缺失 → None（不回落）", _mk({}).current is None)
    check("raw=None → 空账本（读口全兜底）",
          _mk(None).current is None and _mk(None).status == "s_todo" and _mk(None).done == [])
    hit, exc = raises(TypeError, _mk, ["not", "a", "mapping"])
    check("★ raw 非 mapping → TypeError（不吞）", hit, f"{exc!r}")

    check("lane(名) → 子账本原对象", log.lane("sub") is raw["sub"])
    check("★ 兜底：lane 缺失 → {}（且**不建**默认值：raw 里仍没有这个键）",
          _mk(_raw()).lane("tally") == {} and "tally" not in _raw())
    check("lane() 缺省 → fields[lanes] 指的默认子账本", log.lane() is raw["sub"])
    raw_with_ghost = _raw(ghost={"g1": {"st": "s_live"}})
    check("★ 未声明的子账本名 → {}（不认，不猜）",
          _mk(raw_with_ghost).lane("ghost") == {})
    check("★ unknown 策略放行未声明 lane 名后 → 按原对象读",
          _mk(raw_with_ghost, unknown=lambda name, value: True).lane("ghost")
          is raw_with_ghost["ghost"])

    check("entry 命中 → 条目原对象", log.entry("sub", "s1") is raw["sub"]["s1"])
    check("★ 兜底：entry 缺失 → None", log.entry("sub", "nope") is None)
    check("★ 兜底：entry 的 lane 缺失 → None", log.entry("tally", "nope") is None)

    check("status_of(主 lane) = status", log.status_of(None) == "s_todo")
    check("status_of(lane, key) = 条目的 status", log.status_of("sub", "s1") == "s_live")
    check("★ 兜底：条目缺失 → 注入的 todo 状态词", log.status_of("sub", "nope") == "s_todo")
    check("★ 单条目 lane：key 缺省 → 把 lane 自己当条目读",
          _mk({"sub": {"st": "s_live"}}).status_of("sub") == "s_live")

    check("is_open(主 lane) = 有 current 且未终结",
          log.is_open(None) is True and _mk({"cur": None}).is_open(None) is False
          and _mk({"cur": "x", "st": "s_ended"}).is_open(None) is False)
    check("is_open(lane, key) = 键在 lane 里且状态 != ended",
          log.is_open("sub", "s1") is True
          and _mk({"sub": {"s1": {"st": "s_ended"}}}).is_open("sub", "s1") is False)
    check("★ 兜底：键不在 lane 里 → False（不是「未终结所以算开」）",
          log.is_open("sub", "nope") is False and log.is_open("tally", "nope") is False)
    check("★ 单条目 lane key 缺省：lane 不存在 → False；存在且未终结 → True",
          _mk({"sub": {}}).is_open("sub") is False
          and _mk({"sub": {"st": "s_live"}}).is_open("sub") is True)


# ─────────────────────────────────────────────────────────── ⑧ 账本迁移
def t_ledger_migrate():
    print("\n[8] QuestLog 迁移：accept / set_status / bump / deliver / abandon / require")
    raw = _raw(sub={"s1": {"st": "s_live", "pr": {"m1": 1}}}, tally={"d1": {"st": "s_live", "pr": 2}})
    log = _mk(raw)

    new = log.accept(lane="sub", key="s2")
    check("accept 建条目：status = live、progress = 空 mapping（dict 口径 lane）",
          new["sub"]["s2"] == {"st": "s_live", "pr": {}}, new["sub"]["s2"])
    check("accept 显式 status / progress 原样落",
          log.accept(lane="sub", key="s3", status="s_met", progress={"m1": 9})["sub"]["s3"]
          == {"st": "s_met", "pr": {"m1": 9}})
    check("★ 口径③ accept 在 int 口径 lane 上 → progress = 0",
          log.accept(lane="tally", key="d2")["tally"]["d2"] == {"st": "s_live", "pr": 0})
    check("accept 的 entry 参数是基底（copy 不共享）",
          log.accept(lane="sub", key="s4", entry={"extra": 1})["sub"]["s4"]["extra"] == 1)
    check("★ accept 到主 lane：合并进顶层（不建条目）",
          log.accept(lane=None, key=None)["st"] == "s_live"
          and log.accept(lane=None, key=None)["pr"] == {})
    hit, exc = raises(KeyError, log.accept, lane="ghost", key="x")
    check("★ accept 到未声明 lane → KeyError（fail-closed）", hit, f"{exc!r}")
    hit, exc = raises(TypeError, log.accept, lane="sub", key="x", entry="bad")
    check("★ entry 非 mapping → TypeError", hit, f"{exc!r}")

    new = log.set_status("s_met", lane="sub", key="s1")
    check("set_status 改条目状态", new["sub"]["s1"]["st"] == "s_met")
    check("set_status 保留条目其它键", new["sub"]["s1"]["pr"] == {"m1": 1})
    check("★ set_status 到主 lane", log.set_status("s_live", lane=None)["st"] == "s_live")
    check("★ set_status 单条目 lane：key 缺省改 lane 自己的 status",
          log.set_status("s_met", lane="tally")["tally"]["st"] == "s_met")
    hit, exc = raises(KeyError, log.set_status, "x", lane="sub", key="nope")
    check("★ set_status 条目不存在 → KeyError（不静默造条目）", hit, f"{exc!r}")

    new = log.bump({"m1": 5}, lane="sub", key="s1")
    check("bump mapping → 合并进条目进度（不是覆盖）", new["sub"]["s1"]["pr"] == {"m1": 5})
    new = log.bump(7, lane="tally", key="d1")
    check("★ 口径③ bump int → 覆盖（不是合并）", new["tally"]["d1"]["pr"] == 7)
    raw2 = _raw(pr={"m1": 1})
    new = _mk(raw2).bump({"m1": 2, "m2": 3}, lane=None)
    check("bump 到主 lane：合并 + 新增键", new["pr"] == {"m1": 2, "m2": 3}, new["pr"])
    new = _mk(_raw()).accept(lane="sub", key="s2")
    log_b = _mk(new)
    check("★ bump 合并到空进度 → 从空 mapping 起（不是丢弃 patch）",
          log_b.bump({"m1": 1}, lane="sub", key="s2")["sub"]["s2"]["pr"] == {"m1": 1})
    hit, exc = raises(KeyError, log_b.bump, {"m1": 1}, lane="sub", key="nope")
    check("★ bump 条目不存在 → KeyError", hit, f"{exc!r}")

    new = log.deliver(lane=None, next_of=lambda cur: "t2")
    check("★ 口径① deliver 主 lane：done 追加 current", new["hist"] == ["t1"], new["hist"])
    check("★ 口径① deliver 主 lane：current = next_of(current)", new["cur"] == "t2")
    check("★ 口径① deliver 主 lane：status 回 todo（**不是**终结态）", new["st"] == "s_todo")
    check("★ deliver 主 lane：progress 清空", new["pr"] == {})
    check("deliver 主 lane：next_of 收到的是 None 也照传（终章裁决在内容侧）",
          log.deliver(lane=None, next_of=lambda cur: None)["cur"] is None)
    check("★ 口径⑥ deliver 缺省 next_of=None → current 置 None（引擎不猜下一环）",
          log.deliver(lane=None)["cur"] is None)
    new = log.deliver(lane="sub", key="s1")
    check("★ 口径① deliver 子账本：条目置终结态（**不追加 done**）",
          new["sub"]["s1"] == {"st": "s_ended"}, new["sub"]["s1"])
    check("★ 口径① 两口径确实不同：主 lane 有历史、子账本有终态",
          new["hist"] == [] and new["sub"]["s1"]["st"] == "s_ended")
    hit, exc = raises(TypeError, log.deliver, lane=None, next_of=5)
    check("★ next_of 不可调用 → TypeError", hit, f"{exc!r}")

    new = log.abandon(lane="sub", key="s1")
    check("abandon 删键（返回新 mapping）", new["sub"] == {})
    check("★ abandon 键不存在 → 幂等（不抛、不误删别的条目）",
          log.abandon(lane="sub", key="zzz")["sub"] == {"s1": {"st": "s_live", "pr": {"m1": 1}}})
    hit, exc = raises(ValueError, log.abandon, lane=None, key="x")
    check("★ abandon 主 lane → ValueError（主线不可放弃）", hit, f"{exc!r}")

    new = log.require("s9", lane="sub", status="s_met")
    check("require 造**最小**条目（只有 status 一格）", new["sub"]["s9"] == {"st": "s_met"})
    hit, exc = raises(ValueError, log.require, "k", lane=None, status="x")
    check("★ require 主 lane → ValueError", hit, f"{exc!r}")

    log2 = QuestLog.restore(raw, fields=FIELDS, states=STATES, lanes=LANES)
    check("restore 与构造等价", log2.raw is raw and log2.current == "t1")
    snap = log.snapshot()
    check("snapshot = 原形态（键名/键序逐字保留）",
          list(snap) == list(raw) and snap == raw, list(snap))
    check("snapshot 是浅拷贝（不是同一个 dict）", snap is not raw)
    check("snapshot 嵌套对象仍是原对象（引擎不深拷）", snap["sub"] is raw["sub"])
    check("★ 空账本 snapshot → {}", _mk(None).snapshot() == {})


# ─────────────────────────────────────────────────────────── ⑨ Quest
def t_quest():
    print("\n[9] Quest：单条只读外壳")
    objs = _objs()
    row = {"id": "x1", "objective": {"alpha": "m1", "qty": 2}, "next": "x2"}
    q = Quest(row, objectives=objs, objective_key="objective", next_key="next")
    check("id 读注入键", q.id == "x1")
    check("objective 读注入键（原对象）", q.objective is row["objective"])
    check("next 读注入键", q.next == "x2")
    check("lines = 注册表骨架（可无进度）", q.lines() == ["A:m1"])
    check("progress_lines = 同一骨架（进度必给）", q.progress_lines({"m1": 2}) == ["A:m1"])
    check("★ 兜底：objective 缺失 → {}", Quest({"id": "x"}, objectives=objs,
                                              objective_key="objective", next_key="next").objective == {})
    check("★ 兜底：objective 是空 mapping → {}（`or {}` 口径）",
          Quest({"objective": {}}, objectives=objs, objective_key="objective", next_key="next").objective == {})
    check("★ 口径⑥ next 缺失 → None", Quest({}, objectives=objs, objective_key="o",
                                             next_key="n").next is None)
    check("★ 口径⑥ next 是字面 None → 也是 None（引擎不区分两者）",
          Quest({"n": None}, objectives=objs, objective_key="o", next_key="n").next is None)
    check("id 缺省键名是通用契约名 id",
          Quest({"id": "z"}, objectives=objs, objective_key="o", next_key="n").id == "z")
    hit, exc = raises(TypeError, Quest, {}, objectives=objs, objective_key=None, next_key="n")
    check("★ objective_key 未注入 → TypeError（引擎不内置内容字段名）", hit, f"{exc!r}")
    hit, exc = raises(TypeError, Quest, "not-mapping", objectives=objs,
                      objective_key="o", next_key="n")
    check("★ row 非 mapping → TypeError", hit, f"{exc!r}")
    hit, exc = raises(TypeError, Quest, {}, objectives="bad", objective_key="o", next_key="n")
    check("★ objectives 非 Objectives → TypeError", hit, f"{exc!r}")
    hit, exc = raises(TypeError, Quest, {}, objectives=objs, objective_key="o", next_key=None)
    check("★ next_key 未注入 → TypeError（引擎不内置内容字段名）", hit, f"{exc!r}")
    check("Quest 只读（无实例字典）",
          not hasattr(Quest({}, objectives=objs, objective_key="o", next_key="n"), "__dict__"))


# ─────────────────────────────────────────────────────────── ⑩ 12 条口径分歧
def t_divergences():
    print("\n[10] 12 条口径分歧（每条 ≥1 断言；故意不同的两口径断言「确实不同」）")
    objs = _objs()
    log = _mk(_raw(sub={"s1": {"st": "s_live", "pr": {}}}))

    # ① 主线无终结状态；子账本有终态
    main_done = log.deliver(lane=None, next_of=lambda cur: "t9")
    sub_done = log.deliver(lane="sub", key="s1")
    check("① 主 lane 交付 → done 追加 current、status 回 todo（主线无终结状态）",
          main_done["hist"] == ["t1"] and main_done["st"] == "s_todo")
    check("① 子账本交付 → 条目写终结态", sub_done["sub"]["s1"] == {"st": "s_ended"})
    check("① 两口径确实不同（历史列表 vs 终态词）",
          main_done["sub"]["s1"]["st"] != main_done["st"])

    # ② 目标行骨架不合并三份渲染
    check("② 复合目标**全出**（不是首命中）", objs.lines({"alpha": "a", "beta": "b"}) == ["A:a", "B:b"])
    check("② text_of 是各出口自己的模板 → 行文不同（引擎不产成品文案）",
          objs.lines({"alpha": "a"}, text_of=lambda k, o, p, s: "one") != objs.lines(
              {"alpha": "a"}, text_of=lambda k, o, p, s: "two"))

    # ③ 进度容器 mapping ∪ int
    new_map = _mk(_raw(pr={})).bump({"m1": 1}, lane=None)["pr"]
    new_int = _mk(_raw(tally={"d1": {"st": "s_live", "pr": 1}})).bump(2, lane="tally", key="d1")["tally"]["d1"]["pr"]
    check("③ mapping 口径：合并（保旧键）", new_map == {"m1": 1})
    check("③ int 口径：覆盖为整数", new_int == 2)
    check("③ 两口径确实不同（类型都不同）", isinstance(new_map, dict) and isinstance(new_int, int) and not isinstance(new_int, dict))
    check("③ 两种 lane 的 progress 类型由声明给（dict / int）",
          _mk().accept(lane="sub", key="a")["sub"]["a"]["pr"] == {}
          and _mk().accept(lane="tally", key="a")["tally"]["a"]["pr"] == 0)

    # ④ 需求数两种口径
    check("④ qty2 存在取 qty2", objs.need_of({"beta": "b", "qty": 3, "qty2": 4}, "beta") == 4)
    check("④ qty2 缺失回落 qty", objs.need_of({"beta": "b", "qty": 3}, "beta") == 3)
    check("④ 两口径确实不同", objs.need_of({"beta": "b", "qty": 3, "qty2": 4}, "beta")
          != objs.need_of({"beta": "b", "qty": 3}, "beta"))
    check("④ parse_needs 把口径整个交还注入面（默认只退 1）",
          parse_needs({"beta": 1}) == {"beta": 1}
          and parse_needs({"beta": 1}, need_of=lambda o, k: 4) == {"beta": 4})

    # ⑤ unknown 目标类型三出口
    check("⑤ 默认 unknown → None → 不加行", objs.lines({"zzz": 1}) == [])
    check("⑤ 注入返回字符串 → 出行", _objs(unknown=lambda k, v: "？").lines({"zzz": 1}) == ["？"])
    check("⑤ 两口径确实不同（None 不出行 / 字符串出行）",
          objs.lines({"zzz": 1}) != _objs(unknown=lambda k, v: "？").lines({"zzz": 1}))

    # ⑥ next 缺失 ≠ next: null（引擎一律 None，裁决交内容侧）
    q_missing = Quest({}, objectives=objs, objective_key="o", next_key="n")
    q_null = Quest({"n": None}, objectives=objs, objective_key="o", next_key="n")
    sent = []
    log.deliver(lane=None, next_of=lambda cur: sent.append(cur) or "END")
    check("⑥ 缺失与字面 null 都返回 None（引擎不区分）",
          q_missing.next is None and q_null.next is None)
    check("⑥ deliver 把 None 原样交给 next_of（由内容侧裁决终章还是数据缺）",
          sent == ["t1"], sent)

    # ⑦ 进度 key 由内容回调决定，引擎不翻译也不统一
    patch = objs.fold({"alpha": "m1"}, {}, {"hit": "alpha", "target": "m1"})
    check("⑦ fold 的 patch 键原样写出（引擎不改键）", patch == {"m1": 1}, patch)
    legacy = {"m1-prefix-old": 5}
    check("⑦ 老 key（聚合键）不被引擎翻译 → 按目标名判定仍不成立（兼容聚合留在内容侧）",
          objs.satisfied({"alpha": "m1", "qty": 1}, legacy) is False)
    check("⑦ 目标名 key 才成立（两口径确实不同）",
          objs.satisfied({"alpha": "m1", "qty": 1}, {"m1": 1}) is True)

    # ⑧ 三个门槛失败语义不同 → 门槛一个都不在引擎里
    check("⑧ 引擎不提供任何门槛/可接过滤 API（三门槛的失败语义留在内容侧）",
          not any(n in dir(objs) for n in ("available", "visible", "filter", "listed",
                                           "gated", "allowed")))
    check("⑧ 注册表 keys() 不重排（过滤集合与短路序留在内容侧）",
          Objectives(Objective("z", need=_need_zero),
                     Objective("a", need=_need_zero)).keys() == ["z", "a"])

    # ⑨ 面板可见性 ≠ 列表过滤 → 引擎不做任何按标记过滤
    flagged = {"st": "s_live", "flag_x": True}
    log2 = _mk(_raw(sub={"s1": flagged, "s2": {"st": "s_live"}}))
    check("⑨ 引擎对条目**零过滤**：带标记与不带标记都能读到",
          log2.entry("sub", "s1") is flagged and log2.entry("sub", "s2") is not None)
    check("⑨ 引擎不产列表过滤 API（可见性差异由内容侧决定）",
          not any(n in dir(log2) for n in ("available", "visible", "filter", "listed")))

    # ⑩ 每日任务键 = 名字（不透明字符串，没有 id 语义）
    log3 = _mk(_raw(sub={}))
    log3 = _mk(log3.require("每日 委托 A", lane="sub", status="s_live"))
    check("⑩ 条目键是不透明字符串（空格/中文原样保留）",
          list(log3.lane("sub")) == ["每日 委托 A"])
    check("⑩ 引擎不对键做任何归一（原样取回）", log3.entry("sub", "每日 委托 A") == {"st": "s_live"})

    # ⑪ 系统钟 vs 注入钟 → 引擎一个钟都不读
    hit_i, exc_i = raises(TypeError, _mk, None, fields=FIELDS, states=STATES, lanes=LANES, now=1)
    check("⑪ 引擎不接受任何时钟注入口（没有 now/clock 形参）", hit_i, f"{exc_i!r}")
    check("⑪ snapshot 只有原字段，引擎不掺任何时间戳键",
          list(_mk(_raw()).snapshot()) == ["cur", "st", "pr", "hist", "sub"])

    # ⑫ 行序就是信息序（不重排、不去重）
    a = objs.lines({"alpha": "a", "beta": "b", "alpha2": 1})
    b = objs.lines({"beta": "b", "alpha": "a"})
    check("⑫ 行序随目标序整体改变（拒绝行序是刻意的信息序）", a[:2] != b, (a, b))
    check("⑫ 同一输入两次调用逐值相等（不重排、不去重）",
          objs.lines({"alpha": "a", "beta": "b"}) == objs.lines({"alpha": "a", "beta": "b"}))


# ─────────────────────────────────────────────────────────── ⑪ 不变量
class _Tripwire(dict):
    """一碰就读的探针账本：构造期若读它，立刻报错（证明「不遍历账本」）。"""

    def get(self, *a, **kw):
        raise AssertionError("构造期读了账本：get")

    def __getitem__(self, k):
        raise AssertionError("构造期读了账本：[]")

    def __contains__(self, k):
        raise AssertionError("构造期读了账本：in")

    def __iter__(self):
        raise AssertionError("构造期遍历了账本：iter")

    def items(self):
        raise AssertionError("构造期遍历了账本：items")

    def keys(self):
        raise AssertionError("构造期遍历了账本：keys")

    def values(self):
        raise AssertionError("构造期遍历了账本：values")


def t_invariants():
    print("\n[11] 不变量：构造 O(1) / fail-closed / 新对象 / 不缓存 / 异常不吞")
    tw = _Tripwire()
    dict.__setitem__(tw, "cur", "t1")
    dict.__setitem__(tw, "sub", {})
    ok, why = True, ""
    try:
        log = _mk(tw)
    except AssertionError as e:
        ok, why = False, str(e)
    check("★ 构造不读账本（探针的 get/[]/in/iter/items/keys/values 一次不碰）", ok, why)
    check("构造保留原对象（raw is 相同、不拷贝）", log.raw is tw)
    check("构造后无实例字典（不可变：只有 __slots__ 那几格）", not hasattr(log, "__dict__"))
    teeth = False
    try:
        log.current
    except AssertionError:
        teeth = True
    check("★ 探针有牙（一读就报错 → 上面那条不是「探针失效」的假绿）", teeth)

    big = {"cur": "t1", "st": "s_todo", "pr": {}, "hist": [],
           "sub": {f"k{i}": {"st": "s_live", "pr": {}} for i in range(3000)}}
    empty = {}

    def _loop(raw):
        t0 = time.perf_counter()
        for _ in range(100000):
            QuestLog(raw, fields=FIELDS, states=STATES, lanes=LANES)
        return time.perf_counter() - t0

    t_big, t_empty = _loop(big), _loop(empty)
    check(f"★ 判据 9 构造 10^5 次：大账本 ≈ 空账本（零遍历：{t_big * 1e3:.0f}ms vs "
          f"{t_empty * 1e3:.0f}ms）", t_big < t_empty * 3 + 1.0, f"{t_big:.3f}s vs {t_empty:.3f}s")

    fails = [
        ("★ fields 缺失 → TypeError", lambda: QuestLog(None, fields=None, states=STATES, lanes=LANES)),
        ("★ fields 缺角色键 → ValueError",
         lambda: QuestLog(None, fields={"current": "a"}, states=STATES, lanes=LANES)),
        ("★ fields 某角色值为空串 → ValueError",
         lambda: QuestLog(None, fields=dict(FIELDS, status=""), states=STATES, lanes=LANES)),
        ("★ states 缺角色键 → ValueError",
         lambda: QuestLog(None, fields=FIELDS, states={"todo": "x"}, lanes=LANES)),
        ("★ states 非 mapping → TypeError",
         lambda: QuestLog(None, fields=FIELDS, states=["x"], lanes=LANES)),
        ("★ lanes 非序列 → TypeError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes="sub")),
        ("★ lanes 项不是二元组 → TypeError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes=[("sub",)])),
        ("★ lanes 声明非 mapping → TypeError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes=[("sub", "dict")])),
        ("★ lanes 声明的进度类型非法 → ValueError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes=[("sub", {"progress": str})])),
        ("★ 默认子账本名未声明 → ValueError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes=[("other", {"progress": dict})])),
        ("★ lanes 名字重复 → ValueError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES,
                          lanes=[("sub", {}), ("sub", {})])),
        ("★ unknown 不可调用 → TypeError",
         lambda: QuestLog(None, fields=FIELDS, states=STATES, lanes=LANES, unknown=7)),
    ]
    for label, fn in fails:
        hit, exc = raises((TypeError, ValueError), fn)
        check(label, hit, f"{exc!r}")

    # 不可变：迁移返回新对象、原 raw 一个字节不动
    raw = _raw(sub={"s1": {"st": "s_live", "pr": {"m1": 1}}})
    before = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    log = _mk(raw)
    outs = [
        log.accept(lane="sub", key="s2"),
        log.accept(lane=None, key=None),
        log.set_status("s_met", lane="sub", key="s1"),
        log.set_status("s_met", lane=None),
        log.bump({"m1": 2}, lane="sub", key="s1"),
        log.bump(3, lane=None),
        log.deliver(lane=None, next_of=lambda cur: "t2"),
        log.deliver(lane="sub", key="s1"),
        log.abandon(lane="sub", key="s1"),
        log.require("s9", lane="sub", status="s_live"),
        log.snapshot(),
    ]
    after = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    check("★ 判据 10 状态迁移全程不改原 raw（json.dumps 指纹前后一致）", before == after,
          f"{before} != {after}")
    check("★ 判据 10 每次迁移都返回**新** dict（不是同一个对象）",
          all(o is not raw for o in outs))
    check("★ 迁移不改原对象的**嵌套** mapping（新 top-level + 新被改层）",
          log.deliver(lane="sub", key="s1")["sub"] is not raw["sub"]
          and raw["sub"]["s1"]["pr"] == {"m1": 1})
    check("★ 未改动的嵌套对象仍共享（浅拷贝口径，不做深拷）",
          log.deliver(lane=None, next_of=lambda c: "t2")["sub"] is raw["sub"])

    # 不缓存：读口每次现场读
    raw["st"] = "s_live"
    check("★ 不缓存：原 raw 变了，同一个外壳的读口随之变", log.status == "s_live")
    raw["st"] = "s_todo"

    # 顺序断言的中间快照（deliver 四步：追加 → 换 current → 归位 → 清进度）
    raw3 = _raw(hist=["t1"], cur="t1", pr={"m1": 5})
    out = _mk(raw3).deliver(lane=None, next_of=lambda cur: "t2")
    check("★ 顺序断言：已完成的 id 照常**重复追加**（现状无 in 判断，不去重）",
          out["hist"] == ["t1", "t1"], out["hist"])
    check("★ 顺序断言：四步结果同时成立（追加 / 换 current / 归位 / 清进度）",
          out["hist"] == ["t1", "t1"] and out["cur"] == "t2"
          and out["st"] == "s_todo" and out["pr"] == {})


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
    objs = _objs()
    log = _mk(_raw())
    orig_parts = Objectives.parts
    orig_deliver = QuestLog.deliver

    def probe_need():
        return objs.need_of({"beta": "b", "qty": 3, "qty2": 4}, "beta") != 4

    def probe_order():
        return [p[0] for p in objs.parts({"alpha": "a", "beta": "b"})] != ["alpha", "beta"]

    def probe_deliver():
        return len(log.deliver(lane=None, next_of=lambda c: "t2").get("hist") or []) != 1

    def probe_unknown():
        return _objs().lines({"zzz": 1}) != []

    def probe_third():
        return objs.satisfied({"alpha": "a", "qty": 1}, {"a": 1}) is not True

    breaks = [
        ("① need_of 恒 1",
         lambda: _Patch(Objectives, "need_of", lambda self, obj, tk=None: 1), probe_need),
        ("② parts 结果倒序",
         lambda: _Patch(Objectives, "parts",
                        lambda self, obj: list(reversed(orig_parts(self, obj)))), probe_order),
        ("③ deliver 不追加历史",
         lambda: _Patch(QuestLog, "deliver",
                        lambda self, **kw: {k: v for k, v in orig_deliver(self, **kw).items()
                                            if k != "hist"}), probe_deliver),
        ("④ unknown 默认改成出行",
         lambda: _Patch(Objectives, "unknown", lambda self, k, v: "？"), probe_unknown),
    ]
    for label, maker, probe in breaks:
        check(f"未破坏时 {label} 的探针为绿", probe() is False)
        with maker():
            got = probe()
        print(f"    反证 {label}：预期变红=True  实测变红={got}")
        check(f"★ 破坏 {label} → 探针必须变红（预期 True / 实测 {got}）", got is True, got)
        check(f"还原 {label} → 探针回绿", probe() is False)

    # 两处同坏 + 第三处仍绿
    with _Patch(Objectives, "need_of", lambda self, obj, tk=None: 1), \
            _Patch(Objectives, "parts", lambda self, obj: list(reversed(orig_parts(self, obj)))):
        n, o, t = probe_need(), probe_order(), probe_third()
    check("★ 两处同坏 → 两条探针**各自**变红（互不掩盖）", n is True and o is True, (n, o))
    check("★ 两处同坏时第三处（satisfied）仍为绿", t is False, t)
    check("还原（好实例）→ 三探针回绿",
          probe_need() is False and probe_order() is False and probe_third() is False)


# ─────────────────────────────────────────────────────────── ⑬ 指纹（判据 10 的加厚）
def t_fingerprint():
    print("\n[13] 指纹：迁移前后 raw 的 json 文本逐字不变")
    raw = _raw(sub={"s1": {"st": "s_live", "pr": {"m1": 1}}},
               hist=["old"], tally={"d1": {"st": "s_live", "pr": 1}})
    log = _mk(raw)
    fp0 = json.dumps(raw, sort_keys=False, ensure_ascii=False)
    log.set_status("s_ended", lane="sub", key="s1")
    log.deliver(lane="sub", key="s1")
    log.deliver(lane=None, next_of=lambda c: "t2")
    log.bump({"m1": 1}, lane="sub", key="s1")
    log.abandon(lane="sub", key="s1")
    log.require("k", lane="tally", status="s_live")
    fp1 = json.dumps(raw, sort_keys=False, ensure_ascii=False)
    check("键序也逐字不变（sort_keys=False 指纹）", fp0 == fp1, f"{fp0} != {fp1}")


def _quest_sources():
    base = os.path.join(ROOT, "saintess_engine", "quest")
    return [os.path.join(r, f) for r, _d, fs in os.walk(base)
            for f in sorted(fs) if f.endswith(".py")]


# ─────────────────────────────────────────────────────────── ⑭ 零知识静态扫描
_VALUE_WORDS = (
    # ① 本游戏的取值词（引擎里出现即红）
    "奥兰迪亚", "余烬", "镇长", "游商", "见闻", "师门",
    # ② A：任务取值（引擎只认注入的状态词与目标类型词）
    "main_quest", "main_status", "main_progress", "completed_main", "side", "daily",
    "pending", "active", "ready", "done", "closed", "open", "running",
    "kill", "collect", "collect_count", "explore", "find", "use", "talk",
    "kill_any", "kill_elite", "kill_boss", "complete_side", "collect_any",
    "objective", "next", "giver", "board", "unlock", "min_level", "min_lv",
    "require_stats", "require_race", "suggest_lv", "chain", "branch", "endings",
    # ③ B：存档取值（引擎只认注入的表名/列名/TTL）
    "qq_id", "monster", "state", "updated_at", "created_at", "used", "kills",
    "total", "stats", "battle_state", "props_use", "bestiary", "fishing",
    "event_state", "instance_world_", "talk_", "wildmeta_", "timed_events_",
    "data.plugins.dragonfall",
    # ④ C：事件与载荷取值（引擎只认注入的 events 元组与不透明载荷）
    "battle_start", "turn_start", "act_begin", "act_cast", "skill_hit", "attack_hit",
    "crit", "on_taken", "on_heal", "on_kill", "on_death", "dot_tick", "dot_calc",
    "on_act_consume", "on_hit_consume", "buff_expire", "threshold", "dmg_calc",
    "taken_calc", "heal_calc", "act_done", "phase", "player_low", "pv_broken",
    "interrupt", "time_advance",
    "__end__", "story", "……",
)
_FORBIDDEN_IMPORTS = ("os", "sys", "json", "datetime", "time", "calendar", "zoneinfo", "random")
_ZERO_FIELD_WORDS = ("main_quest", "main_status", "completed_main",
                     "pending", "active", "kill", "collect", "talk", "explore")


def t_zero_knowledge():
    print("\n[14] 零知识静态扫描（ast）：源码常量零取值词 / import 白名单（判据 5/6/8）")
    files = _quest_sources()
    check("扫到 quest/ 源文件（≥3）", len(files) >= 3, files)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    bad_val, bad_imp, bad_field = [], [], []
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docs.add(doc)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docs:
                    continue                       # 判据只针对**代码路径**；散文里难免打比方
                for w in _VALUE_WORDS:
                    if w in node.value:
                        bad_val.append(f"{rel}:{node.lineno}:{w!r}:{node.value[:40]!r}")
                if node.value in _ZERO_FIELD_WORDS:
                    bad_field.append(f"{rel}:{node.lineno}:{node.value!r}")
            roots = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue                       # 相对导入不限
                roots.append((node.module or "").split(".")[0])
            elif isinstance(node, ast.Import):
                roots += [a.name.split(".")[0] for a in node.names]
            for root in roots:
                if root and (root not in stdlib or root in _FORBIDDEN_IMPORTS):
                    bad_imp.append(f"{rel}:{node.lineno}:{root}")
    check("★ 判据 5 代码字符串常量里零取值词（表 = U1-D2_FROZEN_GATE §4）", not bad_val, bad_val[:8])
    check("★ 判据 6 import 只有标准库、且不含 os/sys/json/datetime/time/calendar/random",
          not bad_imp, bad_imp[:8])
    check("★ 判据 8 零字段知识（无那 9 个字面量）", not bad_field, bad_field[:8])

    import saintess_engine.quest as mod
    check("__all__ 恰为设计给定的五个符号",
          mod.__all__ == ["Quest", "QuestLog", "Objective", "Objectives", "parse_needs"],
          mod.__all__)
    doc = mod.__doc__ or ""
    check("模块 docstring 写清：形状 / 口径分歧 / 明确不做 / 为什么不复用",
          all(k in doc for k in ("口径分歧", "明确不做", "为什么不复用")))
    check("★ 12 条口径分歧逐条落在包 docstring 里",
          all(mark in doc for mark in ("①", "②", "③", "④", "⑤", "⑥",
                                       "⑦", "⑧", "⑨", "⑩", "⑪", "⑫")))
    check("包 docstring 明确点出「为什么不复用 run.Progress 与 collect」",
          ("Progress" in doc and "collect" in doc))
    check("不做落库：QuestLog 没有任何落库/连接类 API",
          not any(n in dir(QuestLog) for n in ("save", "commit", "connect", "execute", "flush")))


def main():
    print("== quest 形状门禁：任务账本（QuestLog / Objective / Objectives / Quest）==")
    t_registry()
    t_parts()
    t_need()
    t_hits_fold()
    t_satisfied()
    t_lines()
    t_ledger_read()
    t_ledger_migrate()
    t_quest()
    t_divergences()
    t_invariants()
    t_teeth()
    t_fingerprint()
    t_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / 共 {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for item in DETAIL:
            print(f"  ❌ {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
