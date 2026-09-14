# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/worlds.py`
# 搬运改动面**只有「宿主取件」**一类：`store.world`/`store.connection` 4 处 → 宿主句柄；`data` 的 MAP_BY_ID/SUBAREAS/INSTANCES → 宿主句柄
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年核心层 - worlds.py（v141 大陆隔离）

大陆（world）抽象：
- 主大陆 "mainland" = 全游戏静态地图共享（MAP_BY_ID）
- 副本大陆 "inst:<uuid>" = 开本时动态创建/销毁的独立大陆实例
  克隆副本地图为独立地图集，副本进度（rooms/resources_pool/队伍快照）
  挂在大陆实例上，不再挂在队长个人 battle_state 行。

存储：
- 内存态 instance_worlds（运行时读写快）
- 落库 event_state key = "instance_world_{world_id}"（重启防丢，
  惰性重建——首次访问时从 DB 恢复）

设计目标（docs/CONTINENT_ISOLATION_v141.md §2.3/§2.4）：
- 队伍问题从根消失（退队卡图/队长退队僵尸/撤退覆盖进度）
- 多队伍同本天然隔离（各自 inst:<uuid>）
"""
from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional
import importlib
import sys

# ============================================================
# ① 宿主替身口（B13-L2 搬包 2026-09-14；正文 `db.xxx(...)` / `C.xxx` 一行未改）
#    写法照抄包内 `content/world_cmds.py`（B9 线2）：注入优先 → sys.modules → importlib，
#    取不到**大声抛**（绝不静默空跑）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`db` / `content`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("B13-L2：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「`from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`db` / `C`）——`db.xxx` / `C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# ★ B14-2 L8（2026-09-14）：`create_instance_world` 克隆用的三张表切**包内门面**
#   （`deepcopy` 落地 → 与宿主表**身份无关**，只需内容相等；门禁逐值+键序 OK）。
#   `resolve_map_for` 的 MAP_BY_ID **仍走宿主句柄**：宿主 `tests/test_v141_instance_world.py:192`
#   按**对象身份**断言（`is C.MAP_BY_ID.get(...)`）—— 待主 agent 收口（`game/content.py` 改再导出
#   包内门面）时同批切，否则该断言红（实测见报告 §保留/阻塞）。
from . import catalog_space as _cs      # noqa: E402

# 运行时内存态：world_id -> {
#   "name": 副本名,
#   "inst_id": 副本配置 id（inst_goblin_camp）,
#   "maps": {map_id: map_def},      # 克隆的副本图
#   "subareas": {map_id: [sa...]},  # 克隆的子区域
#   "created_at": ts,
#   "leader": qq_id,                # 仅展示/带队，不承载状态
#   "members": [qq_id...],          # 进本快照（展示用）
#   "rooms": {...},                 # 怪池/资源池（v137 副本地图化）
#   "resources_pool": {...},        # 奖励总量
#   "st": {...},                    # 副本战斗状态快照（迁移自 battle_state）
#   "retreated": bool,              # 撤退保留进度标记
# }
instance_worlds: Dict[str, dict] = {}

EVENT_STATE_PREFIX = "instance_world_"


# ============================================================
# 内存态访问
# ============================================================


def get_instance_world(world_id: str) -> Optional[dict]:
    """获取大陆实例。内存没有则尝试从 DB 惰性恢复。"""
    if world_id not in instance_worlds:
        _restore_from_db(world_id)
    return instance_worlds.get(world_id)


def _restore_from_db(world_id: str) -> None:
    """重启后从 event_state 恢复大陆实例（惰性：首次访问才加载）。"""
    try:
        get_event_state = _host_attr("store.world", "get_event_state")
        raw = get_event_state(f"{EVENT_STATE_PREFIX}{world_id}")
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict):
                # P0-2（2026-08-30 审计）：老档/异常路径落库的 set 被 default=str 串化成
                # 字符串 → 重启恢复成字符集合 → 调查点重复刷奖。恢复后对 st.investigated
                # 做校验：str 尝试 ast.literal_eval 解析回 list，失败/非 list 重置为空 list。
                _st = data.get("st")
                if isinstance(_st, dict) and isinstance(_st.get("investigated"), str):
                    try:
                        import ast
                        _parsed = ast.literal_eval(_st["investigated"])
                        if not isinstance(_parsed, list):
                            _parsed = []
                    except Exception:
                        _parsed = []
                    _st["investigated"] = _parsed
                instance_worlds[world_id] = data
    except Exception:
        # DB 不可用/损坏 → 当作不存在，调用方自行兜底
        instance_worlds.pop(world_id, None)


# ============================================================
# 创建 / 销毁
# ============================================================


def create_instance_world(
    inst_id: str,
    members: List[int],
    boss: dict,
    now: Optional[int] = None,
    leader: Optional[int] = None,
    st: Optional[dict] = None,
    rooms: Optional[dict] = None,
    resources_pool: Optional[dict] = None,
) -> str:
    """开本：克隆副本地图为独立大陆。返回 world_id 'inst:<uuid>'。

    参数：
    - inst_id: 副本配置 id（inst_goblin_camp）
    - members: 进本成员 qq_id 列表
    - boss: 构建好的 Boss dict（血量已按人数缩放）
    - now: 当前时间戳（缺省取 time.time()）
    - leader: 队长 qq_id（缺省取 members[0]；仅展示，不承载状态）
    - st: 副本战斗状态快照（_instance_build_state 产物）
    - rooms / resources_pool: v137 副本地图化怪池/资源池
    """
    MAP_BY_ID = _cs.MAP_BY_ID            # B14-2 L8：包内空间门面（真源 `data.MAP_BY_ID`，逐值+键序 OK）
    SUBAREAS = _cs.SUBAREAS              # B14-2 L8：包内空间门面（真源 `data.SUBAREAS`）
    INSTANCES = _cs.INSTANCES            # B14-2 L8：包内空间门面（真源 `data.INSTANCES`）
    world_id = f"inst:{uuid.uuid4().hex[:12]}"
    map_id = inst_id[5:] if str(inst_id).startswith("inst_") else inst_id
    inst = INSTANCES.get(inst_id, {})
    _now = int(now if now is not None else time.time())
    _leader = str(leader if leader is not None else members[0])

    instance_worlds[world_id] = {
        "name": inst.get("name", map_id),
        "inst_id": inst_id,
        "maps": {map_id: deepcopy(MAP_BY_ID.get(map_id, {}))},
        "subareas": {map_id: deepcopy(SUBAREAS.get(map_id, []))},
        "created_at": _now,
        "leader": _leader,
        "members": [str(m) for m in members],
        "rooms": rooms or {},
        "resources_pool": resources_pool or {},
        "st": st,
        "retreated": False,
    }
    _persist(world_id)
    return world_id


def destroy_instance_world(world_id: str) -> None:
    """退本/通关/失败/过期：销毁大陆实例。"""
    instance_worlds.pop(world_id, None)
    try:
        delete_event_state = _host_attr("store.world", "delete_event_state")
        delete_event_state(f"{EVENT_STATE_PREFIX}{world_id}")
    except Exception:
        pass


def _json_ready(obj):
    """v116 兜底（store/battle_state 同构函数）：把 state 里可能残留的 Python set（如
    phase BOSS 的 _phase_warned / instance st 的 investigated）递归深转成 list，保证
    json.dumps 序列化不再抛 TypeError / 不再被 default=str 掩盖成字符串；其余类型原样返回。

    P0-2（2026-08-30 审计）：worlds._persist 原先用 json.dumps(default=str) 兜底，
    set 落库变成字符串，重启恢复成字符集合 → 调查点重复刷奖。本函数在写入前
    显式清洗，与 store/battle_state.py:11-20 的 _json_ready 逻辑保持一致。
    """
    if isinstance(obj, set):
        return [_json_ready(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(x) for x in obj]
    return obj


def _persist(world_id: str) -> None:
    """落库 event_state（重启防丢）。只落非战斗核心字段（st 也落，可恢复）。"""
    data = instance_worlds.get(world_id)
    if data is None:
        return
    try:
        set_event_state = _host_attr("store.world", "set_event_state")
        set_event_state(f"{EVENT_STATE_PREFIX}{world_id}",
                        json.dumps(_json_ready(data), ensure_ascii=False))
    except Exception:
        pass


def update_instance_world(world_id: str, **fields) -> None:
    """更新大陆实例字段（房间/资源池/队伍快照等）并落库。

    v141 审计（2026-08-30）：当前生产 0 消费（instance.py 直接改大陆 dict
    字段后经 _instance_save → set_instance_st 落库）；保留作公共 API
    （未来动态化/监控/运维可能按字段增量更新）。
    """
    data = instance_worlds.get(world_id)
    if data is None:
        return
    for k, v in fields.items():
        data[k] = v
    _persist(world_id)


def set_instance_st(world_id: str, st: Optional[dict]) -> None:
    """设置副本战斗状态快照（迁移自 battle_state 存队长 → 存大陆）。

    v141 消费方：instance.py（开本/_instance_save 落库 st）——生产活跃调用。
    """
    update_instance_world(world_id, st=st)


def get_instance_st(world_id: str) -> Optional[dict]:
    """取副本战斗状态快照。v141 消费方：instance.py（读大陆 st 恢复战斗）。"""
    data = get_instance_world(world_id)
    return (data or {}).get("st")


def list_instance_worlds() -> List[str]:
    """列出全部存活大陆实例 world_id（监控/清理用）。

    v141 审计（2026-08-30）：当前生产 0 消费；保留——监控/运维
    （查看未回收大陆实例、统计泄漏）是明确预期用途，删除会让排查手段缺失。
    """
    return list(instance_worlds.keys())


def cleanup_stale_instances(max_age_sec: int = 24 * 3600) -> int:
    """惰性回收过期大陆实例（24h 无活动）。返回清理数量。

    过期判定：created_at 距今超过 max_age_sec。两层清理：
    1. 内存 instance_worlds dict 轻扫（超龄 → destroy_instance_world，同时删 DB 键）；
    2. DB event_state 键扫描（key LIKE 'instance_world_%'，读 JSON 取 created_at，
       超龄则 delete_event_state）——覆盖进程重启后未惰性恢复的孤儿键
       （内存已无、DB 残留），防 event_state 表只增不删。

    注：store/world.py 的 _EVENT_STATE_PLAYER_PREFIXES 不扩——instance_world_ 键
    无内嵌 qq_id 可提取，玩家活跃度清理机制不匹配，扫描逻辑内聚在本函数。

    幂等（多实例/热重载安全）；轻量（仅一次 LIKE 查询 + 少量 JSON 解析），
    挂任意指令入口（base.py _maint_gate）与启动兜底（main.py）均不阻塞主流程。
    """
    now = int(time.time())
    cleaned = 0
    # 1. 内存 dict 轻扫（destroy 同时删内存 + DB 键）
    stale = []
    for wid, data in instance_worlds.items():
        created = int(data.get("created_at", 0) or 0)
        if created and now - created > max_age_sec:
            stale.append(wid)
    for wid in stale:
        destroy_instance_world(wid)
    cleaned += len(stale)
    # 2. DB event_state 孤儿键扫描（内存已无该 world_id 的 instance_world_* 键）
    try:
        _connect = _host_attr("store.connection", "_connect")
        _db_lock = _host_attr("store.connection", "_lock")
        delete_event_state = _host_attr("store.world", "delete_event_state")
        with _db_lock:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT key, value FROM event_state WHERE key LIKE ?",
                    (EVENT_STATE_PREFIX + "%",),
                ).fetchall()
            finally:
                conn.close()
        for r in rows:
            _k = r["key"]
            _wid = _k[len(EVENT_STATE_PREFIX):]
            if _wid in instance_worlds:
                continue  # 内存仍存活（未超龄）——不碰，避免误删活跃大陆
            _created = 0
            try:
                _data = json.loads(r["value"]) if isinstance(r["value"], str) else r["value"]
                _created = int((_data or {}).get("created_at", 0) or 0)
            except Exception:
                _created = 0  # JSON 损坏无法判定年龄 → 保守不删
            if _created and now - _created > max_age_sec:
                try:
                    delete_event_state(_k)
                    cleaned += 1
                except Exception:
                    pass
    except Exception:
        pass
    return cleaned


def resolve_map_for(world_id: str, map_id: str) -> Optional[dict]:
    """按世界解析地图（纯函数，供不持有 Position 的场景）。

    副本大陆实例优先（克隆图）；实例已销毁/不存在 → 返回 None
    （与原 C.MAP_BY_ID.get 语义区分：调用方需自行回退全局静态图）。
    """
    if world_id and world_id.startswith("inst:"):
        data = get_instance_world(world_id)
        if data is None:
            return None
        return data.get("maps", {}).get(map_id)
    MAP_BY_ID = _host_attr("data", "MAP_BY_ID")  # ★ 保留宿主句柄（B14-2 L8：身份断言未解，见文件头注）
    return MAP_BY_ID.get(map_id)
