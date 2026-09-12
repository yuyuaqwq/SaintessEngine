# -*- coding: utf-8 -*-
"""副本进度预览（编辑器用）—— 用引擎**同一份** `Progress` 算节点/剩余/末层。

为什么值得为它破一条纪律
------------------------
`editor/packages.py` 写着「编辑器主进程零引擎副作用，不 import `saintess_engine`」——
那条纪律针对的是**会挂 hook / 改全局状态**的战斗域。`saintess_engine.run.Progress` 是
**纯计算模块**（有序节点 + 具名剩余池 + 当前位置 + 预算；零挂载、零全局副作用，与
`loot` / `space` / `version` 同性质），import 它不产生任何引擎副作用。

换来的东西是硬的：「当前在第几站 / 这一站还剩什么 / 能不能推进 / 是不是最后一站」四件事
**只有一份实现** —— 编辑器里看到的推进语义和游戏里跑的同一段代码。若在前端用 JS 重写
一遍（节点序、剩余池、末层判定），两处迟早漂移，而且漂移时**没人会发现**。

引擎零知识 → 编辑器不许装懂
---------------------------
怪名 / Boss / 钥匙 / 地图 / 层名全是**内容侧词汇**，引擎与预览都不认识它们。
预览**只**展示：层表 → 节点序、每层折算出的单位数与剩余、末层标记、结构体检。
「这只怪是什么东西 / 这个钥匙从哪来」需要内容侧解析，一律写进 `warnings`，
宁可让用户看到「这类引用由内容侧解释」，也不编一个看起来合理的答案。

数据不合法**如实报错**（`ok=False`）：层空（没有怪/精英/Boss）、Boss 不在末层、
`min_players > max_players`、倍率 ≤ 0 —— 不假装这里有内容。

对外接口
--------
    build(entry, key="") -> dict      # 一条副本数据 → 进度视图（纯 JSON，可直接发前端）
    build_file(data, key) -> dict     # 表形态 `{副本key: 副本对象}` 取一条
"""
from __future__ import annotations

# 纯计算模块：不挂 hook、不改全局（同 loot / space / version 的性质）
from saintess_engine.run import Progress

_POOL = "units"          # 每层的剩余池名（层内要清的战斗单位）

_NO_VOCAB = ("怪名 / 精英 / Boss / 钥匙 / 地图 / 层名都是内容侧词汇：预览只算结构与进度，"
             "不判断某个引用到底是什么怪、哪把钥匙、能不能拿到。")
_SCALE_DEFAULT = "hp_mult / atk_mult 缺省 = 1.0（不调）；≤ 0 会被当成坏数据报出来。"


def _fail(msg: str, warnings=None) -> dict:
    return {"ok": False, "error": msg, "warnings": list(warnings or [])}


def _add(warnings: list, msg: str) -> None:
    """去重追加（同一个原因不用刷屏）。"""
    if msg not in warnings:
        warnings.append(msg)


def _units_of(stage: dict) -> list:
    """一层 → 要清的战斗单位表（普通怪 / 精英 / Boss，各自带类别，不解析引用）。"""
    out = []
    for kind in ("monsters", "elite", "boss"):
        raw = stage.get(kind)
        if raw is None:
            continue
        if not isinstance(raw, list):
            return None                      # 结构不对 → 调用方报错
        for ref in raw:
            out.append({"kind": kind[:-1] if kind != "monsters" else "monster",
                        "ref": str(ref)})
    return out


def build(entry: dict, key: str = "") -> dict:
    """把一条副本数据算成进度视图：`{ok, ...}`（纯 JSON，可直接发前端）。"""
    warnings: list = []
    if not isinstance(entry, dict):
        return _fail("数据不是对象（一个副本应当是一个 JSON 对象）", warnings)

    name = str(entry.get("name") or "").strip()
    if not name:
        return _fail("缺少 name（副本名）", warnings)

    raw = entry.get("stages")
    if not isinstance(raw, list) or not raw:
        return _fail("stages 必须是非空数组（至少一层；顺序即推进顺序）", warnings)

    min_p = int(entry.get("min_players") or 1)
    max_p = int(entry.get("max_players") or 1)
    if min_p > max_p:
        return _fail(f"min_players({min_p}) > max_players({max_p})：人数区间不成立", warnings)
    for fld in ("hp_mult", "atk_mult"):
        v = entry.get(fld)
        if v is not None and float(v) <= 0:
            return _fail(f"{fld} = {v}（≤ 0）：倍率不成立（1.0 = 不调）", warnings)

    # ── 逐层体检 + 折算单位（不合法就如实报，不假装有内容）──
    specs = []
    for i, st in enumerate(raw, 1):
        if not isinstance(st, dict):
            return _fail(f"第 {i} 层不是对象", warnings)
        label = str(st.get("name") or "").strip() or f"第 {i} 层"
        units = _units_of(st)
        if units is None:
            return _fail(f"第 {i} 层（{label}）的 monsters / elite / boss 必须是数组", warnings)
        if not units:
            return _fail(f"第 {i} 层（{label}）没有任何战斗单位（怪/精英/Boss 全空）："
                         f"视图不假装这里有内容 —— 请补上内容或删掉这一层", warnings)
        if st.get("boss") and i != len(raw):
            return _fail(f"第 {i} 层（{label}）有 Boss 但它不是末层（共 {len(raw)} 层）："
                         f"末层判定是引擎 Progress 的 is_last，Boss 放在中间会让「到没到尽头」说不清",
                         warnings)
        specs.append((i, label, st, units))

    # ── 用引擎同一份 Progress 建节点 + 池（节点 key 是预览内部名，不外露）──
    nodes = [{"key": f"stage{i}", "label": label} for i, label, _st, _u in specs]
    prog = Progress(nodes)
    for i, _label, _st, units in specs:
        prog.push_many(f"stage{i}", _POOL, units)

    rows = []
    for i, label, st, units in specs:
        k = f"stage{i}"
        prog.goto(k)
        rows.append({
            "index": i,
            "label": label,
            "key": k,
            "monsters": len(st.get("monsters") or []),
            "elite": len(st.get("elite") or []),
            "boss": len(st.get("boss") or []),
            "pois": list(st.get("pois") or []),
            "secret": str(st.get("secret") or ""),
            "npc": str(st.get("npc") or ""),
            "units": len(units),
            "left": prog.left(k, _POOL),          # ← 引擎的剩余池
            "cleared": prog.node_cleared(k),      # ← 引擎的「这站清没清」
            "is_last": prog.is_last(),            # ← 引擎的末层判定
        })

    prog.goto(nodes[0]["key"])                    # 回到入口（视图只查询，不改推进语义）
    _add(warnings, _NO_VOCAB)
    _add(warnings, _SCALE_DEFAULT)
    if not entry.get("key_item"):
        _add(warnings, "key_item 为空 = 本副本不要钥匙（准入的钥匙关怎么判属于内容侧规则）。")

    return {
        "ok": True,
        "key": key or "",
        "name": name,
        "lv": entry.get("lv"),
        "icon": str(entry.get("icon") or ""),
        "players": {"min": min_p, "max": max_p},
        "key_item": str(entry.get("key_item") or ""),
        "key_source": str(entry.get("key_source") or ""),
        "entry": dict(entry.get("entry") or {}) if isinstance(entry.get("entry"), dict) else {},
        "boss": str(entry.get("boss") or ""),
        "scaling": {"hp_mult": entry.get("hp_mult"), "atk_mult": entry.get("atk_mult")},
        "stage_count": len(raw),
        "total_units": sum(len(u) for _i, _l, _s, u in specs),
        "stages": rows,
        "order": [r["label"] for r in rows],
        "reward": {"gold": entry.get("gold"), "exp": entry.get("exp"),
                   "materials": list(entry.get("materials") or [])},
        "progress_check": {
            "entry_key": nodes[0]["key"],
            "last_key": nodes[-1]["key"],
            "total_left": prog.total_left(),      # ← 引擎的全局剩余
            "done": prog.done,                    # ← 引擎的「全清」（属性，不是方法）
        },
        "warnings": warnings,
    }


def build_file(data: dict, key: str) -> dict:
    """表形态 `{副本key: 副本对象}` 里取一条算视图（key 不存在 → ok=False + 中文原因）。"""
    if not isinstance(data, dict):
        return _fail("整表不是对象（应当是 {副本key: 副本对象}）")
    entry = data.get(key)
    if entry is None:
        return _fail(f"没有这条副本：{key}")
    return build(entry, key)
