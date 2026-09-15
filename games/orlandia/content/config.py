# -*- coding: utf-8 -*-
"""包内配置读口（`content/config.py`）—— 「配置常量域」+「修炼塔表」的**唯一读口**。

为什么有这个模块（B9-L7「域补口」线）
------------------------------------
`game/data/` 下 20 个「配置/常量」模块（经济价 / 签到 / 强化阶梯 / 重锻 / 怪异炼成 / 房产 /
采集点 / 副业 / 公式骨架 / 怪物段乘区 / 战斗表 …）过去在包内只有**两种落法**：
  ① 没有落点（`WEEKLY_PICK` / `TRIAL_*` 这类常量在 B8.2 被逐字抄进包内模块，注释里写「待归口」）；
  ② 只有其中一小撮进了域（`enhance_table` / `panel_rules` 各取了 1~3 张表，其余留在宿主）。
本模块给「常量域」立一个读口：**包内任何模块不再自带常量副本，一律从这里取**；
数据本身由宿主导出器 `scripts/export_domains/b9_l7_domains.py` 从真源单向产出
（`game/data/*.py` 仍是真源，包内 JSON 是它的投影 —— 不许手改包内 JSON）。

域（写进 `<包>/editor/domains.json`，本模块按名字读）
----------------------------------------------------
    content/rules/game_config.json   ← `derive_game_config`   21 组常量 / 110 个成员（kind=rules）
    content/data/trial_floors.json   ← `derive_trial_floors`  30 层塔表（键 = str(floor)，int → 字符串）

两个坑（与包内 `content/tables.py` 同一族，都属于「JSON 只有字符串键」）
----------------------------------------------------------------------
  1. **int 键要还原**：塔表键 `"1".."30"` 与 `UPGRADE_TABLE` / `HOUSE_LEVELS` / `HOUSE_REFUND` /
     `ENHANCE_FAIL_DROP` 这类 int 档位键 —— 不还原 = `.get(3)` 恒 `None`（静默归零）。
     本模块 `int_keys()` 是 `tables.py:_int_keys` 的同口径实现（非整数键**原样保留**，不静默丢）。
  2. **顺序要还原**：塔表真源是 `list`（下标 = 层序 - 1），域文件外层键是**字典序** ——
     `trial_floors()` 按 `floor` 排回源顺序；少了这一步，`content/flow/tower_progress.py`
     的「下一层」推导与页面渲染顺序都会漂移。
  3. **tuple 在 JSON 里是 array**：`stat_templates` / `formula_skeleton` / `prof_config` /
     `gather_pools` 的段乘区与池子条目源侧是 tuple —— 落盘后是 list。按序解包/索引不受影响，
     **判等 `== (a, b)` 的地方要自己 `tuple(...)`**（包内暂无人这么用；宿主切换消费端时注意）。

口径
----
`const_group(组名)` / `const(组名, 常量名)` / `trial_floors()` 全部**只读不写**，值一字不改：
不补默认值、不改类型、不展开引用串（那三件事在导出器里）。缺文件 / 坏 JSON / 空表 → `raise`：
「静默空表」在本项目里比报错难查得多（编辑器显示 0 条且不报错）。

用法::

    from content import config as CFG
    CFG.WEEKLY_PICK                 # 3（真源 game/data/weekly_quests.py:152）
    CFG.TRIAL_MIN_LV                # 70（真源 game/data/trial_tower.py:27）
    CFG.const("econ_config", "ECON_CONFIG")["inn_cost_per_lv"]
    CFG.trial_floors()[2]           # 第 3 层条目（按源层序）
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")
_RULES_DIR = os.path.join(_HERE, "rules")

# 域文件落点（由包内 editor/domains.json 的 kind 决定：rules → content/rules/，data → content/data/）
CONFIG_DOMAIN = "game_config"
FLOORS_DOMAIN = "trial_floors"
_CONFIG_PATH = os.path.join(_RULES_DIR, f"{CONFIG_DOMAIN}.json")
_FLOORS_PATH = os.path.join(_DATA_DIR, f"{FLOORS_DOMAIN}.json")

# 真源标注（报错文案里带上，便于「值不对」时一眼定位是哪个宿主文件哪张表）
CONFIG_SRC = "game/data/*.py（20 个配置模块，逐个判定见 overnight/B9-L7-domains.md §2）"
FLOORS_SRC = "game/data/trial_tower.py:112 TRIAL_FLOORS"


def _read_table(path: str, what: str) -> dict:
    """读一个域文件（缺文件 / 坏 JSON / 空表 → `raise`，**不静默空表**）。"""
    if not os.path.exists(path):
        raise RuntimeError(f"{what} 域文件不存在（{path}）—— 空表 = 静默失效，拒绝继续")
    try:
        with open(path, encoding="utf-8") as f:
            tbl = json.load(f)
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(f"{what} 域文件坏 JSON（{path}）：{e} —— 拒绝继续") from e
    if not isinstance(tbl, dict) or not tbl:
        raise RuntimeError(f"{what} 域文件不是非空 dict（{path}）—— 拒绝继续")
    return tbl


_CONFIG: dict = _read_table(_CONFIG_PATH, CONFIG_DOMAIN)
_FLOORS_RAW: dict = _read_table(_FLOORS_PATH, FLOORS_DOMAIN)


def const_group(name: str) -> dict:
    """取一个常量组（键 = 真源模块名，如 `econ_config` / `trial_tower`）→ `{源常量名: 值}`。

    组不存在 / 组不是 dict → `raise`（组的来路见 `scripts/export_domains/b9_l7_domains.py`
    的 `EXPLICIT_GROUPS` / `AUTO_GROUPS`）。
    """
    grp = _CONFIG.get(name)
    if not isinstance(grp, dict) or not grp:
        raise RuntimeError(f"{CONFIG_DOMAIN} 域里没有常量组 {name!r}（现有：{sorted(_CONFIG)}）"
                           f" —— 组名漂了或域文件没导出，拒绝静默取空")
    return grp


def const(group: str, name: str):
    """取单个常量（源常量名原样，如 `const("trial_tower", "TRIAL_MIN_LV")` → 70）。"""
    grp = const_group(group)
    if name not in grp:
        raise RuntimeError(f"{CONFIG_DOMAIN} 域 {group!r} 组里没有常量 {name!r}"
                           f"（现有：{sorted(grp)}）—— 拒绝静默取 None")
    return grp[name]


def int_keys(tbl) -> dict:
    """JSON 字符串键 → int 键（`content/tables.py:_int_keys` **同口径**：非整数键原样保留）。

    用途：`UPGRADE_TABLE` / `HOUSE_LEVELS` / `HOUSE_REFUND` / `ENHANCE_FAIL_DROP` 这类
    `{int 档位: 值}` 的表 —— 不还原 = `.get(3)` 恒 `None`（静默归零）。
    """
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def trial_floors() -> list:
    """修炼塔塔表 —— **按源层序**（`floor` 1..30）的条目 list（键 int 还原 + 顺序还原）。

    与真源 `TRIAL_FLOORS`（list，下标 = 层序 - 1）逐条等价：条目字段一字不改，
    只有「键型 + 顺序」两处是 JSON 往返必须补回来的（见模块 docstring 的坑 1/2）。
    层号断号/重号/非连续 → `raise`（`_floor_def` 是线性查找，断号 = 玩家卡在某层）。
    """
    rows = []
    for key, ent in _FLOORS_RAW.items():
        if not isinstance(ent, dict):
            raise RuntimeError(f"{FLOORS_DOMAIN} 域条目 {key!r} 不是 dict（{type(ent).__name__}）")
        try:
            kf = int(key)
        except (TypeError, ValueError):
            raise RuntimeError(f"{FLOORS_DOMAIN} 域键 {key!r} 不是整数层号") from None
        if ent.get("floor") != kf:
            raise RuntimeError(f"{FLOORS_DOMAIN} 域键 {key!r} 与条目 floor={ent.get('floor')!r}"
                               f" 不一致 —— 拒绝按错层发奖")
        rows.append(ent)
    rows.sort(key=lambda e: e["floor"])
    floors = [e["floor"] for e in rows]
    if floors != list(range(1, len(rows) + 1)):
        raise RuntimeError(f"{FLOORS_DOMAIN} 层号不是 1..{len(rows)} 连续整数（{floors}）—— 拒绝继续")
    return rows


# ============================================================
# 便捷常量（源常量名原样；值 = 真源同值，读自上面的域）
# ============================================================
# 周常（真源 game/data/weekly_quests.py:152 WEEKLY_PICK / :155 WEEKLY_MIN_LV）
WEEKLY_PICK: int = const("weekly_quests", "WEEKLY_PICK")
WEEKLY_MIN_LV: int = const("weekly_quests", "WEEKLY_MIN_LV")

# 修炼塔门槛与上限（真源 game/data/trial_tower.py:24/27/30）
TRIAL_DAILY_LIMIT: int = const("trial_tower", "TRIAL_DAILY_LIMIT")
TRIAL_MIN_LV: int = const("trial_tower", "TRIAL_MIN_LV")
TRIAL_MAX_FLOOR: int = const("trial_tower", "TRIAL_MAX_FLOOR")

for _n, _v in (("WEEKLY_PICK", WEEKLY_PICK), ("WEEKLY_MIN_LV", WEEKLY_MIN_LV),
               ("TRIAL_DAILY_LIMIT", TRIAL_DAILY_LIMIT), ("TRIAL_MIN_LV", TRIAL_MIN_LV),
               ("TRIAL_MAX_FLOOR", TRIAL_MAX_FLOOR)):
    if isinstance(_v, bool) or not isinstance(_v, int):
        raise RuntimeError(f"{_n} 不是 int（{_v!r}，{type(_v).__name__}）—— 域值形状变了，拒绝继续")

# 塔表条数必须与域里的上限自洽（少了 = 顶层打不到；多了 = 上限把新层藏了）
if TRIAL_MAX_FLOOR != len(_FLOORS_RAW):
    raise RuntimeError(f"TRIAL_MAX_FLOOR={TRIAL_MAX_FLOOR} 与 {FLOORS_DOMAIN} 域条数"
                       f" {len(_FLOORS_RAW)} 不一致 —— 出真源（game/data/trial_tower.py）对完再导")

__all__ = [
    "CONFIG_DOMAIN", "FLOORS_DOMAIN", "CONFIG_SRC", "FLOORS_SRC",
    "const_group", "const", "int_keys", "trial_floors",
    "WEEKLY_PICK", "WEEKLY_MIN_LV",
    "TRIAL_DAILY_LIMIT", "TRIAL_MIN_LV", "TRIAL_MAX_FLOOR",
]
