# -*- coding: utf-8 -*-
"""掉落池预览（编辑器用）—— 用引擎**同一份** LootTable 代码算结构与权重。

为什么值得为它破一条纪律
------------------------
`editor/packages.py` 写着「编辑器主进程零引擎副作用，不 import `saintess_engine`」——
那条纪律针对的是**会挂 hook / 改全局状态**的战斗域。`saintess_engine.loot` 是**纯计算模块**
（池 + 策略注册表 + 展开 + 审计；零挂载、零全局副作用，与 `space` / `version` 同性质），
import 它不产生任何引擎副作用。

换来的东西是硬的：权重的算法、展开的规则、审计的判据**只有一份实现** ——
编辑器里看到的「这条多常见 / 子池能出什么 / 哪里断链」和游戏里跑的同一段代码。
若在前端用 JS 重写一遍（权重归一、cutoff 累计、展开递归），两处迟早漂移，
而且漂移时**没人会发现**（编辑器好看，游戏里不出货）。

引擎零知识 → 编辑器不许装懂
---------------------------
`LootTable` 在这里的 `resolver=None`（内容侧才持有引用解析）。因此预览**只**展示：
结构与权重、展开候选、结构审计。它**不假装知道**某个引用（`mat_a`）是哪件物品、
是哪个池 —— 需要解析才能回答的部分，一律写进 `warnings`，宁可让用户看到「这里要
内容侧 resolver」，也不编一个看起来合理的答案。

对外接口
--------
    build(entry, key="", pools=None) -> dict   # 单条池数据 → 预览（含 warnings）
    build_file(data, key) -> dict              # 表形态取一条（key 不存在 → {ok: False, error}）

返回（ok=True）：`{ok, key, type, strategy_uses, entries, rolls, expanded_count,
expanded_unique, audit: {ok, issues}, warnings}`；坏数据 / 池不存在 → `{ok: False, error, warnings}`。
"""
from __future__ import annotations

# 纯计算模块：不挂 hook、不改全局（同 space / version 的性质）
from saintess_engine.loot import STRATEGIES, LootTable, weigh

_ANCHOR = "__pool__"          # key 缺省时的锚点（只用于表内查找，不对外露出）

_NO_RESOLVER = ("引用解析需要内容侧提供 resolver —— 预览只显示结构与权重，"
                "不判断某个引用（如 mat_a）到底是什么东西、也不会替它编一个答案。")
_LEVEL_WINDOW = ("有条目带等级窗口（min_lv / max_lv）：实际会不会进候选取决于上下文等级"
                 "（player_level / monster_lv），预览没有上下文，占比是按**全量权重**算的。")


def _fail(msg: str, warnings=None) -> dict:
    return {"ok": False, "error": msg, "warnings": list(warnings or [])}


_CYCLE = "池之间疑似循环引用（子池展开递归不收敛）—— 检查 rolls 的 pool 是否绕回了自己。"


def _safe_expand(table: LootTable, ref):
    """引擎 `expand()` 的守卫：池互相引用会递归不收敛 → 报「坏数据」，不是 500。"""
    try:
        return table.expand(ref), None
    except RecursionError:
        return [], _CYCLE


def _add(warnings: list, msg: str) -> None:
    """去重追加（同一个原因不用刷屏）。"""
    if msg not in warnings:
        warnings.append(msg)


def _ratio(w, total):
    """占比（0~1，四位小数）；算不了 → None。"""
    if total is None or total <= 0:
        return None
    return round(float(w) / float(total), 4)


def _pct(w, total):
    r = _ratio(w, total)
    return None if r is None else round(r * 100, 2)


def _n_of(raw):
    """份数原样带回（int 或 [a,b]）——引擎的 `roll_range` 才解释它，预览不改写。"""
    return raw


def build(entry: dict, key: str = "", pools=None) -> dict:
    """把一条池数据算成预览：`{ok, ...}`（纯 JSON，可直接发前端）。"""
    warnings: list = []
    if not isinstance(entry, dict):
        return _fail("数据不是对象（一个池应当是一个 JSON 对象）", warnings)

    anchor = str(key or _ANCHOR)
    tbl_pools = dict(pools) if isinstance(pools, dict) else {}
    tbl_pools.setdefault(anchor, entry)
    table = LootTable(tbl_pools, resolver=None)      # ← 不做引用解析（见模块 docstring）

    ptype = entry.get("type")
    if not isinstance(ptype, str) or not ptype.strip():
        return _fail("缺少 type（策略名）：内置 weighted / fixed / table / table_choice，"
                     "内容侧也能注册自己的策略名", warnings)
    ptype = ptype.strip()

    spec = table.strategy_of(entry)
    uses = spec.get("uses", "entries")
    _add(warnings, _NO_RESOLVER)
    if ptype not in STRATEGIES:
        _add(warnings, f"策略名 {ptype!r} 不在内置策略表里（内置：{', '.join(sorted(STRATEGIES))}）——"
                       f"内容侧可以注册自己的策略；未注册时引擎按 weighted 兜底，预览同此。")

    rows: list = []
    rolls: list = []

    if uses == "entries":
        raw = entry.get("entries")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            return _fail("entries 必须是条目数组", warnings)
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                return _fail(f"entries 第 {i + 1} 项不是对象（每条至少要有 item）", warnings)
            if not str(e.get("item") or "").strip():
                return _fail(f"entries 第 {i + 1} 项缺 item（产出引用）", warnings)
        weights = weigh(raw)                          # ← 引擎同一份权重算法
        total = sum(weights)
        needs_weights = bool(spec.get("needs_weights"))
        if needs_weights and total <= 0:
            return _fail("权重和 ≤ 0：这批条目谁都抽不到（检查 w 字段）", warnings)
        if not raw:
            _add(warnings, "entries 为空：这个池什么都出不来（审计会报「空池」）。")
        if any((e.get("min_lv") is not None or e.get("max_lv") is not None) for e in raw):
            _add(warnings, _LEVEL_WINDOW)
        for e, w in zip(raw, weights):
            w_out = int(w) if needs_weights else None      # fixed：w 不参与抽取 → 不给数（防误导）
            share = _ratio(w, total) if needs_weights else None
            rows.append({
                "ref": str(e.get("item")),
                "w": w_out,
                "n": _n_of(e.get("n")),
                "min_lv": e.get("min_lv"),
                "max_lv": e.get("max_lv"),
                "share": share,                        # 0~1；fixed 型 = None（占比不适用）
                "share_pct": (_pct(w, total) if needs_weights else None),
            })
        if needs_weights:                              # 占比降序（非程序员先看最常见的）
            rows.sort(key=lambda r: (-(r["w"] or 0), r["ref"]))

    elif uses == "rolls":
        raw = entry.get("rolls")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            return _fail("rolls 必须是数组（每行至少要有 pool）", warnings)
        for i, rc in enumerate(raw):
            if not isinstance(rc, dict):
                return _fail(f"rolls 第 {i + 1} 项不是对象（每行至少要有 pool）", warnings)
            if not str(rc.get("pool") or "").strip():
                return _fail(f"rolls 第 {i + 1} 项缺 pool（子池 key 或内容侧引用）", warnings)
        if not raw:
            _add(warnings, "rolls 为空：这个池什么都出不来（审计会报「空池」）。")
        cutoffs = [rc.get("cutoff") for rc in raw if rc.get("cutoff") is not None]
        if cutoffs:
            acc = sum(float(c or 0) for c in cutoffs)
            if abs(acc - 1.0) > 1e-9:
                _add(warnings, f"cutoff 累计 = {round(acc, 4)}（≠ 1.0）：互斥档按累计选择，"
                               f"末档会兜底吃掉剩余概率（引擎容错，不报错）。")
        for rc in raw:
            sub = str(rc.get("pool")).strip()
            is_sub_pool = table.pool(sub) is not None   # 引擎查表（含前缀剥离规则）
            sub_expanded, cycle = _safe_expand(table, sub) if is_sub_pool else ([], None)
            if cycle:
                return _fail(cycle, warnings)
            if not is_sub_pool:
                _add(warnings, f"rolls 里的 {sub} 不在本域数据里：子池前缀 / 引用写法由内容侧"
                               f"注册（inline_prefixes 等），预览不猜 —— 引擎审计对此报「断链」。")
            rolls.append({
                "pool": sub,
                "chance": rc.get("chance"),
                "cutoff": rc.get("cutoff"),
                "n": _n_of(rc.get("n")),
                "fallback": rc.get("fallback"),
                "fallback_n": rc.get("fallback_n"),
                "is_sub_pool": is_sub_pool,
                "expanded_count": len(sub_expanded),
                "expanded_unique": len(set(sub_expanded)),
                "expanded": sub_expanded[:40],          # 子池展开结果（引擎同一份 expand）
            })
    else:
        _add(warnings, f"策略 {ptype!r} 声明 uses={uses!r}：参数表既不是 entries 也不是 rolls，"
                       f"预览只给展开结果（内容侧策略自己解释数据）。")

    expanded, cycle = _safe_expand(table, anchor)     # ← 引擎同一份展开
    if cycle:
        return _fail(cycle, warnings)
    audit_rep = table.audit()                          # ← 引擎同一份审计
    issues = [{"level": lvl, "pool": pk, "message": msg}
              for (lvl, pk, msg) in audit_rep["issues"] if pk == anchor]

    return {
        "ok": True,
        "key": key or "",
        "type": ptype,
        "strategy_uses": uses,
        "entries": rows,
        "rolls": rolls,
        "expanded_count": len(expanded),
        "expanded_unique": len(set(expanded)),
        "audit": {"ok": not issues, "issues": issues},
        "warnings": warnings,
    }


def build_file(data: dict, key: str) -> dict:
    """表形态 `{池key: 池对象}` 里取一条算预览（key 不存在 → ok=False + 中文原因）。"""
    if not isinstance(data, dict):
        return _fail("整表不是对象（应当是 {池key: 池对象}）")
    entry = data.get(key)
    if entry is None:
        return _fail(f"没有这条池：{key}")
    return build(entry, key, pools=data)
