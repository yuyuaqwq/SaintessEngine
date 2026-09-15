# -*- coding: utf-8 -*-
"""包内移动线（`content/travel.py`）—— 真源 `game/services/travel.py`（374 行）**逐字端口**。

★ B9 L5（2026-09-13）：宿主 `game/services/travel.py` 薄壳化 = **只留「加载包 + 注入宿主替身 +
同名 re-export」**，`commands/world.py` 的 14 个调用点与调用签名**一字不变**
（`world.py:223/229/235/1140/1371/1414/1421/1445/1448/1473/1477/1480/1496/1763`）。

只改两类东西（与 `content/flow/weekly_progress.py` / `content/talk_actions.py` 同款）
------------------------------------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| 模块级 `from .. import content as C` | 数据表用**包内门面**（`_cs` / `_cc`）；未进包的符号 `C = _Dom()` 的 `__getattr__` 转注入的宿主聚合层 | ★ B14-2 L6：读表口从「就地重建 + 宿主句柄」切到共享门面，逐符号归属见下表 |
| 函数体内 `from .. import db  # 惰性导入` + `db.xxx(...)` | 模块级 `db` = **惰性宿主代理** `_HostDB` | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import，防在包侧另起一份宿主模块树） |

★ 逐符号归属（真源写法一律 `C.<名>`；下表「符号」列只写名）
----------------------------------------------------------
| 符号 | 包内来源 | 实测口径 |
|---|---|---|
| `MAPS`（121，**有序，且条目带 `subareas`**）/ `MAP_BY_ID` / `PORTALS`（11） | **包内门面** `content/catalog_space.py`（本文件别名 `_cs`） | ★ B14-2 L6：原先是「`worlds`+`subareas`+`maps` 就地重建」（重建函数已删，防同表两份定义）；门面对拍逐条 deep-equal 实测相等（121/121，含 `subareas` 注入）。`MAP_BY_ID` 必须是**带 subareas 的那份**（否则 `landing_subarea` 静默返回 None = 落点变空）；`PORTALS` 键序 = 真源声明序（比域 JSON 字典序更保真） |
| `MAP_TYPE_FIELD` / `MAP_TYPE_TOWN` / `MAP_TYPE_INSTANCE` | **包内门面** `content/catalog_core.py`（别名 `_cc`） | ★ B14-2 L6：原走宿主 `game/core/constants.py`（缺口）；B13-L6 常量入包后切门面（门禁逐值相等） |
| `LEGACY_MAP_ALIAS` / `HIDDEN_MAP_UNLOCK` | **包内门面** `content/catalog_b143.py`（别名 `_cb143`；真源 `game/data/maps.py:4352/4343`） | ★ W4（2026-09-14）：原「无域、无读口」缺口已由 B14-3 建 `game_config.maps` 组补齐；门禁逐键逐值（含键序）相等 ⇒ 切门面，`C` 的 `_HOST_FALLBACK` 里两名同时删除 |
| `map_entry_subarea` / `map_center` / `map_route` / `subarea_links` / `map_exit_subarea` | **宿主**（`game/core/maps.py`，引擎 `Space` 适配层）—— **缺口** | ⚠ **不能**在包里重建：`map_space` 读的是**运行时态** `SUBAREAS`（副本大陆克隆会就地增补房间），包内是按域文件静态重建 ⇒ 重建会在副本场景分叉。故按「谁认识活数据谁给」走宿主 |
| `is_hidden_room` / `reveal_met` / `reveal_progress` | **宿主**（`game/core/maps.py`）—— **缺口** | 读运行时 `SUBAREAS` 的 `hidden`/`reveal` 字段 + `db` 计数 ⇒ 同 `map_space` 的理由 |
| `build_monster`（`game/core/drops.py:389`） | **宿主** —— **缺口** | 怪物构造器**未进包**（`content/flow/boss_script.py` / `content/flow/tower_progress.py` 已登记同一缺口，走调用方传参）；本模块签名不许改（14 个调用点）⇒ 经 `bind_host` 注入 |
| `mount_effects`（`game/core/mounts.py:39`） | **宿主** —— **缺口** | 坐骑域未进包（`content/settlement.py:55` 已登记同一缺口，那边走调用方传 dict；本模块无参数位 ⇒ 注入） |

★ `getattr(C, "is_hidden_room", None)` 这条**兜底分支**照原样保留：本门面 `__getattr__` 在宿主
聚合层拿不到该属性时抛 `AttributeError`（与宿主 `C` 缺属性的表现一致）⇒ `getattr(..., None)`
仍得到 `None`，走「接口缺失 → 全部可见 / 放行」的原分支。

用法::

    from content import travel as TR
    TR.bind_host(db, c)                     # 宿主薄壳注入（游戏仓 game/services/travel.py）
    sas = TR.visible_sas(player, cur_map, group_id, qq_id)
"""
from __future__ import annotations

import sys

import random  # noqa: F401  （真源模块级 `import random`；`move_stamina_cost` / `travel_ambush` 用）

# ★ B14-2 L6：数据表切包内门面（宿主 `game/data` 删掉后本模块仍能活）
from . import catalog_core as _cc        # MAP_TYPE_FIELD / MAP_TYPE_TOWN / MAP_TYPE_INSTANCE
from . import catalog_space as _cs       # MAPS / MAP_BY_ID / PORTALS
from . import catalog_b143 as _cb143     # ★ W4：LEGACY_MAP_ALIAS / HIDDEN_MAP_UNLOCK（原缺口）


# ============================================================
# 宿主替身口
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 函数体内 `from .. import db`）
_HOST_C = None             # 宿主内容聚合层 `game.content` —— 只喂**未进包**的符号（见 docstring 表）

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）—— 与
# `content/flow/weekly_progress.py` / `content/talk_actions.py` 同口径（B8.2 线1 立的规矩）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"

# `C` 上**未进包**的符号 → 转宿主聚合层（理由见模块 docstring 的逐符号归属表）
_HOST_FALLBACK = (
    "map_entry_subarea", "map_exit_subarea", "map_center", "map_route", "subarea_links",
    "is_hidden_room", "reveal_met", "reveal_progress",
    "build_monster", "mount_effects",
)


def bind_host(db=None, c=None) -> None:
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。"""
    global _HOST_DB, _HOST_C
    if db is not None:
        _HOST_DB = db
    if c is not None:
        _HOST_C = c


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(
        "travel：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _HostDB:
    """惰性宿主存储层代理（真源 函数体内 `from .. import db`）——`db.xxx` 正文不动。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _host_c():
    """宿主内容聚合层（真源 `from .. import content as C`）。"""
    return _HOST_C if _HOST_C is not None else _resolve_host("content")


class _Dom:
    """`C` 的宿主兜底面（B14-2 L6：数据表已切包内门面 `_cs` / `_cc`，本类只剩未进包的符号）。"""

    def __getattr__(self, name):
        """未进包的符号 → 宿主聚合层（`__getattr__` 只在常规找不到时才走）。"""
        if name in _HOST_FALLBACK:
            return getattr(_host_c(), name)
        raise AttributeError(name)


C = _Dom()


# ============ 模块常量（world.py 原样随迁，值逐字符同源） ============
# v130.7 意见#28 越级风险增强：比玩家高 5 级起，撞怪概率随等级差线性提升
# （0.30 + (diff-5)*0.05；低 10 级 = 0.55，低 11 级+ = 0.60 封顶）
AMBUSH_HIGH_MIN = 0.30
AMBUSH_HIGH_STEP = 0.05
AMBUSH_HIGH_CAP = 0.60
AMBUSH_MID = 0.18    # 同级/略低（diff 0..4）
AMBUSH_LOW = 0.08    # 玩家等级 > 地图（diff -4..-1）


# ============ 子区域寻址（v86/v87.14/v115） ============

def visible_sas(player: dict, cur_map: dict, group_id: str, qq_id: str) -> list:
    """v115 当前位置地图中**可见**的子区域列表（供面板/移动统一使用）。

    隐藏房间（A 提供 is_hidden_room）未揭示（C.reveal_met）→ 不可见（不列出）。
    若 A 尚未装好网状/hidden 接口，用 getattr 兜底：is_hidden_room 缺失时全部可见。
    """
    sas = cur_map.get("subareas") or []
    map_id = cur_map.get("id", "")
    is_hidden = getattr(C, "is_hidden_room", None)
    reveal_met = getattr(C, "reveal_met", None)
    visible = []
    for sa in sas:
        sa_id = sa.get("id", "")
        if is_hidden is None or reveal_met is None:
            visible.append(sa)
            continue
        try:
            if is_hidden(map_id, sa_id) and not reveal_met(sa.get("reveal"), group_id, qq_id, map_id):
                continue  # 隐藏未揭示 → 跳过
        except Exception:
            pass
        visible.append(sa)
    return visible


def conn_target(conn) -> tuple:
    """解析可前往连接项 → (目标地图 dict, 指定子区域 id 或 None)
    v87.5 支持两字段配置：'map_id' 或 ('map_id', 'subarea_id')"""
    if isinstance(conn, tuple):
        return _cs.MAP_BY_ID[conn[0]], conn[1]
    return _cs.MAP_BY_ID[conn], None


def conn_subarea_name(nm: dict, want_sa) -> str:
    """目标地图的落点子区域显示名(默认入口子区域，可指定)

    v87.16：无指定时用 map_entry_subarea（进城落点=出口/入口），不再是首个子区域
    """
    sas = nm.get("subareas") or []
    if not sas:
        return ""
    if want_sa:
        for s in sas:
            if s["id"] == want_sa:
                return f" · {s['name']}"
        return ""
    # v87.16：跨图落点 = 城镇出口（镇郊）/ 野外入口，显示与实际到达一致
    entry_id = C.map_entry_subarea(nm.get("id", ""))
    if entry_id:
        for s in sas:
            if s["id"] == entry_id:
                return f" · {s['name']}"
    return f" · {sas[0]['name']}"


def subarea_hidden_block(group_id, qq_id, map_id: str, sa: dict) -> str:
    """v115：隐藏未揭示房间不能直接前往（提示需先探索揭开）。

    返回拦截文案（含探索进度 txt，'' 表示无）或 None（可通行）。
    is_hidden/reveal_met 接口缺失时 getattr 兜底放行（同 world 原分支）。
    """
    _is_hidden_fn = getattr(C, "is_hidden_room", None)
    _reveal_met_fn = getattr(C, "reveal_met", None)
    if _is_hidden_fn is not None and _reveal_met_fn is not None:
        try:
            if _is_hidden_fn(map_id, sa["id"]) and not _reveal_met_fn(sa.get("reveal"), group_id, qq_id, map_id):
                _reveal_pr = getattr(C, "reveal_progress", None)
                _progress_txt = ""
                if _reveal_pr is not None:
                    try:
                        _ck, _nk = _reveal_pr(group_id, qq_id, map_id)
                        if _nk is not None:
                            _progress_txt = f"（还差 {_nk - _ck} 次探索）"
                    except Exception:
                        pass
                return f"🔒 这里似乎被什么遮挡着……（在本图继续『探索』可揭开它的面纱）{_progress_txt}"
        except Exception:
            pass
    return None


def resolve_map_target(dest: str):
    """目标地图寻址：地图名/ID 精确 → 旧区域别名 → 区域名（area_name）→ 区域入口。

    v86/v104 P1 口径（与『前往』原 else 分支逐行等价）：返回 dict 或 None。
    """
    for m in _cs.MAPS:
        if dest in (m["name"], m["id"]):
            return m
    if dest in _cb143.LEGACY_MAP_ALIAS:
        return _cs.MAP_BY_ID.get(_cb143.LEGACY_MAP_ALIAS[dest])
    # 区域名 → 区域入口
    for m in _cs.MAPS:
        if dest in m.get("area_name", ""):
            return m
    return None


def move_blocked_msg(cur_map: dict, player: dict, target_sa: dict) -> str:
    """v87.14 同图内不可直达时的提示(城镇星形 / 野外线性)。"""
    cur_sa_id = player.get("cur_subarea") or ""
    cur_name = cur_sa_id
    tgt_name = target_sa.get("name", target_sa.get("id", "？"))
    sas = cur_map.get("subareas") or []
    for s in sas:
        if s["id"] == cur_sa_id:
            cur_name = s["name"]
            break
    _mid = cur_map.get("id", "")
    # v183：必经之路问引擎（`map_route` 的第一个中间站）—— v87.16 起这里手算「星形链首」，
    # 与引擎的 route 是同一件事（已由 tests/test_v183_space_shape.py 逐对比对证明等价）。
    _hub = C.map_center(_mid)
    if _hub and cur_sa_id == _hub:
        _tgt_id = target_sa.get("id") or ""
        _route = C.map_route(_mid, cur_sa_id, _tgt_id)
        if len(_route) >= 2 and _route[1] != _tgt_id:
            first = next((s["name"] for s in sas if s["id"] == _route[1]), _route[1])
            return (f"🧭 你身处【{cur_name}】，不能直接去【{tgt_name}】——"
                    f"路只有一条，需要先经过{first}。")
    # v95.12：按空间连接提示必经路线（街道/出口链），不要一律"回广场"——
    # 镇郊去广场要先经过东大街，提示必须与真实路径一致。
    # v183：原来城镇/野外各有一份 return（两份逐字相同），已合一。
    links = C.subarea_links(_mid, cur_sa_id)
    link_names = [next((s["name"] for s in sas if s["id"] == lid), lid) for lid in links]
    return (f"🧭 你身处【{cur_name}】，不能直接去【{tgt_name}】——"
            f"路只有一条，需要先经过{'、'.join(link_names)}。")


def leave_map_block_msg(cur_map: dict, player: dict) -> str:
    """v87.14 出图必须在该图出口子区域（城镇=城门，野外=入口）。

    未在出口 → 返回引导提示（同 move 跨图两段原文案）；已在出口/无出口 → ''。
    """
    exit_sa_id = C.map_exit_subarea(cur_map.get("id", ""))
    if exit_sa_id and player.get("cur_subarea") != exit_sa_id:
        sas = cur_map.get("subareas") or []
        _exit_name = next((s["name"] for s in sas if s["id"] == exit_sa_id), "出口")
        _cur_sa_name = next((s["name"] for s in sas if s["id"] == player.get("cur_subarea")),
                            player.get("cur_subarea", ""))
        return (f"🧭 你身处【{_cur_sa_name}】，还不能离开{cur_map.get('name', '此地')}——"
                f"需要先到{_exit_name}(『前往 {_exit_name}』)才能出城/出图。")
    return ""


# ============ 等级提示 / 体力经济（v94 / v101.13 坐骑概率免费） ============

def level_warn(player: dict, target: dict) -> str:
    """v87 跨图建议等级提示行（玩家低于目标图等级时）。"""
    if player["level"] < target["lv"]:
        return (f"\n⚠️ 建议等级 Lv.{target['lv']}，你才 Lv.{player['level']}，小心行事！")
    return ""


def stamina_max(player: dict) -> int:
    """体力上限：100 + 等级×2（base._stamina_max 同式，服务层自算版）"""
    return 100 + (player.get("level") or 1) * 2


def stamina_tired_line(player: dict) -> str:
    """体力 0 走不动提示段（move 跨图扣 1 前置拦截，原 4 行文案逐字符随迁）。"""
    return (
        f"⚡ 你太累了，走不动了！(体力 {int(player.get('stamina') or 0)}/{stamina_max(player)})\n"
        "💡 恢复体力：野外营地『休息』/ 吃食物 / 旅店『住宿』，或等体力自然恢复(每1分钟+1)\n"
        "💡 也可以『传送』(已激活的方碑)或使用『回城卷轴』脱身～\n"
        "💡 新手建议：野外活动前先在城镇『商店』买点食物（烤肉串等），体力 0 才不会困在野外～"
    )


def move_stamina_cost(player: dict) -> int:
    """跨图移动体力扣费：v101.13 坐骑 stamina_reduce 概率免费（返回 0/1）。

    等价于原 move 段 `0 if random.random() < float(mount_effects...stamina_reduce) else 1`——
    单次 random 消耗位置与次序完全一致（L3 seed 等价）。
    """
    if random.random() < float(C.mount_effects(player).get("stamina_reduce", 0) or 0):
        return 0
    return 1


# ============ 撞怪档位（v49 意见#4 / v130.7 / v130.8 → v132 ±1） ============

def travel_ambush(player: dict, target_map: dict, group_id=None, qq_id=None,
                  main_kill_hook=None):
    """移动撞怪判定：返回撞到的怪物 dict 或 None。

    生物趋避利害：
    - 玩家等级 ≥ 地图等级+5：威慑低等级生物，不撞怪
    - 玩家等级 ≤ 地图等级-5：闯入强者地盘，30% 概率撞怪
    - 同级/略低：8~18% 概率
    城镇区域不撞怪（安全区）。'城镇外郊' 类型数据不存在，v102.1 清理。

    main_kill_hook：命令层注入 _main_kill_target_on_map（combat 域只读判定）。
    缺省 None 或 group_id/qq_id 空 = 无群上下文 → 维持原语义跳过副本撞怪分支。
    """
    mtype = target_map.get("type", _cc.MAP_TYPE_FIELD)
    if mtype == _cc.MAP_TYPE_TOWN:
        return None
    # v95.23 #247：副本区域不参与移动撞怪——副本 Boss 在入口子区域 monsters 池里，
    # 撞怪会绕过『副本 <名字>』开本流程的等级/人数校验，低等级玩家进副本入口被 Boss 秒杀。
    # 副本入口应显示地图信息，引导玩家走开本流程（'副本' 命令有完整校验）。
    # v105 M19 P0：主线击杀目标只挂副本时放行——撞怪池仅保留主线目标怪
    # （走下方统一概率判定，Boss 按等级差概率撞，不绕过任何校验之外的新增风险面）。
    if mtype == _cc.MAP_TYPE_INSTANCE:
        # v105 M19 P0：主线击杀目标只挂副本时放行——撞怪池仅保留主线目标怪
        # （走下方统一概率判定；group_id/qq_id 为空=既有测试直调场景，维持原跳过）
        _main_ent = None
        if group_id and qq_id and main_kill_hook is not None:
            _main_ent = main_kill_hook(group_id, qq_id, target_map)
        if not _main_ent:
            return None
        monsters = [_main_ent]
        diff = target_map.get("lv", 1) - player["level"]
        if diff <= -5:
            return None
        if diff >= 5:
            chance = AMBUSH_HIGH_MIN
        elif diff >= 0:
            chance = AMBUSH_MID
        else:
            chance = AMBUSH_LOW
        if random.random() >= chance:
            return None
        return C.build_monster(random.choice(monsters), target_map, lv_jitter=1)
    # v87.6 内容下沉子区域：优先取落点入口子区域的怪；入口无怪才找最近有怪子区域
    # （M22 P3：原逻辑取"首个有怪子区域"，入口无怪时会抽到深处高等级怪，玩家刚进图就被深处怪秒）
    _sas = target_map.get("subareas") or []
    _entry_id = C.map_entry_subarea(target_map.get("id", ""))
    monsters = []
    for sa in _sas:
        if sa["id"] == _entry_id and sa.get("monsters"):
            monsters = sa["monsters"]
            break
    if not monsters:
        # 入口无怪：线性图按列表顺序扫描即离入口由近及远
        for sa in _sas:
            if sa.get("monsters"):
                monsters = sa["monsters"]
                break
    if not monsters:
        return None
    diff = target_map.get("lv", 1) - player["level"]
    if diff <= -5:
        return None
    # v130.7 意见#28 越级风险增强：比玩家高 5 级起，撞怪概率随等级差线性提升
    # （0.30 + (diff-5)*0.05；低 10 级 = 0.55，低 11 级+ = 0.60 封顶）
    if diff >= 5:
        chance = min(AMBUSH_HIGH_CAP, AMBUSH_HIGH_MIN + (diff - 5) * AMBUSH_HIGH_STEP)
    elif diff >= 0:
        chance = AMBUSH_MID
    else:
        chance = AMBUSH_LOW
    if random.random() >= chance:
        return None
    # v101.25c 移动撞怪也带等级波动（普通怪 ±1，精英/Boss 固定）
    # v130.8 意见#32：±1 感知弱 → 增强为 ±2；v132 鱼鱼拍板改回 ±1（面板明示 Lv.X±1）
    return C.build_monster(random.choice(monsters), target_map, lv_jitter=1)


# ============ 隐藏图 / 方碑路由（v87 / v115） ============

def hidden_map_block(group_id, qq_id, player: dict, target: dict):
    """隐藏图准入校验 → 命中返回拦截文案（str）；放行返回 None。

    v87：等级门槛 + 物品信物（H6 泛黄书页×3 / H7 烬火信标）+ 主线完成封印。
    三条提示逐字符等价于 move 原分支（文案含引导语，随迁不动）。
    """
    if not target.get("hidden"):
        return None
    unlock = _cb143.HIDDEN_MAP_UNLOCK.get(target["id"], {})
    if player["level"] < unlock.get("level", 99):
        return "前方被无形的屏障阻挡……这里需要更强大的实力！(等级不足)"
    # v87：物品型准入（H6 泛黄书页×3 / H7 烬火信标）
    item_req = unlock.get("item")
    if item_req:
        lack = [f"{name}×{need}" for name, need in item_req.items()
                if db.count_item(group_id, qq_id, name) < need]
        if lack:
            return (
                "入口被古老的力量封锁，似乎需要信物才能进入……\n"
                f"🔒 缺少：{'、'.join(lack)}\n"
                "💡 失落图书馆：集齐 3 张泛黄书页(探索彩蛋/圣堂地窖精英/符文石)\n"
                "💡 灰烬回廊：找到老守墓人·灰须领取烬火信标"
            )
    quests = db.get_quests(group_id, qq_id)
    if unlock.get("quest") not in quests.get("completed_main", []):
        return "地图的入口被古老魔法封印，似乎只有完成主线任务才能解开……"
    return None


def landing_subarea(target: dict, want_sa):
    """跨图移动落点子区域：v86 城镇=出口（entry_subarea），野外=入口；want_sa 覆盖。

    返回子区域 dict 或 None（无 subareas 且无 want_sa 命中时——命令层按 None 兜底，
    等价原 first_sa 语义：落库 cur_subarea=''、展示回退 target desc）。
    """
    target_sas = target.get("subareas") or []
    first_sa = None
    entry_sa_id = C.map_entry_subarea(target["id"])
    for _s in target_sas:
        if _s["id"] == entry_sa_id:
            first_sa = _s
            break
    if first_sa is None and target_sas:
        first_sa = target_sas[0]
    if want_sa:
        for _s in target_sas:
            if _s["id"] == want_sa:
                first_sa = _s
                break
    return first_sa


def portal_arrive_note(group_id, qq_id, target: dict) -> str:
    """到达图含未激活方碑 → 提示行（'' 表示无提示；v13 旅者方碑引导）。"""
    tid = target.get("id", "")
    if tid in _cs.PORTALS and tid not in db.get_portals(qq_id):
        p = _cs.PORTALS[tid]
        return f"\n\n🌌 一座{p['icon']}{p['name']}矗立在此！『激活』可解锁传送点～"
    return ""
