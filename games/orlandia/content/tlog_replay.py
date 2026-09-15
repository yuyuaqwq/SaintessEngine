# -*- coding: utf-8 -*-
"""《奥兰迪亚》战斗流水**回放半边**（P4-D3 搬运物，逐字保真）—— ★ B12B13 线2 起 = 包内唯一真源。

真源（历史）：宿主 `game/services/battle_tlog.py` 旧版 `:245-321`（B10-L2 把采集半边搬走后，
留在宿主的那**另一半**）。本文件 = 该半边的**逐字拷贝**，只动「宿主取件」（见下）。

为什么现在才搬（B10-L2 的阻塞理由已消失）
  · B10-L2 判定：回放半边依赖**宿主重建链**（`game/services/battle_bridge.py` 的
    `prepare_player_for_battle` / `build_sides` / `apply_battle_loadout`）⇒ 留宿主。
  · `battle_bridge` 的唯一实现已归包（`content/bridge.py`，回写半边 `sync_player_from_actor`
    亦已在包内）⇒ 本批（B12B13 线2）把回放半边随包收口。

取件（原真源 `from ..services.battle_bridge import (…)`）
  · ★ **B2-C3（本批）改「包内直取」**：重演用构造半边（`prepare_player_for_battle` /
    `build_sides` / `apply_battle_loadout`）直接取包内唯一真源 `content/bridge.py` ——
    原写法是**调用时**解析宿主**薄壳**同名函数（薄壳本身只是一层委托，两处同源）。
  · 重演端拿到的 event_state 语义一字不变：宿主薄壳把「event_state 视图（DB）」适配后传给
    `content/bridge.py`；本模块走 `build` 覆盖时直接用调用方给的 player/enemies 普通 dict，
    默认分支 `event_state` 为 None（`content/bridge.prepare_player_for_battle` 按无事件状态处理，
    与真源「不传 db = 空 event_state」同款）。
  · 过渡注入槽：`bind_host(bridge=…)` / 旧键 `services.battle_bridge`（宿主壳旧调用）仍认，
    给了就优先用（行为同源）。
  · `_uid` / `_rounds_of` 取自同批采集半边 `content/tlog_collect.py`（同源，零第二份）。
  · 不碰 DB / 时钟 / 单进程锁：本模块零平台知识，DB 只经重建链间接出现。
"""
from __future__ import annotations

import random
from typing import Iterable, Optional

from saintess_engine.tlog import Record

from .tlog_collect import _rounds_of, _uid

# ---------------------------------------------------------------- 取件口（包内直取）
# 真源 `from ..services.battle_bridge import (…)` = 包内 `content/bridge.py` 的构造半边。
# 旧键 `services.battle_bridge`（宿主薄壳注入）保留兼容：薄壳的 3 个同名函数是同一实现的委托。
_INJECTED = {}


def bind_host(**objs):
    """过渡注入槽（幂等）——键 `bridge` 或旧键 `services.battle_bridge`（宿主薄壳 import 期调用）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _bridge():
    """重演用构造半边：注入槽优先 → 包内真源 `content/bridge.py`（B2-C3 包内直取）。"""
    m = _INJECTED.get("bridge") or _INJECTED.get("services.battle_bridge")
    if m is not None:
        return m
    from . import bridge as _BR
    return _BR


# ================================================================ 回放
def find_battle(records: Iterable[Record], tag: Optional[str] = None) -> list:
    """从一段流水里挑出一场战斗的全部记录（按写入顺序）。"""
    out = [r for r in records if str(r.kind).startswith("battle.")]
    if tag is not None:
        out = [r for r in out if r.has_tag(tag)]
    return out


def replay(records: Iterable[Record], *, seed: Optional[int] = None,
           build=None) -> dict:
    """按流水**重演**一场战斗，返回 `{result, rounds, p_acts, expected, matched}`。

    * 重建口径与生产同源：`prepare_player_for_battle` → `build_sides` →
      `apply_battle_loadout` → `Battle(sides=…)`（即 `battle_bridge` 的那一套）。
    * **`seed` 的语义 = 「重演起点」**：它必须在**重建完成之后、第一次行动之前**生效
      （重建本身会消耗随机：装备生成/阈值洗牌等）。所以这里先重建、再 `random.seed`，
      最后重演 —— 记录端也要在同一位置取种子（见 `BattleTLog.attach` 的 docstring）。
    * `build` 可覆盖重建（自定义场景/副本）；默认用记录里的 player/enemies。

    返回的 `matched` = 与记录里 `battle.end` 的 result/rounds/p_acts 是否逐项一致
    —— 这就是「能不能复现同一场」的判据。
    """
    rs = list(records)
    start = next((r for r in rs if r.kind == "battle.start"), None)
    end = next((r for r in rs if r.kind == "battle.end"), None)
    if start is None:
        raise ValueError("流水缺少 battle.start —— 无法重建（记录不完整）")

    from saintess_engine import Battle as B2
    _BR = _bridge()
    apply_battle_loadout = _BR.apply_battle_loadout
    build_sides = _BR.build_sides
    prepare_player_for_battle = _BR.prepare_player_for_battle

    sd = start.fields.get("seed")
    use_seed = seed if seed is not None else sd

    if build is not None:
        btype, sides = build(start.fields)
    else:
        btype = str(start.fields.get("btype") or "monster")
        player = dict(start.fields.get("player") or {})
        enemies = [dict(e) for e in (start.fields.get("enemies") or [])]
        if not player or not enemies:
            raise ValueError("流水缺少重建输入（player/enemies）")
        prepare_player_for_battle(player, player.get("title_bonus"), None)
        sides = build_sides(player, enemies)
        for a in sides.get("player", []):
            apply_battle_loadout(a, player.get("title_bonus"))

    b = B2(btype, sides=sides)
    by_uid = {}
    for side in b.sides.values():
        for a in side:
            by_uid[_uid(a)] = a
    # ★ 重建完成后再设随机流起点（重建会消耗随机）—— 与记录端同一位置取种子
    if use_seed is not None:
        random.seed(int(use_seed))
    for r in rs:
        if r.kind != "battle.act":
            continue
        who = by_uid.get(str(r.fields.get("uid") or "")) or b.focus()
        if who is None:
            continue
        tgt = by_uid.get(str(r.fields.get("target_uid") or ""))
        b.human_act(str(r.fields.get("action") or "attack"),
                    (r.fields.get("skill") or None), who, tgt)

    got = {"result": str(b.result or ""), "rounds": _rounds_of(b),
           "p_acts": int(getattr(b, "_p_acts", 0) or 0)}
    exp = None
    if end is not None:
        exp = {"result": str(end.fields.get("result") or ""),
               "rounds": int(end.fields.get("rounds") or 0),
               "p_acts": int(end.fields.get("p_acts") or 0)}
    return {"result": got["result"], "rounds": got["rounds"], "p_acts": got["p_acts"],
            "expected": exp, "matched": (exp is not None and got == exp),
            "battle": b}
