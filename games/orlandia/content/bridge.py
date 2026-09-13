# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**开战构造半边**（逐字搬自游戏仓 `game/services/battle_bridge.py` :27-372）。

来源与范围
----------
真源 421 行 = **构造半边** `:1-372`（玩家/怪物 → actor、sides 组装、开战仪式、`apply_battle_loadout`）
           + 回写半边 `:375-420`（`sync_player_from_actor`）。
本文件 = 真源 `:27-372` **逐字搬入**，只改两类东西：
  ① **import 层**：外部依赖换成包内同源物（见下表）
  ② **宿主耦合**：读玩家 DB / 流水的部分 → **改成「由调用方传普通 dict」**（替身接口见下表）

本文件是包内「命令层数据 → saintess_engine actor」的翻译层：调用方（宿主/CLI/测试）手里是
普通 dict（player 档 / 怪组），本模块把它们翻译成引擎的 `sides` actors，并做开战装配序列。
方向只有一个：**内容 → 引擎**（本文件只 `import saintess_engine`，引擎零游戏知识）。

① import 层改动（与真源逐行对拍见 `overnight/d3_bridge_verify.py` A1 节）
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from saintess_engine import make_actor`（:25） | 同左 | 引擎工厂；本文件唯一包外依赖（引擎） |
| `from ..content_rules.panel import player_final_stats`（:281） | `from . import panel` | `content/panel.py` = 该模块的逐字搬入物（D3 面板批）|
| `from .battle_equip_proc import apply_to_actor as _EP_apply`（:244） | `from .mech.equip import apply_to_actor as _EP_apply` | ② 装备装配已进包（D2 equip 批）|
| `from .class_mech_proc import apply_class_mech as _CM_apply`（:249） | `from .mech.class_mech import apply_class_mech as _CM_apply` | ③ 职业机制兑现已进包（D2 class_mech 批）|

② 宿主耦合替身接口（本文件**不读玩家 DB / 平台 / 墙上时间**——一律由调用方给普通 dict）
| 真源宿主耦合 | 包内替身 | 调用方给什么 |
|---|---|---|
| `prepare_player_for_battle(player, title_bonus, db)`（:256） | 同签名，第三参改 **`event_state`** | `event_state` = 普通 dict，等价于宿主的 event_state 存储（只用到 `get / 赋值 / del` 三动词）|
| `db.get_event_state("bless_<qq>")`（:304） / `("poi_buff_<qq>")`（:323） | `event_state.get(...)` | 键 → 原始字符串值（缺失 = `None`）|
| `db.set_event_state(k, "")`（:314） / `set_event_state(k, json)`（:339） | `event_state[k] = v` | 同上（原地写回调用方的 dict）|
| `db.delete_event_state(k)`（:337） | `event_state.pop(k, None)` | 同上 |
| `_default_db()`（:369，`from .. import db`）| **不搬**（宿主存储层访问器）| 不传 `event_state` = 无 event_state（内部按空 dict 处理，零副作用）|
| `apply_player_battle_start(player, actor, db)`（:188） | 第三参改 **`event_state`** | 同上（薄壳，保持旧签名语义）|
| `attach_tlog(b, ...)`（:207，读宿主 `tlog_setup` 流水开关 + sink）| **不搬**（宿主流水装配）| —— |

⚠️ 未搬（构造半边之外，属宿主侧契约）：`sync_player_from_actor`（真源 :400-420，战斗后
   actor → player dict 回写）、`attach_tlog`、`_default_db`。清单见
   `overnight/d3-bridge-port.md` §4。

⚠️ 不变式：`player_to_actor` 透传的 `qq_id` / `group_id` 只是**调用方给的普通 dict 字段**，
   包内不解析平台语义（不认 QQ 号 / 群号，只当字符串键用）。

⚠️ 引擎配置不在本文件：装配前需有 `content.apply.install_engine()`（挂引擎 hook + 规则表）；
   包内「①→⑥ 全链」入口是 `content.apply.apply_game_content(actor)`，本文件只做真源
   `apply_battle_loadout` 的 ①②③（装备 → 职业机制），与真源一一对应。
"""
from __future__ import annotations

from typing import Optional

from saintess_engine import make_actor  # 只读 saintess_engine 工厂，不改 saintess_engine

# ============================================================
# 玩家 → player actor
# ============================================================

# 玩家 dict 里需要透传给 saintess_engine actor 的面板/配置字段
# （逐字真源 :32-44；`qq_id` / `group_id` 只是调用方给的普通 dict 字段，包内不解析平台语义）
_PLAYER_PASSTHROUGH = (
    "qq_id", "group_id", "cur_map", "race", "class_tier", "attributes",
    "evolve_path", "learned_skills", "skill_levels",
    # 状态字段（战斗内玩家资源——从旧档恢复或开战仪式已写入 player；
    # 效果类（echo_bless/poi_buff/…）V6 起由 _start_effects_to_actor 翻译进
    # actor.effects 面板快照，不在 passthrough 冗余透传）
    "resources", "stacks", "eff", "hot", "food_effects",
    "buff_hits", "last_element",
    "battle_prefs",   # 战前偏好（双形态/终结阈值/奥术力场档——内容侧读）
    "overflow_shield_cd", "stealth_atk",
    "reduce_all_left", "reduce_left", "combo_seq", "last_combo_tag",
    "tailwind_prev_energy", "last_skill", "last_cast_at",
)

# 开战仪式一次性祝福 → actor.effects 面板快照条目（V6：旧引擎 BUFF_MULT 折算
# /poi ×1.10 在 _apply_buffs；saintess_engine 无 buffs 容器 → 仪式消费的祝福翻译成
# effects 面板快照，整场生效。数值权威：prepare_player_for_battle 消费时已
# 按 event_state 写入 player["_battle_boons"]——纯数据搬运，桥不造数值）。
def _battle_boons_to_effects(player: dict, actor: dict) -> dict:
    """玩家开战仪式产物（_battle_boons 标记）→ actor.effects 面板快照条目。

    条目无 expire（整场），stats._apply_effects 读内嵌 stat/op/mult 折算。
    幂等：已翻译过的键跳过（防 build_sides 重复调用双写）。
    """
    boons = player.get("_battle_boons") or {}
    if not isinstance(boons, dict) or not boons:
        return actor
    ef = actor.setdefault("effects", {})
    for key, b in boons.items():
        if not isinstance(b, dict):
            continue
        if not b.get("stat") or b.get("mult") is None:
            continue
        if key in ef:  # 已翻译（重复 build_sides 幂等）
            continue
        ef[key] = {"stacks": 1, "stat": b["stat"], "op": b.get("op", "mul"),
                   "mult": float(b["mult"])}
    return actor

# 玩家 dict 的 buffs 键（旧引擎把玩家 buffs 写 player["buffs"]——saintess_engine actor.buffs 同构）
def player_to_actor(player: dict) -> dict:
    """玩家 DB dict → saintess_engine player actor（human_controlled=True）。"""
    player = player or {}
    qq = str(player.get("qq_id", ""))
    # 面板当前值：hp/mp 直传（旧 DB hp/mp 是当前值）；max 由 stats 重算或 DB 值
    stats_kw = {}
    for k in ("hp", "mp", "max_hp", "max_mp", "atk", "def", "matk", "mdef", "spd",
              "crit", "crit_dmg", "dodge", "block", "pene", "luck", "tenacity",
              "race"):
        if player.get(k) is not None:
            stats_kw[k] = player[k]
    # 同构状态键透传（V 系列：effects 由 make_actor 播种，调用方按需填；
    # buffs/debuffs/hot/state 旧四键已废弃——透传只会造成脏残留，剔除；
    # poi_buff 已由 V6 翻译进 effects 面板快照条目，不再透传冗余 actor 字段）
    for k in ("shields", "cooldown", "charging", "defending",
              "ct"):
        if player.get(k) is not None:
            stats_kw[k] = player[k]
    skills = player.get("learned_skills") or player.get("skills") or []
    actor = make_actor(
        uid=("p_%s" % qq) if qq else "p_0",
        name=player.get("name", "冒险者"),
        side="player",
        kind="player",
        human_controlled=True,
        class_name=player.get("class_name") or "战士",
        level=int(player.get("level", 1) or 1),
        equipment=player.get("equipment") or {},
        skills=list(skills) if not isinstance(skills, list) else skills,
        learned_skills=list(player.get("learned_skills") or []),
        **stats_kw,
    )
    # 透传额外字段（身份/面板/数据标签——make_actor 会把未知 key 原样带上）
    for k in _PLAYER_PASSTHROUGH:
        if k in player and k not in actor:
            actor[k] = player[k]
    # V6：开战仪式祝福（echo_bless/poi_buff）→ effects 面板快照（整场生效）
    _battle_boons_to_effects(player, actor)
    # 旧 stacks/resources → saintess_engine state 映射（开战仪式/恢复时用；默认空）
    #   注意：只有调用方明确要迁移时才填——本函数不做隐式迁移（避免把旧职业
    #   叠层语义错误地灌进 state，那应由上层职业模块按声明表翻译）
    return actor


# ============================================================
# 怪物 → enemy actor
# ============================================================

def monster_to_actor(mon: dict, idx: int = 0) -> dict:
    """单只怪 dict（build_monster 产物）→ saintess_engine enemy actor。

    lv → level（引擎不认 lv）；身份/站位/掉落字段透传。
    """
    mon = mon or {}
    stats_kw = {}
    for k in ("hp", "max_hp", "mp", "max_mp", "atk", "def", "matk", "mdef", "spd",
              "crit", "crit_dmg", "dodge", "block", "pene", "luck", "tenacity"):
        if mon.get(k) is not None:
            stats_kw[k] = mon[k]
    # 同构状态键透传（V 系列：effects/shields/cooldown；旧 buffs/debuffs/hot/state 废弃剔除）
    for k in ("shields", "cooldown", "charging",
              "defending", "ct"):
        if mon.get(k) is not None:
            stats_kw[k] = mon[k]
    actor = make_actor(
        uid=mon.get("uid") or ("e_%d" % idx),
        name=mon.get("name", "怪物"),
        side=mon.get("side") or "enemy",
        kind=mon.get("kind") or ("monster" if not mon.get("class_name") else "player"),
        class_name=mon.get("class_name"),
        level=int(mon.get("level", mon.get("lv", 1)) or 1),  # lv → level
        equipment=mon.get("equipment") or {},
        skills=list(mon.get("skills") or []),
        learned_skills=list(mon.get("learned_skills") or []),
        auto_act=mon.get("auto_act") or ({"act": {"type": "attack"}} if not mon.get("ai") else None),
        **stats_kw,
    )
    # 怪数据标签透传（站位/身份/掉落/元素/资源定义——make_actor 会原样带未知 key）
    for k in ("rank", "reach", "role", "is_boss", "is_elite", "exp", "gold", "drops",
              "id", "map", "map_area", "mech", "mod", "ai", "resource_def",
              "element_immune", "element_weak", "dmg_taken_mult", "on_taken",
              "abyss_res", "skill_levels", "race", "side", "ext"):
        if mon.get(k) is not None and k not in actor:
            actor[k] = mon[k]
    return actor


def enemies_to_actors(enemies: list) -> list:
    """怪组 list → enemy actor list。"""
    return [monster_to_actor(m, i) for i, m in enumerate(enemies or [])]


# ============================================================
# sides 组装
# ============================================================

def build_sides(player: Optional[dict] = None, enemies: Optional[list] = None,
                allies: Optional[list] = None) -> dict:
    """组 sides：{player: [玩家actor, ...], enemy: [怪actor, ...]}。

    单人野外：player 单 actor；副本 allies 额外 actor（human_controlled 按需）。
    """
    sides: dict = {"player": [], "enemy": []}
    if player is not None:
        p_actor = player_to_actor(player)
        sides["player"].append(p_actor)
    for a in (allies or []):
        sides["player"].append(player_to_actor(a))
    sides["enemy"] = enemies_to_actors(enemies or [])
    return sides


# ============================================================
# 开战仪式（旧 Battle.__init__ 的玩家侧副作用 → 命令层开战前对 player dict 处理）
# ============================================================

def apply_player_battle_start(player: dict, actor: dict, event_state: Optional[dict] = None) -> dict:
    """把旧 Battle.__init__ 的玩家侧开战仪式结果应用到 saintess_engine actor。

    ⚠️ 本函数保持旧签名/语义的薄壳（命令层调用点可能传 actor）——推荐新调用方
    直接调 prepare_player_for_battle(player, title_bonus, event_state)（build_sides 前
    对 player dict 做仪式，build_sides 透传即得仪式后 actor）。

    ⚠️ 宿主耦合替身（真源第三参 `db` → 本包 `event_state`）：`event_state` 是调用方给的
    普通 dict（等价宿主 event_state 存储的 get/赋值/del 三动词），本文件不读 DB。

    目前实现（只做数据搬运，不触发引擎逻辑）：
    - echo_bless/poi_buff 从 event_state 消费写入 player dict（旧引擎构造时做）→
      actor 构造时已透传
    - 装备词条战斗开始效果（护盾/狼嚎/奥术屏障/起手资源/套装/weapon_effects）→
      属职业/装备层（上层模块），N5b 不复制旧 Battle 效果逻辑进桥——留 TODO 增量。

    返回 actor（原地补全后同一引用）。
    """
    prepare_player_for_battle(player, None, event_state)
    return actor


def apply_battle_loadout(actor: dict, title_bonus: Optional[dict] = None) -> dict:
    """开战装配序列（每个 player actor 调一次）：外部面板增幅 + 装备词条 + 职业机制。

    ① `actor["bonus"] = {"panel": 外部增幅, "cap": {}, "cost": {}}`
       （v181.M 统一数值容器；`cap`/`cost` 分域由装备装配覆盖写）
    ② `mech.equip.apply_to_actor` → 武器效果 / 词条挂 `actor.triggers`
       （真源 = 游戏仓 `services/battle_equip_proc.py:1133 apply_to_actor`）
    ③ `mech.class_mech.apply_class_mech` → 技能 mech 兑现装配
       （真源 = 游戏仓 `services/class_mech_proc.py apply_class_mech`）

    ⚠️ ②③ 异常**沿用原写法静默跳过**（个别词条/技能解析失败不阻断开战）。
    三处生产调用点（combat `_open_battle` / `_open_pvp`、tower）原为逐行重复；
    收敛于此的意义：**数值门禁（tests/numeric_sim.py）与生产同源** ——
    否则门禁自己一套口径，数字好看但与线上不一致。

    ⚠️ 与真源的差异 = 只有 ②③ 的实现来源（包内 `content/mech/` 的逐字搬入物）。
       ④ 挂敌身条 / ⑤ 条件乘区 / ⑤b 元素机制（真源在别处调用）不在本函数，
       包内全链入口是 `content.apply.apply_game_content`（①→⑥）。
    """
    try:
        actor["bonus"] = {"panel": dict(title_bonus or {}), "cap": {}, "cost": {}}
    except Exception:                                             # noqa: BLE001
        pass
    try:
        from .mech.equip import apply_to_actor as _EP_apply
        _EP_apply(actor)
    except Exception:                                             # noqa: BLE001
        pass
    try:
        from .mech.class_mech import apply_class_mech as _CM_apply
        _CM_apply(actor)
    except Exception:                                             # noqa: BLE001
        pass
    return actor


def prepare_player_for_battle(player: dict, title_bonus: Optional[dict] = None,
                              event_state: Optional[dict] = None) -> dict:
    """开战仪式（player dict 侧，build_sides 前调用）——纯数据搬运/事件消费。

    对齐旧 Battle.__init__ 的玩家侧副作用（只做不依赖 Battle 实例的部分；
    效果执行类属上层职业/装备模块，N5b 增量）：

    1. 战斗字段键播种（buffs/shields/state/cooldown/... 与旧引擎同构）
    2. max_hp/max_mp 实时重算（v95.19：DB max 是注册/升级快照，换装备后过时——
       战斗内面板/护盾 pct/heal clamp 以实时聚合值为准）
    3. echo_bless 消费（event_state bless_{qq_id} → player.buffs.echo_bless，一次性）
    4. 神龛祝福消费（event_state poi_buff_{qq_id} → player.poi_buff，left-1；用完删）

    ⚠️ 依赖红线：只 import 包内纯函数层（`content/panel.py` 面板）；
    **零 DB / 零平台 / 零墙上时间**——真源第三参 `db` 在此替换为**调用方传的普通 dict**
    `event_state`（替身接口：`get_event_state(k)` → `event_state.get(k)`；
    `set_event_state(k, v)` → `event_state[k] = v`；`delete_event_state(k)` →
    `event_state.pop(k, None)`）。不传 / 传 None = 无 event_state（零副作用）。

    返回 player（原地补全后同一引用）。
    """
    player = player if isinstance(player, dict) else {}
    if not player:
        return player
    # 0. 宿主耦合替身落点（调用方 dict；None → 空 dict = 无 event_state，读永远 miss、写丢弃）
    _es = event_state if isinstance(event_state, dict) else {}
    # 1. 战斗字段播种（与旧 Battle.__init__ _seed 同款；actor 由 build_sides 透传）
    _seed_battle_keys(player)
    # 2. 面板实时化（不传 learned_skills——战斗侧被动由上层动态处理，防双算）
    try:
        from . import panel as _panel
        _cn = player.get("class_name") or "战士"
        _st = _panel.player_final_stats(
            _cn, int(player.get("level", 1) or 1),
            player.get("equipment") or {},
            int(player.get("class_tier", 0) or 0),
            player.get("attributes"),
            int(player.get("evolve_path", 0) or 0),
            title_bonus or {},
            player.get("race"),
        )
        if _st.get("max_hp"):
            player["max_hp"] = int(_st["max_hp"])
        if _st.get("max_mp") is not None:
            player["max_mp"] = int(_st["max_mp"])
    except Exception:
        pass  # 面板重算失败不阻断开战（沿用 DB 值）
    # 3. echo_bless 消费（v97.4：探索事件写 event_state bless_{qid}，本场攻击 +pct%，
    #    一次性）。V6：不写 player.buffs 旧键（容器已删除）——落 _battle_boons 标记，
    #    player_to_actor 翻译成 actor.effects 面板快照（stats 折算，整场生效）。
    try:
        _qq = player.get("qq_id")
        if _qq and not (player.get("_battle_boons") or {}).get("echo_bless"):
            _raw = _es.get(f"bless_{_qq}")
            if _raw:
                import json as _json2
                try:
                    _bless = _json2.loads(_raw)
                    _pct = float((_bless or {}).get("pct", 5) or 5)
                except Exception:
                    _pct = 5.0
                player.setdefault("_battle_boons", {})["echo_bless"] = {
                    "stat": "atk", "op": "mul", "mult": 1.0 + _pct / 100.0}
                _es[f"bless_{_qq}"] = ""      # 替身：db.set_event_state(k, "")
    except Exception:
        pass
    # 4. 神龛祝福消费（v104 M23：poi_buff_{qid}，left-1；用完删 key，flee 也算消耗）
    #    V6：效果落 _battle_boons → actor.effects 面板快照（player.poi_buff 保留
    #    供命令层开战 note 显示，同旧语义）
    try:
        _qq = player.get("qq_id")
        if _qq and not player.get("poi_buff"):
            _raw = _es.get(f"poi_buff_{_qq}")
            if _raw:
                import json as _json
                _pb = _json.loads(_raw)
                if isinstance(_pb, dict) and _pb.get("stat") in ("atk", "def", "spd") \
                        and int(_pb.get("left", 0) or 0) > 0:
                    player["poi_buff"] = {"stat": _pb["stat"],
                                          "mult": float(_pb.get("mult", 1.10)),
                                          "name": _pb.get("name", _pb["stat"])}
                    player.setdefault("_battle_boons", {})["poi_buff"] = {
                        "stat": _pb["stat"], "op": "mul",
                        "mult": float(_pb.get("mult", 1.10))}
                    _pb["left"] = int(_pb["left"]) - 1
                    if _pb["left"] <= 0:
                        _es.pop(f"poi_buff_{_qq}", None)   # 替身：db.delete_event_state(k)
                    else:
                        _es[f"poi_buff_{_qq}"] = _json.dumps(_pb, ensure_ascii=False)
                        # ↑ 替身：db.set_event_state(k, json)
    except Exception:
        pass
    # 【v181.M-R2b 删除原步骤 5】v139 core_resource 配置注入（形态层字段挂 player）——
    #    core_resources.py 退役删除（R2b 函数层 + R2c 文件本体），注入无消费端（形态层未实现）。
    # 【2026-09-11 死代码清理】两个 v139 遗留空壳模块本体已删（battle_modes / battle_conds；
    #    后者唯一活件 COND_LABELS 拆成 core/battle_cond_labels.py），
    #    player 上对应的形态层透传/播种/回写键一并移除。
    return player


def _seed_battle_keys(player: dict) -> dict:
    """玩家战斗可变键播种（旧 Battle.__init__ 玩家侧 setdefault 全量）。"""
    _seeds = {
        "resources": dict, "stacks": dict, "eff": dict, "shields": dict,
        "cooldown": dict, "hot": dict, "food_effects": list,
        "buff_hits": dict, "combo_seq": list,
        "last_combo_tag": None, "last_element": None,
        "tailwind_prev_energy": None,
        "overflow_shield_cd": False, "stealth_atk": False,
        "reduce_all_left": 0, "reduce_left": 0,
        "poi_buff": None, "charging": None, "defending": False,
    }
    for _k, _ctor in _seeds.items():
        if _k not in player or player[_k] is None:
            player[_k] = _ctor() if callable(_ctor) else _ctor
    return player


__all__ = [
    "player_to_actor", "monster_to_actor", "enemies_to_actors", "build_sides",
    "apply_player_battle_start", "apply_battle_loadout", "prepare_player_for_battle",
]
