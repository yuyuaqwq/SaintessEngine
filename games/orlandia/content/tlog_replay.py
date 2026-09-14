# -*- coding: utf-8 -*-
"""《奥兰迪亚》战斗流水**回放半边**（P4-D3 搬运物，逐字保真）—— ★ B12B13 线2 起 = 包内唯一真源。

真源（历史）：宿主 `game/services/battle_tlog.py` 旧版 `:245-321`（B10-L2 把采集半边搬走后，
留在宿主的那**另一半**）。本文件 = 该半边的**逐字拷贝**，只动「宿主取件」（见下）。

为什么现在才搬（B10-L2 的阻塞理由已消失）
  · B10-L2 判定：回放半边依赖**宿主重建链**（`game/services/battle_bridge.py` 的
    `prepare_player_for_battle` / `build_sides` / `apply_battle_loadout`）⇒ 留宿主。
  · `battle_bridge` 的唯一实现已归包（`content/bridge.py`，回写半边 `sync_player_from_actor`
    亦已在包内）⇒ 本批（B12B13 线2）把回放半边随包收口。

取件（原真源 `from ..services.battle_bridge import (…)` 的同义替身）
  · `_host_attr("services.battle_bridge", "<名>")` —— **调用时**解析宿主**薄壳**同名函数，
    与真源逐字同义（宿主薄壳内部把「event_state 视图（DB）」注入给包内 `content/bridge.py`）
    ⇒ 重演端拿到的 event_state 仍是**宿主 DB 视图**：`echo_bless` / `poi_buff` 的读 + 回写
    （消耗一次）语义一字不变。**这是本半边唯一的宿主面**，故按 I2 走注入口、不 import 宿主顶层。
  · `_uid` / `_rounds_of` 取自同批采集半边 `content/tlog_collect.py`（同源，零第二份）。
  · 不碰 DB / 时钟 / 单进程锁：本模块零平台知识，DB 只经重建链句柄间接出现。
"""
from __future__ import annotations

import importlib
import random
import sys
from typing import Iterable, Optional

from saintess_engine.tlog import Record

from .tlog_collect import _rounds_of, _uid

# ---------------------------------------------------------------- 宿主取件口
# 真源 `from ..services.battle_bridge import (…)` 的替身：调用时按模块路径解析宿主**薄壳**。
# 键 = 宿主真源相对模块路径（`services.battle_bridge`），与包内其它模块的 `_host_attr` 同款。
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（AstrBot 插件加载路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = 真源相对模块路径（`services.battle_bridge`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`services.battle_bridge` 这类相对路径）。"""
    m = _INJECTED.get(name)
    if m is not None:
        return m
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("tlog_replay：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「`from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    return getattr(_host_module(mod), attr)


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
    apply_battle_loadout = _host_attr("services.battle_bridge", "apply_battle_loadout")
    build_sides = _host_attr("services.battle_bridge", "build_sides")
    prepare_player_for_battle = _host_attr("services.battle_bridge",
                                           "prepare_player_for_battle")

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
