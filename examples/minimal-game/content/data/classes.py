# -*- coding: utf-8 -*-
"""《铆炉回声》——职业与玩家面板。

引擎只认一个东西：actor["class_name"] 有值 → 走 config 注入的 panel_fn 重算面板。
所以「职业」在本平台 = 一组面板参数 + 一张技能表，不需要引擎知道「职业」这个词。
"""
from __future__ import annotations

# 面板参数：base 是 1 级值，*_per_lv 是每级成长
CLASSES = {
    "cls_kiln": {
        "name": "铆炉匠",
        "hp": 90, "hp_per_lv": 9,
        "atk": 12, "atk_per_lv": 3.0,
        "matk": 3, "matk_per_lv": 0.4,
        "def": 7, "def_per_lv": 0.8,
        "mdef": 4, "mdef_per_lv": 0.5,
        "spd": 54, "crit": 0.12,
    },
    "cls_whistle": {
        "name": "哨鸣师",
        "hp": 78, "hp_per_lv": 7,
        "atk": 6, "atk_per_lv": 0.4,
        "matk": 14, "matk_per_lv": 3.2,
        "def": 5, "def_per_lv": 0.6,
        "mdef": 8, "mdef_per_lv": 0.6,
        "spd": 60, "crit": 0.20,
    },
}

# 自动战斗策略（data 标签，引擎 ai.py 读）：本示例不做 AI —— 交给 auto_run 用普攻，
# 主动技能（过载铆钉）在 tests/test_smoke.py 里用 human_act 显式驱动。
# ⚠️ 这里刻意留一个注释而不是留空表：引擎的 AI 谓词集（self_hp_lt / self_hp_gt /
#    hostile_lowest_hp_lt / round_mod / cd_ok）**没有「资源 ≥ N」谓词**，
#    想「资源够才放技能」只能靠内容侧自己写触发器或扩大谓词集（见 README 的坑 ④）。


def class_panel(class_name, level=1, equipment=None, tier=0, attributes=None,
                evolve_path=0, title_bonus=None, race=None):
    """引擎 panel_fn 的实现（签名固定；本游戏只用到 class_name / level / title_bonus）。

    未知名/空职业 → {}（引擎「零默认值」语义：空面板）。
    """
    base = CLASSES.get(class_name or "")
    if not base:
        return {}
    lv = max(1, int(level or 1))

    def _grow(k):
        return int(base.get(k, 0) + base.get(k + "_per_lv", 0) * lv)

    panel = {
        "max_hp": _grow("hp"),
        "atk": _grow("atk"),
        "matk": _grow("matk"),
        "def": _grow("def"),
        "mdef": _grow("mdef"),
        "spd": int(base.get("spd", 0)),
        "crit": float(base.get("crit", 0.0)),
    }
    # title_bonus：引擎整场透传的外部面板增幅 dict（本游戏只做 flat 加值）
    for k, v in (title_bonus or {}).items():
        if k in panel and isinstance(v, (int, float)):
            panel[k] = float(panel[k]) + float(v)
    return panel


def build_player(class_name, uid, name, level=1, side="player"):
    """造一个玩家 actor（面板由 class_panel 决定；技能 key 来自技能表）。"""
    from saintess_engine import make_actor
    from . import skills as S

    panel = class_panel(class_name, level)
    if not panel:
        raise KeyError(f"未知职业：{class_name!r}")
    # 「def」是 Python 关键字，只能经 ** 展开传给 make_actor（它收 **stats）
    stats = {"hp": panel["max_hp"], "max_hp": panel["max_hp"],
             "spd": panel["spd"], "crit": panel["crit"]}
    for stat in ("atk", "matk", "def", "mdef"):
        stats[stat] = panel[stat]
    return make_actor(
        uid, name, side, kind="player", human_controlled=True,
        class_name=class_name, level=level,
        skills=list((S.PLAYER_SKILLS.get(class_name) or {}).keys()),
        **stats,
    )
