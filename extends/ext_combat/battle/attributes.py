# -*- coding: utf-8 -*-
"""属性写口（Attributes）—— actor 的三个「当前值」标量**只有一个写入口**。

照外部框架（GAS 的 AttributeSet）那条思路落成本引擎的形状：**唯一写入口 + 预改钩子 + 后改钩子**。
引擎零游戏名词：只认 `hp` / `mp` / `ct` 三个结构性名字（它们本来就硬编码在引擎各写点里）。

## 为什么要有它

收口前，引擎里 **10 个写点**（外加写口自身的 2 处内部调用，调用点共 **12** 处）各写各的钳制：`mp` 扣费有 `max(0,…)` 也有 `max(1,…)`、`hp` 有三处
（保命下限 / 裸写 / `min(max_hp,…)`）、`ct` 完全裸写 ⇒ **同一条规则各写一遍，且口径已经不一致**。
"绕过钳制 / 绕过护盾 / 钳到 0 又回血" 这类穿透 bug 就长在这里。收口后：
`tests/test_attrs_write_port.py` 的机器门禁**禁止引擎代码再出现「对 hp/mp/ct 的下标直接赋值」**
（白名单只有一处报价 dict）—— 漏改一处当场红。

## 形状

- `current(actor, key)` / `ceiling(actor, key)` / `floor_of(actor, key)`：读与边界。
- `set_current(actor, key, value, *, reason=None, battle=None)` / `add_current(...)`：**唯一写口**。
- 内建规则（= 钩子未装配时的缺省，**逐字等于今天各写点手写的那套**）：
  下限一律 ≥ 0（= 今天 `max(0,…)` 的路）· 上限 `hi = max(上限, 现在值)`：只在**抬值**方向生效
  —— 现在值没越界 ⇒ 就是 `min(max_hp, …)`（heal/regen 路，逐字相同）；现在值已经越界
  （合成/脏数据）⇒ 不把已越界的值压回来（= 今天 `max(0, old-dmg)` 那条路从不压回；
  越界的责任在数据，不在写口）。`ct` 无上限（时间轴）。
  ★ **保命类下限（`max(1,…)`）不是内建规则** —— 那是机制行为，由调用方算完再传进来。
- **预改钩子** `attr_pre_fn(actor, key, value, ctx) -> float | None`（装配面；未装配 ⇒ 钩子
  **不存在**，一行都不进）：返回**变换后的值**；`None` = 交回内建规则。变换后的值**仍过内建边界**
  （要破界请改上层机制，不是写口的事）。**不做拦截语义** —— 护盾/免疫那类拦截在效果链里。
- **后改钩子** `attr_post_fn(actor, key, old, new, ctx) -> None`：只在值**真的变了**时调用；
  抛错**原样上抛**（fail-closed，不吞）。

`ctx` = `{"old": 旧值, "reason": 调用方给的引擎词, "battle": 本场战斗}`；
`reason` 是引擎词（`"damage"` / `"heal"` / `"cost"` / `"regen"` / `"schedule"` / `"death_guard"` …），
**不是**游戏名词 —— 它只用来记账与排障。

类型保持：写口按**入参类型**落值（int 进 int 出、float 进 float 出）—— 冻结对拍靠这条逐字节相同。
"""
from __future__ import annotations

from saintess_engine import config as _cfg

#: 引擎词表：actor 的「当前值」标量。别的字段（面板派生值 / traits / effects 层数）**不走写口**：
#: 面板是重算出来的、`traits` 是构造期数据、`effects[key].stacks` 已由 `actors.open_entry` 收口。
ATTRS = ("hp", "mp", "ct")

_CEIL_KEY = {"hp": "max_hp", "mp": "max_mp"}


def current(actor: dict, key: str) -> float:
    """读当前值（缺字段 ⇒ 0，与今天各读点 `actor.get(k, 0)` 同一口径）。"""
    return (actor or {}).get(key, 0) or 0


def ceiling(actor: dict, key: str):
    """上限：`hp` → `max_hp` · `mp` → `max_mp` · `ct` → `None`（时间轴无上限）。

    缺 `max_hp` / `max_mp` 时回落到**当前值**（= 今天各写点的写法：`actor.get("max_mp",
     actor.get("mp", 1)) or 1`），不是新造的兜底。
    """
    if key in _CEIL_KEY:
        return (actor or {}).get(_CEIL_KEY[key], (actor or {}).get(key, 1)) or 1
    return None


def floor_of(actor: dict, key: str):
    """下限：`hp` / `mp` → 0 · `ct` → 0.0（时刻不为负）。"""
    return 0.0 if key == "ct" else 0


def _clamp(actor: dict, key: str, value, like) -> float:
    """内建边界（钩子未装配时的缺省）；`like` 决定落值类型（类型保持）。

    上限取 `max(上限, 现在值)` —— 只在**抬值**方向生效，不主动把已越界的值压回来：
    ★ 2026-09-28 实测（`tests/test_host_skeleton.py` 的假适配器 fixture 里 `hp=300 > max_hp=203`）：
    严格上限会把那场胜负从 victory 翻成 defeat ⇒ 那是**数据的责任**，不是写口该顺手做的事。
    于是 `hi=max(上限, 现在值)` 与今天两条路逐字对齐：`min(max_hp,…)`（heal/regen）∪ `max(0,…)`（damage/cost）。
    """
    v = float(value)
    hi = ceiling(actor, key)
    if hi is not None:
        _cur = actor.get(key, None)
        _hi = float(hi) if _cur is None else max(float(hi), float(_cur))
        if v > _hi:
            v = _hi
    lo = float(floor_of(actor, key))
    if v < lo:
        v = lo
    if isinstance(like, int) and not isinstance(like, bool):
        return int(v)
    return v


def _pre(actor: dict, key: str, value, old, reason, battle):
    """预改钩子（未装配 ⇒ 不存在）。返回变换后的值；`None` = 交回内建规则。"""
    fn = _cfg.optional_hook("attr_pre_fn")
    if fn is None:
        return value
    got = fn(actor, key, value, {"old": old, "reason": reason, "battle": battle})
    return value if got is None else got


def _post(actor: dict, key: str, old, new, reason, battle) -> None:
    """后改钩子（未装配 ⇒ 不存在）；只在值真变了时调用，异常原样上抛。"""
    fn = _cfg.optional_hook("attr_post_fn")
    if fn is None:
        return
    fn(actor, key, old, new, {"reason": reason, "battle": battle})


def set_current(actor: dict, key: str, value, *, reason: str = None, battle=None,
                clamp: bool = True):
    """**唯一写入口**：`actor[key] = value`（过预改钩子 + 内建边界），返回值 = 落盘后的值。

    - `key` 不在 `ATTRS` ⇒ `KeyError`（不在词表里的字段不许从写口进 —— 它就是走错了地方）。
    - 值**没变**时不写、不叫后改钩子（幂等写入不留痕）。
    """
    if key not in ATTRS:
        raise KeyError("attributes.set_current：%r 不是引擎属性（只认 %r）；"
                       "面板派生值/标签/效果层数各有自己的口" % (key, ATTRS))
    old = (actor or {}).get(key, None)
    v = _pre(actor, key, value, old, reason, battle)
    if clamp:
        v = _clamp(actor, key, v, like=value)
    if old is None or v != old:
        actor[key] = v
        _post(actor, key, old, v, reason, battle)
    return v


def add_current(actor: dict, key: str, delta, *, reason: str = None, battle=None,
                clamp: bool = True):
    """`actor[key] += delta`（同样过预改钩子 + 内建边界）。"""
    return set_current(actor, key, float(current(actor, key)) + float(delta),
                       reason=reason, battle=battle, clamp=clamp)
