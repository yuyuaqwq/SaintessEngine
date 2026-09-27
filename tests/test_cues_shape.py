#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：表现事件（cue）形状 —— 订阅表 / 装配期对账 / emit 三条硬规矩 / 端到端。

为什么需要它（cue 解耦 B1）
--------------------------
结算函数原先「算值 → 选模板 → 填槽位 → 决定顺序」写在同一条语句里。cue 解耦把
「玩家看到什么」从结算里拆出来：结算只发事实，表现由订阅方渲染（`saintess_engine/cues.py`）。
拆出来的同时必须钉住四件事，否则解耦会静默地改变玩家看到的东西：

  1. **装配期对账有牙**：已声明的 cue 缺订阅 / 订阅表里有引擎不认的名字 /
     同一 cue 声明 ≥2 个 text 订阅者 ⇒ **抛**（不是警告）；
  2. **运行期 fail-closed**：`emit` 时该 cue 没有订阅者 ⇒ 抛（`strict=False` 诊断面才降级成一行坏数据）；
  3. **只读契约 + 坏回执**：`call` 订阅者产出日志行必须显式声明 `emits_lines`；
     回执形状不是 None/str/序列 ⇒ 抛；payload 必须**只读**（引擎给副本）；
  4. **端到端**：真调用点（`landing` 的闪避 / 元素免疫）在装配了订阅表之后**真的走 emit**，
     而**输出逐字节等于**迁移前的兜底模板（零回归），并且顺序 = 订阅者声明序。

跑法：python tests/test_cues_shape.py（exit=0 全绿）
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine import config as CFG                                   # noqa: E402
from saintess_engine.cues import (CueBus, CueContractError, audit_subs,     # noqa: E402
                                  build_bus, normalize_subs)
from ext_combat.battle.cues import CUE_NAMES                                # noqa: E402

passed = failed = 0

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed")


def _raises(fn, exc=CueContractError):
    """跑 `fn`，期待抛 `exc`；返回异常消息（没抛返回 None）。"""
    try:
        fn()
    except exc as e:
        return str(e)
    except Exception as e:                                   # noqa: BLE001
        return "<别的异常 %s: %s>" % (type(e).__name__, e)
    return None


# ============================================================
# 1. 订阅表规范化（形状不对 = 当场现形）
# ============================================================
print("\n【1. 订阅表规范化】")
check("★ 合规表 → 规范化成 {名: (订阅者,)}",
      normalize_subs({"a": {"kind": "text", "key": "a"}}) == {"a": ({"kind": "text", "key": "a"},)},
      str(normalize_subs({"a": {"kind": "text", "key": "a"}})))
check("非映射（列表）⇒ 抛", _raises(lambda: normalize_subs(["a"])) is not None)
check("空名字 ⇒ 抛", _raises(lambda: normalize_subs({"": {"kind": "text", "key": "k"}})) is not None)
check("未知 kind ⇒ 抛", _raises(lambda: normalize_subs({"a": {"kind": "sound"}})) is not None)
check("text 缺 key ⇒ 抛", _raises(lambda: normalize_subs({"a": {"kind": "text"}})) is not None)
check("call 的 handler 是字符串（没解析）⇒ 抛",
      _raises(lambda: normalize_subs({"a": {"kind": "call", "handler": "pkg.mod:fn"}})) is not None)
check("空订阅者序列 ⇒ 抛", _raises(lambda: normalize_subs({"a": ()})) is not None)

# ============================================================
# 2. 装配期对账（三种缺口都要有牙）
# ============================================================
print("\n【2. 装配期对账】")
_NAMES = ("x.a", "x.b", "x.c")
_ok = {"x.a": {"kind": "text", "key": "x.a"}, "x.b": {"kind": "text", "key": "x.b"},
       "x.c": {"kind": "text", "key": "x.c"}}
check("齐全 ⇒ 零问题", audit_subs(_NAMES, normalize_subs(_ok)) == [],
      str(audit_subs(_NAMES, normalize_subs(_ok))))
_miss = dict(_ok)
_miss.pop("x.b")
_p = audit_subs(_NAMES, normalize_subs(_miss))
check("★ 缺订阅 ⇒ 点名缺口 + 条数", len(_p) == 1 and "x.b" in _p[0] and "共 1 条" in _p[0], str(_p))
_p2 = audit_subs(_NAMES, normalize_subs(dict(_ok, **{"x.zzz": {"kind": "text", "key": "k"}})))
check("★ 订阅表里有引擎不认的名字 ⇒ 现形", len(_p2) == 1 and "x.zzz" in _p2[0], str(_p2))
_p3 = audit_subs(_NAMES, normalize_subs(dict(_ok, **{"x.a": (
    {"kind": "text", "key": "x.a"}, {"kind": "text", "key": "x.a2"})})))
check("★ 同一 cue 两个 kind=text ⇒ 现形（一行会变多行）",
      len(_p3) == 1 and "kind=text" in _p3[0], str(_p3))

# ============================================================
# 3. emit 三条硬规矩（同步就地 / 只读契约 / 坏回执）
# ============================================================
print("\n【3. emit：同步就地 · 只读契约 · 坏回执】")
_seen: list = []


def _probe(payload):
    _seen.append(payload)
    return None


class _Table:
    """鸭子类型同内容侧文案表（`render_or(key, default, **slots)`）。"""

    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def render_or(self, key, default, /, **slots):
        tpl = self.mapping.get(key, default)
        return tpl.format(**slots) if slots else tpl


_bus = CueBus(normalize_subs({
    "x.a": ({"kind": "text", "key": "x.a"}, {"kind": "call", "handler": _probe}),
}), table=_Table({"x.a": "T:{n}"}))
_logs: list = ["头"]
_bus.emit(_logs, "x.a", "D:{n}", {"n": 7})
check("★ 就地 append + 顺序 = 订阅者声明序（先 text 后 call，头行不动）",
      _logs == ["头", "T:7"], str(_logs))
check("call 订阅者的回执 None ⇒ 不产出行", len(_seen) == 1 and _seen[0] == {"n": 7}, str(_seen))

_ret_ok = CueBus(normalize_subs({"x.a": {"kind": "call", "handler": lambda p: ["行1", "行2"],
                                          "emits_lines": True}}))
_l2: list = []
_ret_ok.emit(_l2, "x.a", "", {})
check("call + emits_lines=True ⇒ 回执逐条 append（不是拼成一行）", _l2 == ["行1", "行2"], str(_l2))

check("★ call 产出日志行却没声明 emits_lines ⇒ 抛（只读契约）",
      _raises(lambda: CueBus(normalize_subs(
          {"x.a": {"kind": "call", "handler": lambda p: "偷偷加一行"}}
      )).emit([], "x.a", "", {})) is not None)
check("★ 坏回执（返回 int）⇒ 抛", _raises(lambda: CueBus(normalize_subs(
    {"x.a": {"kind": "call", "handler": lambda p: 3, "emits_lines": True}}
)).emit([], "x.a", "", {})) is not None)

_payload = {"n": 1}
_cap: list = []


def _peek(p):
    _cap.append(p)
    p["n"] = 999          # 订阅者乱改：引擎给的必须是**副本**
    return None


CueBus(normalize_subs({"x.a": {"kind": "call", "handler": _peek}})).emit([], "x.a", "", _payload)
check("★ payload 只读（引擎给副本：订阅者改它不影响调用方）",
      _cap[0] is not _payload and _payload == {"n": 1},
      "副本=%s 原件=%s 同一个对象=%s" % (_cap[0], _payload, _cap[0] is _payload))

_nostrict = CueBus({}, strict=False)
_l3: list = []
_nostrict.emit(_l3, "x.a", "", {})
check("strict=False（诊断面）⇒ 不崩，写一条可读坏数据行",
      _l3 == ["x.a 无订阅者（装配缺口）"], str(_l3))
try:
    CueBus({}, strict=True).emit([], "x.a", "", {})
    _strict_raised = None
except Exception as e:                                       # noqa: BLE001
    _strict_raised = type(e).__name__ + ": " + str(e)
check("★ strict=True 运行期缺订阅 ⇒ 抛 EngineNotConfigured（点名 cue）",
      _strict_raised is not None and "EngineNotConfigured" in _strict_raised
      and "x.a" in _strict_raised, str(_strict_raised))

# ============================================================
# 4. 装载口（config hook `cue_subs_fn`）
# ============================================================
print("\n【4. 装载口 cue_subs_fn】")
_saved = CFG._HOOKS.get("cue_subs_fn")
try:
    CFG._HOOKS["cue_subs_fn"] = None
    check("★ 不装配 ⇒ None（不问 strict：这款游戏不用 cue 是合法状态）",
          build_bus(_NAMES) is None)
    CFG._HOOKS["cue_subs_fn"] = lambda: _ok
    _b = build_bus(_NAMES, strict=True)
    check("装了且齐全 ⇒ 建出总线", isinstance(_b, CueBus) and len(_b.subs) == 3)
    CFG._HOOKS["cue_subs_fn"] = lambda: _miss
    _msg = _raises(lambda: build_bus(_NAMES, strict=True))
    check("★ 装了但缺一条 ⇒ 装配期抛，且消息点名缺的那条",
          _msg is not None and "x.b" in _msg and "缺订阅" in _msg, str(_msg))
    _b2 = build_bus(_NAMES, strict=False)
    check("strict=False ⇒ 不抛，问题落在 bus.problems（诊断面可读）",
          isinstance(_b2, CueBus) and bool(_b2.problems), str(getattr(_b2, "problems", None)))
finally:
    CFG._HOOKS["cue_subs_fn"] = _saved

# ============================================================
# 5. 端到端：真调用点（landing 的闪避）真走 emit，且输出逐字不变
# ============================================================
print("\n【5. 端到端（真调用点 × 真装配）】")
from ext_combat import Battle, make_actor                             # noqa: E402
from ext_combat.battle import landing as L                            # noqa: E402

_hits: list = []


def _count(payload):
    _hits.append(dict(payload))
    return None


_SUBS_E2E = {n: ({"kind": "text", "key": n},) for n in CUE_NAMES}
_SUBS_E2E["battle.landing.dodged"] = ({"kind": "text", "key": "battle.landing.dodged"},
                                      {"kind": "call", "handler": _count})
_saved2 = CFG._HOOKS.get("cue_subs_fn")
_saved3 = CFG._HOOKS.get("formula_skeleton_fn")
try:
    CFG._HOOKS["cue_subs_fn"] = lambda: _SUBS_E2E
    # 让「必闪」确定：闪避上限本来读内容侧骨架表（未装配 ⇒ 0.40）⇒ 本测试自己声明 1.0
    CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
    _me = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                     level=5, hp=100, max_hp=100, spd=50)
    _foe = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                      hp=100, max_hp=100, spd=50, dodge=1.0)
    _b = Battle(sides={"player": [_me], "enemy": [_foe]}, seed_ct=False)
    check("★ 装配过订阅表 ⇒ Battle 带总线", _b.cues is not None)
    _lg: list = []
    _got = L.deal_damage(_b, _me, _foe, 30, _lg)
    check("真调用点发出去了（订阅者被调用 = 走的是 emit，不是旧路）",
          len(_hits) == 1 and "name" in _hits[0], "%s / dmg=%s" % (_hits, _got))
    check("★ 输出逐字节 = 迁移前的兜底模板（未注入文案表 ⇒ 回落）",
          _lg == ["💨 乙 闪避了攻击！"], str(_lg))
    check("闪避 ⇒ 本次不扣血", int(_foe["hp"]) == 100 and _got == 0, "%s / %s" % (_foe["hp"], _got))
finally:
    CFG._HOOKS["cue_subs_fn"] = _saved2
    CFG._HOOKS["formula_skeleton_fn"] = _saved3

# 不装配时（过渡态）同一个调用点必须落回旧路、输出一字不变
_saved4 = CFG._HOOKS.get("formula_skeleton_fn")
try:
    CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
    _me2 = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                      level=5, hp=100, max_hp=100, spd=50)
    _foe2 = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                       hp=100, max_hp=100, spd=50, dodge=1.0)
    _b2 = Battle(sides={"player": [_me2], "enemy": [_foe2]}, seed_ct=False)
    _lg2: list = []
    L.deal_damage(_b2, _me2, _foe2, 30, _lg2)
    check("★ 未装配（过渡态）⇒ 落回原路，输出同样逐字不变",
          _b2.cues is None and _lg2 == ["💨 乙 闪避了攻击！"], "%s / %s" % (_b2.cues, _lg2))
finally:
    CFG._HOOKS["formula_skeleton_fn"] = _saved4

# ============================================================
# 6. 内容侧声明与引擎声明**同源**（示例包的表必须覆盖 CUE_NAMES）
# ============================================================
print("\n【6. 示例包声明覆盖引擎 CUE_NAMES】")
_p = os.path.join(_ROOT, "examples", "minimal-game", "content", "cues.py")
_spec = importlib.util.spec_from_file_location("_minimal_cues", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
check("★ 引擎 CUE_NAMES 全部被示例包声明（缺一条 ⇒ 装配期会抛）",
      audit_subs(CUE_NAMES, normalize_subs(_mod.SUBS)) == [],
      str(audit_subs(CUE_NAMES, normalize_subs(_mod.SUBS))))
check("示例包不多声明引擎不认的名字（拼写漂移现形）",
      not [k for k in _mod.SUBS if k not in CUE_NAMES], str(sorted(_mod.SUBS)))
check("CUE_NAMES 无重复（同名即接口）", len(set(CUE_NAMES)) == len(CUE_NAMES), str(CUE_NAMES))

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
