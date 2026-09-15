# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 存档层**表结构声明**（B17，2026-09-14）。

真源：宿主 `game/store/connection.py`（DDL 四段 + `_ensure_legacy_columns` + 地图 id 集合
**逐字搬移**，正文一字未改）。表结构 = 核心逻辑 ⇒ 归包；宿主只留「连接怎么来」的工厂。

注册动作（`install(db)`）由注入的连接骨架执行：注册序 `core → social → professions → identity`
→ 迁移器（老库缺列自愈），与改造前 `connection.py` 的注册序**逐序相同**。
"""
from __future__ import annotations

from saintess_engine.store import ensure_columns

from .handles import flush_log
# ★ W2a：内容聚合面取自**包内门面**（原 `from .handles import C` → 宿主 `game.content`）。
from ..facade import C  # noqa: F401  （`content.facade` 零 import 依赖，EAGER 窗口安全）

# v135 装配期循环解除：connection 不再顶层依赖 content（data._assembly → core →
# smith_stock → db → store.connection → content 未完成初始化）。C_MAP_IDS 改为
# 惰性求值——首次访问时 content 必已完成装配（消费端都在命令层运行期）。
_C_MAP_IDS_CACHE = None


def _map_ids() -> set:
    global _C_MAP_IDS_CACHE
    if _C_MAP_IDS_CACHE is None:
        _C_MAP_IDS_CACHE = set(C.MAP_BY_ID.keys())
    return _C_MAP_IDS_CACHE


# 兼容旧引用（store 层内部使用 C_MAP_IDS 做集合运算）
C_MAP_IDS = _map_ids()

# ================= v103.5 B1-1 建表 SQL 按域拆分 =================
# 原巨型 executescript（317 行 init_db）拆为 3 个常量，init_db 依次执行，行为零变化。
# 加新表：按域加入对应常量（或新建常量），并在 init_db 补 executescript。
_SQL_CORE_TABLES = """
CREATE TABLE IF NOT EXISTS players (
                qq_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                gold INTEGER DEFAULT 0,
                hp INTEGER,
                mp INTEGER,
                max_hp INTEGER,
                max_mp INTEGER,
                cur_map TEXT DEFAULT 'vila',
                cur_subarea TEXT DEFAULT '',
                equipment TEXT DEFAULT '{}',
                skills TEXT DEFAULT '[]',
                class_tier INTEGER DEFAULT 0,
                attr_pts INTEGER DEFAULT 0,
                attributes TEXT DEFAULT '{"str":0,"agi":0,"int":0,"vit":0}',
                skill_points INTEGER DEFAULT 0,
                learned_skills TEXT DEFAULT '[]',
                hidden_class_unlock TEXT DEFAULT '[]',
                shortcuts TEXT DEFAULT '{}',
                evolve_path INTEGER DEFAULT 0,
                skill_levels TEXT DEFAULT '{}',
                learned_blueprints TEXT DEFAULT '[]',
                lucky_until INTEGER DEFAULT 0,
                stamina INTEGER DEFAULT 100,
                stamina_ts INTEGER DEFAULT 0,
                created_at INTEGER,
                last_active INTEGER,
                race TEXT DEFAULT 'human',
                gender TEXT DEFAULT '',
                faction TEXT DEFAULT '',
                battle_prefs TEXT DEFAULT '{}',
                investigate_date TEXT DEFAULT '',
                investigate_count INTEGER DEFAULT 0
            );CREATE TABLE IF NOT EXISTS inventory (
                qq_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_data TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                PRIMARY KEY (qq_id, item_key)
            );CREATE TABLE IF NOT EXISTS quests (
                qq_id TEXT PRIMARY KEY,
                main_quest TEXT,
                main_status TEXT DEFAULT 'pending',
                main_progress TEXT DEFAULT '{}',
                daily TEXT DEFAULT '{}',
                completed_main TEXT DEFAULT '[]',
                side TEXT DEFAULT '{}'
            );CREATE TABLE IF NOT EXISTS battle_state (
                qq_id TEXT PRIMARY KEY,
                monster TEXT NOT NULL,
                state TEXT NOT NULL,
                updated_at INTEGER
            );CREATE TABLE IF NOT EXISTS achievements (
                qq_id TEXT NOT NULL,
                ach_key TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                claimed INTEGER DEFAULT 0,
                PRIMARY KEY (qq_id, ach_key)
            );CREATE TABLE IF NOT EXISTS stats (
                qq_id TEXT PRIMARY KEY,
                kills INTEGER DEFAULT 0,
                elite_kills INTEGER DEFAULT 0,
                boss_kills INTEGER DEFAULT 0,
                deaths INTEGER DEFAULT 0,
                day_kills INTEGER DEFAULT 0,
                day_date TEXT DEFAULT '',
                visited_areas INTEGER DEFAULT 0,
                inst_clears INTEGER DEFAULT 0,
                party_count INTEGER DEFAULT 0,
                fish_count INTEGER DEFAULT 0,
                gather_count INTEGER DEFAULT 0,
                mine_count INTEGER DEFAULT 0,
                cook_count INTEGER DEFAULT 0,
                alchemy_count INTEGER DEFAULT 0,
                craft_count INTEGER DEFAULT 0,
                enhance_count INTEGER DEFAULT 0,
                enchant_count INTEGER DEFAULT 0,
                world_events INTEGER DEFAULT 0,
                catch_collect INTEGER DEFAULT 0,
                chests_opened INTEGER DEFAULT 0
            );CREATE TABLE IF NOT EXISTS reputation (
                qq_id TEXT NOT NULL,
                faction TEXT NOT NULL,
                points INTEGER DEFAULT 0,
                PRIMARY KEY (qq_id, faction)
            );CREATE TABLE IF NOT EXISTS signin (
                qq_id TEXT PRIMARY KEY,
                last_date TEXT DEFAULT '',
                streak INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0
            );CREATE TABLE IF NOT EXISTS props_use (
                qq_id TEXT PRIMARY KEY,
                used TEXT DEFAULT '{}'
            );CREATE TABLE IF NOT EXISTS fishing (
                qq_id TEXT PRIMARY KEY,
                total INTEGER DEFAULT 0
            );CREATE TABLE IF NOT EXISTS bestiary (
                qq_id TEXT NOT NULL,
                monster TEXT NOT NULL,
                kills INTEGER DEFAULT 0,
                PRIMARY KEY (qq_id, monster)
            );CREATE TABLE IF NOT EXISTS visited (
                qq_id TEXT NOT NULL,
                map_id TEXT NOT NULL,
                PRIMARY KEY (qq_id, map_id)
            );CREATE TABLE IF NOT EXISTS visited_subareas (
                qq_id TEXT NOT NULL,
                map_id TEXT NOT NULL,
                sa_id TEXT NOT NULL,
                first_at INTEGER,
                PRIMARY KEY (qq_id, map_id, sa_id)
            );CREATE TABLE IF NOT EXISTS player_groups (
                qq_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                first_seen INTEGER,
                last_active INTEGER,
                PRIMARY KEY (qq_id, group_id)
            );CREATE TABLE IF NOT EXISTS possessed (
                qq_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                got_at INTEGER,
                PRIMARY KEY (qq_id, item_key)
            );"""

_SQL_SOCIAL_TABLES = """
CREATE TABLE IF NOT EXISTS world_event (
                id INTEGER PRIMARY KEY,
                etype TEXT NOT NULL,
                starts_at INTEGER,
                ends_at INTEGER,
                data TEXT DEFAULT '{}'
            );CREATE TABLE IF NOT EXISTS event_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );CREATE TABLE IF NOT EXISTS market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                seller TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_data TEXT NOT NULL,
                price INTEGER NOT NULL,
                listed_at INTEGER
            );CREATE TABLE IF NOT EXISTS party (
                group_id TEXT NOT NULL,
                leader TEXT NOT NULL,
                member TEXT NOT NULL,
                created_at INTEGER,
                PRIMARY KEY (group_id, member)
            );CREATE TABLE IF NOT EXISTS guilds (
                gid INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                leader TEXT NOT NULL,
                icon TEXT DEFAULT '🏰',
                desc TEXT DEFAULT '',
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                created_at INTEGER
            );CREATE TABLE IF NOT EXISTS guild_members (
                gid INTEGER NOT NULL,
                qq_id TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                joined_at INTEGER,
                contribute INTEGER DEFAULT 0,
                sign_date TEXT DEFAULT '',
                task_date TEXT DEFAULT '',
                task_progress INTEGER DEFAULT 0,
                PRIMARY KEY (gid, qq_id)
            );CREATE TABLE IF NOT EXISTS pets (
                qq_id TEXT PRIMARY KEY,
                pet_key TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                satiety INTEGER DEFAULT 100,
                bond INTEGER DEFAULT 0,
                last_sat_time INTEGER DEFAULT 0
            );CREATE TABLE IF NOT EXISTS pet_dex (
                qq_id TEXT NOT NULL,
                pet_key TEXT NOT NULL,
                hatched INTEGER DEFAULT 0,
                PRIMARY KEY (qq_id, pet_key)
            );CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qq_id TEXT NOT NULL,
                group_id TEXT DEFAULT '',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                reply TEXT DEFAULT ''
            );"""

_SQL_PROF_TABLES = """
CREATE TABLE IF NOT EXISTS professions (
                qq_id TEXT PRIMARY KEY,
                gather_lv INTEGER DEFAULT 1,
                gather_exp INTEGER DEFAULT 0,
                mining_lv INTEGER DEFAULT 1,
                mining_exp INTEGER DEFAULT 0,
                fishing_lv INTEGER DEFAULT 1,
                fishing_exp INTEGER DEFAULT 0,
                alchemy_lv INTEGER DEFAULT 1,
                alchemy_exp INTEGER DEFAULT 0,
                craft_lv INTEGER DEFAULT 1,
                craft_exp INTEGER DEFAULT 0,
                cooking_lv INTEGER DEFAULT 1,
                cooking_exp INTEGER DEFAULT 0,
                enhance_lv INTEGER DEFAULT 1,
                enhance_exp INTEGER DEFAULT 0,
                enchant_lv INTEGER DEFAULT 1,
                enchant_exp INTEGER DEFAULT 0,
                fish_king INTEGER DEFAULT 0,
                explore_wandering INTEGER DEFAULT 0
            );"""

# ================= 平台身份映射（2026-09-07 QQ官方 bot 迁移）=================
# 场景：AstrBot 从 NapCat(OneBot/QQ号体系) 切到 QQ 官方 API(botpy/openid 体系)。
# 官方 API 只给 openid，不给 QQ 号 → dragonfall 玩家表仍以 QQ 号为主键，
# 建 openid ↔ qq_id 双向映射，命令层拿到 openid 时翻译回 QQ 号（改库/改命令皆不用动）。
_SQL_IDENTITY_TABLES = """
CREATE TABLE IF NOT EXISTS identity_map (
                openid TEXT PRIMARY KEY,
                qq_id TEXT NOT NULL,
                platform TEXT DEFAULT 'qq_official',
                bind_time INTEGER DEFAULT 0
            );
CREATE INDEX IF NOT EXISTS idx_identity_qq ON identity_map(qq_id);"""


def _ensure_legacy_columns(conn):
    """老库 ALTER 补列自愈。

    「PRAGMA 查缺 → ALTER 补」的**机制**在框架 `saintess_engine.store.ensure_columns`；
    此处只列**本游戏**要补的列（列定义与历史注释保留，便于追溯是哪一版加的）。
    """
    # players 表（列随版本演进，逐条注明出处）
    ensure_columns(conn, "players", {
        "class_tier": "INTEGER DEFAULT 0",                       # 转职系统
        "attr_pts": "INTEGER DEFAULT 0",
        "attributes": "TEXT DEFAULT '{\"str\":0,\"agi\":0,\"int\":0,\"vit\":0}'",
        "skill_points": "INTEGER DEFAULT 0",
        "learned_skills": "TEXT DEFAULT '[]'",
        "hidden_class_unlock": "TEXT DEFAULT '[]'",
        "portals": "TEXT DEFAULT '[]'",
        "skill_bar": "TEXT DEFAULT '[]'",
        "skill_spent": "INTEGER DEFAULT 0",
        "shortcuts": "TEXT DEFAULT '{}'",
        "explore_wandering": "INTEGER DEFAULT 0",
        "evolve_path": "INTEGER DEFAULT 0",
        "skill_levels": "TEXT DEFAULT '{}'",
        "mounts": "TEXT DEFAULT '{}'",
        "learned_blueprints": "TEXT DEFAULT '[]'",
        "lucky_until": "INTEGER DEFAULT 0",
        "investigate_date": "TEXT DEFAULT ''",                   # v140 波2：副本通关后调查
        "investigate_count": "INTEGER DEFAULT 0",
        "stamina": "INTEGER DEFAULT 100",                        # v94 体力系统
        "stamina_ts": "INTEGER DEFAULT 0",
        "race": "TEXT DEFAULT 'human'",                          # 阶段九 种族系统
        "gender": "TEXT DEFAULT ''",                             # v95.24 性别系统
        "battle_prefs": "TEXT DEFAULT '{}'",                     # v139 职业融合：战前指令偏好
        "equipped_title": "TEXT DEFAULT ''",                     # 阶段九 成就系统
        "deed_lv": "INTEGER DEFAULT 1",                          # v84 房屋升级
        "cur_subarea": "TEXT DEFAULT ''",                        # v86 子区域
        "world_id": "TEXT DEFAULT 'mainland'",                   # v141 大陆隔离
        "apprentices": "TEXT DEFAULT '[]'",                      # 导师进修
        "deed": "TEXT DEFAULT ''",                               # v68 地契
        "faction": "TEXT DEFAULT ''",                            # v116 阵营国战
    })
    # stats 表：阶段九成就系统的计数列
    ensure_columns(conn, "stats", {
        c: "INTEGER DEFAULT 0" for c in (
            "visited_areas", "inst_clears", "party_count", "fish_count", "gather_count",
            "mine_count", "cook_count", "alchemy_count", "craft_count", "enhance_count",
            "enchant_count", "world_events", "catch_collect", "chests_opened",
        )
    })
    # feedback 表：意见回复
    ensure_columns(conn, "feedback", {"reply": "TEXT DEFAULT ''"})
    # market 表 v66 摆摊：'' = 群市场寄售；有值 = 在该地图摆摊
    ensure_columns(conn, "market", {"map_id": "TEXT DEFAULT ''"})
    # professions 表：v67 双副业 activated + 导师进修 enhance/enchant 独立副业
    ensure_columns(conn, "professions", {
        "activated": "TEXT DEFAULT '[]'",
        "enhance_lv": "INTEGER DEFAULT 1",
        "enhance_exp": "INTEGER DEFAULT 0",
        "enchant_lv": "INTEGER DEFAULT 1",
        "enchant_exp": "INTEGER DEFAULT 0",
    })
    # pets 表：24 章宠物系统——饱食度自然衰减时间戳
    ensure_columns(conn, "pets", {"last_sat_time": "INTEGER DEFAULT 0"})


# ================= 建表注册（框架按注册序 executescript）=================
def install(db):
    """把 4 段 DDL + 老库补列迁移器注册到**注入的连接骨架**上（宿主工厂调一次；幂等）。"""
    db.register_schema("core", _SQL_CORE_TABLES)
    db.register_schema("social", _SQL_SOCIAL_TABLES)
    db.register_schema("professions", _SQL_PROF_TABLES)
    db.register_schema("identity", _SQL_IDENTITY_TABLES)
    db.register_migration(_ensure_legacy_columns)
    flush_log("persistence.schema：已注册 4 段 DDL + 迁移器（db=%s）" % _db_path_of(db))
    return db


def _db_path_of(db):
    return getattr(db, "path", "?")
