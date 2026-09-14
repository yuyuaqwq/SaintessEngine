# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— **存档层 professions 域**（B17，2026-09-14）。

真源：宿主 `game/store/professions.py`（逐字端口：正文一字未改，**只动「取件」**）。
宿主 `game/store/professions.py` 现在只剩一层**委托薄壳**（`from content.persistence.professions import *`）。

| 真源写法 | 包内替身 | 为什么 |
|---|---|---|
| `from .connection import _connect, _lock[, atomic]` | `from .handles import ...` | 连接/锁/事务三个句柄由**注入面**给（宿主工厂注入 db_path） |
| `from .. import content as C` | `from ..facade import C`（**包内聚合门面**；★ W2a 改指） | 包内禁 import 宿主（I2）；内容面 = 包内门面 |
| 函数内 `from ..<宿主模块> import <名>` | `_host_attr("…", "…")` / `_host_attrs(...)` | 同位置、调用时解析（与真源「函数内惰性 import」同刻） |
| `time.time()` | `clock()` | 时钟是四个注入点之一（默认 = stdlib `time.time`，行为零变化） |

**注入面**：`content/persistence/handles.py`（`bind(db_path=…, clock=…, flush_log=…, lock=…)`）；
宿主装配点 = `game/store/store_factory.py`。纯包环境（编辑器）需注入自己的句柄 —— 见 B19/B20 接点。
"""
"""奥兰迪亚·余烬纪年存储层 - professions：副业等级与经验

副业（采集/挖掘/垂钓/炼金/锻造/烹饪）独立成长线：
- 每条副业 Lv.1~10，升级需求按 constants.prof_exp_need 二次曲线 need(lv)=5lv²+15lv
  （v105 平衡曲线，2026-08-13 鱼鱼拍板，累计 2100 满级；Lv.1→2 仅 20）
- add_prof_exp 自动处理升级与封顶（Lv.10 满级不再累积）
- 19 章 §4.1 设计表已按同一 v105 曲线对齐（见 design/new_world/19_副业体系详案.md §4.1）
"""
from .handles import _connect, _lock
# ★ W2a：内容聚合面取自**包内门面**（原 `from .handles import C` → 宿主 `game.content`）
from ..facade import C
import json  # v67 activated 列 JSON 序列化

PROF_FIELDS = {
    "gather": "采集",
    "mining": "挖掘",
    "fishing": "垂钓",
    "alchemy": "炼金",
    "craft": "锻造",
    "cooking": "烹饪",
    "enhance": "强化",
    "enchant": "附魔",
}


def _ensure_prof_row(conn, qq_id):
    conn.execute(
        "INSERT OR IGNORE INTO professions (qq_id) VALUES (?)", (qq_id,)
    )


def get_professions(group_id, qq_id):
    """返回全部副业等级/经验 dict：{key: {"lv": n, "exp": n, "name": 中文}}"""
    with _lock:
        conn = _connect()
        try:
            _ensure_prof_row(conn, qq_id)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM professions WHERE qq_id=?", (qq_id,)
            ).fetchone()
            d = dict(row) if row else {}
        finally:
            conn.close()
    out = {}
    for key, name in PROF_FIELDS.items():
        out[key] = {
            "name": name,
            "lv": d.get(f"{key}_lv", 1),
            "exp": d.get(f"{key}_exp", 0),
        }
    return out


def get_prof_level(group_id, qq_id, key):
    return get_professions(group_id, qq_id)[key]["lv"]


def _has_achievement(qq_id, ach_key):
    """成就是否已解锁（achievements 表存在该行且 progress>=1，即"达成即生效"，
    与 base.py _title_bonus 口径一致；已领取 claimed=1 是其子集）。

    任何异常按未解锁处理，绝不阻断副业经验。
    """
    try:
        from .stats import get_achievements  # 函数内导入，规避模块加载环
        return any(
            r.get("ach_key") == ach_key and r.get("progress", 0) >= 1
            for r in get_achievements("", qq_id)
        )
    except Exception:
        return False


def _is_human(qq_id):
    """v134.1 副业亲和：玩家是否为人类（锁外查 players.race，异常按非人类处理不阻断）"""
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT race FROM players WHERE qq_id=?", (qq_id,)).fetchone()
            return bool(row and row["race"] == "human")
        finally:
            conn.close()
    except Exception:
        return False


def add_prof_exp(group_id, qq_id, key, exp=1):
    """给副业加经验，自动升级。返回 (level, leveled_up)"""
    if key not in PROF_FIELDS:  # B2 加固（2026-08-10）：动态列名前白名单校验
        raise ValueError(f"add_prof_exp 非法副业: {key}（不在 PROF_FIELDS）")
    # v104.2 M13 P2 实装（14 章 2.5）：全知全能（ach_apprentice8）→ 全副业经验 +10%
    # 向上取整：现曲线单次经验仅 1~5，向下取整会让加成永远不可见；保证至少 +1
    # 注意：必须在 _lock 外检查（get_achievements 会取同一把锁，Lock 不可重入）
    if exp > 0 and _has_achievement(qq_id, "ach_apprentice8"):
        exp = (exp * 11 + 9) // 10  # ceil(exp * 1.10)，纯整数运算
    # v134.1 人类 副业亲和 prof_bonus +10%（与全知全能成就叠加；同向上取整保证可见）
    if exp > 0 and _is_human(qq_id):
        exp = (exp * 11 + 9) // 10  # ceil(exp * 1.10)
    with _lock:
        conn = _connect()
        try:
            _ensure_prof_row(conn, qq_id)
            conn.commit()
            row = conn.execute(
                f"SELECT {key}_lv AS lv, {key}_exp AS exp FROM professions WHERE qq_id=?",
                (qq_id,),
            ).fetchone()
            lv = row["lv"] if row else 1
            cur = row["exp"] if row else 0
            if lv >= 10:
                return lv, False
            cur += exp
            leveled = False
            while lv < 10 and cur >= C.prof_exp_need(lv):
                cur -= C.prof_exp_need(lv)
                lv += 1
                leveled = True
            if lv >= 10:
                cur = 0
            conn.execute(
                f"UPDATE professions SET {key}_lv=?, {key}_exp=? WHERE qq_id=?",
                (lv, cur, qq_id),
            )
            conn.commit()
            return lv, leveled
        finally:
            conn.close()


def prof_top(group_id, limit=10):
    """副业总分排行(仅已激活副业等级之和，v113.6 鱼鱼拍板)

    v113.5 T1 修复：全服排行(跨群)——玩家副业数据全局，与等级榜 top_players
    同口径（其注释明确"玩家数据全局，排行不按群过滤"），group_id 仅作兼容参数
    不再过滤；旧 v104 按群 JOIN player_groups 导致跨群玩家互相看不到。
    v113.6 修复：未激活副业不计分——此前 8 条全加，未激活也是 Lv.1 → 人人默认
    8 分，排行失去意义。改为 Python 侧解析 activated 只加已激活副业等级。
    """
    with _lock:
        conn = _connect()
        try:
            _cols = ("gather_lv,mining_lv,fishing_lv,alchemy_lv,craft_lv,"
                     "cooking_lv,enhance_lv,enchant_lv,activated")
            rows = conn.execute(
                "SELECT qq_id, " + _cols + " FROM professions"
            ).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                raw = d.pop("activated", "") or "[]"
                try:
                    act = json.loads(raw)
                    act = [k for k in act if k in PROF_FIELDS] if isinstance(act, list) else []
                except (ValueError, TypeError):
                    act = []
                total = sum(d.get(f"{k}_lv", 0) for k in act)
                items.append({"qq_id": d["qq_id"], "total": total})
            items.sort(key=lambda x: (-x["total"], x["qq_id"]))
            return items[:limit]
        finally:
            conn.close()


# ---------- v167 副业解除数量上限 ----------
# v67 曾设双副业上限（MAX_ACTIVE_PROFS=2，同时激活最多 2 条）；
# v167（鱼鱼拍板）移除上限概念：可无限学/无限发展副业，未激活动作一律自动激活，
# 永不再因"数量满"拦截。常量保留兼容 import，但不再参与任何位满判断。
MAX_ACTIVE_PROFS = 999


def get_activated_profs(group_id, qq_id):
    """已激活的副业 key 列表(v167：解除数量上限，全部拜师副业均可激活)"""
    with _lock:
        conn = _connect()
        try:
            _ensure_prof_row(conn, qq_id)
            conn.commit()
            row = conn.execute(
                "SELECT activated FROM professions WHERE qq_id=?", (qq_id,)
            ).fetchone()
            raw = (row["activated"] if row else "") or "[]"
            try:
                import json
                lst = json.loads(raw)
                return [k for k in lst if k in PROF_FIELDS] if isinstance(lst, list) else []
            except (ValueError, TypeError):
                return []
        finally:
            conn.close()


def activate_prof(group_id, qq_id, key):
    """激活副业(幂等)。返回 True=本次新激活；False=已在激活列表或非法 key"""
    if key not in PROF_FIELDS:
        return False
    lst = get_activated_profs(group_id, qq_id)
    if key in lst:
        return False
    lst.append(key)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE professions SET activated=? WHERE qq_id=?",
                (json.dumps(lst, ensure_ascii=False), qq_id),
            )
            conn.commit()
        finally:
            conn.close()
    return True


def forget_prof(group_id, qq_id, key):
    """遗忘副业：移除激活 + 等级/经验清零 + 清学徒资格(拜师记录)。

    v104 P0 修复：遗忘后必须同时从 players.apprentices 移除该副业——
    否则再激活免拜师，且 附魔 Lv.1 被 Lv.2 门槛拦截、唯一经验来源被堵，
    永久卡 Lv.1 死锁。8 副业全路径生效（enhance/enchant 同表逻辑）。
    返回旧等级
    """
    if key not in PROF_FIELDS:  # B2 加固（2026-08-10）：动态列名前白名单校验
        return None
    lst = get_activated_profs(group_id, qq_id)
    if key not in lst:
        return None
    lst.remove(key)
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                f"SELECT {key}_lv AS lv FROM professions WHERE qq_id=?", (qq_id,)
            ).fetchone()
            old_lv = row["lv"] if row else 1
            conn.execute(
                f"UPDATE professions SET activated=?, {key}_lv=1, {key}_exp=0 WHERE qq_id=?",
                (json.dumps(lst, ensure_ascii=False), qq_id),
            )
            # v104 P0：同步清 players.apprentices 里的拜师资格（防附魔遗忘死锁）
            try:
                prow = conn.execute(
                    "SELECT apprentices FROM players WHERE qq_id=?", (qq_id,)
                ).fetchone()
                appr = []
                if prow and prow["apprentices"]:
                    try:
                        appr = json.loads(prow["apprentices"])
                    except (ValueError, TypeError):
                        appr = []
                if key in appr:
                    appr.remove(key)
                    conn.execute(
                        "UPDATE players SET apprentices=? WHERE qq_id=?",
                        (json.dumps(appr, ensure_ascii=False), qq_id),
                    )
            except Exception:
                pass  # 玩家表/列异常不阻断遗忘主流程（等级清零已生效）
            conn.commit()
            return old_lv
        finally:
            conn.close()


def bump_fish_king(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            _ensure_prof_row(conn, qq_id)
            conn.execute(
                "UPDATE professions SET fish_king=fish_king+1 WHERE qq_id=?",
                (qq_id,),
            )
            conn.commit()
        finally:
            conn.close()


def get_fish_king(group_id, qq_id):
    with _lock:
        conn = _connect()
        try:
            _ensure_prof_row(conn, qq_id)
            row = conn.execute(
                "SELECT fish_king FROM professions WHERE qq_id=?", (qq_id,)
            ).fetchone()
            return row["fish_king"] if row else 0
        finally:
            conn.close()

__all__ = [
    "_connect",
    "_lock",
    "C",
    "json",
    "PROF_FIELDS",
    "_ensure_prof_row",
    "get_professions",
    "get_prof_level",
    "_has_achievement",
    "_is_human",
    "add_prof_exp",
    "prof_top",
    "MAX_ACTIVE_PROFS",
    "get_activated_profs",
    "activate_prof",
    "forget_prof",
    "bump_fish_king",
    "get_fish_king",
]
