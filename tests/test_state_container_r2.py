# -*- coding: utf-8 -*-
"""状态容器收口第 2 批门禁：承伤资源并进 effects 容器 + 承伤减免读点 + 死字段清零。

背景（设计案 `DESIGN_state_container_r2.md` §0/§2/§3 A+B 批）
-------------------------------------------------------------
这一批做三件事，每一件都是「第二本账 / 死字段 / 缺读点」：

  ① **第二本账**：`actor["shields"]` 是独立于 `effects` 的**第二个状态容器** ——
     自己的写口（`effects.act_shield` 里 `setdefault`）、自己的到期段
     （`schedule._settle_time_effects` 第 2 段）、自己的序列化播种、自己的存档透传。
     ⇒ 收口：护盾变成「`effects` 容器里一条**带 `value`** 的条目」，
     **是否吸收由内容侧声明 `absorb` 决定**（引擎零游戏名词：它不认「哪个 key 是盾」）。
  ② **死字段**：`reduce_left`（容器 `expire` 的影子账，引擎内零消费者）与
     `halve`（实测全仓只写不读）删净。
  ③ **缺读点**：承伤减免那一族原先**只有写、没有读**（技能挂的 `reduce` 一直不真减伤）。
     ⇒ 收口：引擎问内容侧「哪些条目声明了 `taken_pct`」，累加 `value`，按
     **内容侧骨架表** `formulas.reduce_cap()` 封顶后打折。

判据（本文件逐条钉住）
--------------------
  ① 护盾同源叠厚语义**逐字不变**（value 累加 + expire 取 max + 新永久盖掉旧临时）
  ② 承伤吸收：逐条扣 `value` / 归零即从容器删 / 剩余伤害继续结算 / 每条一条 cue
  ③ 到期即删：走容器**那一个** `expire` 到期段（独立容器的到期段已删）
  ④ 承伤减免读点真能减伤（按 `1-r` 折、封顶走 `formulas.reduce_cap()`、
     **未装配骨架表时不装配那一段 ⇒ 零行为变化**）
  ⑤ ★ 反证：把声明里的 `absorb` 删掉 ⇒ 那条条目**不再吸收**
     （证明「吸收型由**声明**决定」而不是硬编码键名）
  ⑥ ★ 反证：绕过容器写口直接给 `effects` 塞一个带 `value` 的条目、但**没有** `absorb`
     声明 ⇒ 不吸收（只有「声明 + 写口」两条都成立，这条目才是承伤资源）
  ⑦ 死字段清零：引擎侧已无 `shields` / `halve` / `reduce_left` 三个键名（静态扫描）

跑法：python tests/test_state_container_r2.py
"""
from __future__ import annotations

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB", os.path.join(FW_ROOT, "test_state_container_r2.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
# 与 tests/run_all.py 的 `_ext_path()` 同款：扩展包目录（`extends/`）要能 import ext_combat。
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))
sys.path.insert(0, _HERE)

from ext_combat.battle import effects as EFF                     # noqa: E402
from ext_combat.battle import landing as LND                     # noqa: E402
from ext_combat.battle import schedule as SCH                    # noqa: E402
from ext_combat.battle import state_effects as SE                # noqa: E402
from ext_combat.battle.actors import (EXPIRE_FIELD, VALUE_FIELD, _MUTABLE_KEYS,  # noqa: E402
                                      make_actor, open_entry)
from ext_combat.battle.battle import Battle                      # noqa: E402
from ext_combat.battle.game_config import get_effect_rules       # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check                                     # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# 已迁移点位的措辞真源在内容侧文案表（引擎模板已删）⇒ 合成战斗必须自己注入
# 「订阅表 + 文案表」，否则吸收/减免那几行会是坏数据行（本文件不接任何内容包）。
from _cue_text_fixture import TEXT as FIX_TEXT                    # noqa: E402
from _cue_text_fixture import install as fix_install              # noqa: E402

fix_install()

# 引擎不内置时间模型（未装配即抛）⇒ 自带最小一份（照 tests/test_state_container.py）。
from saintess_engine import config as CFG                          # noqa: E402
from saintess_engine.config import set_config, get_config          # noqa: E402

_TIME_HOOKS = ("time_model_fn", "action_base_fn", "recover_model_fn", "recover_base_fn")
_saved_hooks = {n: CFG._HOOKS.get(n) for n in _TIME_HOOKS}
_saved_provider, _saved_strict = CFG._hook_provider, CFG.strict
CFG._hook_provider = None
CFG.strict = False
CFG.mount(time_model_fn=lambda spd, base: float(base) * (50.0 / max(float(spd or 0), 1.0)),
          action_base_fn=lambda a: 1.0 if a in ("attack", "skill", "defend") else 0.0,
          recover_model_fn=lambda spd, base: float(base),
          recover_base_fn=lambda a: 0.0)

# 闪避/格挡在本门禁里只会**抢走**被测的那几手 ⇒ 探针 actor 的 dodge 归零。
# （这是**数据**层面的控制，不是打桩被测函数 —— 引擎的 dodge 读点一字不动。）


def _mk(uid, side, hp=200):
    a = make_actor(uid, uid, side, human_controlled=(side == "player"),
                   **{"hp": hp, "max_hp": hp, "atk": 10, "matk": 10, "def": 0,
                      "mdef": 0, "spd": 50, "stats_spd": 50, "dodge": 0.0, "block": 0.0})
    return a


def _bt(a, b):
    return Battle(btype="monster", sides={"player": [a], "enemy": [b]},
                  seed_ct=False, text=FIX_TEXT)


#: 探针声明表（装 → 拆）。只往**当前挂载的规则表**里加两条/删两条，真源与用完还原
#: 都跟 tests/test_cue_coverage.py 的探针做法同款（补的是「内容侧本该给的输入声明」，
#: 不是那一行 cue —— 发射点仍是引擎结算里的真代码）。
def _probe_rules(spec: dict):
    """把 `spec`（{键: 规则 或 None=摘掉}）写进**挂载中的**效果规则表；**返回还原函数**。

    ⚠️ `get_effect_rules()` 在没挂表时返回的是**每次新建的 `{}`**（`get_config(...) or {}`），
       直接往那个对象上写等于写进一个没人读的临时 dict —— 第一版就踩了这个坑（探针全部
       无效、判据集体变红）。这里改成**装一张真表**再逐条改，装/拆都还原。
    """
    _T_RULES = "effect_rules"
    prev = get_config(_T_RULES)
    tbl = dict(prev or {})
    set_config(_T_RULES, tbl)
    for k, v in spec.items():
        if v is None:
            tbl.pop(k, None)
        else:
            tbl[k] = v

    def _restore():
        if prev is None:
            set_config(_T_RULES, {})
        else:
            set_config(_T_RULES, prev)

    return _restore


def _io_read(path: str) -> str:
    import io
    return io.open(path, encoding="utf-8").read()


# ============================================================
# ① 护盾同源叠厚（与旧独立容器**逐字同语义**）
# ============================================================
print("\n【① 护盾同源叠厚：value 累加 + expire 取 max】")
ABS = {"shield_a": {"absorb": True}, "shield_b": {"absorb": True}}
probe = _probe_rules(ABS)
a, b = _mk("a", "player"), _mk("b", "enemy")
bt = _bt(a, b)
EFF.act_shield(bt, a, a, {"key": "shield_a", "value": 100, "turns": 3}, [])
e1 = (a["effects"].get("shield_a") or {})
check("① 首敲：容器里一条带 value 的条目（不再是独立容器）",
      e1.get(VALUE_FIELD) == 100 and "shields" not in a, "%s / %s" % (e1, sorted(a)))
check("① 首敲：到期走条目的 `expire`（不是旧容器的 `expire_at`）",
      EXPIRE_FIELD in e1 and "expire_at" not in e1, str(e1))

EFF.act_shield(bt, a, a, {"key": "shield_a", "value": 50, "turns": 2}, [])
e2 = (a["effects"].get("shield_a") or {})
check("① 同源再敲：value 累加（100+50）", e2.get(VALUE_FIELD) == 150, str(e2))
check("① 同源再敲：expire 取 max（不缩短）", e2.get(EXPIRE_FIELD) == e1.get(EXPIRE_FIELD),
      "%s vs %s" % (e2.get(EXPIRE_FIELD), e1.get(EXPIRE_FIELD)))

EFF.act_shield(bt, a, a, {"key": "shield_a", "value": 10, "turns": 999}, [])
e3 = (a["effects"].get("shield_a") or {})
# 「永久」= `expire` 是 None（与旧 `shields[key].expire_at = None` **逐字同款**）：
# 到期段读 `entry.get("expire")` 是 None ⇒ `continue` ⇒ 永不删。键在不在都不影响语义。
check("① 临时 + 永久 ⇒ 变永久（`expire` = None ⇒ 到期段不动它）",
      e3.get(VALUE_FIELD) == 160 and e3.get(EXPIRE_FIELD) is None, str(e3))

# 反向：已有永久 + 新敲临时 ⇒ 仍永久（旧实现同款：`cur[expire] is None` 时不覆盖）
EFF.act_shield(bt, a, a, {"key": "shield_b", "value": 7, "turns": 999}, [])
EFF.act_shield(bt, a, a, {"key": "shield_b", "value": 3, "turns": 2}, [])
e4 = (a["effects"].get("shield_b") or {})
check("① 永久 + 临时 ⇒ 仍是永久（永久不被临时改回）",
      e4.get(VALUE_FIELD) == 10 and e4.get(EXPIRE_FIELD) is None, str(e4))
check("① 异源并存各计各的（两条条目都在容器里）",
      set(a["effects"]) >= {"shield_a", "shield_b"}, str(sorted(a["effects"])))
probe()

# ============================================================
# ② 承伤吸收：逐条扣 / 归零即删 / 剩余伤害继续结算
# ============================================================
print("\n【② 承伤吸收：逐条扣 · 归零即删 · 剩余继续结算】")
probe = _probe_rules(ABS)
t, src = _mk("t", "enemy", hp=300), _mk("src", "player")
bt2 = _bt(t, src)
open_entry(t, "shield_a", stacks=1, value=30, expire=99.0)
open_entry(t, "shield_b", stacks=1, value=100, expire=99.0)
lg = []
real = LND.deal_damage(bt2, src, t, 70, lg, dmg_kind="phys")
# 70 伤害 vs 30+100=130 的盾 ⇒ 全被吸光：先扣光第一条（30），再从第二条扣 40，
# 剩 30 继续被第二条吃掉 ⇒ 一滴血都不掉（这一格就是「剩余继续往下走」的对照组，
# 下一格才是真·有剩余伤害的情形）。
check("② 逐条扣：先把第一条扣光（30）再从第二条扣 40",
      (t["effects"].get("shield_a") is None)
      and (t["effects"].get("shield_b") or {}).get(VALUE_FIELD) == 60,
      "%s" % (t["effects"],))
check("② 归零即从容器删（不留 value=0 的僵尸条目）", "shield_a" not in t["effects"],
      str(sorted(t["effects"])))
check("② 每吸收一次发一条 cue（复用 shield_absorb，不新造语义）",
      [x for x in lg if "护盾吸收" in x] and len([x for x in lg if "护盾吸收" in x]) == 2, str(lg))
check("② 全被吸光 ⇒ 扣血 0（伤害一点没落到血上）",
      real == 0 and int(t["hp"]) == 300, "real=%s hp=%s" % (real, t["hp"]))

# 「剩余伤害继续结算」：这一发 200 > 剩余 60 ⇒ 盾扣光后 140 继续落到血上
lg = []
real = LND.deal_damage(bt2, src, t, 200, lg, dmg_kind="phys")
check("★ ② 剩余伤害继续往下走（60 盾吃光后 140 落到血上）+ 吸收族清空",
      real == 140 and int(t["hp"]) == 160 and not SE.absorb_keys(t),
      "real=%s hp=%s 残留=%s" % (real, t["hp"], SE.absorb_keys(t)))
probe()

# ============================================================
# ③ 到期即删：走容器那一个 expire 段（独立容器的到期段已删）
# ============================================================
print("\n【③ 到期：容器 expire 段 · 永久条目不动】")
probe = _probe_rules(ABS)
t2, src2 = _mk("t2", "enemy", hp=300), _mk("src2", "player")
bt3 = _bt(t2, src2)
EFF.act_shield(bt3, t2, t2, {"key": "shield_a", "value": 50, "turns": 2}, [])
EFF.act_shield(bt3, t2, t2, {"key": "shield_b", "value": 50, "turns": 999}, [])
_exp = (t2["effects"].get("shield_a") or {}).get(EXPIRE_FIELD)
bt3._now = float(_exp) - 0.5
SCH._settle_time_effects(bt3, [])
check("③ 未到点：条目留着", "shield_a" in t2["effects"], str(t2["effects"]))
bt3._now = float(_exp)
SCH._settle_time_effects(bt3, [])
check("③ 到点：被容器的**那一个**到期段清掉（引擎已无第二段）",
      "shield_a" not in t2["effects"], str(sorted(t2["effects"])))
check("③ 永久条目不吃时间结算（expire 无值 ⇒ 不动）", "shield_b" in t2["effects"],
      str(sorted(t2["effects"])))
probe()

# ============================================================
# ④ 承伤减免读点（taken_pct 族）
# ============================================================
print("\n【④ 承伤减免读点：按 1-r 折 · 封顶走内容侧骨架表】")
RED = {"ward_a": {"taken_pct": True}, "ward_b": {"taken_pct": True}}
probe2 = _probe_rules(RED)

# ④a 未装配骨架表：封顶 0.0 ⇒ 折到 0 ⇒ **这一段不装配、零行为变化**
probe3 = _probe_rules({"ward_a": None, "ward_b": None})
t3, src3 = _mk("t3", "enemy", hp=300), _mk("src3", "player")
bt4 = _bt(t3, src3)
open_entry(t3, "ward_a", stacks=1, value=0.45, expire=99.0)
lg = []
real = LND.deal_damage(bt4, src3, t3, 100, lg, dmg_kind="phys")
check("④ 未装配骨架表（reduce_cap=0）⇒ 一点不打折（这一段对没声明的包零行为变化）",
      real == 100 and int(t3["hp"]) == 200, "real=%s hp=%s" % (real, t3["hp"]))
probe3()

# ④b 装配了封顶：按 1-r 折 + cue
def _with_skeleton(patch: dict):
    """把公式骨架里缺的那几格临时补上（内容侧本该声明的东西）→ 返回还原函数。"""
    import copy
    from ext_combat.battle import formulas as _F
    prev = CFG.optional_hook("formula_skeleton_fn")
    base = copy.deepcopy(dict(prev() if prev else (_F._skeleton() or {})))
    for _k, _v in patch.items():
        if isinstance(_v, dict):
            _grp = dict(base.get(_k) or {})
            _grp.update(_v)
            base[_k] = _grp
        else:
            base[_k] = _v
    CFG.mount(formula_skeleton_fn=lambda: base)
    return lambda: (CFG.mount(formula_skeleton_fn=prev) if prev is not None
                    else CFG.set_hook("formula_skeleton_fn", None))


undo_skel = _with_skeleton({"reduce": {"cap": 0.9}})
t4, src4 = _mk("t4", "enemy", hp=500), _mk("src4", "player")
bt5 = _bt(t4, src4)
open_entry(t4, "ward_a", stacks=1, value=0.25, expire=99.0)
lg = []
real = LND.deal_damage(bt5, src4, t4, 100, lg, dmg_kind="phys")
check("④ 带 taken_pct 声明的条目真能减伤（100 × (1-0.25) = 75）",
      real == 75 and int(t4["hp"]) == 425, "real=%s hp=%s" % (real, t4["hp"]))
check("④ 减免发一条表现事件（措辞走内容侧文案表）",
      any("减免了 25% 承伤" in x for x in lg), str(lg))
check("④ 减免读口是公开的累计口径（state_reduce_of 读到 0.25）",
      abs(LND.state_reduce_of(t4) - 0.25) < 1e-9, repr(LND.state_reduce_of(t4)))

# ④c 两条叠加 = 累加，但仍受封顶
open_entry(t4, "ward_b", stacks=1, value=0.4, expire=99.0)
check("④ 两条声明的条目累加（0.25+0.40）", abs(LND.state_reduce_of(t4) - 0.65) < 1e-9,
      repr(LND.state_reduce_of(t4)))
undo_skel2 = _with_skeleton({"reduce": {"cap": 0.5}})
check("④ 累加后仍按内容侧封顶 clamp（min(0.65, 0.5) = 0.5）",
      abs(LND.state_reduce_of(t4) - 0.5) < 1e-9, repr(LND.state_reduce_of(t4)))
lg = []
real = LND.deal_damage(bt5, src4, t4, 100, lg, dmg_kind="phys")
check("④ 封顶后按 1-0.5 折（100 → 50），cue 报的是生效后的比例",
      real == 50 and any("减免了 50% 承伤" in x for x in lg),
      "real=%s / %s" % (real, lg))
undo_skel2()
undo_skel()
probe2()

# ============================================================
# ⑤ ★ 反证：删掉声明里的 absorb ⇒ 那条条目不再吸收
# ============================================================
print("\n【⑤ ★ 反证：吸收型由「声明」决定，不是硬编码键名】")
t5, src5 = _mk("t5", "enemy", hp=300), _mk("src5", "player")
bt6 = _bt(t5, src5)
probe_off = _probe_rules({"shield_a": None})               # ★ 把 absorb 声明摘掉
open_entry(t5, "shield_a", stacks=1, value=30, expire=99.0)
check("⑤ 声明摘掉后 absorb_keys 认不出它", SE.absorb_keys(t5) == [], str(SE.absorb_keys(t5)))
lg = []
real = LND.deal_damage(bt6, src5, t5, 70, lg, dmg_kind="phys")
check("★ ⑤ 摘掉 `absorb` 声明 ⇒ **不再吸收**（伤害全额落到血上）",
      real == 70 and int(t5["hp"]) == 230
      and (t5["effects"].get("shield_a") or {}).get(VALUE_FIELD) == 30,
      "real=%s hp=%s 条目=%s" % (real, t5["hp"], t5["effects"].get("shield_a")))
check("★ ⑤ 也不再发吸收那一行（没吸收就没有那条表现）",
      not [x for x in lg if "护盾吸收" in x], str(lg))

# 同一个键把声明加回去 ⇒ 立刻恢复吸收（证明判定只看声明，不看键名历史）
probe_on = _probe_rules({"shield_a": {"absorb": True}})
open_entry(t5, "shield_a", stacks=1, value=30, expire=99.0)   # 重挂（上一格它没被消耗）
lg = []
real = LND.deal_damage(bt6, src5, t5, 70, lg, dmg_kind="phys")
check("★ ⑤ 声明加回去 ⇒ 同一个键立刻恢复吸收（判定纯看声明；30 盾吃光 70 的 30，40 落到血上）",
      real == 40 and int(t5["hp"]) == 190 and "shield_a" not in t5["effects"],
      "real=%s hp=%s / %s" % (real, t5["hp"], t5["effects"]))
probe_on()
probe_off()

# ============================================================
# ⑥ ★ 反证：绕过写口塞 value、没有 absorb 声明 ⇒ 不吸收
# ============================================================
print("\n【⑥ ★ 反证：只有「声明 + 写口」两条都成立才算承伤资源】")
t6, src6 = _mk("t6", "enemy", hp=300), _mk("src6", "player")
bt7 = _bt(t6, src6)
probe_sneaky = _probe_rules({"sneaky": None})             # 明确「无声明」
# ① 绕过容器写口，直接手写一条带 value 的条目（模拟旧式硬塞）
t6.setdefault("effects", {})["sneaky"] = {"stacks": 1, "value": 500, "expire": 99.0}
# ② 它有 value，但它**没有** absorb 声明
check("⑥ 硬塞的条目在容器里、value 也在（不是没塞进去）",
      (t6["effects"].get("sneaky") or {}).get(VALUE_FIELD) == 500, str(t6["effects"]))
check("⑥ 但 absorb_keys 认不出它（没有声明）", "sneaky" not in SE.absorb_keys(t6),
      str(SE.absorb_keys(t6)))
lg = []
real = LND.deal_damage(bt7, src6, t6, 60, lg, dmg_kind="phys")
check("★ ⑥ 没有 absorb 声明 ⇒ 不吸收（哪怕 value 有 500），伤害全额落到血上",
      real == 60 and int(t6["hp"]) == 240
      and (t6["effects"].get("sneaky") or {}).get(VALUE_FIELD) == 500,
      "real=%s hp=%s" % (real, t6["hp"]))
check("★ ⑥ 也不发吸收那一行", not [x for x in lg if "护盾吸收" in x], str(lg))
# 给它补上声明 ⇒ 变承伤资源（证明缺的就是那一条声明）
probe_sneaky_on = _probe_rules({"sneaky": {"absorb": True}})
lg = []
real = LND.deal_damage(bt7, src6, t6, 60, lg, dmg_kind="phys")
check("★ ⑥ 补上声明后同一条目才开始吸收（吸收与否的唯一开关 = 声明；500 盾吃掉 60 全额）",
      real == 0 and int(t6["hp"]) == 240
      and (t6["effects"].get("sneaky") or {}).get(VALUE_FIELD) == 440,
      "real=%s hp=%s / %s" % (real, t6["hp"], t6["effects"]))
probe_sneaky_on()
probe_sneaky()

# ============================================================
# ⑦ 死字段 / 独立容器清零（静态扫描，漏改一处就红）
# ============================================================
print("\n【⑦ 独立容器与死字段已从引擎清零（静态扫描）】")
#: 引擎三个可执行根：承伤资源/调度/承伤减伤都在这里，键名一个都不许剩。
_ROOTS = ("extends", "saintess_engine", "examples")
_BANNED = ("shields", "halve", "reduce_left")
_HITS = []
for _sub in _ROOTS:
    for _dp, _dirs, _files in os.walk(os.path.join(FW_ROOT, _sub)):
        _dirs[:] = [d for d in _dirs if d not in ("__pycache__", ".git")]
        for _f in sorted(_files):
            if not _f.endswith(".py"):
                continue
            _p = os.path.join(_dp, _f)
            _rel = os.path.relpath(_p, FW_ROOT).replace("\\", "/")
            for _i, _ln in enumerate(_io_read(_p).splitlines(), 1):
                # 剥掉行内注释（docstring 靠 `ast` 单独剥）—— 否则「注释里提一句旧键名」
                # 会被误判成「键还在」（第一版就踩了：effects.py 的收口说明里写了
                # `actor["shields"]` 三个字，被当成残留）。
                _code = _ln.split("#", 1)[0]
                for _kw in _BANNED:
                    if ('"%s"' % _kw) in _code or ("'%s'" % _kw) in _code:
                        _HITS.append((_rel, _i, _kw, _code.strip()[:60]))
check("★ 可执行代码里已无 shields / halve / reduce_left 三个键名",
      not _HITS, str(_HITS[:6]))
_DOC_HITS = []
for _sub in _ROOTS:
    for _dp, _dirs, _files in os.walk(os.path.join(FW_ROOT, _sub)):
        _dirs[:] = [d for d in _dirs if d not in ("__pycache__", ".git")]
        for _f in sorted(_files):
            if not _f.endswith(".py"):
                continue
            _p = os.path.join(_dp, _f)
            _src = _io_read(_p)
            try:
                _tree = ast.parse(_src, filename=_p)
            except SyntaxError:                                  # noqa: PERF203
                continue
            for _n in ast.walk(_tree):
                if not (isinstance(_n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                         ast.AsyncFunctionDef))):
                    continue
                _body = getattr(_n, "body", None)
                if not _body:
                    continue
                _head = _body[0]
                if not (isinstance(_head, ast.Expr)
                        and isinstance(_head.value, ast.Constant)
                        and isinstance(_head.value.value, str)):
                    continue
                for _kw in _BANNED:
                    if ('"%s"' % _kw) in _head.value.value or ("'%s'" % _kw) in _head.value.value:
                        _DOC_HITS.append((os.path.relpath(_p, FW_ROOT).replace("\\", "/"),
                                         _head.lineno, _kw))
check("★ docstring 里也不再有这三个键名（收口说明别再教人用旧键）",
      not _DOC_HITS, str(_DOC_HITS[:6]))
check("★ 播种表里没有 shields（独立容器已删）",
      "shields" not in _MUTABLE_KEYS, str(_MUTABLE_KEYS))
check("★ make_actor 不再播种 shields（存档/续战靠 effects 一条容器）",
      "shields" not in make_actor("z", "z", "player"), str(sorted(make_actor("z", "z", "player"))))


def io_open(path):
    import io
    return io.open(path, encoding="utf-8").read()


CFG._hook_provider, CFG.strict = _saved_provider, _saved_strict
for _n in _TIME_HOOKS:
    if _saved_hooks[_n] is None:
        CFG._HOOKS.pop(_n, None)
    else:
        CFG._HOOKS[_n] = _saved_hooks[_n]
print("\n===== 结果：通过 %d / 共 %d =====" % (PASS, PASS + FAIL))
if FAILURES:
    print("失败明细：")
    for _x in FAILURES:
        print("  - " + _x)
sys.exit(1 if FAIL else 0)
