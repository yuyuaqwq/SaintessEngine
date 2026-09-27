# -*- coding: utf-8 -*-
"""属性写口（attributes）门禁：唯一写入口 / 内建边界 / 两个钩子 / 禁止引擎直写 / 反证。

一套 = 「属性只有一个写入口 + 预改钩子 + 后改钩子」（`extends/ext_combat/battle/attributes.py`），
照外部框架（GAS 的 AttributeSet）那条思路落成本引擎的形状。四处专门钉住的地方：

  ① **词表**：只有 `hp`/`mp`/`ct` 能走写口；别的 key ⇒ `KeyError`（走错地方当场炸）
  ② **内建边界**：`hp`→[0,max_hp] · `mp`→[0,max_mp] · `ct`→≥0；**类型保持**（int 进 int 出）
  ③ **两个钩子**：预改（装了才进；返回 None = 交回内建）· 后改（只在真变时调用；抛错上抛）
  ④ **机器门禁**：引擎代码里**不得再出现** `["hp"] =` / `["mp"] =` / `["ct"] =` 直写
     （白名单只有一处报价 dict）—— "漏改一处"就靠它当场红

反证（改的时候手验过，本文件把它们钉住）：
  · 把 `attributes._clamp` 的 `hi` 分支改坏 ⇒ ② 的钳制断言变红（`_variant` 内存改坏，见 §⑧）
  · 把后改钩子的调用去掉 ⇒ ⑤/⑥ 的记账断言变红
  · 把某个写点改回裸写 ⇒ ④ 的机器门禁变红

跑法：python tests/test_attrs_write_port.py
"""
import io
import os
import re
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_attrs.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from ext_combat.battle import attributes as ATTR                  # noqa: E402
from ext_combat.battle import landing as LND                      # noqa: E402
from ext_combat.battle import actions as ACT                      # noqa: E402
from ext_combat.battle.actors import make_actor                   # noqa: E402
from ext_combat.battle.battle import Battle                       # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                     # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

from saintess_engine import config as CFG                         # noqa: E402

_saved_pre = CFG._HOOKS.get("attr_pre_fn")
_saved_post = CFG._HOOKS.get("attr_post_fn")
_saved_base = CFG._HOOKS.get("action_base_fn")
_saved_tm = CFG._HOOKS.get("time_model_fn")
# ★ 2026-09-27（cue 解耦 B0–B5 落地后）：战斗日志不再由引擎拼 —— 结算发**表现事件**，
#   措辞由内容侧订阅表 + 文案表渲染（`render_required` 必须命中）⇒ 本门禁要在**装了 cue**
#   的环境里跑，否则屏上只会是一行坏数据（那一行是给「内容侧没接」的包的提示，
#   不是「写口改了表现」）。装的是引擎自带的标准夹具（与 `test_battle_text_inject` 同源）。
_saved_subs = CFG._HOOKS.get("cue_subs_fn")
_saved_table = CFG._HOOKS.get("text_table_fn")
from _cue_text_fixture import SUBS as _FIX_SUBS, TEXT as _FIX_TEXT   # noqa: E402
CFG._HOOKS["cue_subs_fn"] = lambda: _FIX_SUBS
CFG._HOOKS["text_table_fn"] = lambda: _FIX_TEXT
_ATTR_SRC = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "attributes.py")

# ct 那条路要走内容侧声明的时间模型（引擎零数值）⇒ 本门禁临时装两个桩（用完还原）。
# 装桩不违反「不配 = 不存在」：这里正是要验**装配之后**写口仍然被走到。
CFG._HOOKS["action_base_fn"] = lambda action: 100.0
CFG._HOOKS["time_model_fn"] = lambda spd, base: 120.0


def _mk(uid, side, **kw):
    return make_actor(uid, uid, side, **{"hp": 100, "max_hp": 100, "mp": 30, "max_mp": 30,
                                         "atk": 10, "spd": 50, "stats_spd": 50, **kw})


def _bt(a, b):
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]}, seed_ct=False)


def _hook_pre(fn):
    CFG._HOOKS["attr_pre_fn"] = fn


def _hook_post(fn):
    CFG._HOOKS["attr_post_fn"] = fn


def _no_hooks():
    CFG._HOOKS["attr_pre_fn"] = None
    CFG._HOOKS["attr_post_fn"] = None


def _variant(anchor, repl):
    """内存里改坏一份拷贝（真源只读）—— 反证用。"""
    src = io.open(_ATTR_SRC, encoding="utf-8").read()
    assert src.count(anchor) == 1, "锚点必须唯一命中：%r" % anchor
    ns = types.ModuleType("attrs_bad")
    ns.__file__ = _ATTR_SRC
    ns.__package__ = "ext_combat.battle"          # 不设它，相对 import 在 exec 时直接炸
    exec(compile(src.replace(anchor, repl), _ATTR_SRC, "exec"), ns.__dict__)
    return ns


def main():
    global PASS, FAIL
    print("=== 属性写口门禁 ===")

    # ① 词表与入口
    a = _mk("a", "player")
    check("① 引擎词表 = hp/mp/ct", ATTR.ATTRS == ("hp", "mp", "ct"), repr(ATTR.ATTRS))
    try:
        ATTR.set_current(a, "atk", 1)
        check("① 不在词表里的 key ⇒ KeyError（不许从写口进）", False, "没抛")
    except KeyError as e:
        check("① 不在词表里的 key ⇒ KeyError（不许从写口进）", "atk" in str(e), str(e))
    check("① current 缺字段 ⇒ 0（与今天各读点同口径）", ATTR.current({}, "hp") == 0)

    # ② 内建边界 + 类型保持
    _no_hooks()
    ATTR.set_current(a, "hp", 999)
    check("② hp 超上限 ⇒ 钳到 max_hp", a["hp"] == 100, repr(a["hp"]))
    ATTR.set_current(a, "hp", -50)
    check("② hp 为负 ⇒ 钳到 0", a["hp"] == 0, repr(a["hp"]))
    ATTR.set_current(a, "mp", 9999)
    check("② mp 超上限 ⇒ 钳到 max_mp", a["mp"] == 30, repr(a["mp"]))
    ATTR.set_current(a, "ct", 12345.5)
    check("② ct 无上限（时间轴不封顶）", a["ct"] == 12345.5, repr(a["ct"]))
    ATTR.set_current(a, "hp", 77)
    check("② 类型保持：int 进 int 出", isinstance(a["hp"], int) and a["hp"] == 77, repr(a["hp"]))
    ATTR.set_current(a, "ct", 5)
    check("② 类型保持：按**入参类型**落值（int 进 int 出；冻结对拍靠这条）",
          isinstance(a["ct"], int) and a["ct"] == 5, repr(a["ct"]))
    ATTR.set_current(a, "ct", 5.5)
    check("② 类型保持：float 进 float 出", isinstance(a["ct"], float) and a["ct"] == 5.5,
          repr(a["ct"]))
    b = _mk("b", "player")
    ATTR.add_current(b, "mp", -7)
    check("② add_current 走同一条口", b["mp"] == 23, repr(b["mp"]))
    # ★ 上限只在**抬值**方向生效：已越界的脏数据不被压回（实测 host_skeleton 的合成 fixture
    #   `hp=300 > max_hp=203` 会被严格上限翻掉胜负 ⇒ 那是数据的责任，不是写口的）
    dirty = {"hp": 300, "max_hp": 203}
    ATTR.set_current(dirty, "hp", 250)
    check("② 已越界的值不被压回（数据自己的责任）", dirty["hp"] == 250, repr(dirty["hp"]))
    ATTR.set_current(dirty, "hp", 400)
    check("② 但也不许往更高抬过边界（hi = max(上限, 现在值)，跟着现在值走）", dirty["hp"] == 250,
          repr(dirty["hp"]))

    # ③ 预改钩子（两态：装 / 不装）
    _no_hooks()
    b2 = _mk("b2", "player")
    ATTR.set_current(b2, "hp", 50)
    _base = b2["hp"]
    _hook_pre(lambda actor, key, value, ctx: value + 1 if key == "hp" else None)
    ATTR.set_current(b2, "hp", 50)
    check("③ 装了预改钩子 ⇒ 值被变换（+1）", b2["hp"] == _base + 1, "%s → %s" % (_base, b2["hp"]))
    _hook_pre(lambda actor, key, value, ctx: None)
    ATTR.set_current(b2, "hp", 50)
    check("③ 预改钩子答 None ⇒ 交回内建规则（原值）", b2["hp"] == 50, repr(b2["hp"]))
    _hook_pre(lambda actor, key, value, ctx: 10 ** 6 if key == "hp" else None)
    ATTR.set_current(b2, "hp", 50)
    check("③ 钩子返回值**仍过内建边界**（要破界请改上层机制）", b2["hp"] == 100, repr(b2["hp"]))
    _no_hooks()

    # ④ 后改钩子：只在真变时调用 + 异常上抛
    _no_hooks()
    seen = []
    _hook_post(lambda actor, key, old, new, ctx: seen.append((key, old, new, ctx.get("reason"))))
    c = _mk("c", "player")
    ATTR.set_current(c, "hp", 80, reason="probe")
    check("④ 值真变了 ⇒ 后改钩子被调用（带 old/new/reason）",
          seen == [("hp", 100, 80, "probe")], repr(seen))
    ATTR.set_current(c, "hp", 80, reason="probe")
    check("④ 值没变 ⇒ 不写、不叫钩子（幂等写入不留痕）", len(seen) == 1, repr(seen))
    _hook_post(lambda actor, key, old, new, ctx: (_ for _ in ()).throw(ValueError("坏钩子")))
    try:
        ATTR.set_current(c, "hp", 70, reason="probe")
        check("④ 后改钩子抛错 ⇒ 原样上抛（fail-closed，不吞）", False, "被吞了")
    except ValueError as e:
        check("④ 后改钩子抛错 ⇒ 原样上抛（fail-closed，不吞）", "坏钩子" in str(e), str(e))
    _no_hooks()

    # ⑤ 端到端：真战斗里每种 reason 都真实出现（记账口）
    seen2 = []
    _hook_post(lambda actor, key, old, new, ctx: seen2.append((key, ctx.get("reason"))))
    h, f = _mk("h", "player"), _mk("f", "enemy")
    bt = _bt(h, f)
    logs = []
    LND.deal_damage(bt, f, h, 30, logs)
    LND.heal_actor(bt, h, 15, logs)
    ACT._spend_skill_cost(h, {"mp": 5})
    bt._seed_ct_one(h)
    reasons = set(seen2)
    check("⑤ 伤害写点走写口（reason=damage）", ("hp", "damage") in reasons, repr(sorted(reasons)))
    check("⑤ 治疗写点走写口（reason=heal）", ("hp", "heal") in reasons, repr(sorted(reasons)))
    check("⑤ 扣蓝写点走写口（reason=cost）", ("mp", "cost") in reasons, repr(sorted(reasons)))
    check("⑤ 排程写点走写口（reason=schedule_seed）",
          ("ct", "schedule_seed") in reasons, repr(sorted(reasons)))
    check("⑤ 伤害行照常上屏（写口不改表现）",
          any("伤害" in x for x in logs), repr(logs))
    _no_hooks()

    # ⑥ 机器门禁：引擎里不得直写 hp/mp/ct
    rx = re.compile(r"""\[["'](hp|mp|ct)["']\]\s*=(?!=)""")
    allow_path = "extends/ext_combat/battle/actions.py"
    allow_anchor = 'out["mp"] = max(1,'
    hits = []
    for sub in ("extends", "saintess_engine"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(FW_ROOT, sub)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, FW_ROOT).replace("\\", "/")
                for i, line in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
                    if rx.search(line):
                        hits.append((rel, i, line.strip()))
    ap = os.path.join(FW_ROOT, allow_path)
    _atxt = io.open(ap, encoding="utf-8").read()
    check("⑥ 白名单锚点在 actions.py 里唯一命中（条数恒 1）",
          _atxt.count(allow_anchor) == 1, str(_atxt.count(allow_anchor)))
    _rest = [x for x in hits if not (x[0] == allow_path and allow_anchor in x[2])]
    check("⑥ 引擎代码里没有 hp/mp/ct 的直写（漏改一处 ⇒ 这里红）",
          _rest == [], repr(_rest))
    check("⑥ 扫出来的唯一命中就是那处报价 dict（不是 actor 属性）",
          len(hits) == 1, repr(hits))

    # ⑦ 反证：把内建上界分支改坏 ⇒ 钳制失效（有牙）
    bad = _variant("    if hi is not None:", "    if False:")
    _bx = {"hp": 100, "max_hp": 100}
    _good = ATTR.set_current(dict(_bx), "hp", 999)
    _bad = bad.set_current(dict(_bx), "hp", 999)
    check("⑦ 反证·真模块钳到上限", _good == 100, repr(_good))
    check("⑦ 反证·改坏 `hi` 分支后钳制失效（判据有牙）", _bad == 999, repr(_bad))

    print("\n===== 结果：通过 %d / 共 %d =====" % (PASS, PASS + FAIL))
    if FAILURES:
        for f_ in FAILURES:
            print("  ✗ %s" % f_)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        CFG._HOOKS["attr_pre_fn"] = _saved_pre
        CFG._HOOKS["attr_post_fn"] = _saved_post
        CFG._HOOKS["action_base_fn"] = _saved_base
        CFG._HOOKS["time_model_fn"] = _saved_tm
        CFG._HOOKS["cue_subs_fn"] = _saved_subs
        CFG._HOOKS["text_table_fn"] = _saved_table
