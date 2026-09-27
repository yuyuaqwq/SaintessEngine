# -*- coding: utf-8 -*-
"""状态容器（effects）**通用面**门禁：条目词表 / 唯一写入口 / 三类到期 / 查询口。

背景（2026-09-28「状态容器收口」）：防御姿态原来是一个**裸 bool 兄弟字段**（置位在
`_do_defend`、清理散在 `Battle.act` 与 `_on_actor_dead`）—— 到期没有任何地方声明，靠人记得清
（六路真人试玩查出来的缺陷就是这么来的：敲一次『防御』整场减半）。现在它只是容器里一条
**窗口条目** `effects["defend"] = {"stacks": 1, "until": "own_act"}`，容器本身的通用面如下：

  · 写：`actors.open_entry(actor, tag, stacks=…, expire=…, until=…, period=…, grants=…)`
        —— 引擎侧**唯一**写入口（只落声明了的字段；`open_window` = `until` 那一类的糖）
  · 到期：`expire` = 时刻（`schedule._settle_time_effects` 统一清）
          `until`  = 边界帧（那一帧的通用消费段 `consume_windows` 清）/ 离场（`drop_windows` 清）
          两者都无 = 常驻
  · 查：`has_tag(actor, tag)` = 引擎侧**唯一** tag 查询口（容器 key ∪ 条目 `grants`；
        层级 = `.` 边界前缀，查父级命中子级）

反证（改的时候手验过，本文件把它们钉住）：
  · `landing.deal_damage` 里的 `window_open(target, DEFEND_TAG)` 改坏 ⇒ ④ 减半当场失效
    （同一处改坏后 `Temp/gas-a` 的 5 组战斗采集脚本逐字节变红：6 手「格挡后」全没了）；
  · `Battle.act` 里的 `consume_windows(actor)` 注掉 ⇒ ④ 的「自己下一次行动即到期」变红
    （窗口黏住 ⇒ 到期之后那两手又减半，采集脚本同样逐字节变红）；
  · 往 actor 上塞**裸键/裸值**（不是容器条目）⇒ ④ 的减半**不发生**（唯一真源 = 容器条目；
    旧裸 bool 字段已全仓删除，连键名都不存在了）。

跑法：python tests/test_state_container.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_state_container.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from ext_combat.battle.actors import (DEFEND_TAG, WINDOW_FIELD, WINDOW_OWN_ACT,   # noqa: E402
                                      _MUTABLE_KEYS, has_tag, make_actor, open_entry,
                                      open_window, tags_of, window_open)
from ext_combat.battle.battle import ActCtx, Battle               # noqa: E402
from ext_combat.battle import landing as LND                      # noqa: E402
from ext_combat.battle import schedule as SCH                     # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                    # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# ★ B2（2026-09-27）：已迁移点位（`battle.landing.*` / `battle.landing.blocked_amount`…）
#   的措辞真源在**内容侧文案表**，引擎模板已删 ⇒ 合成战斗必须自己注入「订阅表 + 文案表」，
#   否则「格挡后」那一行会是坏数据行（本文件不接任何内容包）。
#   `_cue_text_fixture` = 门禁夹具（**不是真源**）。
from _cue_text_fixture import TEXT as FIX_TEXT                   # noqa: E402
from _cue_text_fixture import install as fix_install             # noqa: E402

fix_install()

# 引擎不内置时间模型（未装配即抛 `EngineNotConfigured` —— fail-closed 是设计）⇒
# 本测试自带最小一份（照 tests/test_cross_hand_state.py 的挂法）。
from saintess_engine import config as CFG                         # noqa: E402

_TIME_HOOKS = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn")
_saved_hooks = {n: CFG._HOOKS.get(n) for n in _TIME_HOOKS}
_saved_provider, _saved_strict = CFG._hook_provider, CFG.strict
CFG._hook_provider = None
CFG.strict = False
CFG.mount(time_model_fn=lambda spd, base: float(base) * (50.0 / max(float(spd or 0), 1.0)),
          action_base_fn=lambda a: 1.0 if a in ("attack", "skill", "defend") else 0.0,
          recover_model_fn=lambda spd, base: float(base),
          recover_base_fn=lambda a: 0.0)


def _mk(uid, side, human=False, hp=200):
    return make_actor(uid, uid, side, human_controlled=human,
                      **{"hp": hp, "max_hp": hp, "atk": 10, "matk": 10,
                         "def": 0, "mdef": 0, "spd": 50, "stats_spd": 50})


def _bt(a, b):
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]}, seed_ct=False,
                  text=FIX_TEXT)


# ============================================================
# ① 写入口：只落声明了的字段
# ============================================================
print("\n【① open_entry：唯一写入口，只落声明字段】")
a = _mk("c1", "player", hp=100)
e1 = open_entry(a, "res_x", stacks=3)
check("① 只给 stacks ⇒ 条目里只有 stacks（不塞 None 空键）",
      e1 == {"stacks": 3}, str(e1))
e2 = open_entry(a, "burn_y", stacks=2, expire=5.0,
                period={"dir": "damage", "interval": 1.0}, grants=["debuff.burn"])
check("① 四类属性一次落上（stacks / expire / period / grants）",
      e2.get("stacks") == 2 and e2.get("expire") == 5.0
      and (e2.get("period") or {}).get("dir") == "damage"
      and e2.get("grants") == ["debuff.burn"], str(e2))
open_entry(a, "res_x", stacks=7)
check("① 重复写同一个 tag = 覆盖（刷新语义归调用点）",
      (a["effects"].get("res_x") or {}).get("stacks") == 7, str(a["effects"].get("res_x")))
check("① 写口落进的是真容器（不是扔掉的一次性 dict）",
      a["effects"].get("burn_y") is e2, str(a["effects"]))

# ============================================================
# ② 三类到期：时刻 / 边界帧 / 常驻 + 离场
# ============================================================
print("\n【② 三类到期：时刻 / 边界帧 / 常驻 / 离场】")
b = _mk("e1", "enemy", hp=100)
bt = _bt(a, b)
open_entry(a, "timed", stacks=1, expire=2.0)
open_entry(a, "forever", stacks=1)
open_window(a, "win_x")
check("② 开窗口 = 容器里的条目（`until` 声明 + 读口）",
      window_open(a, "win_x") and (a["effects"]["win_x"] or {}).get(WINDOW_FIELD) == WINDOW_OWN_ACT,
      str(a["effects"].get("win_x")))

lg = []
bt._now = 1.5                                    # 未到点
SCH._settle_time_effects(bt, lg)
check("② 未到点不动：`expire` 还在未来 ⇒ 条目留着",
      "timed" in a["effects"], str(a["effects"]))
bt._now = 2.0                                    # 到点（`now >= expire`）
SCH._settle_time_effects(bt, lg)
check("② 时刻到期：到点被**统一结算段**清掉（expire）",
      "timed" not in a["effects"], str(a["effects"]))
check("② 常驻条目与窗口条目都不吃时间结算（expire 无值 ⇒ 不动）",
      "forever" in a["effects"] and window_open(a, "win_x"), str(a["effects"]))

bt.act(ActCtx(caster=a, action="attack"))
check("② 边界帧到期：`until=own_act` 在**自己行动那一帧**被通用消费段清掉",
      not window_open(a, "win_x"), str(a["effects"]))
check("② 同帧不动常驻条目（消费段按声明清，不是「清空容器」）",
      "forever" in a["effects"], str(a["effects"]))

open_window(a, "win_y")
_sch_logs = []
bt._on_actor_dead(a, _sch_logs)
check("② 离场（死亡）⇒ 窗口条目作废、常驻条目不动",
      not window_open(a, "win_y") and "forever" in a["effects"], str(a["effects"]))

# ============================================================
# ③ 查询口：tag（层级 + 授予标签）
# ============================================================
print("\n【③ has_tag：引擎侧唯一 tag 查询口（含层级与 grants）】")
q = _mk("q1", "player", hp=100)
open_entry(q, "mark_x", stacks=1, grants=["control.stun"])
check("③ 条目 key 本身查得到", has_tag(q, "mark_x"), str(tags_of(q)))
check("③ 层级：查父级 `control` 命中 `control.stun`", has_tag(q, "control"), str(tags_of(q)))
check("③ 层级：子级精确也命中", has_tag(q, "control.stun"), str(tags_of(q)))
check("③ 层级：不作反向命中（查 `control.stun` 不因有 `control` 而真）",
      not has_tag(q, "control.stun.extra"), str(tags_of(q)))
check("③ 层级按 `.` 边界：`controlx` 不算命中 `control`",
      not has_tag(q, "controlx"), str(tags_of(q)))
check("③ 空/未知 tag ⇒ False（不猜）",
      not has_tag(q, "") and not has_tag(q, "nope") and not has_tag(None, "nope"))
# ============================================================
# ④ 消费方：防御姿态（端到端 —— 收口后的唯一实例）
# ============================================================
print("\n【④ 防御姿态：容器窗口条目 → 减半 → 自己下一次行动到期】")
a3, b3 = _mk("a3", "player", human=True), _mk("b3", "enemy")
bt3 = _bt(a3, b3)
bt3._do_defend(ActCtx(caster=a3, action="defend"))
check("④ 敲『防御』⇒ 容器里有窗口条目（`until=own_act`）；可变状态格 = 播种表那套（无兄弟字段）",
      window_open(a3, DEFEND_TAG)
      and (a3["effects"][DEFEND_TAG] or {}).get(WINDOW_FIELD) == WINDOW_OWN_ACT
      and all(k in a3 for k in _MUTABLE_KEYS),
      str(a3.get("effects")))

_lg = []
_d1 = LND.deal_damage(bt3, b3, a3, 10, _lg)
check("④ 姿态期内挨打 ⇒ 减半（10 → 5）+ 出「格挡后」那一行",
      _d1 == 5 and any("格挡后" in x for x in _lg), "%s / %s" % (_d1, _lg))

a4, b4 = _mk("a4", "player", human=True), _mk("b4", "enemy")
bt4 = _bt(a4, b4)
a4["defend"] = True                        # 裸值：不是容器条目
_lg4 = []
_d4 = LND.deal_damage(bt4, b4, a4, 10, _lg4)
check("④ 反证：裸值（非容器条目）**不生效** ⇒ 不减半（唯一真源 = 容器条目）",
      _d4 == 10 and not any("格挡后" in x for x in _lg4), "%s / %s" % (_d4, _lg4))

bt3.act(ActCtx(caster=a3, action="attack"))
check("★ ④ 自己下一次行动 ⇒ 姿态到期（窗口条目从容器里消失）",
      not window_open(a3, DEFEND_TAG), str(a3.get("effects")))
_lg2 = []
_d2 = LND.deal_damage(bt3, b3, a3, 10, _lg2)
check("★ ④ 到期之后挨打 ⇒ 全额（10 点 · 不再有「格挡后」那一行）",
      _d2 == 10 and not any("格挡后" in x for x in _lg2), "%s / %s" % (_d2, _lg2))

a5, b5 = _mk("a5", "player", human=True), _mk("b5", "enemy")
bt5 = _bt(a5, b5)
bt5._do_defend(ActCtx(caster=a5, action="defend"))
a5.setdefault("effects", {})["stun_x"] = {"mode": "skip", "expire": None}
bt5.act(ActCtx(caster=a5, action="attack"))
check("④ 被控跳过那一手 ⇒ 同样算「下一次行动已到」（姿态到期、控制消费掉）",
      not window_open(a5, DEFEND_TAG) and "stun_x" not in (a5.get("effects") or {}),
      str(a5.get("effects")))

a6, b6 = _mk("a6", "player", human=True), _mk("b6", "enemy")
bt6 = _bt(a6, b6)
bt6._do_defend(ActCtx(caster=a6, action="defend"))
bt6._on_actor_dead(a6, [])
check("④ 死亡 ⇒ 窗口条目离场作废（容器声明说了算）",
      not window_open(a6, DEFEND_TAG), str(a6.get("effects")))

# ============================================================
CFG._hook_provider, CFG.strict = _saved_provider, _saved_strict
for _n in _TIME_HOOKS:
    if _saved_hooks[_n] is None:
        CFG._HOOKS.pop(_n, None)
    else:
        CFG._HOOKS[_n] = _saved_hooks[_n]
print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
if FAILURES:
    print("失败明细：")
    for _x in FAILURES:
        print("  - " + _x)
sys.exit(1 if FAIL else 0)
