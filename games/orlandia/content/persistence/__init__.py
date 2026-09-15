# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 存档层（B17 由宿主 `game/store/` 整体端口）。

形状与宿主旧 `game/store/__init__.py` **一致**（同名聚合导出，宿主 `db.xxx` 调用面不变）。
唯一差异：`DB_PATH` 不在包侧（库路径是部署信息，由宿主 `store_factory.py` 解析后**注入**
`handles`）—— 需要读路径时用 `handles.db_path()`。
"""
from .handles import (  # noqa: F401
    bind, db_path, clock, flush_log, lock, connect, atomic, init_db, get_db, set_db,
)
from .schema import C_MAP_IDS, _map_ids  # noqa: F401
from .players import (  # noqa: F401
    record_player_group, get_player_groups, get_group_players,
    create_player, get_player, find_player_by_name, update_player,
    top_players, all_players, get_portals, add_portal,
    get_skill_bar, set_skill_bar, delete_player,
)
from .inventory import (  # noqa: F401
    _key_to_id, add_item, get_inventory, count_item, remove_item,
    update_item_data, sell_item_atomic,
    record_possessed, record_possessed_conn,
    get_possessed, get_possessed_rows, count_possessed,
)
from .quests import get_quests, save_quests, expire_daily  # noqa: F401
from .battle_state import save_battle, get_battle, get_battle_raw, clear_battle  # noqa: F401
from .stats import (  # noqa: F401
    init_stats, bump_stats, get_stats, set_achievement, get_achievements,
)
from .professions import (  # noqa: F401
    get_professions, get_prof_level, add_prof_exp, prof_top,
    bump_fish_king, get_fish_king, PROF_FIELDS,
    MAX_ACTIVE_PROFS, get_activated_profs, activate_prof, forget_prof,
)
from .social import (  # noqa: F401
    add_reputation, get_reputation, get_signin, save_signin, signin_claim,
    market_list, market_add, market_remove,
    market_list_by_seller, market_get, market_sync_stall, market_remove_by_seller,
    market_buy_atomic, market_stall_sell_atomic, market_exchange_atomic,
    party_create, party_add, party_members, party_leave,
    guild_create, guild_get_by_leader, guild_get_by_member,
    guild_get_by_name, guild_members, guild_join, guild_leave,
    guild_add_exp, guild_set_sign, guild_get_sign,
    guild_set_task, guild_get_task, guild_top,
    pet_get, pet_create, pet_update, pet_delete,
    pet_decay_satiety, pet_dex_get, pet_dex_add,
)
from .world import (  # noqa: F401
    bump_fishing, get_fishing_total, bump_bestiary, get_bestiary,
    add_visited, get_visited_count, get_visited_maps, get_world_event, save_world_event,
    clear_world_event, get_event_state, set_event_state, delete_event_state,
    get_talk_state, set_talk_state, clear_talk_state, talk_state_key,
    get_talk_flags, set_talk_flag, get_boss_dmg_mult,
    cleanup_stale_event_state,
    home_storage_deposit_atomic, home_storage_take_atomic,
    add_visited_subarea, get_visited_subareas, count_visited_subareas,
    get_visited_subareas_rows,
)
from .feedback import (  # noqa: F401
    add_feedback, get_feedback,
)
from .props_use import (  # noqa: F401
    get_props_use, mark_props_use, props_use_claim_atomic,
)


def __getattr__(name):
    """模块级 `__getattr__`（PEP 562）—— 只补两个**旧宿主名的只读兼容读点**。

    ★ P5E-DELETE（2026-09-15，删壳批）：删壳后仍有测试读旧宿主 `game/db.py` 的两个模块级
    成员，本模块头注早已写明「库路径是部署信息、锁在 `handles`」：

    * `DB_PATH` —— 旧宿主模块级常量；包侧真源 = `handles.db_path()`（每次访问求值）。
      受影响（全删态实测 7 个文件）：commands_fishing · legacy_schema_migration ·
      f1_atomicity · store_concurrency · v116_props_daily · v87_12_props_effects ·
      v135_quality_roll。
    * `_lock` —— 旧宿主模块级重入锁；包侧真源 = `handles._lock`（`_LockProxy`，
      `handles.py:121`）。受影响：`tests/test_store_concurrency.py:56`
      （「锁内再进 store 不死锁」——本测试的判据对象就是这把锁本身）。

    处置口径：**不把库路径/锁变成包内状态**（那与 R2 的 fail-closed 设计相反），
    只提供同名兼容读（`DB_PATH` 未注入时照旧抛 RuntimeError —— fail-closed 语义一字不动）。
    ⇒ 测试侧一行都不用改，断言强度也不变。
    """
    if name == "DB_PATH":
        return db_path()
    if name == "_lock":
        from . import handles as _handles
        return _handles._lock
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
