# -*- coding: utf-8 -*-
"""标签机制（tag）门禁：注册表 / 统一查询面 / 层级 / 槽位名 / 两个散点收口。

一套 = GAS `GameplayTag` 那三件东西（`extends/ext_combat/battle/tags.py`）：
  ① 注册表（名字由内容侧声明：EFFECT_RULES 的键 + 引擎固定词汇表的槽位名）
  ② 授予（traits ∪ effects 条目 key ∪ 条目 grants）= 查询口合成的一个面；撤销 = 条目没了即没了
  ③ 查询：`has`（父级查得到子级）/ `has_exact` / `has_any` / `has_all`；`slot()` 取槽位名

反证（改的时候手验过，本文件把它们钉住）：
  · 把 `tags.name_match` 的前缀分支去掉 ⇒ ③ 的层级断言变红；
  · 把 `effects.py` 控制免疫点的槽位读改回写死 `cc_immune` ⇒ ⑤ 的「换名」断言变红；
  · 把 `tags.of` 的 grants 来源去掉 ⇒ ② 的授权断言变红。

跑法：python tests/test_tags.py
"""
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_tags.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from ext_combat.battle import tags                              # noqa: E402
from ext_combat.battle import effects as EFF                     # noqa: E402
from ext_combat.battle import landing as LND                     # noqa: E402
from ext_combat.battle import traits as TR                       # noqa: E402
from ext_combat.battle import game_config as GC                  # noqa: E402
from ext_combat.battle.actors import make_actor, open_entry      # noqa: E402
from ext_combat.battle.battle import Battle                      # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                    # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# ★ B2（2026-09-27）：已迁移点位（含 `battle.landing.woken`「惊醒」那一行）的措辞真源在
#   **内容侧文案表**，引擎模板已删 ⇒ 合成战斗必须自己注入「订阅表 + 文案表」，
#   否则那一行是坏数据行（本文件不接任何内容包）。`_cue_text_fixture` = 门禁夹具（不是真源）。
from _cue_text_fixture import TEXT as FIX_TEXT                    # noqa: E402
from _cue_text_fixture import install as fix_install              # noqa: E402

fix_install()

from saintess_engine import config as CFG                        # noqa: E402

_saved_slots = CFG._HOOKS.get("tag_slots_fn")
_saved_rules = GC.get_effect_rules()


def _mk(uid, side, **kw):
    return make_actor(uid, uid, side, **{"hp": 100, "max_hp": 100, "atk": 10,
                                         "spd": 50, "stats_spd": 50, **kw})


def _bt(a, b):
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]}, seed_ct=False,
                  text=FIX_TEXT)


def _rules(mapping):
    """临时挂一张效果声明表（DOT 免疫那一支要看 `period.dir`）。"""
    GC.load_game_rules(types.SimpleNamespace(EFFECT_ACTIONS={}, EFFECT_RULES=mapping))


# ============================================================
# ① 注册表：声明过的名字登记进来
# ============================================================
print("\n【① 注册表：内容侧声明 → 登记】")
tags.reset_registry()
check("① 清空后是空的（reset 可用）", tags.registered() == frozenset(), str(tags.registered()))
tags.register_many(["burn", "control.stun", "", None])
check("① 登记只收非空名（空/None 忽略）",
      tags.registered() == frozenset({"burn", "control.stun"}), str(tags.registered()))
_rules({"burn_z": {"period": {"dir": "damage"}}, "freeze_z": {}})
check("① 装载效果表 ⇒ 声明过的键自动进注册表（load_game_rules 那一挂）",
      {"burn_z", "freeze_z"} <= set(tags.registered()), str(sorted(tags.registered())))
check("① 引擎固定词汇表的槽位名也在注册表里（缺省即登记）",
      set(tags.DEFAULT_SLOTS.values()) <= set(tags.registered()), str(sorted(tags.registered())))

# ============================================================
# ② 统一查询面：traits ∪ 容器 key ∪ grants
# ============================================================
print("\n【② 统一面：三个来源一个查询】")
a = _mk("a1", "player", traits=["boss"])
open_entry(a, "burn", stacks=2)
open_entry(a, "shout", stacks=1, grants=["debuff.mark"])
check("② traits 来源", tags.has(a, "boss"), str(sorted(tags.of(a))))
check("② effects 条目 key 来源", tags.has(a, "burn"), str(sorted(tags.of(a))))
check("② grants 来源（一条状态授多个 tag）", tags.has(a, "debuff.mark"), str(sorted(tags.of(a))))
check("② sources_of 能点名来源（排障面）",
      tags.sources_of(a, "boss") == ("traits",)
      and tags.sources_of(a, "burn") == ("effects",)
      and tags.sources_of(a, "debuff.mark") == ("grants",),
      "%s / %s / %s" % (tags.sources_of(a, "boss"), tags.sources_of(a, "burn"),
                        tags.sources_of(a, "debuff.mark")))
check("② 撤销 = 条目没了即没了（不另开接口）",
      (a["effects"].pop("shout", None) is not None) and not tags.has(a, "debuff.mark"),
      str(sorted(tags.of(a))))
check("② 只身份标签来源（`traits.of` 那条路）不掺状态标签",
      set(tags.of(a, sources=("traits",))) == {"boss"}, str(tags.of(a, sources=("traits",))))

# ============================================================
# ③ 层级：父级查得到子级
# ============================================================
print("\n【③ 层级：父级 → 子级】")
c = _mk("c1", "player")
open_entry(c, "control.stun", stacks=1, grants=["debuff.slow.deep"])
check("③ 查父级 `control` 命中 `control.stun`", tags.has(c, "control"), str(sorted(tags.of(c))))
check("③ 查子级精确也命中", tags.has(c, "control.stun"), str(sorted(tags.of(c))))
check("③ 不做反向命中（有 `control.stun` 不等于有 `control.stun.deeper`）",
      not tags.has(c, "control.stun.deeper"), str(sorted(tags.of(c))))
check("③ 点边界：`controlx` / `contro` 都不命中",
      not tags.has(c, "controlx") and not tags.has(c, "contro"), str(sorted(tags.of(c))))
check("③ grants 也走层级（`debuff` 命中 `debuff.slow.deep`）",
      tags.has(c, "debuff"), str(sorted(tags.of(c))))
check("③ has_exact 只认精确",
      tags.has_exact(c, "control.stun") and not tags.has_exact(c, "control"),
      str(sorted(tags.of(c))))
check("③ has_any / has_all（空名单 ⇒ False，不恒真）",
      tags.has_any(c, ["nope", "control"]) and tags.has_all(c, ["control", "debuff"])
      and not tags.has_any(c, []) and not tags.has_all(c, []))
check("③ ancestors / root_of / name_match 三个结构件",
      tags.ancestors("control.stun.deep") == ("control.stun.deep", "control.stun", "control")
      and tags.root_of("control.stun.deep") == "control"
      and tags.name_match("control.stun", "control")
      and not tags.name_match("control", "control.stun"))
check("③ traits 面保持**精确**（扁平名不受层级影响：现行行为一字不动）",
      TR.has(a, "boss") and not TR.has(a, "bos") and TR.has_any(a, ["boss", "nope"]),
      str(TR.of(a)))

# ============================================================
# ④ 槽位：引擎固定词汇表 ↔ 具体 tag 名
# ============================================================
print("\n【④ 槽位：名字归内容侧声明】")
check("④ 未装配 ⇒ 内建缺省", tags.slot("immune_control") == "cc_immune"
      and tags.slot("immune_dots") == "immune_dots", str(tags.DEFAULT_SLOTS))
CFG.mount(tag_slots_fn=lambda: {"immune_control": "immune.x"})
check("④ 装配面声明 ⇒ 按声明取名字", tags.slot("immune_control") == "immune.x")
CFG.mount(tag_slots_fn=lambda: {})
check("④ 装配面给空 dict ⇒ 回落缺省（不静默改语义）",
      tags.slot("immune_control") == "cc_immune")
try:
    tags.slot("no_such_slot")
    _raised = False
except KeyError:
    _raised = True
check("④ 未知名 ⇒ KeyError（fail-closed：引擎不猜名字）", _raised)
CFG.mount(tag_slots_fn=lambda: {"immune_control": "immune.x"})

# ============================================================
# ⑤ 收口有牙：控制免疫点真的走槽位（端到端）
# ============================================================
print("\n【⑤ 控制免疫点：走槽位 + 层级】")
hero, foe = _mk("h1", "player"), _mk("f1", "enemy")
bt = _bt(hero, foe)
bt._now = 5.0
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("⑤ 无免疫态 ⇒ 控制照常落下",
      "stun_x" in hero["effects"] and not any("免疫控制" in x for x in lg), "%s / %s" % (hero["effects"], lg))

hero["effects"].pop("stun_x", None)
hero["effects"]["immune.x"] = {"expire": 9.0}          # 槽位已指向 immune.x
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("⑤ 槽位名下的免疫态 ⇒ 控制不施加（+ 出免疫那一行）",
      "stun_x" not in hero["effects"] and any("免疫控制" in x for x in lg), "%s / %s" % (hero["effects"], lg))

hero["effects"].pop("immune.x", None)
hero["effects"]["immune.x.aura"] = {"expire": 9.0}     # 子级名
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("★ ⑤ 层级：写了子级名 `immune.x.aura` 也吃（父级查得到子级）",
      "stun_x" not in hero["effects"] and any("免疫控制" in x for x in lg), "%s / %s" % (hero["effects"], lg))

hero["effects"].pop("immune.x.aura", None)
hero["effects"]["cc_immune"] = {"expire": 9.0}         # 旧名，槽位已换 ⇒ 不再拦
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("★ ⑤ 换名生效（旧名不再拦 ⇒ 证明判定真读槽位，不是写死串）",
      "stun_x" in hero["effects"] and not any("免疫控制" in x for x in lg), "%s / %s" % (hero["effects"], lg))

CFG._HOOKS["tag_slots_fn"] = lambda: {}
hero["effects"].pop("stun_x", None)
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("⑤ 回落缺省名 ⇒ 旧名 `cc_immune` 又拦得住（缺省行为与设计前逐字一致）",
      "stun_x" not in hero["effects"] and any("免疫控制" in x for x in lg), "%s / %s" % (hero["effects"], lg))

# 到期的那条（时间过去了 ⇒ 不再免疫）
hero["effects"]["cc_immune"] = {"expire": 1.0}
hero["effects"].pop("stun_x", None)
lg = []
EFF.act_apply(bt, foe, hero, {"key": "stun_x", "mode": "skip", "turns": 3, "on": "target"}, lg)
check("⑤ 免疫态已过期（expire < now）⇒ 控制照常落下",
      "stun_x" in hero["effects"], "%s / %s" % (hero["effects"], lg))

# ============================================================
# ⑥ DOT 免疫名单也走槽位
# ============================================================
print("\n【⑥ DOT 免疫名单：名字走槽位】")
_rules({"burn_z": {"period": {"dir": "damage"}}})
holder, caster = _mk("h2", "player"), _mk("c2", "enemy")
bt2 = _bt(holder, caster)
holder[tags.slot("immune_dots")] = ["burn_z"]
lg = []
EFF.act_apply(bt2, caster, holder, {"key": "burn_z", "turns": 3, "on": "target"}, lg)
check("⑥ 缺省槽位名下的名单拦得住（现行行为）",
      "burn_z" not in holder["effects"] and any("免疫" in x for x in lg), "%s / %s" % (holder["effects"], lg))

CFG._HOOKS["tag_slots_fn"] = lambda: {"immune_dots": "immune.dots"}
holder[tags.slot("immune_dots")] = ["burn_z"]
lg = []
EFF.act_apply(bt2, caster, holder, {"key": "burn_z", "turns": 3, "on": "target"}, lg)
check("★ ⑥ 换名后名单跟着换（同一个名单，新名字下照拦）",
      "burn_z" not in holder["effects"] and any("免疫" in x for x in lg), "%s / %s" % (holder["effects"], lg))

# ============================================================
# ⑦ 声明层级继承：前缀带行为（子级只写差异）
# ============================================================
print("\n【⑦ 声明层级继承：前缀带行为】")
_rules({"control": {"consume": {"mode": "skip"}},
        "control.stun": {"consume": {"mode": "no_skill"}},
        "status": {"wake_on_hit": True}})
_r1, _s1 = tags.rule_of("control.stun")
check("⑦ 精确声明优先（子级自己声明过就用自己那份）",
      (_r1.get("consume") or {}).get("mode") == "no_skill" and _s1 == "control.stun",
      "%s / %s" % (_r1, _s1))
_r2, _s2 = tags.rule_of("control.freeze")
check("★ ⑦ 子级没声明 ⇒ 继承父级（前缀带行为）",
      (_r2.get("consume") or {}).get("mode") == "skip" and _s2 == "control",
      "%s / %s" % (_r2, _s2))
_r3, _s3 = tags.rule_of("nope.nothing")
check("⑦ 全都没有 ⇒ 空声明（不声明 = 不适用，零兜底）",
      _r3 == {} and _s3 is None, "%s / %s" % (_r3, _s3))
_r4, _s4 = tags.rule_of("control")
check("⑦ 父级自身照常精确命中（层级查询不削一级）", _s4 == "control", str(_s4))
check("⑦ 空 tag ⇒ 空声明", tags.rule_of("") == ({}, None))

h3, f3 = _mk("h3", "player"), _mk("f3", "enemy")
bt3 = _bt(h3, f3)
bt3._now = 1.0
lg = []
EFF.act_apply(bt3, f3, h3, {"key": "control.freeze", "turns": 3, "on": "target"}, lg)
check("★ ⑦ 端到端：父级声明了消费方式 ⇒ 子级 tag 落地即**控制条目**（引擎只按前缀查表）",
      (h3["effects"].get("control.freeze") or {}).get("mode") == "skip",
      "%s / %s" % (h3["effects"], lg))

h4, f4 = _mk("h4", "player"), _mk("h4b", "enemy")
bt4 = _bt(h4, f4)
open_entry(h4, "status.sleep", stacks=1)
lg = []
LND.deal_damage(bt4, f4, h4, 1, lg)
check("★ ⑦ 端到端：父级声明 wake_on_hit ⇒ 子级状态被攻击打醒并移除（另一条读点也吃前缀）",
      "status.sleep" not in h4["effects"] and any("惊醒" in x for x in lg),
      "%s / %s" % (h4["effects"], lg))

# ============================================================
if _saved_slots is None:
    CFG._HOOKS.pop("tag_slots_fn", None)
else:
    CFG._HOOKS["tag_slots_fn"] = _saved_slots
GC.load_game_rules(types.SimpleNamespace(EFFECT_ACTIONS={}, EFFECT_RULES=_saved_rules))
print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
if FAILURES:
    print("失败明细：")
    for _x in FAILURES:
        print("  - " + _x)
sys.exit(1 if FAIL else 0)
