# -*- coding: utf-8 -*-
"""跨手状态的两条真源口径（2026-09-27 · 六路真人试玩查出来的两个**跨游戏**缺陷）。

① **防御姿态到期 = 「到你下一次行动之前」**
   `_do_defend` 只置 `defending=True`，全仓此前**只有死亡**会清它（`battle.py` 的 `_do_defend`
   置 / `_on_actor_dead` 清，中间没有任何到期点）⇒ 敲一次『防御』这一场剩下的每一手都被减半：
   骑士/法师/刺客/狂战四路实测复现（第 5 手按一次，第 6~16 手每一下都带 `(格挡后 N 点伤害)`），
   难度口径在这条上等于不存在。到期点现在落在**行动者自己动手的那一帧**（`Battle.act()` 入口，
   = 「你下一次行动」）：在那之前（对面打过来的那些手）减伤照旧有效。

② **战斗级跨手标记 `battle.flags`**
   内容侧「每场一次 / 每场几层」那类记账要一个**过得了 `to_state`/`from_state` 往返**的格子。
   原先 `serialize.to_state` 把 `flags` 写死 `{}`、`from_state` 不读它 ⇒ 挂在 `Battle` 上的临时
   属性每手清零（本包「场」这条路由**每一手**都要往返一次序列化）—— 焚身「一场一次」四轮试玩
   都复现，凡「跨手记住点什么」的机制全栽同一坑。

**反证（改的时候手验过，本文件就是把它们钉住）**：
  · 把 `Battle.act()` 里那行 `actor["defending"] = False` 注掉 ⇒ ① 变红；
  · 把 `serialize.to_state` 的 `"flags": dict(battle.flags or {})` 改回 `"flags": {}` ⇒ ② 变红。

跑法：python tests/test_cross_hand_state.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_cross_hand.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

from ext_combat.battle.actors import make_actor              # noqa: E402
from ext_combat.battle.battle import ActCtx, Battle           # noqa: E402
from ext_combat.battle import landing as LND                  # noqa: E402
from ext_combat.battle import serialize as SER                # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                 # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# 引擎不内置行动基准数值（未装配即抛 `EngineNotConfigured` —— fail-closed 是设计）⇒
# 本测试自带最小一份时间模型（照 tests/test_engine_neutral_fallback.py 的挂法）。
from saintess_engine import config as CFG                      # noqa: E402

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
    """单人 vs 单人（同一等级 ⇒ 等级压制不参与，减伤只可能来自 defending）。"""
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]}, seed_ct=False)


# ============================================================
# ① 防御姿态的到期口径
# ============================================================
print("\n【① 防御姿态：到期 = 你自己下一次行动之前】")
a, b = _mk("a1", "player", human=True), _mk("b1", "enemy")
bt = _bt(a, b)
bt._do_defend(ActCtx(caster=a, action="defend"))
check("① 敲『防御』⇒ 姿态置上", a.get("defending") is True, str(a.get("defending")))

_lg = []
_d1 = LND.deal_damage(bt, b, a, 10, _lg)
check("① 姿态期内挨打 ⇒ 减半（10 → 5）+ 出「格挡后」那一行",
      _d1 == 5 and any("格挡后" in x for x in _lg), "%s / %s" % (_d1, _lg))

# 自己动手（= 真源那句「你下一次行动」）
bt.act(ActCtx(caster=a, action="attack"))
check("★ 自己下一次行动 ⇒ 姿态**到期**（defending 落回 False）",
      a.get("defending") is False, str(a.get("defending")))

_lg2 = []
_d2 = LND.deal_damage(bt, b, a, 10, _lg2)
check("★ 到期之后挨打 ⇒ 全额（10 点 · 不再有「格挡后」那一行）",
      _d2 == 10 and not any("格挡后" in x for x in _lg2), "%s / %s" % (_d2, _lg2))

# 被控跳过那一手也算「这一次行动已到」（口径写进 act() 的注释里）
a2, b2 = _mk("a2", "player", human=True), _mk("b2", "enemy")
bt2 = _bt(a2, b2)
bt2._do_defend(ActCtx(caster=a2, action="defend"))
a2.setdefault("effects", {})["stun_x"] = {"mode": "skip", "expire": None}
bt2.act(ActCtx(caster=a2, action="attack"))
check("① 被控跳过那一手 ⇒ 同样算「下一次行动已到」（姿态到期、控制消费掉）",
      a2.get("defending") is False and "stun_x" not in (a2.get("effects") or {}),
      "defending=%s effects=%s" % (a2.get("defending"), list((a2.get("effects") or {}).keys())))

# 反证的一半：死亡那条老路一个字没动（照旧清）
a3, b3 = _mk("a3", "player", human=True), _mk("b3", "enemy")
bt3 = _bt(a3, b3)
bt3._do_defend(ActCtx(caster=a3, action="defend"))
bt3._on_actor_dead(a3, [])
check("① 死亡仍照旧清姿态（老路径未改）", a3.get("defending") is False)

# ============================================================
# ② 战斗级跨手标记（battle.flags 过序列化往返）
# ============================================================
print("\n【② battle.flags：过得了 to_state / from_state 往返】")
c, d = _mk("c1", "player", human=True), _mk("d1", "enemy")
bt4 = _bt(c, d)
bt4.flags["burn_used"] = 1
_st = SER.to_state(bt4)
check("② to_state 带着 flags（不是写死的空字典）",
      (_st.get("flags") or {}).get("burn_used") == 1, str(_st.get("flags")))
bt5 = SER.from_state(_st)
check("★ from_state 把 flags 读回来（跨手记账的落点）",
      (bt5.flags or {}).get("burn_used") == 1, str(getattr(bt5, "flags", None)))

bt5.flags["burn_used"] = 2
_st2 = SER.to_state(bt5)
bt6 = SER.from_state(_st2)
check("★ 第二手再往返一次仍在（= 真路径每一手往返一遍）",
      (bt6.flags or {}).get("burn_used") == 2, str(getattr(bt6, "flags", None)))

check("② 空 flags 往返 = 空字典（不是 None）",
      SER.from_state(SER.to_state(_bt(_mk("e1", "player"), _mk("f1", "enemy")))).flags == {},
      "flags=%r" % (SER.from_state(SER.to_state(_bt(_mk("e2", "player"), _mk("f2", "enemy")))).flags,))

# **反证**：原先那条路（挂在 Battle 上的临时属性）就是过不了往返的
bt7 = _bt(_mk("g1", "player"), _mk("h1", "enemy"))
setattr(bt7, "_aeth_mech_used", {"burn_used": 1})
check("反证：临时属性（setattr）过不了往返 —— 这正是原先那套写法每手清零的原因",
      not hasattr(SER.from_state(SER.to_state(bt7)), "_aeth_mech_used"))

check("② flags 里放 JSON 化不出来的东西 ⇒ state_to_json 不炸（default=str 兜底）",
      bool(SER.state_to_json({"flags": {"x": {1, 2}}})))

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
