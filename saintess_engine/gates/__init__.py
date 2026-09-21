# -*- coding: utf-8 -*-
"""数值预算门禁（E3）—— 把「配平」从人肉检查变成可复跑的引擎工具。

设计真源：`aetheran-designer/12_迁移引擎评估/02_引擎提升设计_E3E5E4.md` §2。

## 为什么建

旧项目**没有**这个能力：装备 687 条靠人肉 + 工作区十几个临时 `_audit_*.py` 脚本检查，
所以会出现「同装等一件强三倍」这种事。本模块给出一组**纯函数校验器**，
让内容侧（或 CI）能一次跑完、拿到全部违规、给退出码。

## 通用约定

- 每个校验器签名 = `(被测数据…, *, <阈值>, label) -> list[str]`；**空列表 = 通过**，
  否则每条是一个**完整的中文可读句**。
- **点名到条目**是硬要求：每条报错含 `组标签 + 条目 id + 字段名 + 实测值 + 阈值 + 差多少`。
- 数值格式：一律 `%.4g`（避免浮点噪音进文案）；比值用 `%.1%`。
- `label` 空串 / 非 str ⇒ 抛 `TypeError`（**用法错抛异常**）；`budget`/`tol`/`cap` 非法 ⇒ 抛 `ValueError`。
  （对比：**数据错**只给文案，不抛 —— 因为配平是"一次跑完、报全部"的批处理。）

## 有意不做（划清边界，别当漏项）

- **不算 PE**：公式与边际归因在内容侧（`03_数值公式/02_PE模型与属性权重.md`）。引擎只比大小、只算比率。
- **不猜分组键**：哪些条目算「同组」由调用方给。
- **不读文件、不建索引、不缓存**。
- **不做越权修正**：只报不改。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

__all__ = [
    "within_budget", "spread_within", "monotone_by", "within_cap",
    "share_within", "sum_within",
]

_DIRECTIONS = ("nondecreasing", "nonincreasing", "increasing", "decreasing")


# ════════════════════════════════════════════════════════════
# 内部：参数校验（用法错 ⇒ 抛）
# ════════════════════════════════════════════════════════════
def _num(v, name, *, allow_none=False, positive=False, nonneg=False):
    """数值入参校验。`positive` = 必须 > 0；`nonneg` = 必须 ≥ 0；都不给 ⇒ 允许负数。

    ★ 默认**允许负数**是有意的：`spread_within` 要处理"全负组"（分母改用 `|min|`）。
    只在语义上确实不该为负的地方（预算/占比/上限）才传 `nonneg=True`。
    """
    if v is None:
        if allow_none:
            return None
        raise ValueError(f"{name} 不得为 None")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} 必须是数值，收到 {type(v).__name__}: {v!r}")
    if v != v:
        raise ValueError(f"{name} 不得为 NaN")
    if positive and v <= 0:
        raise ValueError(f"{name} 必须 > 0，收到 {v!r}")
    if nonneg and not positive and v < 0:
        raise ValueError(f"{name} 不得为负，收到 {v!r}")
    return float(v)


def _label(label) -> str:
    if not isinstance(label, str) or not label.strip():
        raise TypeError(f"label 必须是非空字符串（用法错），收到 {label!r}")
    return label


def _g(x) -> str:
    """数值文案：`%.4g`（避免 10.000000000000002 之类的浮点噪音）。"""
    return f"{x:.4g}"


def _p(x) -> str:
    return f"{x:.1%}"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ════════════════════════════════════════════════════════════
# 校验器 1 · 单值预算内
# ════════════════════════════════════════════════════════════
def within_budget(value, *, budget, label) -> list[str]:
    """`value ≤ budget` 通过；**严格大于**才报红（恰等于预算是允许的）。

    落地判据：`PE(装等 L, 品阶 Q) = PE_base(L) × (1 + 0.08 × Q)`，单件 PE 不得超过它。
    """
    lb = _label(label)
    b = _num(budget, f"{lb}: budget", nonneg=True)
    v = _num(value, f"{lb}: value", nonneg=True)
    if v <= b:
        return []
    over = (v / b - 1.0) if b > 0 else float("inf")
    return [f"{lb} 超预算：实测 {_g(v)} > 上限 {_g(b)}（超出 {_p(over)}）"]


# ════════════════════════════════════════════════════════════
# 校验器 2 · 同组极差
# ════════════════════════════════════════════════════════════
def spread_within(rows: Sequence[tuple[str, float]], *, tol, label) -> list[str]:
    """`(max − min) / max ≤ tol`（装备 5% / 技能 15%）。

    - `rows` 长度 ≥ 1；**0 条 → 抛 ValueError**（空组不能算通过，否则「没填 = 配平」）。
    - 重复 id → 抛 ValueError（点名重复 id）。
    - `max ≤ 0`（全负/全零）时改用 `(max − min) / abs(min)` —— 否则除零。
    - **分组由调用方给**（同装等 + 同品阶 + 同槽位 / 同职业 + 同等级段），引擎不猜分组键。
    """
    lb = _label(label)
    t = _num(tol, f"{lb}: tol")
    if t > 1:
        raise ValueError(f"{lb}: tol 必须 ≤ 1，收到 {t!r}")
    rows = list(rows)
    if not rows:
        raise ValueError(f"{lb}: rows 为空 —— 空组不能算通过（否则「没填 = 配平」）")
    seen: set = set()
    for rid, _v in rows:
        if rid in seen:
            raise ValueError(f"{lb}: 重复 id {rid!r}")
        seen.add(rid)
    vals = [(str(rid), _num(v, f"{lb}: {rid}")) for rid, v in rows]
    hi_id, hi = max(vals, key=lambda p: p[1])
    lo_id, lo = min(vals, key=lambda p: p[1])
    denom = hi if hi > 0 else abs(lo)
    if denom == 0:
        return []                                   # 全零 ⇒ 极差 0 ⇒ 必通过
    r = (hi - lo) / denom
    # 越界条目：取极差贡献最大的若干条（这里给 max/min 两侧 + 明显偏离均值的）
    bad = [i for i, v in vals if abs(v - hi) > 1e-12 and abs(v - lo) > 1e-12]
    ids = ", ".join([hi_id, lo_id] + [i for i in bad][:6])
    if r <= t:
        return []
    return [f"{lb} 极差超限：max {_g(hi)}（{hi_id}）/ min {_g(lo)}（{lo_id}）"
            f"= {r:.1%} > {t:.0%}；越界条目：{ids}"]


# ════════════════════════════════════════════════════════════
# 校验器 3 · 成长单调
# ════════════════════════════════════════════════════════════
def monotone_by(rows: Sequence[tuple[int, Mapping[str, float]]], *, keys,
                order_key="level", direction="nondecreasing", label):
    """升 1 级不许降。返回 **`(errors, warns)`**。

    - 内部按 `order_key`（默认第 0 元）**升序**排序后再比（调用方给的表可能乱序）。
    - 键重复 → 抛 ValueError（点名）。
    - **缺字段的行直接跳过该字段**（「宁放过不假红」），跳过次数作为 `warn` 返回。
    """
    lb = _label(label)
    if direction not in _DIRECTIONS:
        raise ValueError(f"{lb}: direction={direction!r} 非法（允许 {_DIRECTIONS}）")
    if not isinstance(keys, Sequence) or isinstance(keys, str) or not keys:
        raise ValueError(f"{lb}: keys 必须是非空字符串序列")
    rows = list(rows)
    if not rows:
        raise ValueError(f"{lb}: rows 为空")
    idx = [i for i, r in enumerate(rows) if _is_num(r[0])]
    if len(idx) != len(rows):
        raise ValueError(f"{lb}: 每行第 0 元必须是数值（作为 {order_key}），"
                         f"有 {len(rows) - len(idx)} 行不满足")
    ordered = sorted(rows, key=lambda r: r[0])
    lv = [r[0] for r in ordered]
    if len(set(lv)) != len(lv):
        dup = sorted({x for x in lv if lv.count(x) > 1})
        raise ValueError(f"{lb}: {order_key} 重复 {dup}")
    errs: list[str] = []
    warns: list[str] = []
    strict = direction in ("increasing", "decreasing")
    up = direction in ("nondecreasing", "increasing")
    for k in keys:
        prev_lv = prev_v = None
        for row in ordered:
            level, fields = row[0], row[1]
            if not isinstance(fields, Mapping) or k not in fields:
                warns.append(f"{lb}：{order_key} {level} 缺字段 {k}（已跳过）")
                continue
            v = fields[k]
            if not _is_num(v):
                warns.append(f"{lb}：{order_key} {level} 的 {k} 不是数值（已跳过）")
                continue
            if prev_v is not None:
                bad = (v < prev_v) if up else (v > prev_v)
                if strict and v == prev_v:
                    bad = True
                if bad:
                    word = "降到" if v < prev_v else "升到"
                    errs.append(f"{lb} 成长非单调：{k} 在 {order_key} {prev_lv}→{level} "
                                f"从 {_g(prev_v)} {word} {_g(v)}（{v - prev_v:+.4g}）")
            prev_lv, prev_v = level, v
    return errs, warns


# ════════════════════════════════════════════════════════════
# 校验器 4 · 属性 cap 未越界
# ════════════════════════════════════════════════════════════
def within_cap(value, *, cap, label) -> list[str]:
    """`cap is None` ⇒ **无上限，永远通过**；给了数值 ⇒ `value ≤ cap`。

    ★ 字段级坑（改动声明时必读）：`crit_dmg` 的上限 **1.5** 是**加算量**（上限 3.0 倍），不是比例；
    `haste` 是 `None`（自然递减，无上限）；`pene_*` / `lifesteal` / `heal_power` / `elem_res` / `thorns`
    是「直接百分比」而非 rating。**cap 表的值必须逐条照抄，不许把 `None` 写成 0。**
    """
    lb = _label(label)
    v = _num(value, f"{lb}: value", nonneg=True)
    c = _num(cap, f"{lb}: cap", allow_none=True, nonneg=True)
    if c is None:
        return []
    if v <= c:
        return []
    return [f"{lb} 超出上限：实测 {_g(v)} > 上限 {_g(c)}（超出 {_g(v - c)}）"]


# ════════════════════════════════════════════════════════════
# 校验器 5 · 占比上限
# ════════════════════════════════════════════════════════════
def share_within(parts: Sequence[tuple[str, float]], *, total, cap, label) -> list[str]:
    """逐部件 `part / total ≤ cap`（主属性 ≤60% / 词条合计 ≤40% / 单一来源 ≤45%）。

    `total ≤ 0` → 抛 ValueError（不能除以 0 也算通过）。
    """
    lb = _label(label)
    tot = _num(total, f"{lb}: total", positive=True)
    c = _num(cap, f"{lb}: cap")
    if not (0 < c <= 1):
        raise ValueError(f"{lb}: cap 必须 ∈ (0,1]，收到 {c!r}")
    parts = list(parts)
    if not parts:
        raise ValueError(f"{lb}: parts 为空")
    out = []
    for name, v in parts:
        x = _num(v, f"{lb}: {name}", nonneg=True)
        r = x / tot
        if r > c:
            out.append(f"{lb} {name} 占比超限：{name}={_g(x)} / total={_g(tot)} "
                       f"= {r:.1%} > {c:.0%}")
    return out


# ════════════════════════════════════════════════════════════
# 校验器 6 · 合计预算内
# ════════════════════════════════════════════════════════════
def sum_within(parts: Sequence[tuple[str, float]], *, budget, label) -> list[str]:
    """`Σ parts ≤ budget`（用于「6 槽合计 = 35%」这类整体校验）。"""
    lb = _label(label)
    b = _num(budget, f"{lb}: budget")
    parts = list(parts)
    if not parts:
        raise ValueError(f"{lb}: parts 为空")
    tot = 0.0
    for name, v in parts:
        tot += _num(v, f"{lb}: {name}", nonneg=True)
    if tot <= b:
        return []
    over = (tot / b - 1.0) if b > 0 else float("inf")
    return [f"{lb} 合计超预算：Σ={_g(tot)} > 上限 {_g(b)}（超出 {_p(over)}）"]
