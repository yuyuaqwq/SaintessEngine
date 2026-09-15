# -*- coding: utf-8 -*-
"""包内统一奖励发放域（`content/reward.py`）—— 真源 `game/reward.py`（225 行）**逐字端口**。

真源（游戏仓 `qqbot/data/plugins/dragonfall`，**只读**）
------------------------------------------------------
`game/reward.py` = 「确定奖励发放」的唯一入口 `grant_reward()`（任务 / 成就 / 收藏 / 对话NPC /
签到 / 周常 / 爬塔 全走这里）+ 批量物品辅助 `grant_items_batch()` + 五个发放子过程
（`_grant_items` / `_grant_pets` / `_grant_mounts` / `_grant_title` / `_grant_bonus`）。
2026-09-14（B12B13-TAIL 线3）起宿主 `game/reward.py` 已成**薄壳**（模块别名到本文件）。

宿主耦合替身（**只改「宿主取件」两类：① 存储/流水 import 口 ② 读表口**；正文逻辑一行未改）
--------------------------------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .log_setup import LOG`（模块级） | `_log()` → `content/obs.py::log()` | B2-C4：包内唯一日志取用口（fail-closed）；`LOG.warning(...)` 调用点 `_log().warning(...)` 不变 |
| `def _c(): import game.content as C; return C` | **删**（B2-C4）：读表口逐名改包内直取（`EQUIP_ROSTER`/`ITEMS`/`MATERIALS`/`TITLES`/`make_pet_egg`/`make_mount_rein`，证据 `out/evidence/identity_map.txt`） |
| `from .store.inventory import _key_to_id`（`_grant_items` 内） | `_key_to_id = _host_key_to_id()` | 同位置同惰性时机（B1 已切包内 `content/persistence/inventory.py`） |
| `from .import db`（`grant_items_batch` / `grant_reward` 内） | 模块级 `db = _HostDB()`（属性访问时解析） | 正文里 `db.xxx(...)` **一行未改**；兜底 = 包内 `content/_pkgref.DB`（B1 口径） |
| `from . import tlog_setup as _tlog`（`grant_reward` 的 try 内） | `content/obs.py::emit(...)` | B2-C4（接口表第 14 行）：解析在 try 之外（未接上 → 抛，不被 `except` 吞掉） |
| `from .content_rules.gameplay import check_player_level_up`（函数内） | `check_player_level_up = _host_levelup()` | 升级结算：B1 已切包内 `content/gameplay_rules.py` |
| `from .core.stat_bonus import stat_bonus`（函数内） | `stat_bonus = _host_stat_bonus()` | 属性加成：B1 已切包内 `content/stat_bonus.py` |
| `C.generate_roster_equip`（2 处） | `_drops().generate_roster_equip` | `core.drops` 面：**包内直取** `content/drops.py`（接口表第 5 行冻结落点，B2-C2 已落地）；宿主同对象为过渡保险 |

宿主模块解析：`bind_host` 注入优先 → `sys.modules`（两个宿主包名）→ `importlib`；**绝不静默空跑**
（取不到就抛）—— 与 `content/affix.py` / `content/flow/weekly_progress.py` 同款。

不变式
------
* 本文件**不 import 宿主模块**（方向只有 内容 → 引擎/标准库）；宿主面全部经注入句柄或惰性取件。
* 行为与真源逐字节相同：证据 `overnight/b12b13_L3_snap.py`（40 例快照，渲染文本 + 整库 dump，
  改前/改后 sha256 `1af7e7373814e987dd87741439d3645f7ef806377dc6cb500488fab25614bc5b` 逐字节相同）。
* 文案（`🎁 获得…` / `🎒 …` / `🥚 …` / `🐾 …` / `🏅 …` / `✨ 永久属性…`）逐字保留 —— 文案槽位
  与玩家可见句子由宿主渲染（`tests/test_texts_table.py` 的扫面在宿主命令层，不在本文件）。
"""
from __future__ import annotations

import importlib
import inspect
import sys
import uuid

from . import obs                                                        # noqa: E402  B2-C4：LOG/tlog 唯一取用口
from .catalog_items import (EQUIP_ROSTER, EQUIP_ROSTER_BY_NAME,          # noqa: E402  B2-C4：`C.<名>` 包内直取
                            ITEMS, MATERIALS)
from .catalog_quests import TITLES                                       # noqa: E402  真源 `C.TITLES`
from .mounts import make_mount_rein                                      # noqa: E402  真源 `C.make_mount_rein`
from .pets import make_pet_egg                                           # noqa: E402  真源 `C.make_pet_egg`

# ============================================================
# 宿主面取件口（B2-C4 收口）—— 注入优先（宿主薄壳 `game/reward.py:91` 的 `bind_host`）→ 包内兜底
#   本文件 B2 读点：LOG → `content/obs.py`；tlog → `content/obs.py::emit`；`C.<名>` → 包内直取；
#   残留只剩 `core.drops` 面（B2-C2 待落地 `content/drops.py`，见 `_drops()`）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等；宿主薄壳 import 期调用；签名/语义逐字不变）。键 = `db` / `content` /
    `log` / `tlog` / `key_to_id` / `levelup` / `stat_bonus`；值 = **模块/对象**（定值）或
    **零参可调用**（活源，每次取用时调用一次 → 等价真源「函数内惰性 import 宿主」的时机）。
    `None` 忽略。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _live_provider(v):
    """`v` 是否宿主薄壳口径的**零参活源**（`bind_host` docstring：「零参可调用（活源，每次取用
    时调用一次）」）—— 非零参的可调用对象是**定值**（函数对象本身就是要用的东西）。

    ★ R2（终态补债）：原判据 `callable(v)` 过宽。宿主薄壳注入的 `levelup` / `stat_bonus` /
    `key_to_id` 都是零参 provider（`game/reward.py:73-88` 的 `_levelup` / `_stat_bonus` /
    `_key_to_id_fn`），而**终态**（`game.json` 的 `bind` 在位 ⇒ `content/facade.py::bind_host`
    扇出 `_PKG_SURFACE` 的包内落点）注入的是**目标函数本身**（`check_player_level_up` /
    `stat_bonus` / `_key_to_id`，都是带参函数）⇒ 被误当活源**零参调用** ⇒
    `TypeError: check_player_level_up() missing 3 required positional arguments`，
    `grant_reward` 整条断（R2 实测：`bind` 在位时 `test_commands_dialogue` /
    `test_commands_apprentice` / `test_v1242_audit_fix` 红，摘掉 bind 即绿）。
    按文档契约改成「零参」判据后，两种注入形态各归其位，宿主壳活源语义不变。
    """
    if not callable(v):
        return False
    try:
        params = inspect.signature(v).parameters
    except (TypeError, ValueError):          # 内建/无签名对象：按定值处理（不冒零参调用的险）
        return False
    for p in params.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is p.empty:
            return False
    return True


def _resolve(key: str, fallback):
    """注入优先（**零参**可调用 = 活源 → 调一次；模块/对象 = 定值）→ 否则走 `fallback()`（包内兜底）。"""
    v = _INJECTED.get(key)
    if v is not None:
        return v() if _live_provider(v) else v
    return fallback()


def _host_db():
    """存储层句柄（真源 `from .import db`）—— 注入优先 → 包内 `content/_pkgref.DB`（B1 口径）。"""
    from ._pkgref import DB as _pdb
    return _resolve("db", lambda: _pdb)


class _HostDB:
    """惰性存储层代理（真源 `from .import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_host_db(), name)


db = _HostDB()                       # 真源 `from .import db`（两处，函数内）

#: `core.drops` 面的包内落点（接口表第 5 行冻结：`content/drops.py`，B2-C2 线负责落地）
_DROPS_PKG = "content.drops"
_DROPS = None


def _drops():
    """`core.drops` 取件口（B2-C4）—— **包内直取** `content/drops.py`（接口表第 5 行冻结落点，
    B2-C2 已落地）；宿主 `game.core.drops` 为同对象过渡保险。"""
    global _DROPS
    if _DROPS is None:
        try:
            _DROPS = importlib.import_module(_DROPS_PKG)
        except ImportError:
            last = None
            for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
                m = sys.modules.get("%s.core.drops" % prefix)
                if m is not None:
                    _DROPS = m
                    break
            if _DROPS is None:
                for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
                    try:
                        _DROPS = importlib.import_module("%s.core.drops" % prefix)
                        break
                    except Exception as exc:                    # noqa: BLE001
                        last = exc
            if _DROPS is None:
                raise RuntimeError("reward：core.drops 取不到（%s）——拒绝静默空跑" % (last,))
    return _DROPS




def _log():
    """日志门面（真源模块级 `from .log_setup import LOG`）—— B2-C4：包内唯一取用口 `content/obs.py`。"""
    return obs.log()


def _host_key_to_id():
    """物品 key → ID（真源 `_grant_items` 内 `from .store.inventory import _key_to_id`）。"""
    from .persistence.inventory import _key_to_id as _k2i   # B1：包内直取
    return _resolve("key_to_id", lambda: _k2i)


def _host_levelup():
    """升级结算（真源 `from .content_rules.gameplay import check_player_level_up`）。"""
    from .gameplay_rules import check_player_level_up as _lv   # B1：包内直取
    return _resolve("levelup", lambda: _lv)


def _host_stat_bonus():
    """属性加成（真源 `from .core.stat_bonus import stat_bonus`）。"""
    from .stat_bonus import stat_bonus as _sb   # B1：包内直取
    return _resolve("stat_bonus", lambda: _sb)


# ============================================================
# ↓↓↓ 以下 = 真源正文（只改上表登记的「宿主取件」几行）
# ============================================================

def _grant_items(group_id, qq_id, items, lines, db):
    """物品/材料/装备入包。items: [{item, n}]。返回 (成功, 失败计数)。"""
    _key_to_id = _host_key_to_id()
    fail = 0
    for it in items or []:
        try:
            key = it.get("item") or it.get("key")
            n = int(it.get("n") or it.get("count") or 1)
            if not key:
                continue
            # eq: 前缀 = 名册装备
            if isinstance(key, str) and key.startswith("eq:"):
                rid = key[3:]
                _rids = EQUIP_ROSTER_BY_NAME.get(rid, [rid]) if rid not in EQUIP_ROSTER else [rid]
                _rid = _rids[0]
                if _rid not in EQUIP_ROSTER:
                    print(f"[dragonfall][reward] 装备奖励名册缺失: {rid}")
                    fail += 1
                    continue
                eq = _drops().generate_roster_equip(_rid)
                db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", eq)
                lines.append(f"  🎁 获得装备：{eq.get('name', rid)}")
                continue
            # 普通物品/材料
            kid = _key_to_id(key) if _key_to_id else key
            _idata = ITEMS.get(kid) or MATERIALS.get(kid)
            if _idata is None:
                print(f"[dragonfall][reward] 物品奖励缺失: {key}（未收录），已跳过")
                fail += 1
                continue
            db.add_item(group_id, qq_id, kid, _idata, count=n)
            lines.append(f"  🎒 {_idata.get('name', key)} ×{n}")
        except Exception as e:
            _log().warning(f"[dragonfall][reward] 物品发放失败 {it}: {e}")
            fail += 1
    return fail


def _grant_pets(group_id, qq_id, pets, lines, db):
    for pid in pets or []:
        try:
            egg = make_pet_egg(pid)
            if not egg:
                continue
            db.add_item(group_id, qq_id, f"petegg_{pid}", egg)
            lines.append(f"  🥚 获得道具：{egg['name']}！『使用 宠物蛋』孵化！")
        except Exception:
            pass


def _grant_mounts(group_id, qq_id, mounts, lines, db):
    for mid in mounts or []:
        try:
            rein = make_mount_rein(mid)
            if not rein:
                continue
            db.add_item(group_id, qq_id, f"mountrein_{mid}", rein)
            lines.append(f"  🐾 获得道具：{rein['name']}！『使用 缰绳』驯服坐骑！")
        except Exception:
            pass


def _grant_title(group_id, qq_id, title, lines):
    """称号授予：titles.py 按 id/中文名匹配，播报解锁（条件系统自动判定拥有）。"""
    if not title:
        return
    tinfo = next((t for t in TITLES if t.get("id") == title), None)
    if not tinfo:
        tinfo = next((t for t in TITLES if t.get("name") == title), None)
    if tinfo:
        lines.append(f"  🏅 获得称号：「{tinfo.get('name', title)}」！")
    else:
        print(f"[dragonfall][reward] 称号 id 缺失：{title}（titles.py 未登记），已跳过")


def _grant_bonus(group_id, qq_id, bonus, lines, db):
    """永久属性加成（收藏册满套 bonus）。

    注意：游戏内永久属性走 stat_bonus() 动态计算（读 TITLES/ACHIEVEMENTS 已解锁项），
    **不落 players 表字段**。收藏册满套 bonus 的实装 = 让 stat_bonus() 认识"收藏册已集齐"，
    由 title_bonus 模块动态给，这里不做存储。若数据里 bonus 到达这里，说明调用方用了
    grant 的直接 bonus 语义——仅播报（属性由 title_bonus 动态源保证），不重复落库。
    """
    if not bonus:
        return
    parts = []
    _CN = {"atk": "攻击", "def": "防御", "matk": "魔攻", "mdef": "魔防",
           "spd": "速度", "hp": "生命", "mp": "魔力", "crit": "暴击", "dodge": "闪避"}
    for k, v in (bonus or {}).items():
        parts.append(f"{_CN.get(k, k)}+{v}")
    if parts:
        lines.append(f"  ✨ 永久属性：{'、'.join(parts)}（已自动生效）")


def grant_items_batch(group_id, qq_id, items_dict, lines=None) -> tuple:
    """批量物品发放辅助（成就等多条奖励合并物品时用）。

    items_dict: {item_key: count}（成就 reward.items 原生形态，兼容中文名）
    lines: 可选文案列表（追加物品行）
    返回 (lines, 是否全部成功)。物品缺失静默跳过不阻塞。
    """
    if lines is None:
        lines = []
    items = [{"item": k, "n": v} for k, v in (items_dict or {}).items()]
    _fail = _grant_items(group_id, qq_id, items, lines, db)
    return lines, _fail == 0


def grant_reward(reward: dict, group_id, qq_id, *, player=None, lines=None) -> list:
    """统一奖励发放入口。

    reward: REWARD dict（见模块 docstring）。None/空 dict → 返回空文案。
    player: 可选，传入可省一次 DB 读（调用方已有 player 时）。
    lines: 可选，已有文案列表时追加（否则新建）。
    返回文案行列表（含升级结算日志）。

    用法：
        from content.reward import grant_reward
        lines = grant_reward({"exp": 100, "gold": 50, "items": [...]}, gid, qid)
    """
    # 流水埋点：`content/obs.py::emit`（B2-C4）。未启用 → None（零行为，宿主契约）；
    # **解析放在 try 之外** —— 句柄没接上是装配缺陷，必须抛（否则 fail-closed 被吃掉，见接口表 §2④）。
    _r = reward or {}
    _it = _r.get("items")
    obs.emit("drop.grant", actor=qq_id, source="reward",
             exp=int(_r.get("exp", 0) or 0),
             gold=int(_r.get("gold", 0) or 0),
             items=(len(_it) if hasattr(_it, "__len__") else 0))
    check_player_level_up = _host_levelup()
    stat_bonus = _host_stat_bonus()
    if lines is None:
        lines = []
    if not reward:
        return lines
    reward = dict(reward)  # 防污染原数据
    # ── 经验/金币（含升级结算）──────────────────────────────
    exp = int(reward.get("exp") or 0)
    gold = int(reward.get("gold") or 0)
    if exp or gold:
        # 重新读 DB 最新 player（不信任调用方传入的旧引用——多动作连发时
        # 前一动作已把 exp/gold 写库，旧 player 里还是旧值，直接整段 update 会覆盖）
        player = db.get_player(group_id, qq_id)
        if player:
            player = dict(player)
            player["qq_id"] = player.get("qq_id") or qq_id
            player["_title_bonus"] = stat_bonus(group_id, qq_id, player)
            if exp:
                player["exp"] = player.get("exp", 0) + exp
            if gold:
                player["gold"] = player.get("gold", 0) + gold
            lv_logs, player = check_player_level_up(group_id, qq_id, player)
            db.update_player(group_id, qq_id,
                             exp=player["exp"], gold=player["gold"], level=player["level"],
                             hp=player["hp"], mp=player["mp"], max_hp=player["max_hp"], max_mp=player["max_mp"],
                             skills=player["skills"], attr_pts=player.get("attr_pts", 0),
                             skill_points=player.get("skill_points", 0),
                             learned_skills=player.get("learned_skills", []))
            parts = []
            if exp:
                parts.append(f"经验 +{exp}")
            if gold:
                parts.append(f"金币 +{gold}")
            if parts:
                lines.append(f"🎁 获得{'、'.join(parts)}")
            lines += lv_logs
    # ── 物品/材料/装备 ──────────────────────────────────────
    items = reward.get("items") or []
    # 兼容旧 items: {key: count} dict 形态
    if isinstance(items, dict):
        items = [{"item": k, "n": v} for k, v in items.items()]
    _grant_items(group_id, qq_id, items, lines, db)
    # 兼容旧 reward_item（任务单值/列表）——由调用方转成 items 传入，此处不处理
    # ── 名册装备 ────────────────────────────────────────────
    for eq in reward.get("equips") or []:
        rid = eq.get("rid") if isinstance(eq, dict) else eq
        try:
            equip = _drops().generate_roster_equip(rid)
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", equip)
            lines.append(f"  🎁 获得装备：{equip.get('name', rid)}")
        except Exception:
            print(f"[dragonfall][reward] 装备奖励名册缺失: {rid}，已跳过")
    # ── 宠物蛋 / 坐骑缰绳 ───────────────────────────────────
    _grant_pets(group_id, qq_id, reward.get("pets"), lines, db)
    _grant_mounts(group_id, qq_id, reward.get("mounts"), lines, db)
    # ── 称号 / 永久属性 ─────────────────────────────────────
    _grant_title(group_id, qq_id, reward.get("title"), lines)
    _grant_bonus(group_id, qq_id, reward.get("bonus"), lines, db)
    return lines
