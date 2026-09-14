# -*- coding: utf-8 -*-
"""v181.P4 N5b4-5a 副本战斗控制器（saintess_engine 原生重写版）。

鱼鱼 2026-09-08 拍板：副本战斗不用旧引擎、不在老 instance.py 上打洞——
本控制器以 saintess_engine state 为战斗权威：

- `st["battle"]` = B2(...).to_state()（sides 全员 actors + now + killed；无镜像）
- `build_battle(st)`：遭遇/切怪/Boss 战组 sides → 构造 → 落 st["battle"]
- `act(...)`：from_state → human_act（副本轮流由玩法壳驱动，此处对指定 actor 出手）
  → to_state 落回；heal/buff 技能 target=None 防奶敌（同 PVP 语义）
- `sync_views(st, group_id)`：唯一视图/DB 同步点——actors → st["players"]/
  st["boss"]/st["enemies"] 玩法壳旧键 + 玩家 DB 血量（战斗内 DB 保持开本值、
  每刻同步，保留现行为）
- 轮转/超时/通关/肃清账务 = 玩法壳（instance.py）薄壳调用本控制器读 actors 结果

5a 边界（随批次补）：target_picker/on_event 预留 None（5b 仇恨/团队广播）；
宠物 Battle pet 只存不驱动（宠物批）；玩家词条种子护盾由玩法壳保留调用
（装配启用待鱼鱼拍板）；副本旧毒（debuffs.poison δ层）未迁 state dot（内容批）。

引擎零改动依赖：saintess_engine + bridge + schedule；本文件不 import 旧 game.battle。

★ B8.2 线4 端口（2026-09-13，包内 `content/flow/instance_battle.py`）
----------------------------------------------------------------
真源（只读，未改一行）：`qqbot/data/plugins/dragonfall/game/commands/instance_battle.py`（428 行）。
本文件 = 真源正文**搬入**，只改「import 层」与「宿主耦合 → 调用方传参」两类东西
（控制流/数值/顺序/日志内容一字未动）。

① import 层改动
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from ..core import instance_run as IR`（:26） | `from . import instance_run as IR` | 副本运行态已进包（D3；`roster_of`/`alive_of`/`set_alive` 函数体与真源逐字相同） |
| `from ..core import texts as T`（:27） | **不搬**（文案由调用方渲染，见 ② ） | 文案表是宿主资产（`game/data/text_specs.json`） |
| `from ..services import battle_bridge as BR`（:28） | `from .. import bridge as BR` | 开战构造半边已进包（D3；`player_to_actor`/`monster_to_actor` 与真源逐字相同） |
| `from ..data.kinds import K_HEAL, K_BUFF`（:29） | `from ..mech.kinds import K_HEAL, K_BUFF` | kind 常量已进包（P4） |
| `from ..content_rules.skills import skill_info`（:308） | `from .. import skills as _SK` | 技能链已进包（D3） |
| `from ..content_rules.skills import skill_level_of`（:169） | 同左（包内 skills） | 团队广播治疗量口径不变 |
| `from ..services.battle_bridge import sync_player_from_actor`（:388） | 调用方传 `sync_player_fn` | 回写半边**未进包** = 缺口（真源 :375-420） |
| `from .. import db as _db`（:408） | 调用方传 `db_update_fn`；**★ B2-C3 起缺省自解析**（见 ② R1） | 玩家 DB 血量同步 |
| `from .battle_item_use import make_override`（:201） | `from ..mech.item_use import make_override` | 道具翻译器已进包（B8.2 线4 端口） |
| `from .boss_script import …`（:206-224） | 调用方传 `script_api` | 缺省 = 包内 `content/flow/boss_script.py`（D3 端口） |
| 宿主聚合层 `MONSTER_MODS`（:134，嘲讽/仇恨 target_policy） | `_monster_mods()` | 包内域 `content/data/monster_mods.json`（140 条，与真源逐项相等） |

② 宿主耦合替身接口（调用方传什么 / 缺省行为）
| 真源宿主耦合 | 包内替身 | 调用方传什么 | 缺省（不传） |
|---|---|---|---|
| `T.text("instance.日志_团队治疗", name=…, amount=…)`（:183） | `team_heal_text(name, amount) -> str` | 宿主 `T.text` 渲染器（文案键在宿主） | ★ **B2-C3**：缺省 = 包内 `team_heal_text`（宿主壳传的就是它；不再是「该行不追加」） |
| `T.static("instance.结算_战斗异常")`（:311）/ `T.static("instance.面板_战斗_不在")`（:330） | `act(...)` 返回第 4 位 **abort 码**（`"no_sides"` / `"no_actor"` / `""`） | 调用方按码拼文案（对齐 `instance_gate` 的 `v.reason` 渲染口径） | —— |
**B11-L2（2026-09-14）收口**：`sync_player_fn` 缺省已闭合 —— 不传 = 包内
`content.bridge.sync_player_from_actor`（B9-L8 把回写半边搬进包内同一模块；
宿主薄壳传的 `services.battle_bridge.sync_player_from_actor` 就是它的一层委托，两边同源）。

| `sync_player_from_actor(snap, actor)` | `sync_player_fn(snap, actor)` | 宿主 `services.battle_bridge.sync_player_from_actor` | 缺省 = 包内 `content.bridge.sync_player_from_actor`（**B11-L2 闭合**，不再是缺口） |
| `db.update_player(group_id, key, hp=…, mp=…, max_hp=…, max_mp=…)` | `db_update_fn(group_id, key, hp, mp, max_hp, max_mp)` | 宿主 `db.update_player` 包装 | ★ **B2-C3（R1）**：`None` → **自解析**（注入槽 `bind_host(db_update=…)` → 包内 `content.persistence`，见下「R1 收口」）——**不再**是「不写库」 |
| `.boss_script` 三函数（`boss_script_cfg` / `make_script_event` / `make_script_hook`） | `script_api=模块或对象` | 宿主 `.boss_script` 模块（等价物 = 包内同名模块） | ★ **B2-C3**：缺省 = 包内端口 `_ScriptApiPort`（`game/commands/_boss_script_port.py` 的包内等价物：耦合三样换包内源） |
| `st` 存档（宿主持久化） | 同左 | 普通 dict（键名/类型/缺失语义一律不变） | —— |

★ **R1 收口（B2-C3，2026-09-14）**：`db_update_fn` 缺省原为 `None` = **不写库**（B2_W0_INTERFACE.md §4 R1）。
把读点 `content/cmds_instance_router.py` 的 `IB` 直接改指本模块、而不同时接上句柄 ⇒
「战斗中 DB 血量每刻同步」这条现行为会**静默丢失**。本批按接口表冻结的约定**先接句柄、再改读点**：

| 取用 | 注入槽（`bind_host`） | 缺省解析（包内直取） |
|---|---|---|
| `db_update` | `bind_host(db_update=<callable>)` 或 `bind_host(db=<宿主 db 模块>)`（wave 2 宿主壳注入） | 包内 `content/persistence`（`content/_pkgref.py` 的 `DB`，B1 落地的包内存储层）→ `update_player(group_id, key, hp=…, mp=…, max_hp=…, max_mp=…)` |

解析**不进 try**（句柄取不到 = 装配缺陷 → 抛）；**写库调用**在 try 内（真源口径：DB 写失败不阻断战斗）。

③ 不变式：④ 文案面 —— **B18 L3c（2026-09-14）起调用点已进包**：副本战斗日志域的 3 条 key
（`instance.日志_团队治疗` / `instance.结算_战斗异常` / `instance.面板_战斗_不在`）仍在宿主
`game/data/text_specs.json` 里声明（唯一真源不变），但 `T.text/T.static` 的**调用点**从宿主
`game/commands/instance_battle.py` 迁到本模块（`team_heal_text` / `abort_text`），宿主该文件的
文案调用点计数归 0；渲染走包内 `content/texts.py`（读宿主薄壳注入的同一份 SPEC_PATH），
故整句逐字不变。`tests/test_texts_table.py` 的「声明 ↔ 调用点」双向对账已相应把本模块
加进 `WIRED["副本战斗日志"]`（跨线共享改动点，全文见 `overnight/W-B18-L3c.md`）。
对拍证据：`overnight/_l4_snapshot.py`（改包前后逐字节等价）+ `_l4_dep_audit.py`（依赖同源）。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from . import instance_run as IR
from .. import bridge as BR
from .. import texts as T                                      # B18 L3c：渲染点唯一 = 包内 content/texts.py
from ..mech.kinds import K_HEAL, K_BUFF

_HERE = os.path.dirname(os.path.abspath(__file__))            # <pkg>/content/flow
_DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")      # <pkg>/content/data

# ============================================================
# ★ B2-C3（R1）：`db_update_fn` 自解析口 —— 与宿主壳 `game/commands/instance_battle.py:55-58`
# 的 `_db_update` 逐字同源（`db.update_player(group_id, key, hp=…, mp=…, max_hp=…, max_mp=…)`）。
# 冻结理由与顺序见文件头 ② R1；写法照 `content/reward.py` / `content/travel.py` 的替身口
# （注入优先 → 包内直取；取不到抛，拒绝静默空跑）。
# ============================================================
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等）——键 `db_update`（callable）或 `db`（宿主 db 模块）；`None` 忽略。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _default_db_update():
    """缺省写库口 = 包内 `content.persistence`（B1 落地的包内存储层；与宿主 `game.db` 同库同实现）。"""
    from .._pkgref import DB as _db

    def _update(group_id, key, hp, mp, max_hp, max_mp):
        _db.update_player(group_id, key, hp=hp, mp=mp, max_hp=max_hp, max_mp=max_mp)

    return _update


def _resolve_db_update():
    """取写库口：注入槽 `db_update` → 注入槽 `db`（模块）→ 包内直取。"""
    fn = _INJECTED.get("db_update")
    if fn is not None:
        return fn
    mod = _INJECTED.get("db")
    if mod is not None:
        return mod.update_player
    return _default_db_update()


# ============================================================
# ★ B2-C3：`script_api` 缺省自解析口
# ------------------------------------------------------------
# 真源宿主壳 `game/commands/instance_battle.py::_script_api()` =
# `game/commands/_boss_script_port.py:script_api()`：把三处宿主耦合绑进包内 `content/flow/boss_script.py`
#   ① `data`            = 宿主 `game.content` 的 `MONSTER_MODS` / `INSTANCES`
#                         ⇒ 包内等价物 = `content/catalog_quests.MONSTER_MODS` / `content/catalog_space.INSTANCES`
#                         （宿主 `game.content` 就是这两个包内门面的聚合，**同一对象**）
#   ② `phase_templates` = 包内 `content/tables.merge_phase_config`（宿主端口用的也是它）
#   ③ `build_monster`   = `content/drops.py`（已进包）⇒ 注入槽 → 包内 `content.drops`
#                         → 包内门面 `content/facade.py::C`；都取不到 = None
#                         （与宿主端口 `getattr(C, "build_monster", None)` 逐字同宽容度）
# 缺省从「裸 `boss_script` 模块」升级为本端口 = 与宿主壳注入的 `script_api` **同形同源**，
# 否则读点改包内直取后 Boss 剧本会退化（阶段模板不合并 / 援军变木桩）。
# ★ B2-INTFIX（2026-09-14）：宿主聚合层句柄**只有一个家** = 包内唯一规范落点
#   `content/persistence/handles.py::_host_content()`（注入 → `sys.modules` → importlib → 抛）。
#   本文件原来的私有 `_host_content()`（第三份同义实现）已删 —— 它是 C2↔C4 接口错位的成因之一。
# ★ W2b（2026-09-15）：**该兜底改指包内门面** `content/facade.py::C` ——
#   本文件不再有 `_host_content()` 消费者（`handles._host_content` 的 4 个消费者全部改口）。
# ============================================================


def _resolve_build_monster():
    """Boss 援军构造器：注入槽 → 包内 `content.drops` → **包内聚合门面** `facade.C` → None。

    ★ W2b（2026-09-15）：最后一级兜底从 `persistence.handles._host_content()`（宿主聚合层）
    换成包内门面 `content/facade.py::C`（`C.build_monster` = `content.drops.build_monster`，
    探针实测同一只对象），包侧不再回宿主取件。
    """
    fn = _INJECTED.get("build_monster")
    if fn is not None:
        return fn
    try:
        from .. import drops as _drops
    except Exception:                                             # noqa: BLE001  未落地
        _drops = None
    if _drops is not None:
        fn = getattr(_drops, "build_monster", None)
        if fn is not None:
            return fn
    from ..facade import C                                        # W2b：包内门面（惰性句柄）
    return getattr(C, "build_monster", None)


class _ScriptApiPort:
    """宿主壳 `_boss_script_port._ScriptApi` 的**包内端口**（逐字同形：只把三处耦合换包内源）。

    见 `game/commands/_boss_script_port.py:49-72`（真源适配器）：非绑定符号原样透传包内模块。
    """

    _BOUND_FACTORIES = ("make_script_hook", "make_script_event")

    def __init__(self, bs):
        object.__setattr__(self, "_bs", bs)

    @staticmethod
    def _deps() -> dict:
        from ..catalog_quests import MONSTER_MODS
        from ..catalog_space import INSTANCES
        from ..tables import merge_phase_config
        return {"data": {"MONSTER_MODS": MONSTER_MODS, "INSTANCES": INSTANCES},
                "phase_templates": merge_phase_config,
                "build_monster": _resolve_build_monster()}

    def __getattr__(self, name):
        bs = object.__getattribute__(self, "_bs")
        fn = getattr(bs, name)
        if not callable(fn):
            return fn
        if name in self._BOUND_FACTORIES:
            def _factory(st, **kw):
                d = self._deps()
                d.update(kw)                  # 调用方显式传参优先
                return fn(st, **d)
            return _factory
        if name == "boss_script_cfg":
            def _cfg(st, actor, data=None):
                return fn(st, actor, data if data is not None else self._deps()["data"])
            return _cfg
        return fn


def _default_script_api():
    """缺省 Boss 剧本导演：注入槽 `script_api` → 包内端口 `_ScriptApiPort`。"""
    injected = _INJECTED.get("script_api")
    if injected is not None:
        return injected
    from . import boss_script as _BS
    return _ScriptApiPort(_BS)

# ── 文案（B18 L3c：3 条 key 的**调用点**从宿主 `game/commands/instance_battle.py` 迁进包内）──
# key / 槽位 / 整句逐字未改（表仍是宿主 `game/data/text_specs.json`，包内 `content/texts.py`
# 经宿主薄壳注入的 SPEC_PATH 读同一份）→ 宿主该文件的 `T.text/T.static` 调用点计数归 0。
TEAM_HEAL_KEY = "instance.日志_团队治疗"
ABORT_TEXT = {"no_sides": "instance.结算_战斗异常",
              "no_actor": "instance.面板_战斗_不在"}


def team_heal_text(name, amount) -> str:
    """团队治疗广播行（真源 = 宿主旧 `game/commands/instance_battle.py::_team_heal_text`）。"""
    return T.text(TEAM_HEAL_KEY, name=name, amount=amount)


def abort_text(code) -> str:
    """行动中止码 → 文案（真源 = 宿主旧 `_ABORT_TEXT` 映射；code ∈ ABORT_TEXT）。"""
    return T.static(ABORT_TEXT[code])


# ★ B2-C3：模块级渲染器别名（`_attach_instance_hooks` 的 `team_heal_text` 形参同名遮蔽，
# 缺省解析要用模块级那一只；它与宿主壳传入的 `_IB.team_heal_text` 是**同一函数对象**）。
_TEAM_HEAL_RENDERER = team_heal_text

# 玩家快照/玩法壳视图需要同步回的每玩家键（actor → snap 或 st per-player 键）
# V 系列：战斗状态权威 = effects（snap 由 sync_player_from_actor 回写），
# p_buffs/p_hot 等玩法壳视图键的折算由显示层按需读 effects（N5b4-1 双引擎通用）
_VIEW_SNAP_KEYS = (
    "hp", "mp", "max_hp", "max_mp", "effects", "shields", "defending", "charging",
    "ct", "cooldown", "food_effects",
)
_VIEW_ST_KEYS = {
    "effects": "p_effects", "shields": "p_shields", "food_effects": "p_food_effects",
    "defending": "p_defending", "charging": "charging", "cooldown": "cooldown",
}

_MODS = None


def _monster_mods() -> dict:
    """MONSTER_MODS（包内域 `content/data/monster_mods.json`）。

    真源读宿主聚合层 `game.content.MONSTER_MODS`（同源导出物；自动仇恨目标策略
    `target_policy` 只在 3 条怪上有值）。读不到 → 空 dict（真源同分支：查不到 =
    回落 `hate_top`/`front`，不抛）。
    """
    global _MODS
    if _MODS is None:
        try:
            with open(os.path.join(_DATA_DIR, "monster_mods.json"), encoding="utf-8") as f:
                _MODS = json.load(f)
        except Exception:                                     # noqa: BLE001
            _MODS = {}
    return _MODS


def _player_actor(snap: dict, st: dict, key: str) -> dict:
    """玩家快照 + st per-player 键 → saintess_engine player actor（sides 用）。

    快照字段全透传（身份/面板/站位）；V 系列：状态在 snap.effects（由
    sync_player_from_actor 每帧回写），p_effects 顶层键为老档兜底。
    """
    actor = BR.player_to_actor(snap)
    # 状态键合并：快照内键优先，st 顶层键兜底（老存档恢复兼容）
    _snap_src = {}
    for _k in ("effects", "shields", "defending", "charging", "ct",
               "cooldown", "food_effects"):
        if snap.get(_k) is not None:
            _snap_src[_k] = snap[_k]
    for _snap_k, _st_k in _VIEW_ST_KEYS.items():
        if _snap_k not in _snap_src and (st.get(_st_k) or {}).get(str(key)) is not None:
            _snap_src[_snap_k] = (st.get(_st_k) or {}).get(str(key))
    if _snap_src.get("effects") is not None:
        actor["effects"] = dict(_snap_src["effects"])
    if _snap_src.get("shields") is not None:
        actor["shields"] = dict(_snap_src["shields"])
    if _snap_src.get("defending") is not None:
        actor["defending"] = bool(_snap_src["defending"])
    if _snap_src.get("charging") is not None:
        actor["charging"] = _snap_src["charging"]
    if _snap_src.get("cooldown") is not None:
        actor["cooldown"] = dict(_snap_src["cooldown"])
    if _snap_src.get("food_effects") is not None:
        actor["food_effects"] = list(_snap_src["food_effects"])
    actor["ct"] = float(_snap_src.get("ct", 0) or 0)
    # 统一数值容器（v181.M-bonus）：快照 bonus 全容器恢复（panel/cap/cost 随 actor
    # 落盘/恢复）；旧档快照（无 bonus 键，stat_bonus/cap_bonus 旧键）一次性转换——
    # 仅存档数据迁移，非引擎读源回落（引擎读源一律 bonus 分域 get 兜底）
    _bns = snap.get("bonus")
    if isinstance(_bns, dict):
        actor["bonus"] = {
            "panel": dict(_bns.get("panel") or {}),
            "cap": dict(_bns.get("cap") or {}),
            "cost": dict(_bns.get("cost") or {}),
        }
    else:
        actor["bonus"] = {
            "panel": dict(snap.get("stat_bonus") or snap.get("title_bonus") or {}),
            "cap": dict(snap.get("cap_bonus") or {}),
            "cost": {},
        }
    actor.pop("stat_bonus", None)
    actor.pop("cap_bonus", None)
    return actor


def _instance_target_picker(st: dict):
    """副本自动怪目标选择闭包（5b G1：仇恨/嘲讽/target_policy）。

    返回 callable(battle, actor) -> Optional[actor]（None=引擎回落默认敌对）。
    语义对齐旧 _pick_instance_target（battle.py 1440-1479）：
    ① 嘲讽强制：st.taunt_target 存活 → 打嘲讽者
    ② 按怪 target_policy（MONSTER_MODS target_policy；Boss 缺省 hate_top，
       其他缺省 front）+ st.threat 表 → FM.pick_by_policy
    引擎零游戏知识（target_picker 只是决策注入点）。
    """
    def pick(battle, actor):
        try:
            from saintess_engine import formation as FM
            alive_p = [a for a in battle.sides_of("player")
                       if int(a.get("hp", 0) or 0) > 0]
            if not alive_p:
                return None
            # N5B target_hint：AI 战术目标提示（v1：lowest_hp 残血收割）——
            # hint 与仇恨不冲突时优先（一次性，消费即弃；未知 hint 回落仇恨）
            _hint = actor.pop("_target_hint", None)
            if _hint == "lowest_hp":
                return min(alive_p, key=lambda a: (
                    int(a.get("hp", 0) or 0) /
                    max(1, int(a.get("max_hp", 1) or 1))))
            # ① 嘲讽强制
            tk = str(st.get("taunt_target") or "")
            if tk:
                for a in alive_p:
                    if str(a.get("qq_id") or "") == tk:
                        return a
            # ② target_policy + threat（threat 表 key=qq_id → pick 用 uid 映射）
            _threat = {}
            for a in alive_p:
                _q = str(a.get("qq_id") or "")
                _threat[str(a.get("uid") or ("p_%s" % _q))] = float(
                    (st.get("threat") or {}).get(_q, 0) or 0)
            _tpol = ""
            try:
                _mid = actor.get("id") or ""
                _tpol = str((_monster_mods().get(_mid, {}) or {}).get("target_policy", "") or "")
            except Exception:
                _tpol = ""
            if not _tpol:
                _tpol = "hate_top" if str(actor.get("role", "")) == "boss" else "front"
            picked = FM.pick_by_policy(_tpol, alive_p, threat=_threat)
            return picked
        except Exception:
            return None
    return pick


def _instance_team_event(st: dict, team_heal_text=None):
    """副本团队技能广播观察者（5b G2：act_cast + info.team → 全队效果）。

    旧引擎由 battle.py 生成 team_effects（6176/6256/7204）→ instance 层 _apply_team_effect
    消费；saintess_engine 引擎零游戏知识——本观察者经 on_event（事件总线尾部通知）监听：
      act_cast + info.team == "heal_all" → 除施放者外全队治疗（施放者已由 _do_heal 治疗）
    数据现状：skills.py team 值仅 heal_all（牧师救赎之光）——按数据声明做，无 if-elif 扩散。

    ★ 端口差异：真源行内 `logs.append(T.text("instance.日志_团队治疗", …))`（宿主文案表）
    → 本包 `team_heal_text(name, amount)`（渲染器由调用方注入）。`None` = 治疗照算、
    该行不追加（包内零文案表，缺口见文件头 ②）。
    """
    def on_event(battle, evt_name, ctx, logs):
        try:
            if evt_name != "act_cast":
                return
            info = (ctx or {}).get("info") or {}
            team = info.get("team")
            if not team or team != "heal_all":
                return
            caster = (ctx or {}).get("actor")
            if not caster or int(caster.get("hp", 0) or 0) <= 0:
                return
            # 治疗量 = 施法者面板公式（对齐 _do_heal/_heal_amount，独立算全队口径）
            from saintess_engine.battle.actions import heal_amount as _hcalc
            from saintess_engine import stats as _S
            from saintess_engine.battle.landing import heal_actor as _heal
            from .. import skills as _SK
            _stp = _S.actor_stats(battle, caster)
            _lv = _SK.skill_level_of(caster, info.get("name", "")) if caster.get("class_name") else 0
            try:
                _heal_v = _hcalc(_stp, caster, info, _lv)
            except Exception:
                _heal_v = 0
            if _heal_v <= 0:
                return
            for _a in battle.sides_of("player"):
                if _a is caster or int(_a.get("hp", 0) or 0) <= 0:
                    continue
                _real = _heal(battle, _a, _heal_v, logs)
                if _real > 0 and team_heal_text is not None:
                    logs.append(team_heal_text(_a.get('name', '队友'), _real))
        except Exception:
            pass  # 观察者异常不阻断战斗结算
    return on_event


def _attach_instance_hooks(b, st: dict, *, script_api=None, team_heal_text=None) -> None:
    """battle 恢复/重建后重挂命令层注入钩子（5b：target_picker + 5a：action_override）。

    saintess_engine 的 Battle 构造参数（target_picker/on_event/action_override）都是运行回调，
    不随 to_state/from_state 序列化——每次 from_state 后必须重挂，否则副本自动怪
    不按仇恨选目标、道具行动回调丢失。

    :param script_api: Boss 剧本导演实现（模块/对象，需有 `boss_script_cfg` /
        `make_script_event` / `make_script_hook`）；缺省 = 包内端口 `_default_script_api()`
        （★ B2-C3：与宿主壳 `_script_api()` 同形同源；不再是裸 `boss_script` 模块）。
    :param team_heal_text: 团队治疗行渲染器（见 `_instance_team_event`）；缺省 = 包内
        `team_heal_text`（★ B2-C3：宿主壳传的就是它，不再默认不追加该行）。
    """
    try:
        b.target_picker = _instance_target_picker(st)
    except Exception:
        b.target_picker = None
    try:
        from ..mech.item_use import make_override
        b.action_override = make_override()
    except Exception:
        b.action_override = None
    if script_api is None:
        script_api = _default_script_api()                     # 包内端口（B2-C3）
    if team_heal_text is None:
        team_heal_text = _TEAM_HEAL_RENDERER                   # 包内渲染器（B2-C3）
    try:
        _se = script_api.make_script_event(st)
        _te = _instance_team_event(st, team_heal_text)

        def _combined_event(battle, evt_name, ctx, logs):
            _te(battle, evt_name, ctx, logs)
            _se(battle, evt_name, ctx, logs)
        b.on_event = _combined_event
    except Exception:
        b.on_event = None
    try:
        # 5c P1：Boss 剧本导演钩子（敌方阵容有剧本 Boss 才挂；无 → None 回落）
        _has_script = any(
            script_api.boss_script_cfg(st, a) is not None
            for a in b.sides_of("enemy")
            if int(a.get("hp", 0) or 0) > 0
        )
        b.script_hook = script_api.make_script_hook(st) if _has_script else None
    except Exception:
        b.script_hook = None


def build_battle(st: dict, *, script_api=None, team_heal_text=None) -> "object":
    """遭遇/切怪/Boss 战：组 sides → B2 → st["battle"]=to_state。返回 B2。

    玩家 side = st["members"] 存活者 actor；敌 side = st["enemies"] 单位 actor。
    宠物：当前队长/首成员宠物照传（只存不驱动，宠物批前不参与）。
    """
    from saintess_engine import Battle as B2
    sides: dict = {"player": [], "enemy": []}
    _roster = IR.roster_of(st)   # v185：名单视图（保序；缺 alive 键 = 存活）
    for kk in _roster.members:
        if not _roster.alive(kk):
            continue
        snap = (st.get("players") or {}).get(kk)
        if not snap or int(snap.get("hp", 0) or 0) <= 0:
            continue
        sides["player"].append(_player_actor(snap, st, kk))
    for u in st.get("enemies") or []:
        if not isinstance(u, dict):
            continue
        try:
            sides["enemy"].append(BR.monster_to_actor(u))
        except Exception:
            continue  # 个别单位翻译失败不阻断整场（数据异常容错）
    _pet = {}
    try:
        _first_alive = next((a for a in sides["player"]), None)
        if _first_alive:
            _k0 = str(_first_alive.get("qq_id") or "")
            _pet = (st.get("pets") or {}).get(_k0) or {}
    except Exception:
        pass
    b = B2("instance", sides=sides, title_bonus={}, pet=_pet or {})
    # 5b：构造时注入副本命令层钩子（target_picker 仇恨选目标等）
    _attach_instance_hooks(b, st, script_api=script_api, team_heal_text=team_heal_text)
    st["battle"] = b.to_state()
    return b


def _players_of(st: dict) -> list:
    """st["battle"] sides player actors（存活+死亡全量，按序）。"""
    _b = (st.get("battle") or {}).get("sides") or {}
    return list(_b.get("player") or [])


def _enemies_of(st: dict) -> list:
    _b = (st.get("battle") or {}).get("sides") or {}
    return list(_b.get("enemy") or [])


def player_actor_of(st: dict, qq_id) -> Optional[dict]:
    """按 qq_id 找玩家 actor（存活优先，死亡兜底——展示要显示倒地者）。"""
    _q = str(qq_id)
    acts = [a for a in _players_of(st) if str(a.get("qq_id") or "") == _q]
    if not acts:
        return None
    alive = [a for a in acts if (a.get("hp") or 0) > 0]
    return (alive or acts)[0]


def next_actor_key(st: dict) -> Optional[str]:
    """下一个该行动玩家 = sides player 存活 actor 中 ct 最小者。"""
    best, best_t = None, None
    for a in _players_of(st):
        if (a.get("hp") or 0) <= 0:
            continue
        t = float(a.get("ct", 0) or 0)
        if best_t is None or t < best_t:
            best_t, best = t, a
    return str(best.get("qq_id") or "") if best else None


def act(st: dict, group_id, qq_id, action: str, skill_name=None,
        target=None, *, script_api=None, team_heal_text=None) -> tuple:
    """真人行动：from_state → human_act → to_state 落回。

    返回 (logs, ended, next_key, abort)：abort = "" 正常 / "no_sides" 战斗状态异常 /
    "no_actor" 行动者不在战斗中（文案由调用方渲染，见文件头 ②）。
    副本轮流由玩法壳驱动：调用前已确认轮到 qq_id。
    target：外部解析好的目标 actor（None=自动）；heal/buff 强制 None 防奶敌。
    """
    from saintess_engine import Battle as B2
    from .. import skills as _SK
    st_battle = st.get("battle") or {}
    if not st_battle.get("sides"):
        return [], True, None, "no_sides"
    b = B2.from_state(st_battle)
    # I3：from_state 后注入道具行动回调 + 5b target_picker（action_override/
    # target_picker 不可序列化，恢复必重挂——副本自动怪选目标、道具行动都靠它们）
    _attach_instance_hooks(b, st, script_api=script_api, team_heal_text=team_heal_text)
    # 从重建后的 b.sides 定位行动者（不能从 st 旧 dict 找——from_state 是反序列化
    # 副本，引擎修改落在 b 内 actor，若用 st 旧 actor 则 to_state 落回时修改丢失：
    # hp/ct/defending 全部不写回，副本战斗永远无进展）。PVP act 同口径。
    my = None
    try:
        for _a in b.sides_of("player"):
            if str(_a.get("qq_id") or "") == str(qq_id):
                my = _a
                break
    except Exception:
        my = None
    if my is None:
        my = player_actor_of(st, qq_id)
    if my is None:
        return [], True, None, "no_actor"
    _tgt = target
    # 目标解析：saintess_engine 引擎只吃 actor dict（字符串会崩）——名字/编号在此翻译。
    # 支持：None=自动 / actor dict 直传 / 字符串=敌名（前缀匹配，v2 多怪指定）
    #       / aN 编号（A 层第 N 个存活敌，formation 站位编号语义，v127.3）
    if isinstance(_tgt, str):
        _s = _tgt.strip().lower()
        _alive_e = [u for u in b.sides_of("enemy") if (u.get("hp") or 0) > 0]
        _picked = None
        if _s.startswith("a") and _s[1:].isdigit():
            _idx = int(_s[1:]) - 1
            if 0 <= _idx < len(_alive_e):
                _picked = _alive_e[_idx]
        elif _s.isdigit():
            _idx = int(_s) - 1
            if 0 <= _idx < len(_alive_e):
                _picked = _alive_e[_idx]
        else:
            _nm = _tgt.strip()
            for u in _alive_e:
                if (u.get("name") or "") == _nm or (u.get("name") or "").startswith(_nm):
                    _picked = u
                    break
        _tgt = _picked  # 解析失败 → None 自动选目标（引擎 _default_target）
    _action, _skill = action, skill_name
    if action == "skill" and skill_name:
        try:
            _info = _SK.skill_info(my.get("class_name") or "", skill_name) or {}
            if _info.get("kind") in (K_HEAL, K_BUFF):
                _tgt = None  # 治疗/增益作用自己（防奶敌）
        except Exception:
            pass
    logs, ended, who = b.human_act(_action, _skill, actor=my, target=_tgt)
    st["battle"] = b.to_state()
    nxt = None
    if not ended:
        try:
            nxt = next_actor_key(st)
        except Exception:
            nxt = None
    return logs, ended, nxt, ""


def _pkg_sync_player(snap: dict, actor: dict) -> None:
    """缺省回写半边：包内 `content.bridge.sync_player_from_actor`（B9-L8 已搬入包内）。

    宿主薄壳传的 `services.battle_bridge.sync_player_from_actor` 是它的一层委托
    （B9-L8 报告：宿主 47 行薄壳 → 同一实现）——两边同源，缺省因此与传参行为一致。
    """
    BR.sync_player_from_actor(snap, actor)


def sync_views(st: dict, group_id, sync_player_fn=None, db_update_fn=None) -> None:
    """唯一视图/DB 同步点：saintess_engine actors → 玩法壳旧键 + 玩家 DB 血量。

    - st["players"][k] 快照：hp/mp/max/buffs/shields/defending/charging/ct/...
    - st per-player 键（p_buffs/p_hot/p_defending/...）同帧更新（老玩法壳读）
    - st["boss"]/st["enemy"]/st["enemies"]：存活敌视图（死亡由玩法壳 compact）
    - st["now"]
    - DB：存活玩家 hp/mp 写回（战斗内 DB 保持开本值每刻同步，保留现行为）

    ★ 端口差异：真源 `sync_player_from_actor`（:388）→ 缺省 = 包内 `_pkg_sync_player`
    （B11-L2 收口：B9-L8 已把回写半边搬进 `content/bridge.py`，缺省不再是「不回写」）；
    ★ B2-C3（R1）：`db_update_fn=None` 不再是「不写库」——缺省走 `_resolve_db_update()`
    （注入槽 `bind_host(db_update=…)` / `bind_host(db=…)` → 包内 `content.persistence`），
    与宿主壳 `game/commands/instance_battle.py::_db_update` 写库行为逐字一致。
    """
    players = st.setdefault("players", {})
    if sync_player_fn is None:
        sync_player_fn = _pkg_sync_player
    if db_update_fn is None:
        db_update_fn = _resolve_db_update()   # 解析不进 try：取不到 = 装配缺陷（拒绝静默不写库）
    for _a in _players_of(st):
        _k = str(_a.get("qq_id") or "")
        snap = players.get(_k)
        if snap is None:
            continue
        if sync_player_fn is not None:
            sync_player_fn(snap, _a)  # hp/mp/max/buffs/shields/defending/charging...
        for _ak, _sk in _VIEW_ST_KEYS.items():
            if _a.get(_ak) is not None:
                st.setdefault(_sk, {})[_k] = _a[_ak]
        snap["ct"] = float(_a.get("ct", 0) or 0)
        # v181.M-bonus：统一数值容器全量回写快照（panel/cap/cost；下轮 _player_actor 恢复）
        _bn = _a.get("bonus")
        snap["bonus"] = {
            "panel": dict((_bn or {}).get("panel") or {}),
            "cap": dict((_bn or {}).get("cap") or {}),
            "cost": dict((_bn or {}).get("cost") or {}),
        }
        snap.pop("stat_bonus", None)
        snap.pop("cap_bonus", None)
        # 倒地标记（O105 语义）——v185：存活表收口 instance_run（缺 alive 键 = 存活）
        if snap.get("hp", 0) <= 0 and IR.alive_of(st, _k):
            IR.set_alive(st, _k, False)
        # DB 血量同步（快照权威 → db，保留现行为）
        if db_update_fn is not None:
            try:
                db_update_fn(group_id, _k,
                             int(snap.get("hp", 0) or 0),
                             int(snap.get("mp", 0) or 0),
                             int(snap.get("max_hp", 0) or 0),
                             int(snap.get("max_mp", 0) or 0))
            except Exception:
                pass
    # 敌视图（存活单位；死亡单位由玩法壳 compact 移除并记账）
    _alive_e = [a for a in _enemies_of(st) if (a.get("hp") or 0) > 0]
    st["enemies"] = _alive_e
    if _alive_e:
        st.setdefault("boss", _alive_e[0])
        st["enemy"] = _alive_e[0]
    elif st.get("boss") is not None:
        # 全灭：boss 键保留原引用（玩法壳按存活/uid 判定）
        pass
    try:
        st["now"] = float((st.get("battle") or {}).get("now", 0.0) or 0.0)
    except Exception:
        pass
