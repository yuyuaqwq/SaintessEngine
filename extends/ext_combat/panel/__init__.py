# -*- coding: utf-8 -*-
"""面板栈（E2）—— 把「属性聚合」从内容侧的 Python 模块提升为**引擎形状**。

设计真源：`aetheran-designer/12_迁移引擎评估/01_引擎提升设计_E1E2.md` §2（字段级设计）。

## 这个形状解决什么

现状（**既有债**）：`config._HOOKS["panel_fn"]` 的形参**就是游戏词汇**
（`fn(class_name, level, equipment, tier, evolve_path, panel_bonus, race)`，实测 8 个位置参数、6/8 是游戏词）
⇒ 引擎纯度缺陷；且面板聚合本体写在内容侧的 Python 里（旧包 `content/panel.py` 569 行）。

本形状：内容侧只声明「有哪些层、每层怎么作用到哪些键」，引擎负责**逐键合并 + 钳制 + 归因打印**。

## 与 `Bonus` 的边界（写死，防止两套形状互相蚕食）

| 语义 | 落哪个形状 |
|---|---|
| **面板键级合成**（atk/def/spd…） | **本形状** |
| 叠层上限的 flat 增量（`cap`） | `Bonus`（不动） |
| 技能消耗修正（`cost`，嵌套声明） | `Bonus`（不动） |
| 面板增幅的**来源标签** | 本形状的层 `src` |

## 三条有意定死的语义（别在执行时走样）

1. **`mul` 的键若不在基础里 ⇒ 结果 0**（与 `Bonus` 既有口径一致）。
   **不**改成"1 则不变" —— 静默把 ×0 变 ×1 = 悄悄改了数值。
2. **`cap`/`floor` 只作用于 `add`/`mul`，不作用于 `set`** —— `set` 的语义是"这层说了算"，钳它会让
   "设置值"与"声明值"不一致；要限 `set` 就把范围写进 `values`。
3. **不提供 `drop`/撤销口** —— 面板聚合是**每次全量重算**（`battle/stats.py` 是纯函数，无状态累积）。
   层是"声明"不是"账本"；要撤销 = 改声明 / 置 `status: "inactive"`。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["PanelStack", "ResolvedPanel", "PanelDeclError", "TraceRow"]

_MODES = ("add", "mul", "set")
_BASE_MODES = ("actor", "value")
_MAX_CACHE = 512
#: `(stack_id, version) -> PanelStack` 进程内缓存（一次校验，反复用）
_STACK_CACHE: dict = {}


class PanelDeclError(ValueError):
    """面板栈声明非法（装配期 fail-closed；不做运行期兜底）。"""


class TraceRow(dict):
    """一层对某个键的作用（可当 dict 用）。"""

    __slots__ = ()


def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise PanelDeclError(msg)


def _when_ok(when, ctx) -> bool:
    """`when` 判据：对象 = 逐条 key==值 全等（AND）；数组 = 任一命中即真（OR）。

    **缺 `when` = 恒通过**；`when` 写了但键/值不认识 → **按不命中处理**（fail-closed）。
    """
    if when is None:
        return True
    flags = (ctx or {}).get("flags") or {}
    items = when if isinstance(when, list) else [when]

    def one(it) -> bool:
        if not isinstance(it, dict):
            return False
        for k, want in it.items():
            if flags.get(k) != want:
                return False
        return True

    return any(one(i) for i in items) if isinstance(when, list) else one(when)


class ResolvedPanel(Mapping):
    """求值结果。是 `Mapping[str, number]` ⇒ 可直接当 dict 用（兼容 `st.get("atk")` 读法）。"""

    def __init__(self, values: dict, layers_used: list, ctx: dict):
        self._v = values
        self._layers = layers_used
        self._ctx = ctx
        self._trace: dict[str, list] = {}

    def __getitem__(self, k):
        return self._v[k]

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __repr__(self):
        return f"ResolvedPanel({dict(sorted(self._v.items()))})"

    def as_dict(self) -> dict:
        return dict(self._v)

    def trace(self, key: str) -> list:
        """逐层中间量（打印数据源）：每层对 `key` 做了什么、值从多少变到多少。"""
        return self._trace.get(key, [])

    def shares(self, key: str) -> dict:
        """按层 `group` 汇总的来源占比（只算 `add` 层 —— 占比的语义是"贡献了多少点"）。"""
        base = self._base_of(key)
        tot = self._v.get(key, 0.0) - base
        if not tot:
            return {}
        out: dict = {}
        for r in self.trace(key):
            if r.get("mode") != "add" or r.get("delta") is None:
                continue
            out[r["group"]] = out.get(r["group"], 0.0) + float(r["delta"])
        return {g: round(v / tot, 6) for g, v in out.items()}

    def _base_of(self, key):
        return self._base0.get(key, 0.0) if hasattr(self, "_base0") else 0.0

    def set_base_snapshot(self, base: dict):
        self._base0 = dict(base)
        self._trace = {k: self._trace[k] for k in self._trace}   # 保持引用
        return self


class PanelStack:
    """不可变面板栈。用 `from_decl` 构造（构造函数不做校验）。"""

    def __init__(self, decl: dict, layers: list):
        self._decl = decl
        self._layers = layers

    # ── 构造 + 校验 ────────────────────────────────────────────
    @classmethod
    def from_decl(cls, decl: dict) -> "PanelStack":
        _need(isinstance(decl, dict), f"面板栈必须是对象，收到 {type(decl).__name__}")
        ver = decl.get("version")
        _need(isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1,
              f"栈的 version 必须是 ≥1 的整数，收到 {ver!r}")

        base = decl.get("base")
        _need(isinstance(base, dict), "栈缺 base")
        bmode = base.get("mode")
        _need(bmode in _BASE_MODES, f"base.mode={bmode!r} 非法（允许 {_BASE_MODES}）")
        if bmode == "actor":
            _need(isinstance(base.get("keys"), list) and base["keys"],
                  "base.mode=actor 时必须显式列出 base.keys（零默认值：引擎不猜键集）")
            for k in base["keys"]:
                _need(isinstance(k, str) and k, f"base.keys 里有非法键名 {k!r}")
        else:
            bv = base.get("value")
            _need(isinstance(bv, dict) and bv, "base.mode=value 时必须给非空的 base.value")
            for k, v in bv.items():
                _need(_is_finite(v), f"base.value[{k!r}] 必须是有限数，收到 {v!r}")

        layers = decl.get("layers")
        _need(isinstance(layers, list), "栈缺 layers（可为空数组）")
        seen_id, seen_order = set(), set()
        norm = []
        for i, L in enumerate(layers):
            _need(isinstance(L, dict), f"第 {i} 层必须是对象")
            lid = L.get("id")
            _need(isinstance(lid, str) and lid.strip(), f"第 {i} 层缺 id")
            _need(lid not in seen_id, f"层 id {lid!r} 重复")
            seen_id.add(lid)
            src = L.get("src")
            _need(isinstance(src, str) and src.strip(), f"层 {lid!r} 的 src 不得为空")
            grp = L.get("group")
            _need(isinstance(grp, str) and grp.strip(), f"层 {lid!r} 的 group 不得为空")
            mode = L.get("mode")
            _need(mode in _MODES, f"层 {lid!r} 的 mode={mode!r} 非法（允许 {_MODES}）")
            keys = L.get("keys")
            _need((keys == "*") or (isinstance(keys, list) and len(keys) > 0),
                  f"层 {lid!r} 的 keys 必须是非空数组或 \"*\"")
            if isinstance(keys, list):
                for k in keys:
                    _need(isinstance(k, str) and k, f"层 {lid!r} 的 keys 里有非法键名 {k!r}")
            has_v, has_r = isinstance(L.get("values"), dict), isinstance(L.get("ref"), str)
            _need(has_v != has_r, f"层 {lid!r} 必须**恰好**有 values 或 ref 之一")
            if has_v and L["values"]:
                for k, v in L["values"].items():
                    _need(_is_finite(v), f"层 {lid!r} 的 values[{k!r}] 必须是有限数")
            if has_v and mode != "set":
                # mul/whole 可以用 values["*"]；add 需要逐键
                _need(bool(L["values"]), f"层 {lid!r} 的 values 不得为空")
            if L.get("apply") is not None:
                _need(L["apply"] in ("per_key", "whole"),
                      f"层 {lid!r} 的 apply={L['apply']!r} 非法（per_key/whole）")
            if L.get("order") is not None:
                _need(isinstance(L["order"], int) and not isinstance(L["order"], bool),
                      f"层 {lid!r} 的 order 必须是整数")
                _need(L["order"] not in seen_order, f"层序 order={L['order']} 重号")
                seen_order.add(L["order"])
            if L.get("weight") is not None:
                _need(isinstance(L["weight"], int) and not isinstance(L["weight"], bool),
                      f"层 {lid!r} 的 weight 必须是整数")
            for fld in ("cap", "floor"):
                if L.get(fld) is not None:
                    _need(_is_finite(L[fld]), f"层 {lid!r} 的 {fld} 必须是有限数")
            if L.get("status") is not None:
                _need(L["status"] in ("active", "inactive"),
                      f"层 {lid!r} 的 status={L['status']!r} 非法（active/inactive）")
            _need(L.get("when") is None or isinstance(L["when"], dict)
                  or (isinstance(L["when"], list) and all(isinstance(x, dict) for x in L["when"])),
                  f"层 {lid!r} 的 when 必须是映射或映射数组")
            n = dict(L)
            n["_i"] = i
            n["order"] = L.get("order", i)
            n["apply"] = L.get("apply", "per_key")
            n["weight"] = L.get("weight", 0)
            n["status"] = L.get("status", "active")
            norm.append(n)

        emit = decl.get("emit") or {}
        _need(isinstance(emit, dict), "emit 必须是对象")
        ik = emit.get("int_keys") or []
        _need(isinstance(ik, list) and all(isinstance(x, str) for x in ik),
              "emit.int_keys 必须是字符串数组")
        rd = emit.get("round", 6)
        _need(isinstance(rd, int) and not isinstance(rd, bool) and rd >= 0,
              f"emit.round 必须是 ≥0 的整数，收到 {rd!r}")
        und = decl.get("audit")
        _need(und is None or isinstance(und, dict), "audit 必须是对象")

        norm.sort(key=lambda L: (L["order"], L["_i"]))              # 唯一合并序
        return cls(dict(decl, emit=dict(emit, int_keys=ik, round=rd)), norm)

    # ── 求值 ──────────────────────────────────────────────────
    def resolve(self, base: dict, ctx: dict | None = None) -> ResolvedPanel:
        """按声明求值。`base` = `{键: 数}`（`base.mode=actor` 时由调用方从 actor 取）。"""
        ctx = ctx or {}
        # ★ base.mode 决定基础值从哪来（这是 `resolve` 的**第一件事**，别忽略）：
        #   mode=value ⇒ 用声明里的常量基础值（调用方传的 base 被忽略）
        #   mode=actor ⇒ 用调用方传的 base（＝它按 base.keys 从 actor 裸字段取的值）
        _bd = self._decl["base"]
        if _bd["mode"] == "value":
            vals: dict = dict(_bd["value"])
        else:
            _miss = [k for k in _bd["keys"] if k not in (base or {})]
            if _miss:
                raise PanelDeclError(
                    f"base.mode=actor：调用方未提供声明的键 {_miss}"
                    f"（声明的 keys = {_bd['keys']}）")
            vals = {k: float(base[k]) for k in _bd["keys"]}
        trace: dict = {k: [] for k in vals}
        resolved: dict = {}

        for L in self._layers:
            if L["status"] == "inactive":
                continue
            if not _when_ok(L.get("when"), ctx):
                continue
            keys = sorted(vals) if L["keys"] == "*" else list(L["keys"])
            if L["mode"] == "set":
                for k in keys:
                    v = self._value_of(L, k, ctx)
                    vals[k] = v                                     # 覆盖：不钳
                    trace.setdefault(k, []).append(TraceRow(
                        layer=L["id"], src=L["src"], group=L["group"], mode="set",
                        **{"in": None}, out=v, delta=None))
                continue
            for k in keys:
                c = self._value_of(L, k, ctx)
                old = vals.get(k, 0)
                v = old + c if L["mode"] == "add" else old * c
                # ★ 用 .get()：`cap`/`floor` 是可选字段，只在声明时才在 dict 里
                if L.get("cap") is not None:
                    v = min(v, L["cap"])
                if L.get("floor") is not None:
                    v = max(v, L["floor"])
                vals[k] = v
                trace.setdefault(k, []).append(TraceRow(
                    layer=L["id"], src=L["src"], group=L["group"], mode=L["mode"],
                    **{"in": old}, out=v, delta=(v - old)))

        ik, rd = self._decl["emit"]["int_keys"], self._decl["emit"]["round"]
        for k, v in vals.items():
            resolved[k] = int(v) if k in ik else round(float(v), rd)

        rp = ResolvedPanel(resolved, self._layers, ctx)
        rp._trace = trace
        rp.set_base_snapshot(vals)
        return rp

    def _value_of(self, L, k, ctx):
        if "ref" in L and isinstance(L["ref"], str):
            path = L["ref"]
            _need(path.startswith("$"), f"层 {L['id']!r} 的 ref 必须以 $ 开头，收到 {path!r}")
            cur = (ctx.get("refs") or {})
            for seg in path[1:].split("."):
                _need(isinstance(cur, dict) and seg in cur,
                      f"层 {L['id']!r} 的 ref={path!r} 取不到"
                      f"（ctx['refs'] 顶层域：{sorted((ctx.get('refs') or {}))[:8]}…）")
                cur = cur[seg]
            _need(_is_finite(cur), f"层 {L['id']!r} 的 ref={path!r} 取到的不是有限数：{cur!r}")
            return cur
        v = L["values"]
        if L["mode"] == "mul" and L["apply"] == "whole":
            _need("*" in v, f"层 {L['id']!r} 的 apply=whole 需要 values[\"*\"]")
            return v["*"]
        _need(k in v,
              f"层 {L['id']!r} 的 values 里没有键 {k!r}（有的是 {sorted(v)[:8]}…）")
        return v[k]


def cached_stack(stack_id: str, decl: dict) -> PanelStack:
    """按 `(stack_id, version)` 缓存校验结果（对齐 `expr` 的编译缓存口径）。"""
    key = (stack_id, decl.get("version"))
    hit = _STACK_CACHE.get(key)
    if hit is not None:
        return hit
    s = PanelStack.from_decl(decl)
    if len(_STACK_CACHE) >= _MAX_CACHE:
        _STACK_CACHE.clear()
    _STACK_CACHE[key] = s
    return s
