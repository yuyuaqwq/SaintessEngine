# -*- coding: utf-8 -*-
"""包内副本战斗行动路由实现（`content/cmds_instance_router.py`）—— B18-L5 **整块搬包**（2026-09-14）。

真源：宿主 `game/commands/instance_router.py`（492 行，`class InstanceRouterCmds`）。
本模块 = 那个类的**实现本体**（入口 `_instance_router` + 轮转/结算/展示助手，逐字搬成
`class InstanceRouterImpl`：类体缩进 / 注释 / docstring 一行未改）。

宿主侧现在只剩：包加载口 + 再导出（`InstanceRouterCmds = InstanceRouterImpl`，既有 import 点
零改动）+ 模块常量 `INSTANCE_TIMEOUT` + 文案接线登记（`_ROUTER_TEXT_KEYS`，供
`tests/test_texts_table.py` 的「声明 ↔ 调用点」双向对账）。宿主里**零 `T.text/T.static`
调用点**（B18 §3 验收线：渲染进包）。

搬的边界（正文改动面只有「宿主取件」一类，其余逐字）
----------------------------------------------------
| 真源写法 | 包内替身 |
|---|---|
| `from .. import content as C` | `C = _HostMod("content")` |
| `from .. import db` | `db = _HostMod("db")` |
| `from ..core import texts as T` | `T = _HostMod("core.texts")`（文案唯一真源 `game/data/text_specs.json`） |
| `from ..content_rules.skills import skill_info` | `skill_info = _HostFn("content_rules.skills", "skill_info")` |
| `from . import instance_battle as IB` | `IB = _HostMod("commands.instance_battle")`（宿主薄壳：编排在包、宿主耦合回调在宿主 → 必须走宿主面） |
| `from .. import tlog_setup as _tlog`（函数内） | `_tlog = _HostMod("tlog_setup")`（模块级，调用时解析） |
| `from content.mech.kinds import K_HEAL, K_BUFF`（函数内） | 原样保留（改相对 `.mech.kinds`，同一模块） |

替身写法与 `content/instance_cmds.py` / `content/world_cmds.py` **同款**（注入优先 → `sys.modules`
→ `importlib`；**绝不静默空跑**）。

包内直连（不再经宿主）
----------------------
`IR`（副本运行态适配层）→ 包内 `content/flow/instance_run.py` —— 与 `content/instance_cmds.py`
同源同款（B11-L2 已归包；宿主 `game/core/instance_run.py` 是**同名再导出壳**，逐名同一函数对象）。

I2 合规：包内不 import 宿主（替身在调用时解析）；`self` 侧玩法壳方法
（`_instance_defeat` / `_instance_victory` / `_instance_kill_reward` / `_instance_save` /
`_instance_battle_footer` / `_instance_current_members` / `_instance_map_view` /
`_instance_elite_scale` / `_find_skill_cfg` / `_unlock_battle` / `_player` …）由宿主
`class InstanceCmds` 的 MRO（`InstanceImpl` + 本类 + `CommandBase`）提供，与搬包前逐位等价。
"""
from __future__ import annotations

import importlib
import sys
import time

from .flow import instance_run as IR   # 包内直连（宿主 core.instance_run 是同名再导出壳）


# ============================================================
# 宿主替身口（写法照抄 content/instance_cmds.py）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = 替身要解析的名字。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("cmds_instance_router：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 from ..<mod> import <attr>」的同义替身（调用时解析）。"""
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
    """宿主模块替身（`C` / `db` / `T` / `IB`…）—— 正文 `X.attr` 一字未改。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


class _HostObj:
    """宿主对象惰性替身（函数/常量/类型）：`bind_host` 注入优先，否则调用时解析。"""

    def __init__(self, mod, attr):
        self._mod = mod
        self._attr = attr

    def _v(self):
        if self._attr in _INJECTED:
            return _INJECTED[self._attr]
        return _host_attr(self._mod, self._attr)

    def __repr__(self):
        return repr(self._v())


class _HostFn(_HostObj):
    """宿主函数替身（调用时解析）。"""

    def __call__(self, *a, **k):
        return self._v()(*a, **k)


C = _HostMod("content")                                     # 真源 `from .. import content as C`
db = _HostMod("db")                                        # 真源 `from .. import db`
T = _HostMod("core.texts")                                 # 真源 `from ..core import texts as T`
skill_info = _HostFn("content_rules.skills", "skill_info")  # 真源 `from ..content_rules.skills import skill_info`
IB = _HostMod("commands.instance_battle")                   # 真源 `from . import instance_battle as IB`
_tlog = _HostMod("tlog_setup")                              # 真源 `from .. import tlog_setup as _tlog`

__all__ = ["InstanceRouterImpl", "INSTANCE_TIMEOUT"]
INSTANCE_TIMEOUT = 60  # 副本行动超时（秒）——与 instance.py 模块常量同源（v101.30d 60s）


class InstanceRouterImpl:
    """副本战斗行动路由薄壳（saintess_engine 版，v3 §4.1-4.5 全逻辑）。"""

    # ------------------------------------------------------------------
    # 4.1 入口守卫 + 轮转
    # ------------------------------------------------------------------
    def _router_authoritative_st(self, st: dict) -> dict:
        """权威大陆实例 st：world_id=inst: 时优先取大陆实例（队友/自己可能已行动，
        大陆实例永远最新）；无大陆实例（测试/旧镜像）回落传入 st。"""
        _wid = (st or {}).get("world_id") or ""
        if _wid.startswith("inst:"):
            try:
                _live = C.get_instance_st(_wid)
                if _live is not None and not _live.get("_expired"):
                    return _live
            except Exception:
                pass
        return st

    def _router_no_enemy_hint(self, event, group_id, st):
        """肃清/无敌人引导（对应旧 _instance_act 2465-2483，读视图）。

        v185：句壳收口文案表 `instance.结算_无敌人_*`（本方法不再内联玩家可见文案）。
        """
        if st.get("stage_pending"):
            return event.plain_result(T.static("instance.结算_无敌人_探索"))
        stages = st.get("inst_stages") or []
        idx = st.get("stage_idx", 0)
        if stages and idx < len(stages) - 1:
            nxt = T.text("instance.结算_无敌人_下一层", name=stages[idx + 1]["name"])
        else:
            nxt = T.static("instance.结算_无敌人_最后一层")
        return event.plain_result(T.text("instance.结算_无敌人_已肃清", nxt=nxt))

    def _router_wait_hint(self, event, group_id, st, cur_key):
        members = st.get("members") or []
        try:
            st["turn"] = members.index(cur_key)
        except Exception:
            st["turn"] = 0
        cur_name = (self._player(group_id, cur_key) or {}).get("name", cur_key)
        return event.plain_result(T.text("instance.结算_等待行动", name=cur_name))

    # ------------------------------------------------------------------
    # 4.4 结算辅助（薄壳；账务 5b 完善）
    # ------------------------------------------------------------------
    def _router_collect_killed(self, st: dict, since_prev: bool = False) -> list:
        """battle killed（uid 累计）→ 死亡敌人单位 dict 列表。

        v3 §4.4 死亡账：saintess_engine 击杀记录（state.killed uid）转玩法壳消费的
        单位快照（st[\"_last_killed\"]/击杀任务）。死亡 actor 不从 sides 移除
        （只进 killed），因此从 enemy side 按 uid 取 hp<=0 的 actor 快照。
        副本内 state.killed 为整场累计；玩家行动一段只消费新增段（上一段
        已入账的过滤由调用方控制——见 _router_advance_killed）。
        """
        _b = st.get("battle") or {}
        uids = set(_b.get("killed") or [])
        out = []
        for a in (IB._enemies_of(st) or []):
            if a.get("uid") in uids and int(a.get("hp", 1) or 0) <= 0:
                out.append(dict(a))
        return out

    def _router_snapshot_killed(self, st: dict) -> set:
        """记录当前 battle killed uid 集合（用于 diff 本刻新增死亡）。"""
        _b = st.get("battle") or {}
        return set(_b.get("killed") or [])

    def _router_advance_killed(self, st: dict, prev_killed: set) -> list:
        """本刻新增死亡敌人 → 玩法壳账（st[\"_last_killed\"] 单刻语义）。

        对齐旧 compact：_last_killed = 本刻死亡（新死亡单位），供
        _instance_kill_reward（读 _last_killed）/ _instance_victory 兜底
        （读 _last_killed 找 Boss）。整场累计 killed 与上段快照 diff。
        """
        _b = st.get("battle") or {}
        cur_uids = set(_b.get("killed") or [])
        new_uids = cur_uids - (prev_killed or set())
        if not new_uids:
            return []
        units = []
        for a in (IB._enemies_of(st) or []):
            if a.get("uid") in new_uids and int(a.get("hp", 1) or 0) <= 0:
                units.append(dict(a))
        if units:
            st["_last_killed"] = units
            st["killed_enemies"] = []  # compact 语义：单刻账已并入 _last_killed
        return units

    def _router_has_living_players(self, group_id, st) -> bool:
        """当前在场且存活玩家 ≥1（v185：存活/血量口径委托 instance_run.living_players，
        在场过滤仍走 _instance_current_members —— 签名与语义逐字保留）。"""
        _live = set(IR.living_players(st))
        return any(k in _live for k in self._instance_current_members(group_id, st))

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def _instance_router(self, event, group_id, qq_id, player, st,
                               action, skill_name=None, target=None):
        """副本刻行动（saintess_engine 版）——v3 蓝图 §4.1-4.5 全逻辑新写。

        参数/协议对齐旧 _instance_act（CombatCmds 接线点 R2 改调本方法）。
        返回 async generator：yield event.plain_result(...) 文本。
        """
        from .mech.kinds import K_HEAL, K_BUFF   # B14 收口：原 ..data.kinds
        # 嘲讽强制剩余帧递减（每玩家行动帧；到 0 清强制回正常仇恨）
        _tl = int(st.get("taunt_left", 0) or 0)
        if _tl > 0:
            st["taunt_left"] = _tl - 1
            if st["taunt_left"] <= 0:
                st.pop("taunt_target", None)
                try:
                    yield event.plain_result(T.static("instance.结算_嘲讽结束"))
                except Exception:
                    pass
        # 4.1a 权威 st（大陆实例优先）
        st = self._router_authoritative_st(st)

        # 4.1b 懒构建 battle state（遭遇/切怪点若未 build_battle——R3 前过渡态）
        # R4 修复：battle sides 敌 uid 与视图 enemies uid 不一致（切房/新怪入场只更新
        # 视图、残留上一场 sides 打旧尸体死循环）→ 强制重建
        _b = st.get("battle") or {}
        _need_build = False
        if not _b.get("sides"):
            _need_build = True
        elif st.get("enemies"):
            _b_uids = {str(u.get("uid") or "") for u in
                       ((_b.get("sides") or {}).get("enemy") or [])}
            _v_uids = {str(u.get("uid") or "") for u in st.get("enemies")}
            if _b_uids != _v_uids:
                _need_build = True
        if _need_build:
            # 无敌人视图 → 肃清引导（不 build）
            if not (st.get("enemies") or []):
                yield self._router_no_enemy_hint(event, group_id, st)
                return
            try:
                IB.build_battle(st)
            except Exception:
                yield event.plain_result(T.static("instance.结算_战斗异常"))
                return

        # 4.1c 无敌人（视图空——战斗中途被肃清完）→ 引导
        if not (st.get("enemies") or []):
            yield self._router_no_enemy_hint(event, group_id, st)
            return

        # 当前成员/存活前置
        members = st.get("members") or []
        now = int(time.time())
        logs = []

        # ---- 1. 轮转：谁该行动（存活玩家 ct 最小者）+ 超时自动防御 ----
        # 对应旧 2494-2521；超时自动防御 = 对非请求超时者调 act("defend")（v3 4.1）
        guard = 0
        while True:
            guard += 1
            if guard > 20:  # 防死循环保险（多 AFK 消化上限）
                break
            cur_key = IB.next_actor_key(st)
            if cur_key is None:
                # 无存活玩家 → 失败结算
                st["over"] = True
                async for _r in self._instance_defeat(event, group_id, qq_id, player, st, logs):
                    yield _r
                return
            if str(cur_key) == str(qq_id):
                break
            # 非请求者：超时 → 自动防御；未超时 → 等待提示
            if now - int(st.get("turn_time", now) or now) > INSTANCE_TIMEOUT:
                _def_name = (self._player(group_id, cur_key) or {}).get("name", cur_key)
                logs.append(T.text("instance.日志_超时自动防御", name=_def_name))
                _dlogs, _dended, _dnxt = IB.act(st, group_id, cur_key, "defend")
                IB.sync_views(st, group_id)
                logs += _dlogs
                if _dended or not IB.next_actor_key(st):
                    break
                continue
            # 未超时 → 等待（含轮转到请求者前的等待提示）
            yield self._router_wait_hint(event, group_id, st, cur_key)
            return

        # 2. 确认轮到当前请求者；无存活玩家守卫（自动防御段可能全灭）
        if not self._router_has_living_players(group_id, st):
            st["over"] = True
            async for _r in self._instance_defeat(event, group_id, qq_id, player, st, logs):
                yield _r
            return
        cur_key = str(qq_id)
        try:
            st["turn"] = members.index(cur_key)
        except Exception:
            st["turn"] = 0
        st["turn_time"] = now

        # ---- 2.5 目标解析（heal/buff 已在 IB.act 内强制 None 防奶敌）----
        _tgt = target
        if action == "skill" and skill_name:
            try:
                _info = skill_info(player.get("class_name") or "", skill_name) or {}
            except Exception:
                _info = {}
            if _info.get("kind") in (K_HEAL, K_BUFF):
                _tgt = None

        # 行动前敌 hp 快照（账务 dealt：行动前后敌 hp 差）
        _prev_killed = self._router_snapshot_killed(st)
        try:
            _hp_before = sum(int(u.get("hp", 0) or 0) for u in IB._enemies_of(st))
        except Exception:
            _hp_before = 0
        try:
            _mem_before = sum(int((st.get("players") or {}).get(str(m), {}).get("hp", 0) or 0)
                              for m in members
                              if IR.alive_of(st, m))
        except Exception:
            _mem_before = 0

        # ---- 3. 行动（instance_battle.act：from_state → human_act → 落回）----
        act_logs, ended, _who = IB.act(st, group_id, qq_id, action, skill_name, target=_tgt)
        IB.sync_views(st, group_id)
        logs += act_logs

        # ---- 3.5 账务薄壳（v3 §4.3：dealt/仇恨；5b 基础 + v173.5 仇恨配置）----
        try:
            # v173.5：本次行动技能仇恨配置——hate_mult 伤害仇恨倍率（缺省 1）；
            # effect=taunt 嘲讽：仇恨=当前最高×hate_taunt_mult+100 + 强制锁
            _hm = 1.0
            _is_taunt = False
            _tmult = 3.0
            _tlock = 3
            if action == "skill" and skill_name:
                try:
                    _cfg = self._find_skill_cfg(player, skill_name) or {}
                    _hm = float(_cfg.get("hate_mult", 1.0) or 1.0)
                    if str(_cfg.get("effect", "")) == "taunt":
                        _is_taunt = True
                        _tmult = float(_cfg.get("hate_taunt_mult", 3.0) or 3.0)
                        _tlock = int(_cfg.get("hate_lock_turns", 3) or 3)
                except Exception:
                    pass
            _hp_after = sum(int(u.get("hp", 0) or 0) for u in IB._enemies_of(st))
            dealt = max(0, _hp_before - _hp_after)
            if dealt > 0:
                st.setdefault("contribution", {})
                st["contribution"][str(qq_id)] = st["contribution"].get(str(qq_id), 0) + dealt
                st.setdefault("threat", {})
                st["threat"][str(qq_id)] = st["threat"].get(str(qq_id), 0) + int(dealt * max(0.0, _hm))
            # 嘲讽（v173.5 数值模型：仇恨=当前最高×N+100，强制 taunt_target lock 帧）
            if _is_taunt:
                _th = st.setdefault("threat", {})
                _mx = max([float(v) for v in _th.values()] or [0.0])
                _th[str(qq_id)] = int(_mx * max(0.0, _tmult) + 100)
                st["taunt_target"] = str(qq_id)
                st["taunt_left"] = max(int(st.get("taunt_left", 0) or 0), max(1, _tlock))
                logs.append(T.static("instance.日志_嘲讽"))
            # 治疗仇恨（v49 语义基础：×0.8）
            _mem_after = sum(int((st.get("players") or {}).get(str(m), {}).get("hp", 0) or 0)
                             for m in members
                             if IR.alive_of(st, m))
            _heal = max(0, _mem_after - _mem_before)
            if _heal > 0:
                st.setdefault("threat", {})
                st["threat"][str(qq_id)] = st["threat"].get(str(qq_id), 0) + int(_heal * 0.8)
        except Exception:
            pass

        # ---- 4. 结算分支（v3 §4.4，读 actors/视图结果）----
        # 4a. 玩家倒地（本次行动/敌方段致死）→ 全员倒地失败 / 同归
        if not self._router_has_living_players(group_id, st):
            st["over"] = True
            if not (st.get("enemies") or []):
                logs.append(T.static("instance.日志_同归于尽"))
            async for _r in self._instance_defeat(event, group_id, qq_id, player, st, logs):
                yield _r
            return

        # 死亡账（本刻新增）——切怪/层清/通关结算前入 _last_killed
        self._router_advance_killed(st, _prev_killed)

        # 4b. 敌全灭（视图空——sync_views 已过滤死亡）→ 分层判定
        if not (st.get("enemies") or []):
            # 守卫（暗格精英守卫）→ 宝箱分支（不通关）
            if st.get("secret_guard_pending"):
                st["secret_guard_pending"] = False
                kill_lines = self._instance_kill_reward(group_id, st)
                # v185：清战斗视图回地图模式（暗格守卫标志差异显式写：secret_chest）
                IR.clear_battle_view(st, secret_chest=True)
                IR.clear_pet_hits(st)
                # 战斗结束 → 解锁 + 保存（玩法壳行为保留）
                for _m in st["members"]:
                    self._unlock_battle(group_id, _m)
                self._instance_save(group_id, st)
                yield event.plain_result(
                    "\n".join(logs) +
                    (("\n" + "\n".join(kill_lines)) if kill_lines else "") +
                    "\n━━━━━━━━━━━━\n" +
                    T.static("instance.结算_密室_守卫败退") + "\n" +
                    T.static("instance.结算_密室_调查宝箱")
                )
                return

            # dungeon rooms（v137 副本地图化）：Boss 房通关 / 普通房回地图
            if st.get("rooms"):
                cur_sa = ""
                try:
                    cur_sa = (self._player(group_id, st.get("leader") or "") or {}).get("cur_subarea", "") or ""
                except Exception:
                    cur_sa = ""
                _rstate = (st.get("rooms") or {}).get(cur_sa) or {}
                _is_boss_r = bool(_rstate.get("_is_boss"))
                if not _is_boss_r:
                    try:
                        _dun_cfg = (C.MAP_BY_ID.get(st.get("inst_id") or "") or {}).get("dungeon") or {}
                        _is_boss_r = (_dun_cfg.get("boss_room") or "") == cur_sa
                    except Exception:
                        _is_boss_r = False
                _room_boss = _is_boss_r and (
                    IR.monsters_left(st, cur_sa) == 0 or bool(_rstate.get("_boss_room")))
                if _room_boss:
                    IR.mark_boss_room_done(st, cur_sa)
                # 同步大陆权威 st（rooms 同对象或镜像更新）
                try:
                    _wid = st.get("world_id") or ""
                    if _wid.startswith("inst:"):
                        _sa = C.get_instance_st(_wid)
                        if _sa is not None:
                            IR.mark_boss_room_done(_sa, cur_sa)
                except Exception:
                    pass
                # v185：清战斗视图回地图模式（房间形态标志差异显式写：stage_cleared/over）
                IR.clear_battle_view(st, stage_cleared=True, over=False)
                IR.clear_pet_hits(st)
                for _m in st["members"]:
                    self._unlock_battle(group_id, _m)
                self._instance_save(group_id, st)
                if _room_boss:
                    _st_final = st
                    try:
                        _wid2 = st.get("world_id") or ""
                        if _wid2.startswith("inst:"):
                            _st_final = C.get_instance_st(_wid2) or st
                    except Exception:
                        _st_final = st
                    async for _r in self._instance_victory(
                            event, group_id, qq_id, player, _st_final,
                            logs + [T.static("instance.面板_中心_击败Boss")]):
                        yield _r
                    return
                map_view = self._instance_map_view(st, group_id, qq_id)
                yield event.plain_result(
                    "\n".join(logs) +
                    (("\n" + "\n".join(self._instance_kill_reward(group_id, st))) if (st.get("_last_killed") or []) else "") +
                    "\n━━━━━━━━━━━━\n" +
                    T.text("instance.结算_肃清", name=cur_sa) + "\n" +
                    map_view + "\n" +
                    "━━━━━━━━━━━━\n" +
                    T.static("instance.结算_房间引导")
                )
                return

            # stages 副本：stage_pending 有怪 → 切下一只；否则层清/通关
            pending = st.get("stage_pending") or []
            stages = st.get("inst_stages") or []
            if pending:
                # 切下一只（build_battle 重新构造）
                kill_lines = self._instance_kill_reward(group_id, st)
                nxt = pending.pop(0)
                _boss = C.build_monster(nxt, {"id": st.get("inst_id"), "name": st.get("inst_id"), "area": "instance"})
                st["boss"] = _boss
                if nxt[2] == "elite":
                    self._instance_elite_scale(st, st["boss"])
                st["enemy"] = st["boss"]
                st["enemies"] = [st["boss"]]  # 切怪默认单怪；副本 minions 由 R3 组装
                st["_last_killed"] = []
                st["killed_enemies"] = []
                st["turn"] = 0
                st["turn_time"] = int(time.time())
                IR.clear_pet_hits(st)   # v185：切怪重置宠物命中（同 clear_pet_hits 语义）
                try:
                    IB.build_battle(st)
                    IB.sync_views(st, group_id)
                except Exception:
                    pass
                self._instance_save(group_id, st)
                yield event.plain_result(
                    "\n".join(logs) +
                    (("\n" + "\n".join(kill_lines)) if kill_lines else "") +
                    "\n━━━━━━━━━━━━\n" +
                    T.static("instance.结算_切怪_新怪") + "\n" +
                    self._instance_battle_footer(st, group_id) + "\n" +
                    T.text("instance.结算_轮到行动",
                           name=self._router_next_player_name(st, group_id))
                )
                return
            if stages:
                last = st.get("stage_idx", 0) >= len(stages) - 1
                if not last:
                    # 层肃清 → 地图模式
                    kill_lines = self._instance_kill_reward(group_id, st)
                    # v185：清战斗视图回地图模式（分层形态标志差异显式写：stage_cleared/over）
                    IR.clear_battle_view(st, stage_cleared=True, over=False)
                    IR.clear_pet_hits(st)
                    for _m in st["members"]:
                        self._unlock_battle(group_id, _m)
                    self._instance_save(group_id, st)
                    cur_name = stages[st.get("stage_idx", 0)]["name"]
                    nxt_name = stages[st.get("stage_idx", 0) + 1]["name"]
                    map_view = self._instance_map_view(st, group_id, qq_id)
                    yield event.plain_result(
                        "\n".join(logs) +
                        (("\n" + "\n".join(kill_lines)) if kill_lines else "") +
                        "\n━━━━━━━━━━━━\n" +
                        T.text("instance.结算_肃清", name=cur_name) + "\n" +
                        map_view + "\n" +
                        "━━━━━━━━━━━━\n" +
                        T.text("instance.结算_层前路", name=nxt_name)
                    )
                    return
            # 末层 / 无 stages → 通关
            st["over"] = True
            _tlog.emit("instance.clear", actor=qq_id, iid=str(st.get("inst_id") or ""),
                       first_clear=bool(st.get("first_clear")))
            _fc_cur = self._instance_current_members(group_id, st) or [str(st.get("leader") or "")]
            st["first_clear"] = not any(
                a.get("ach_key") == f"inst_clear_{st['inst_id']}" and a.get("progress", 0) >= 1
                for _m2 in _fc_cur
                for a in (db.get_achievements(group_id, _m2) or [])
            )
            async for _r in self._instance_victory(event, group_id, qq_id, player, st, logs):
                yield _r
            return

        # ---- 5. 未结束：收尾展示（v3 §4.5：footer + 轮到 X + 保存）----
        nxt_key = IB.next_actor_key(st)
        if nxt_key and nxt_key in members:
            st["turn"] = members.index(nxt_key)
        else:
            st["turn"] = 0
        st["turn_time"] = now
        self._instance_save(group_id, st)
        nxt_name = self._router_next_player_name(st, group_id, nxt_key)
        yield event.plain_result(
            "\n".join(logs) +
            "\n━━━━━━━━━━━━\n" +
            self._instance_battle_footer(st, group_id) + "\n" +
            T.text("instance.结算_轮到行动", name=nxt_name)
        )

    # ------------------------------------------------------------------
    # 展示辅助（轮转名——新写读 players 视图，不依赖旧 CT helpers）
    # ------------------------------------------------------------------
    def _router_next_player_name(self, st: dict, group_id: int, fallback_key=None) -> str:
        nxt = IB.next_actor_key(st)
        key = str(nxt) if nxt else (str(fallback_key) if fallback_key else str(st.get("members", [""])[0] or ""))
        return (st.get("players", {}).get(key, {}) or {}).get("name", key)
