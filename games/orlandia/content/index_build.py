# -*- coding: utf-8 -*-
"""包内名字索引构建（`content/index_build.py`）—— 宿主 `game/data/_assembly.py` 索引段**逐字端口**。

真源：`C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/data/_assembly.py`
      （索引构建段 `:179-278` + 它依赖的两处前置派生：扁平技能表 `:165-177`、
        装配时机产物 `:93-163`（网状房间/副本层已并入 SUBAREAS/INSTANCES，由域承载））
本文件 = **逐字端口**：「表来源」从宿主聚合层（`game.data` / `C`）改成**包内门面 / 读口**；
逻辑、顺序、默认值、冲突覆盖规则、注释口径**一字不改**。

调用方 = 包内 `content/index.py: _indexes()`（惰性、恰好一次；宿主 `game.data._assembly`
的 `build_index(...)` 调用也落在同一只包内字典上 —— 见该文件头注）。

表来源（逐表；括号 = 包内域）
----------------------------
    materials / items / sets / runes  ← `content/catalog_items.py`   (items / sets / runes)
    skills（含 `_SKILL_FLAT`）        ← `content/catalog_core.py` 的 `PLAYER_SKILLS` / `TUTOR_SKILLS`
    recipes                           ← `content/catalog_life.py` 的 `CRAFT_RECIPES`   (craft)
    alchemy / cooking                 ← `content/catalog_life.py`   (alchemy / cooking)
    classes / races                   ← `content/catalog_core.py`   (classes / races)
    monster_skills                    ← `content/catalog_quests.py` (monsters)
    quality                           ← `content/catalog_b143.py` 的 `QUALITY` + 缺口表 `QUALITY_CN` (equipment)
    weapon_types                      ← 缺口表 `WEAPON_TYPES` / `WT_CN`（`QUALITY` 同域的 equipment 域）
    monsters                          ← `content/catalog_space.py` 的 `SUBAREAS` / `INSTANCES` (subareas / instances)
    fish                              ← `content/catalog_life.py` 的 `FISH_POOL`   (fishing_pool)
    npcs                              ← `content/catalog_quests.py` 的 `NPCS` / `HIDDEN_NPCS` (npcs)
    shop_weapons                      ← `content/catalog_life.py` 的 `SHOP_WEAPONS` (shop)

★ 缺口：3 张**无域表**（宿主 `game/data/equipment.py:49/325/330`）
-----------------------------------------------------------------
`QUALITY_CN` · `WT_CN` · `WEAPON_TYPES` —— 包内 66 个域**没有**它们（实测全库 JSON 零命中），
`content/catalog_b143.py` 等门面也没有；导出器 `scripts/export_domains/b14_3_gaps.py:26-29`
明写这 12 个 equipment 常量「本轮不进域（缺口以读点为准）」—— 而**索引构建就是一个读点**
（本文件是它的唯一消费者）。解析顺序见 `_gap_tables()`：

  ① 包内门面（将来 `catalog_b143`/`catalog_items` 一暴露就自动生效，零改动）
  ② `equipment` 域键（导出器给 `derive_equipment` 加 3 行、重导一次即自动生效）
  ③ 宿主 `data` 句柄兜底（宿主薄壳注入；**删 `game/data` 后这 3 张表随之消失** → 见报告缺口）

⇒ 现状（③ 生效）：两表 `quality` / `weapon_types` 的取值与宿主逐字节相同，宿主在跑时**零回归**；
但它们是**删宿主 `game/data` 的前置阻塞**：不先把这 3 个常量导出进 `equipment` 域，
删表后 `C.display("weapon_types", …)`（包内 `economy_cmds` 有 5 处消费）会退回裸 id。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content

# 缺口表名（宿主 equipment.py 有、包内 66 域无）
GAP_TABLES = ("WEAPON_TYPES", "WT_CN", "QUALITY_CN")
# 探针/报告用：每张缺口表的**实际来源**（facade:… / domain:equipment / host:game.data / missing）
GAP_SOURCES: dict = {}


def _read_json(sub: str, name: str):
    """读包内 `content/<sub>/<name>.json`（缺文件 / 坏 JSON → `{}`，不抛 —— 与 `content/tables.py:48` 同款）。

    ⚠️ 2026-09-14 收口修：原实现拼路径漏了 `.json` 后缀 ⇒ 二级解析（`equipment` 域）恒读空、
    三级宿主兜底一直在替它兜着（`GAP_SOURCES` 表现为 `host:game.data`）—— 本函数是补域键后
    「包内单跑 17/17」生效的唯一开关，故必须带后缀。
    """
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                        # noqa: BLE001
        return {}


def _gap_tables(_host_getter=None, _B143=None, _CI=None, _CC=None) -> dict:
    """取 3 张无域表（`GAP_TABLES`）—— 三级解析，逐级记 `GAP_SOURCES`（见文件头注）。

    `_host_getter` = 取宿主 `data` 模块的回调（`content/index.py:_host_data`）；取不到 → `None`。
    任一级取到就返回（**不合并、不补默认值**：这三张表必须整份来自同一处，混源必漂）。
    """
    out: dict = {}
    for name in GAP_TABLES:
        val = None
        for mod in (_B143, _CI, _CC):                        # ① 门面
            if mod is not None and getattr(mod, name, None):
                val, src = getattr(mod, name), "facade:%s" % mod.__name__
                break
        if val is None:                                      # ② equipment 域
            dom = _read_json("data", "equipment")
            grp = dom.get("equipment") if isinstance(dom, dict) else None
            ent = (grp or {}).get(name) if isinstance(grp, dict) else None
            if ent:
                val, src = ent, "domain:equipment"
        if val is None and _host_getter is not None:         # ③ 宿主句柄兜底
            try:
                ent = getattr(_host_getter(), name)
                if ent:
                    val, src = ent, "host:game.data"
            except Exception:                                # noqa: BLE001
                pass
        if val is None:
            val, src = {}, "missing"
        GAP_SOURCES[name] = src
        out[name] = val
    return out


def build_into(_indexes: dict, _host_getter=None) -> dict:
    """构建全部名字索引，写进 `_indexes`（= 包内 `content/index.py::_INDEXES`）。

    ⚠️ 调用方保证「恰好一次」（`content/index.py:_indexes()` 的 `_BUILT` 标志先置位再调本函数，
    本函数内部对 `build_index` 的重入因此不会循环）。
    """
    # ---- 表来源：包内门面 / 读口（宿主聚合层 `C` 的读点全换这里）----
    from . import catalog_core as _CC
    from . import catalog_items as _CI
    from . import catalog_life as _CL
    from . import catalog_quests as _CQ
    from . import catalog_space as _CS
    from . import catalog_b143 as _B143
    from .index import build_index, pinyin_id

    CLASSES = _CC.CLASSES
    RACES = _CC.RACES
    PLAYER_SKILLS = _CC.PLAYER_SKILLS
    TUTOR_SKILLS = _CC.TUTOR_SKILLS
    MATERIALS = _CI.MATERIALS
    ITEMS = _CI.ITEMS
    SETS = _CI.SETS
    RUNES = _CI.RUNES
    CRAFT_RECIPES = _CL.CRAFT_RECIPES
    ALCHEMY_RECIPES = _CL.ALCHEMY_RECIPES
    COOKING_RECIPES = _CL.COOKING_RECIPES
    FISH_POOL = _CL.FISH_POOL
    SHOP_WEAPONS = _CL.SHOP_WEAPONS
    MONSTER_SKILLS = _CQ.MONSTER_SKILLS
    NPCS = _CQ.NPCS
    HIDDEN_NPCS = _CQ.HIDDEN_NPCS
    SUBAREAS = _CS.SUBAREAS
    INSTANCES = _CS.INSTANCES
    QUALITY = _B143.QUALITY
    _gap = _gap_tables(_host_getter, _B143, _CI, _CC)
    WEAPON_TYPES = _gap["WEAPON_TYPES"]
    WT_CN = _gap["WT_CN"]
    QUALITY_CN = _gap["QUALITY_CN"]

    _INDEXES = _indexes

    # ---- 2. 扁平派生表（兼容 v48 前旧结构 {职业:{技能}} 与 v48 新结构 {cls_id:{skills}}）----
    _SKILL_FLAT = {}
    for _cid, _cinfo in PLAYER_SKILLS.items():
        if isinstance(_cinfo, dict) and "skills" in _cinfo:
            _SKILL_FLAT.update(_cinfo["skills"])
        else:
            _SKILL_FLAT.update(_cinfo)
    # v101.20 职业导师专属技能（TUTOR_SKILLS）并入扁平表 → 名字↔ID 索引可解析，
    # skill_info 查询链（基础→分支→导师）最后一环才生效；重名职业技能已在 TUTOR 表剔除
    for _cid, _cinfo in (TUTOR_SKILLS or {}).items():
        if isinstance(_cinfo, dict):
            _SKILL_FLAT.update(_cinfo)

    # ---- 3. ID 索引（v48：key 已是 ID，一律传 name_field="name"）----
    build_index("materials", MATERIALS, prefix="mat_", name_field="name")
    build_index("skills", _SKILL_FLAT, prefix="sk_", name_field="name")
    build_index("recipes", CRAFT_RECIPES, prefix="rec_", name_field="name")
    build_index("sets", SETS, prefix="set_", name_field="name")
    build_index("items", ITEMS, prefix="it_", name_field="name")  # v48：修复旧版畸形 ID（it_i___t...）
    build_index("classes", CLASSES, prefix="cls_", name_field="name")
    build_index("runes", RUNES, prefix="rn_", name_field="name")
    build_index("monster_skills", MONSTER_SKILLS, prefix="ms_", name_field="name")
    build_index("alchemy", ALCHEMY_RECIPES, prefix="al_", name_field="name")
    build_index("cooking", COOKING_RECIPES, prefix="cook_", name_field="name")
    build_index("races", RACES, name_field="name")  # 阶段九：种族（08 章，key 即 ID，无前缀）

    # 品质：颜色档位（白/绿/蓝/紫/橙）→ ID（white/...）；稀有度文字（普通/稀有）单独查 QUALITY[name]
    if any(k in QUALITY_CN for k in QUALITY):  # v48：key 已是英文 ID
        _INDEXES["quality"] = {
            "name_to_id": {QUALITY_CN[k]: k for k in QUALITY},
            "id_to_name": dict(QUALITY_CN),
        }
    else:  # v48 前：key 是中文档位
        _INDEXES["quality"] = {
            "name_to_id": {v: k for k, v in QUALITY_CN.items()},
            "id_to_name": dict(QUALITY_CN),
        }
    # 武器类型：key 已是英文 ID（先 build_index 建骨架，WT_CN 再覆盖中文展示映射）
    build_index("weapon_types", WEAPON_TYPES)
    _INDEXES["weapon_types"]["id_to_name"] = dict(WT_CN)
    _INDEXES["weapon_types"]["name_to_id"] = {v: k for k, v in WT_CN.items()}

    # 怪物：v87.6 内容下沉子区域——从 SUBAREAS 的 monsters/elite/boss 收集 怪物名→id（地图级仅兜底）
    # v104 M24：INSTANCES stages 副本专属怪（试炼侍从/寒冰守卫/月骑士等 28 个）一并进索引，
    #           且同名冲突时实例怪优先（后写覆盖，参照 build_index 的 n2i 覆盖规则）
    _MONSTER_INDEX = {}
    _MONSTER_ID_NAMES = {}  # v104 M24：全量 id→名（含同名冲突落败方），旧 bestiary 已存 id 仍可 display

    def _collect_monster_entries(_slots_source, _slots):
        """收集 (mid, mname) 对；兼容三种槽位形态：
        - 条目列表（monsters 多怪）：[[mid, 名, role, lv, skills, drops], ...]
        - 扁平单条目（elite/boss 6 元组）：[mid, 名, role, lv, skills, drops]
        - str 单怪（理论兼容，直接跳过）
        v104 M24：原实现把扁平单条目当条目列表逐元素迭代，
        导致 elite/boss 的技能列表被误判为怪物条目（索引垃圾键 ms_* 的根源）。
        """
        for _slot in _slots:
            _ent = _slots_source.get(_slot)
            if not _ent:
                continue
            if isinstance(_ent, (tuple, list)) and _ent and isinstance(_ent[0], (tuple, list)):
                _lst = _ent  # 条目列表
            else:
                _lst = [_ent]  # 扁平单条目（或 str）
            for _t in _lst:
                if isinstance(_t, (tuple, list)) and len(_t) >= 2:
                    yield _t[0], _t[1]

    for _sas in SUBAREAS.values():
        for _sa in _sas:
            for _mid, _mname in _collect_monster_entries(_sa, ("monsters", "elite", "boss")):
                # 同名怪物（多地图）→ 取第一个 id，保证反查稳定
                if _mname not in _MONSTER_INDEX:
                    _MONSTER_INDEX[_mname] = _mid
                _MONSTER_ID_NAMES.setdefault(_mid, _mname)
    # v104 M24：实例层副本专属怪进索引——同名冲突时实例怪优先（无条件覆盖，
    # 与 build_index 的 name_to_id 后写覆盖规则一致；实例内部 elite/boss 槽位排在 monsters 之后，
    # 同名时实例专属的 elite/boss 变体自然胜出，不再串到子区域同名怪）
    for _ins in INSTANCES.values():
        for _st in (_ins.get("stages") or []):
            if not isinstance(_st, dict):
                continue
            for _mid, _mname in _collect_monster_entries(_st, ("monsters", "elite", "boss")):
                _MONSTER_INDEX[_mname] = _mid
                _MONSTER_ID_NAMES.setdefault(_mid, _mname)
    _INDEXES["monsters"] = {"name_to_id": dict(_MONSTER_INDEX),
                            "id_to_name": dict(_MONSTER_ID_NAMES)}

    # 鱼：FISH_POOL 是 list，手工建索引
    _FISH_INDEX = {}
    for _i, _f in enumerate(FISH_POOL):
        _fid = f"fish_{pinyin_id(_f['name'])}"
        _FISH_INDEX[_f["name"]] = _fid
    _INDEXES["fish"] = {"name_to_id": _FISH_INDEX,
                        "id_to_name": {v: k for k, v in _FISH_INDEX.items()}}

    # NPC：key 已是 npc_xxx id，补 name 映射（含隐藏/层内 NPC）
    _NPC_INDEX = {}
    for _nk, _nv in list(NPCS.items()) + list(HIDDEN_NPCS.items()):
        _nn = _nv.get("name", _nk) if isinstance(_nv, dict) else _nk
        _NPC_INDEX[_nn] = _nk
    _INDEXES["npcs"] = {"name_to_id": _NPC_INDEX,
                        "id_to_name": {v: k for k, v in _NPC_INDEX.items()}}

    # 商店武器：SHOP_WEAPONS 值是 (名字, 类型, lv, 品质) 元组，补索引
    _SHOP_W_INDEX = {}
    for _mk, _mlist in SHOP_WEAPONS.items():
        for _t in _mlist:
            if isinstance(_t, (tuple, list)) and _t:
                _wn = _t[0]
                _SHOP_W_INDEX.setdefault(_wn, f"sw_{pinyin_id(_wn)}")
    _INDEXES["shop_weapons"] = {"name_to_id": _SHOP_W_INDEX,
                                "id_to_name": {v: k for k, v in _SHOP_W_INDEX.items()}}
    return _indexes


__all__ = ["build_into", "GAP_TABLES", "GAP_SOURCES"]
