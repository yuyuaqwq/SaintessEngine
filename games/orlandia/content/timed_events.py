# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/timed_events.py`
# 搬运改动面**只有「宿主取件」**一类：3 处函数内 `from .. import db` → 模块级 `db = _HostMod("db")`
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""奥兰迪亚·余烬纪年 core 层 — timed_events.py（v127.5 通用倒计时事件引擎）

把一切"限时存在 / 限时有效 / 到时触发"的玩家状态统一挂到懒计时引擎，
由任意玩家指令（_maint_gate 挂 refresh）惰性刷新，无后台定时器。

设计铁律：
- 数据驱动：新倒计时事件类型 = register_timed() + 各自读写封装，引擎零改动
- 懒计时：不跑定时器；读前 get_timed 校验 + 任意指令 refresh 物理清理
- 一致性：显示出口 + 查找出口都必须走 get_timed → 过期即不可见/不可找，
  不存在"过期还看得见"的窗口
- 存储：复用 event_state KV（一个玩家一个 key，内部 dict 多事件互不覆盖）
  key = timed_events:{qq_id}，value = JSON {"<type>:<sub>": {"type","data","expire"}}
- 纯核心：不碰 DB 以外 IO；宿主存储经 `db` 替身（B13-L2 搬包后，正文 `db.xxx` 一字未改）

=== 用法示例 ===

# 1. 注册事件类型（模块加载时一次）
register_timed("wild_npc", duration_sec=3600)   # 默认 60 分钟，可按 NPC 覆盖

# 2. 挂载/刷新一个事件（偶遇命中时）
expire = set_timed(group_id, qq_id, key="wild:w_old_trader",
                   type_key="wild_npc", data={"map": map_id})

# 3. 读取（显示/查找出口）——过期自动惰性清除返回 None
ev = get_timed(group_id, qq_id, key="wild:w_old_trader")
if ev:  # {"type","data","expire","remain"}
    ...

# 4. 删除（主动结束事件）
remove_timed(group_id, qq_id, key="wild:w_old_trader")

# 5. 强制刷新（挂 _maint_gate，任意玩家指令触发）
refresh_timed(group_id, qq_id)

# 6. 过期回调注册（可选）：on_expire(type_key)(group_id, qq_id, data) -> None
#    引擎在过期时调用，用于清状态（如对话会话作废）

【骨架归属（2026-09-11，M3）】引擎的**机制**（类型注册表 / 惰性过期 /
「get / list / refresh 三条路径都触发 on_expire」）来自框架
`saintess_engine.clock.LazyTimers`；本文件只留**本游戏的存储适配与对外 API**：
存储 key 格式、event_state 三件套、group_id 兼容签名。
"""
import json

from saintess_engine.clock import LazyTimers
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


db = _HostMod("db")     # 真源 3 处函数内 `from .. import db`（延迟 import 防循环）

# 玩家事件存储 key 模板（按玩家全局，跨群共享——倒计时只属于玩家本人）
_PLAYER_KEY = "timed_events_{qq_id}"


# ---------------------------------------------------------------- 存储适配
# 框架的 owner = 本游戏的 (group_id, qq_id)。用元组而非单值，是因为 on_expire
# 回调签名带 group_id（v127.5 起，如 wild_npc 过期要 db.clear_talk_state(group_id)）。
def _load(owner) -> dict:
    raw = db.get_event_state(_PLAYER_KEY.format(qq_id=owner[1]))
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save(owner, events: dict) -> None:
    db.set_event_state(_PLAYER_KEY.format(qq_id=owner[1]),
                       json.dumps(events, ensure_ascii=False))


def _remove_whole(owner) -> None:
    db.delete_event_state(_PLAYER_KEY.format(qq_id=owner[1]))


_timers = LazyTimers(load=_load, save=_save, remove=_remove_whole)


# ------------------------------------------------------------------ 对外 API
def register_timed(type_key: str, duration_sec: int | None = None,
                   on_expire=None) -> None:
    """注册/覆盖一个倒计时事件类型。duration_sec 默认秒数（set_timed 未传时用）。

    `on_expire(group_id, qq_id, data) -> None`：该类型的实例过期被清理时调用
    （get / list / refresh 三条路径都会走到，读路径不得绕过）。
    """
    if on_expire is None:
        _timers.register(type_key, duration_sec=duration_sec)
        return

    def _adapted(owner, data):
        group_id, qq_id = owner
        return on_expire(group_id, qq_id, data)

    _timers.register(type_key, duration_sec=duration_sec, on_expire=_adapted)


def set_timed(group_id: str, qq_id: str, key: str, type_key: str,
              data: dict | None = None,
              duration_sec: int | None = None) -> int:
    """挂载/刷新一个倒计时事件，返回 expire 时间戳。

    - 同 key 重复挂载 = 顶替刷新（新 expire）
    - 默认时长取类型注册值；未注册类型默认 60s（防御，正常都会 register）
    """
    return _timers.set((group_id, qq_id), key, type_key,
                       data=data, duration_sec=duration_sec)


def get_timed(group_id: str, qq_id: str, key: str) -> dict | None:
    """读取单个事件：未过期返回 {type,data,expire,remain}；过期惰性清除返回 None。

    所有显示/查找出口都必须走这里 → 过期即不可见（惰性正确性核心）。
    过期清除前同样触发 on_expire（读路径不得绕过数据保全回调）。
    """
    return _timers.get((group_id, qq_id), key)


def remove_timed(group_id: str, qq_id: str, key: str) -> bool:
    """主动删除一个事件（返回是否删掉了）"""
    return _timers.remove((group_id, qq_id), key)


def list_timed(group_id: str, qq_id: str, type_key: str | None = None,
               data_match: dict | None = None) -> list:
    """列出未过期事件（可选按 type / data 过滤），顺带惰性清除过期项。

    data_match：data 子集匹配（如 {"map": "oak_plain"} → 只留在该图的事件）
    返回 [{"key","type","data","expire","remain"}, ...]
    """
    return _timers.items((group_id, qq_id), type_key=type_key, data_match=data_match)


def refresh_timed(group_id: str, qq_id: str) -> int:
    """惰性全量刷新：扫该玩家所有事件，过期的执行 on_expire 回调 + 物理删除。

    返回清理的过期事件数（供测试断言）。
    - on_expire(type_key)(group_id, qq_id, data)：清理副作用（如会话作废）
    - 无回调的过期事件仅物理删除（静默）
    """
    return _timers.refresh((group_id, qq_id))
