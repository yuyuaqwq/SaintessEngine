# -*- coding: utf-8 -*-
"""声明式公式表（E1）—— 让「换个游戏只写 JSON」在数值公式这一层成立。

设计真源：`aetheran-designer/12_迁移引擎评估/01_引擎提升设计_E1E2.md` §3（字段级设计 + V1–V12）。

## 这个形状解决什么

现状：`config._HOOKS["formulas"]` 要内容侧交一个 **Python 模块对象**（实测被消费 13 个方法）。
⇒ 想给新游戏换一套公式，必须写一个 Python 模块。

本形状：内容侧只写**一张 JSON 声明表**，本模块负责校验 + 预编译 + 求值 + 逐步打印。

## 三类条目

| `kind` | 语义 | 关键字段 |
|---|---|---|
| `formula` | 单条表达式 | `expr` |
| `aggregate` | 对**多变来源列表**求和/连乘 | `op` / `over` / `item_expr` / `combine` |
| `chain` | 多步流水线（每步可引用前面所有步） | `steps[]` / `random` |

## 边界（本批**不做**，别当漏项）

1. **不替换既有 13 个公式读口** —— 本模块交付「形状 + 求值器 + 校验 + 打印」；
   **接线**（哪条战斗流程调哪条声明）留下一批（E1b），且接线要逐条与 `battle/actions.py` 做冻结比对。
2. 不做公式的可视化编辑器（只落域声明 + schema）。
3. 不做公式的预算门禁（归 E3）。
4. 不启用 `expr` 侧的变量表（变量域由**每条声明**的 `vars` 表达）。

## ⚠️ 已登记的边界（实测发现，本批不动 · 下一轮再议）

`expr` 的 tokenizer 对**孤立的二元操作符**（前一个 token 已是操作数时出现的 `*` / `/` / `+`）
是**静默忽略**的 —— 例：`"a +* 3"` 会被当作 `a + 3` 求值，**不报错**。
⇒ V4（"能编译通过"）抓不住这类笔误。

**为什么本批不动**：设计 §3.2.4 明写「不改 `expr/` 除 `^` 之外的任何一行」，
且改成报错会动到既有表达式的接受面（有零回归风险，需先扫全量表达式）。
**建议的下一轮处置**：在 `expr` 的 tokenizer 把"孤立二元操作符"改为 `ExprError`，
前置条件 = 先扫 `games/orlandia/**` 与 `examples/**` 的全部表达式串，确认零命中后再改。
"""
from __future__ import annotations

import random as _random
from typing import Any

from .. import expr as _expr

__all__ = ["FormulaTable", "FormulaDeclError", "StepRow"]

_KINDS = ("formula", "aggregate", "chain")
_RETURNS = ("number", "int", "pct", "tick")
_REF_PREFIXES = ("const.", "formula.", "skeleton.", "param.")
#: 域条目表里的保留键（不是条目）：常量段
CONST_KEY = "$const"
_ROUND_DEFAULT = 6


class FormulaDeclError(ValueError):
    """公式声明非法（装配期 fail-closed；不做运行期兜底）。"""


class StepRow(dict):
    """`chain` 的一步中间量（可当 dict 用；打印格式对齐设计 §2.4）。"""

    __slots__ = ()


# ════════════════════════════════════════════════════════════
# 小工具
# ════════════════════════════════════════════════════════════
def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and (
        x == x and x not in (float("inf"), float("-inf")))


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise FormulaDeclError(msg)


def _round_to(v, nd):
    if isinstance(v, int):
        return v
    return round(float(v), int(nd))


def _apply_clamp(v, clamp, floor, cap):
    """结果钳制。`floor`/`cap` 是 `clamp` 的单边糖（V8 保证不同现）。"""
    if clamp is not None:
        lo, hi = clamp
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)
        return v
    if floor is not None:
        v = max(v, floor)
    if cap is not None:
        v = min(v, cap)
    return v


def _apply_guard(vrs: dict, guard: dict | None) -> dict:
    """输入变量级钳制（求值**前**施加）—— 用于 `max(spd,1)` 这类防除零。"""
    if not guard:
        return vrs
    out = dict(vrs)
    for name, g in guard.items():
        if name not in out:
            continue
        v = out[name]
        if not isinstance(v, (int, float)):
            continue
        if g.get("floor") is not None:
            v = max(v, float(g["floor"]))
        if g.get("cap") is not None:
            v = min(v, float(g["cap"]))
        out[name] = v
    return out


def _when_match(when, ctx) -> bool:
    """`when` 判据：缺 = 恒通过；写了但**值不认识** = 不命中（不作为报错）。

    形状：`{flag: 值}` 或 `[{flag: 值}, ...]`（数组 = 逐项 OR？否 —— 数组 = 全部 AND，
    与 §2.2.2 口径一致；每项内部 `{flag: 值}` 是 AND，值可为标量或列表（列表 = 命中任一））。
    """
    if when is None:
        return True
    flags = (ctx or {}).get("flags") or {}
    items = when if isinstance(when, list) else [when]
    for it in items:
        if not isinstance(it, dict):
            return False
        for k, want in it.items():
            got = flags.get(k)
            if got is None:
                return False
            wants = want if isinstance(want, list) else [want]
            if got not in wants:
                return False
    return True


# ════════════════════════════════════════════════════════════
# 主对象
# ════════════════════════════════════════════════════════════
class FormulaTable:
    """不可变公式表。用 `from_decl` 构造（构造函数不做校验）。"""

    def __init__(self, decl: dict, entries: dict, consts: dict, skeleton_fn=None):
        self._decl = decl
        self._e = entries          # id -> 规范化后的条目（含预编译产物）
        self._consts = consts
        self._skeleton_fn = skeleton_fn

    # ── 构造 + 校验（V1–V12 全跑）─────────────────────────────
    @classmethod
    def from_decl(cls, table: dict, *, skeleton_fn=None) -> "FormulaTable":
        """`table` = 域条目表 `{id: 条目}`（+ 可选保留键 `$const`）。"""
        _need(isinstance(table, dict), f"公式表必须是对象，收到 {type(table).__name__}")
        consts = table.get(CONST_KEY) or {}
        _need(isinstance(consts, dict), f"{CONST_KEY} 必须是对象")

        entries: dict[str, dict] = {}
        for eid, e in table.items():
            if eid == CONST_KEY:
                continue
            _need(isinstance(e, dict), f"条目 {eid!r} 必须是对象")
            kind = e.get("kind")                           # V1
            _need(kind in _KINDS,
                  f"条目 {eid!r} 的 kind={kind!r} 非法（允许 {_KINDS}）")
            # ★ 与设计文档的一处矛盾（实测发现，已按示例为准）：
            #   字段表写「`returns` 必填=是」，但设计自己给的 `chain` 示例里**没写**
            #   （只在每步上写了）—— 因为 chain 的返回型**可从最后一步推出**，顶层写是冗余。
            #   ⇒ 裁决：`formula`/`aggregate` 必填；`chain` 可省（省则取最后一步的 returns）。
            ret = e.get("returns")
            if ret is None and kind == "chain":
                _steps0 = e.get("steps") or []
                ret = (_steps0[-1].get("returns") if _steps0 and isinstance(_steps0[-1], dict)
                       else "number")
                e = dict(e, returns=ret)
            _need(ret in _RETURNS,
                  f"条目 {eid!r} 的 returns={ret!r} 非法（允许 {_RETURNS}）")
            _need(isinstance(e.get("version"), int) and not isinstance(e.get("version"), bool)
                  and e["version"] >= 1, f"条目 {eid!r} 的 version 必须是 ≥1 的整数")
            vrs = e.get("vars")
            if kind != "chain":
                _need(isinstance(vrs, list) and len(vrs) > 0,
                      f"条目 {eid!r}（{kind}）的 vars 必须是非空数组")
            _need(isinstance(vrs, list) if vrs is not None else True,
                  f"条目 {eid!r} 的 vars 必须是数组")

            # V7 数值有限性
            for nm, val in (e.get("params") or {}).items():
                if not isinstance(val, dict):
                    _need(_is_finite(val),
                          f"条目 {eid!r} 的 params.{nm} 必须是有限数或 {{ref: …}}")
            for fld in ("floor", "cap"):
                if e.get(fld) is not None:
                    _need(_is_finite(e[fld]), f"条目 {eid!r} 的 {fld} 必须是有限数")

            # V8 clamp / floor / cap 不共存、lo ≤ hi
            if e.get("clamp") is not None:
                cl = e["clamp"]
                _need(isinstance(cl, list) and len(cl) == 2,
                      f"条目 {eid!r} 的 clamp 必须是 [lo, hi]")
                _need(e.get("floor") is None and e.get("cap") is None,
                      f"条目 {eid!r} 同时写了 clamp 与 floor/cap（声明自相矛盾）")
                lo, hi = cl
                if lo is not None:
                    _need(_is_finite(lo), f"条目 {eid!r} 的 clamp[0] 必须是有限数或 null")
                if hi is not None:
                    _need(_is_finite(hi), f"条目 {eid!r} 的 clamp[1] 必须是有限数或 null")
                if lo is not None and hi is not None:
                    _need(lo <= hi, f"条目 {eid!r} 的 clamp lo({lo}) > hi({hi})")

            # V11 round
            rd = e.get("round", _ROUND_DEFAULT)
            _need(isinstance(rd, int) and not isinstance(rd, bool) and rd >= 0,
                  f"条目 {eid!r} 的 round 必须是 ≥0 的整数")

            # V12 when 结构
            when = e.get("when")
            _need(when is None or isinstance(when, dict)
                  or (isinstance(when, list) and all(isinstance(x, dict) for x in when)),
                  f"条目 {eid!r} 的 when 必须是映射或映射数组")

            norm = dict(e)
            norm["round"] = rd
            norm["_compiled"] = {}

            # ── kind 专有字段 ──
            if kind == "formula":
                _need(isinstance(e.get("expr"), str) and e["expr"].strip(),
                      f"条目 {eid!r}（formula）的 expr 必须是非空字符串")
                norm["_compiled"]["expr"] = _compile(eid, "expr", e["expr"])   # V4
            elif kind == "aggregate":
                _need(e.get("op") in ("sum", "prod"),
                      f"条目 {eid!r}（aggregate）的 op 必须是 sum/prod")
                for fld in ("over", "item_expr", "combine"):
                    _need(isinstance(e.get(fld), str) and e[fld].strip(),
                          f"条目 {eid!r}（aggregate）缺 {fld}")
                norm["_compiled"]["item_expr"] = _compile(eid, "item_expr", e["item_expr"])
                norm["_compiled"]["combine"] = _compile(eid, "combine", e["combine"])
            else:  # chain  (V10)
                steps = e.get("steps")
                _need(isinstance(steps, list) and len(steps) > 0,
                      f"条目 {eid!r}（chain）的 steps 必须是非空数组")
                seen: set[str] = set()
                csteps = []
                for i, st in enumerate(steps):
                    _need(isinstance(st, dict), f"条目 {eid!r} 的第 {i} 步必须是对象")
                    sid = st.get("id")
                    _need(isinstance(sid, str) and sid.strip(),
                          f"条目 {eid!r} 的第 {i} 步缺 id")
                    _need(sid not in seen, f"条目 {eid!r} 的步 id {sid!r} 重复")
                    seen.add(sid)
                    has_expr, has_use = isinstance(st.get("expr"), str), isinstance(st.get("use"), str)
                    _need(has_expr != has_use,
                          f"条目 {eid!r} 的步 {sid!r} 必须**恰好**有 expr 或 use 之一")
                    cs = dict(st)
                    cs["round"] = st.get("round", rd)
                    cs["_compiled"] = {}
                    if has_expr:
                        cs["_compiled"]["expr"] = _compile(eid, f"steps.{sid}.expr", st["expr"])
                    csteps.append(cs)
                norm["_steps"] = csteps
                rnd = e.get("random")                                    # V7
                if rnd is not None:
                    _need(isinstance(rnd, dict) and isinstance(rnd.get("key"), str),
                          f"条目 {eid!r} 的 random 必须形如 {{key, pct}}")
                    _need(isinstance(rnd.get("pct"), (int, float, str)),
                          f"条目 {eid!r} 的 random.pct 必须是数或变量名")
                    if isinstance(rnd["pct"], (int, float)):
                        _need(_is_finite(rnd["pct"]),
                              f"条目 {eid!r} 的 random.pct 必须是有限数")
                norm["_random"] = rnd
            entries[eid] = norm

        _check_no_cycle(entries)                                            # V2
        for eid, e in entries.items():
            _check_var_domain(eid, e)                                       # V5 / V9
        return cls(table, entries, consts, skeleton_fn)

    # ── 只读接口 ──────────────────────────────────────────────
    def ids(self) -> list[str]:
        return list(self._e)

    def vars_of(self, eid: str) -> frozenset[str]:
        e = self._get(eid)
        out = set(e.get("vars") or [])
        if e["kind"] == "chain":
            out |= {s["id"] for s in e["_steps"]}
        if e.get("_random"):
            out.add(e["_random"]["key"])
        return frozenset(out)

    def check(self, eid: str, vrs: dict) -> list[str]:
        """缺变量体检（**不抛**）：返回该条声明需要但 `vrs` 里没有的名字。"""
        need = set(self._e.get(eid, {}).get("vars") or [])
        if self._e.get(eid, {}).get("_random"):
            need.add(self._e[eid]["_random"]["key"])
        return sorted(n for n in need if n not in vrs)

    def wrong_vars(self, eid: str, vrs: dict) -> list[str]:
        """多变量体检（**不抛**）：传了但该条不认识的变量名（防拼写漂移）。"""
        known = self.vars_of(eid)
        return sorted(k for k in vrs if k not in known)

    # ── 求值 ──────────────────────────────────────────────────
    def eval(self, eid: str, vrs: dict, *, ctx=None):
        """求单条（`formula` / `aggregate`）。**不做 try/except**（声明错在装配期已拦）。"""
        e = self._get(eid)
        _need(e["kind"] != "chain",
              f"条目 {eid!r} 是 chain，请用 .run()（它会返回逐步中间量）")
        if not _when_match(e.get("when"), ctx):
            return None
        return self._eval_entry(eid, e, vrs, ctx)

    def run(self, eid: str, vrs: dict, *, ctx=None):
        """跑 `chain`：返回 `(最终值, [StepRow, …])`。"""
        e = self._get(eid)
        _need(e["kind"] == "chain", f"条目 {eid!r} 不是 chain，请用 .eval()")
        if not _when_match(e.get("when"), ctx):
            return None, []
        return self._run_chain(eid, e, vrs, ctx)

    # ── 内部 ──────────────────────────────────────────────────
    def _get(self, eid):
        _need(eid in self._e, f"公式 id {eid!r} 不在声明表里"
                              f"（表里有 {len(self._e)} 条：{sorted(self._e)[:6]}…）")
        return self._e[eid]

    def _eval_entry(self, eid, e, vrs, ctx):
        p = self._params(eid, e, vrs, ctx)
        if e["kind"] == "formula":
            local = dict(vrs)
            local.update(p)
            local = _apply_guard(local, e.get("guard"))
            local = self._inject_random(e, local)
            v = _expr.eval_expr(e["_compiled"]["expr"], local)
            return self._finish(e, v)

        # aggregate
        over = list(vrs.get(e["over"]) or [])
        acc = 0.0 if e["op"] == "sum" else 1.0
        for x in over:
            iv = _expr.eval_expr(e["_compiled"]["item_expr"], dict(p, x=float(x)))
            acc = (acc + iv) if e["op"] == "sum" else (acc * iv)
        local = dict(vrs)
        local.update(p)
        local["agg"] = acc                      # `combine` 里聚合结果的固定变量名
        local = _apply_guard(local, e.get("guard"))
        local = self._inject_random(e, local)
        v = _expr.eval_expr(e["_compiled"]["combine"], local)
        return self._finish(e, v)

    def _run_chain(self, eid, e, vrs, ctx):
        p = self._params(eid, e, vrs, ctx)
        local = dict(vrs)
        local.update(p)
        local = _apply_guard(local, e.get("guard"))
        local = self._inject_random(e, local)
        rows: list[StepRow] = []
        prev = None
        for st in e["_steps"]:
            if "use" in st:                     # 引用另一条条目的结果
                # ★ E1b/P2 修：必须传 `local`（已累积前面所有步的输出），**不是** `vrs`。
                #   设计口径「每步可用前面所有步结果作变量，步 id 即变量名」对 `use` 步同样成立。
                #   传 `vrs` 会让"用 `use` 把多条串成一条全链"**根本不可行**：
                #   被引的条目看不到上一步产出的 `eff_def` / `k_def` 这类中间量。
                #   （`expr` 步一直是传 `local` 的 —— 这是两处不一致，不是有意区分。）
                v = self._eval_ref(eid, st["use"], local, ctx)
            else:
                v = _expr.eval_expr(st["_compiled"]["expr"], local)
            fl = st.get("floor")
            if fl is not None:
                v = max(v, fl)
            v = _apply_clamp(v, st.get("clamp"), None, st.get("cap"))
            v = _round_to(v, st.get("round", _ROUND_DEFAULT))
            local[st["id"]] = v                 # 步 id 即变量名 ⇒ 后续步可用
            rows.append(StepRow(
                step=st["id"], label=st.get("trace") or st["id"],
                **{"in": prev}, out=v,
                delta_pct=(None if prev in (None, 0) else round((v - prev) / prev * 100.0, 2))))
            prev = v
        if e["_steps"]:
            last = e["_steps"][-1]
            out = local[last["id"]]
            if last.get("returns") == "int" or e.get("returns") == "int":
                out = int(out)
            return out, rows
        return None, []

    def _eval_ref(self, eid, ref_id, vrs, ctx):
        """`use`：引用另一条条目的结果（递归求值，环已在装配期拦下）。"""
        _need(ref_id in self._e,
              f"条目 {eid!r} 的 use={ref_id!r} 指向不存在的条目")
        tgt = self._e[ref_id]
        if tgt["kind"] == "chain":
            return self._run_chain(ref_id, tgt, vrs, ctx)[0]
        return self._eval_entry(ref_id, tgt, vrs, ctx)

    def _inject_random(self, e, local):
        """`random`：引擎唯一允许的随机来源（F2 波动 ±5%）。"""
        rnd = e.get("_random")
        if not rnd:
            return local
        pct = rnd["pct"]
        if isinstance(pct, str):
            pct = float(local.get(pct, 0.0) or 0.0)
        local[rnd["key"]] = _random.uniform(-abs(pct), abs(pct))
        return local

    def _finish(self, e, v):
        v = _apply_clamp(v, e.get("clamp"), e.get("floor"), e.get("cap"))
        v = _round_to(v, e.get("round", _ROUND_DEFAULT))
        if e.get("returns") == "int":
            v = int(v)
        return v

    # ── params 解析（4 种前缀，缺就报错，不静默 0）──────────────
    def _params(self, eid, e, vrs, ctx):
        out = {}
        for nm, spec in (e.get("params") or {}).items():
            if not isinstance(spec, dict):
                out[nm] = spec
                continue
            ref = spec.get("ref")
            _need(isinstance(ref, str) and ref,
                  f"条目 {eid!r} 的 params.{nm} 必须是数或 {{ref: …}}")
            pre = next((p for p in _REF_PREFIXES if ref.startswith(p)), None)
            _need(pre is not None,
                  f"条目 {eid!r} 的 params.{nm}.ref={ref!r} 前缀不认识"
                  f"（允许 {_REF_PREFIXES}）")
            path = ref[len(pre):]
            if pre == "const.":
                cur = self._consts
                for seg in path.split("."):
                    _need(isinstance(cur, dict) and seg in cur,
                          f"条目 {eid!r} 的 const 路径 {ref!r} 在 {CONST_KEY} 里取不到")
                    cur = cur[seg]
                out[nm] = cur
            elif pre == "formula.":
                out[nm] = self._eval_ref(eid, path, vrs, ctx)
            elif pre == "skeleton.":
                sk = self._skeleton() or {}
                cur = sk
                for seg in path.split("."):
                    _need(isinstance(cur, dict) and seg in cur,
                          f"条目 {eid!r} 的 skeleton 路径 {ref!r} 在骨架表里取不到"
                          f"（骨架表顶层键：{sorted(sk)[:8]}…）")
                    cur = cur[seg]
                out[nm] = cur
            else:  # param.
                tb = ((ctx or {}).get("tables") or {})
                cur = tb
                for seg in path.split("."):
                    _need(isinstance(cur, dict) and seg in cur,
                          f"条目 {eid!r} 的 param 路径 {ref!r} 在 ctx['tables'] 里取不到"
                          f"（顶层域：{sorted(tb)[:8]}…）")
                    cur = cur[seg]
                out[nm] = cur
            _need(_is_finite(out[nm]),
                  f"条目 {eid!r} 的 params.{nm}（来自 {ref!r}）不是有限数：{out[nm]!r}")
        return out

    def _skeleton(self):
        if self._skeleton_fn is None:
            return None
        return self._skeleton_fn() if callable(self._skeleton_fn) else self._skeleton_fn


# ════════════════════════════════════════════════════════════
# 装配期辅助
# ════════════════════════════════════════════════════════════
def _compile(eid: str, where: str, s: str):
    """V4：语法错必须装配期现形（`expr.ExprError` 直接上抛，外面包一层点名）。"""
    try:
        return _expr.compile_expr(s)
    except _expr.ExprError as exc:
        raise FormulaDeclError(f"条目 {eid!r} 的 {where} 编译失败：{exc}") from exc


def _check_no_cycle(entries: dict) -> None:
    """V2：`formula.` 引用不得成环（拓扑排序）。"""
    deps = {}
    for eid, e in entries.items():
        d = set()
        for spec in (e.get("params") or {}).values():
            if isinstance(spec, dict) and isinstance(spec.get("ref"), str) \
                    and spec["ref"].startswith("formula."):
                d.add(spec["ref"][len("formula."):])
        if e["kind"] == "chain":
            for st in e["_steps"]:
                if isinstance(st.get("use"), str):
                    d.add(st["use"])
        deps[eid] = d
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in entries}

    def visit(n, stack):
        color[n] = GREY
        for m in deps.get(n, ()):
            if m not in color:
                raise FormulaDeclError(f"条目 {n!r} 引用了不存在的条目 {m!r}")
            if color[m] == GREY:
                raise FormulaDeclError(
                    f"`formula.` 引用成环：{' → '.join(stack + [n, m])}")
            if color[m] == WHITE:
                visit(m, stack + [n])
        color[n] = BLACK

    for k in entries:
        if color[k] == WHITE:
            visit(k, [])


def _check_var_domain(eid: str, e: dict) -> None:
    """V5 / V9：表达式里出现的变量名必须落在**声明过的集合**里。

    允许集合 = `vars` ∪ 步 id ∪ `params` 名 ∪ `guard`/`random` 注入名 ∪ 聚合固定名
    （`aggregate` 的 `x` / `agg`；`chain` 的 `use` 步自带）。
    ★ 为什么必须有这条：`eval_expr` 对**未知变量取 0**（`expr/__init__.py`）⇒
      表达式里拼错一个变量名会**静默算成 0**，是最难查的一类错。
    """
    allowed = set(e.get("vars") or [])
    allowed |= set((e.get("params") or {}))
    allowed |= set((e.get("guard") or {}))
    if e.get("_random"):
        allowed.add(e["_random"]["key"])

    def scan(where, code, extra=frozenset()):
        for tok in code or ():
            if tok[0] == "var" and tok[1] not in allowed and tok[1] not in extra:
                raise FormulaDeclError(
                    f"条目 {eid!r} 的 {where} 里出现了未声明的变量 {tok[1]!r}；"
                    f"声明过的变量域 = {sorted(allowed)}"
                    f"（若这是拼写错，改成域里的名字；若是新变量，请加进 vars）")

    if e["kind"] == "formula":
        scan("expr", e["_compiled"]["expr"])
    elif e["kind"] == "aggregate":
        _need(e["over"] in allowed,
              f"条目 {eid!r}（aggregate）的 over={e['over']!r} 不在 vars 里")
        scan("item_expr", e["_compiled"]["item_expr"], extra={"x"})
        scan("combine", e["_compiled"]["combine"], extra={"agg"})
    else:
        step_ids = {s["id"] for s in e["_steps"]}
        for st in e["_steps"]:
            if "expr" in st:
                scan(f"steps.{st['id']}.expr", st["_compiled"]["expr"], extra=step_ids)

# ============================================================
# E1b：语义槽位 → 声明 id 的绑定（读口）
# ============================================================

#: 引擎**拥有**的槽位名全集。★ 名字中性（引擎不认识任何内容 id）；
#: 包只回答它认识的槽位，答 `None` = 本槽位不声明 ⇒ 对应读口走原路。
#: 加槽位 = 加引擎能力，所以这张表放在引擎侧并在 wiki 列全。
SLOTS = (
    "damage",        # 一次命中的伤害
    "miss",          # 未命中率
    "crit_pct",      # 暴击率
    "crit_mult",     # 暴击倍率
    "act_time",      # 一次行动耗时（时间模型）
    "cd",            # 冷却
    "heal",          # 治疗量
    "threat",        # 仇恨
    "drop_rate",     # 掉落率
)


def binding_of(slot, *, table=None):
    """按**中性槽位名**问绑定表 ⇒ 声明 id（`str`）| `None`。

    **不配 = 不存在**（R1）：
      - `formula_bindings_fn` 未装配 ⇒ 返回 `None`
      - 槽位名不在 `SLOTS` 里 ⇒ 抛 `FormulaDeclError`（**拼错槽位名必须现形**，
        不许静默返回 None —— 否则"绑了但没生效"会变成一个查不出的哑弹）
      - 装配了但答 `None` ⇒ 返回 `None`（= 本槽位有意不声明）

    :param table: 可选，已装配的 `FormulaTable`。给了就不再自己取 hook
        （热路径上避免一次 hook 查询 + 一次装配）
    """
    if slot not in SLOTS:
        raise FormulaDeclError(
            f"槽位名 {slot!r} 不在引擎槽位全集里：{list(SLOTS)}。"
            "★ 拼错槽位名必须现形 —— 静默返回 None 会让『绑了但没生效』变成查不出的哑弹。")
    from .. import config
    f = config.get_hook("formula_bindings_fn")
    if f is None:
        return None
    did = f(slot)
    if did is None:
        return None
    if not isinstance(did, str) or not did.strip():
        raise FormulaDeclError(
            f"槽位 {slot!r} 的绑定必须是声明 id（非空字符串）或 None，收到 {did!r}")
    if table is not None and did not in table.ids():
        raise FormulaDeclError(
            f"槽位 {slot!r} 绑到了声明 {did!r}，但公式表里没有这条（现有 {len(table.ids())} 条）")
    return did


def bindings(*, table=None):
    """一次问全 `SLOTS` ⇒ `{槽位: 声明 id}`（只含**真正绑了**的槽位）。体检/打印用。"""
    out = {}
    for slot in SLOTS:
        did = binding_of(slot, table=table)
        if did is not None:
            out[slot] = did
    return out
