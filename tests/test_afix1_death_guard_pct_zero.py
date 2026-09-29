# -*- coding: utf-8 -*-
"""afix1：landing._apply_death_guard 的 `guard_hp_pct` 回落**只认 None**，不吞合法 0.0。

真缺陷（黑盒复现，注入面 = `config.set_config("effect_rules", …)`，即 state_def 的真读口链）：
内容侧声明 `guard_hp_pct: 0.0`（语义 = 「只保命、不回血」，由紧接着的 `max(1, …)` 兜到 1 血），
原写法 `float(cfg.get("guard_hp_pct") or 0.10)` 把 **0.0 当 falsy 吞成 0.10**
⇒ max_hp=1000 时玩家被拉到 **100 血**，而不是声明的 1 血 —— 声明被静默改写，且无报错。

判据只认**行为**：真调生产函数，逐值钉住三种形态（0.0 / 0.1 / 缺键）。
不重写一遍实现（那会变成测判据自己）。
"""
import sys, os
sys.path.insert(0, r"C:/Users/yuyu/framework-engine")
sys.path.insert(0, r"C:/Users/yuyu/framework-engine/extends")
from saintess_engine import config
from ext_combat.battle import landing as L

FAILS = []
def chk(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)

# 写口桩：只接住 hp 写，不参与判定（判据仍真调生产函数本身）
_orig_set = L.ATTR.set_current
L.ATTR.set_current = lambda actor, stat, value, **kw: actor.__setitem__(stat, value)
_oc = L._cue
L._cue = lambda b, l, k, p=None: None
_orig_cfg = config.get_config


def probe(decl, label):
    """decl = guard_hp_pct 的声明值；None = 缺键（不写这个键）。"""
    tbl = {"death_guard": {"cap": 1, "heal_pct": 0.0}}
    if decl is not None:
        tbl["death_guard"]["guard_hp_pct"] = decl
    config.set_config("effect_rules", tbl)
    t = {"name": "目标", "hp": 0, "max_hp": 1000, "uid": "u1",
         "effects": {"death_guard": {"stacks": 1, "expire": 0}}}
    r = L._apply_death_guard({"name": "b"}, t, [])
    return r, t


try:
    # ── §1 合法 0.0：必须按声明给「保底 1 血」，不是 10% ──────────────
    r, t = probe(0.0, "声明 0.0")
    chk(r is True, "§1 声明 0.0 应当触发保命，实际 %r" % r)
    chk(t["hp"] == 1, "§1 ★ 声明 guard_hp_pct=0.0 时 hp=%r（应 1 = max(1, 1000×0.0)；"
                       "得 100 说明 `or 0.10` 把合法 0.0 吞了）" % t["hp"])

    # ── §2 正常值 0.1 逐值不变（防修过头）─────────────────────────────
    r, t = probe(0.1, "声明 0.1")
    chk(t["hp"] == 100, "§2 声明 0.1 时 hp=%r（应 100 = max_hp×0.10）" % t["hp"])

    # ── §3 缺键：仍走引擎缺省 0.10（行为逐字不变）──────────────────────
    r, t = probe(None, "缺键")
    chk(t["hp"] == 100, "§3 没声明 guard_hp_pct 时 hp=%r（应 100 = 缺省 0.10）" % t["hp"])

    # ── §4 零回归：非零大值仍按声明给 ────────────────────────────────
    r, t = probe(0.5, "声明 0.5")
    chk(t["hp"] == 500, "§4 声明 0.5 时 hp=%r（应 500）" % t["hp"])
finally:
    L.ATTR.set_current = _orig_set
    L._cue = _oc

print("\n=== afix1 death_guard guard_hp_pct: FAIL %d ===" % len(FAILS))
if FAILS:
    raise SystemExit(1)
print("PASS 0")
