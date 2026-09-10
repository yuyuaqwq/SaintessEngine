# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - battle_bars.py（v181 通用挂敌身条 / 蓄力三律）

把《云海猎团》职业融合提炼的 2 个通用机制实现为纯函数模块：
1. enemy_bar  挂敌身资源条（拳师破绽 shaken / 暗影神谕诅咒 curse）
   —— 积蓄挂在敌方身上，**容器 = actor.effects（V 系列统一单容器）**，
      键 = `data/battle2_rules.BAR_STATE_PREFIX + bar_key`（如 `bar:shaken`）；
      独立于异常免疫，阈值递增防无限控、触发后免疫窗口、
      阶段转换保留部分进度
2. charge     蓄力三律（游侠电荷 / 弓手 / 时咒）
   —— 边攒边打出伤、打断仅 -1 阶不清零（P3）、满阶强制释放

时间制（v181 破绽改造）：
- 积蓄/衰减**按刻连续结算**（`bar_settle(host, key, now)`：dt × decay_per_turn，
  val 内部小数、展示取整），不再「每个宿主行动扣一次」
- 免疫窗口 = **绝对时刻**（`immune_until`）：期内不积蓄、不触发，到期即可再触发
- 所有公开 API 接受可选 `now`（`battle._now` 口径）；传了才结算/才受免疫约束，
  不传 = 纯读写（序列化检查、静态探针等无时钟上下文）

数据驱动铁律：
- 不写任何职业特判（不出现 class_name 字符串比较）
- 所有数值从 battle_config ENEMY_BAR_CFG / CHARGE_CFG 读（或调用方传入）
- 无配置 = 默认不启用
- 状态存 actor.effects 命名空间键（随战斗序列化）

⚠️ 条条目不带 `stacks` / `stat` / `mult` / `mode` / `expire` / `period`——
避开 effects 容器的四种自动化（到期清理 / 周期跳 / 面板折算 / 控制消费），
见 tests/test_numeric_bar_decay.py 容器安全断言。

S3 通用件归位（docs/ENGINE_CONTENT_SPLIT_PLAN.md §6.5 / §7-S3）：
本体自 game/core/battle_bars.py 迁入引擎（game/battle2/support/），**读点改 config
注入面**——`config.mech_cfg(name)` / `config.bar_prefix()` 由内容侧装配
（game/bootstrap.py）注入，引擎零 game.data import（门禁 test_engine_no_content.py）。
（S3 前这里是 importlib 延迟直读 data.battle_config/data.battle2_rules——
既为避 core ↔ data 循环导入，也是引擎反向依赖的一条边。）
"""
from math import ceil, floor

from .. import config as _bcfg


def _battle_cfg(name: str) -> dict:
    """读取机制配置表 MECH_CFG[机制键]（内容侧 config 注入；未装配 → {}）。"""
    try:
        return _bcfg.mech_cfg(name) or {}
    except Exception:
        return {}


def _cfg(cfg: dict, key, default=None):
    if not isinstance(cfg, dict):
        return default
    return cfg.get(key, default)


def _state_prefix() -> str:
    """条状态在 effects 容器里的键前缀（内容侧 config 注入；未装配 → 历史兜底 "bar:"）。"""
    try:
        return _bcfg.bar_prefix() or "bar:"
    except Exception:
        return "bar:"


def bar_effect_key(bar_key: str) -> str:
    """条 → effects 容器键（如 shaken → bar:shaken）。"""
    return _state_prefix() + str(bar_key)


# ============================================================
# 一、enemy_bar 挂敌身资源条（时间制）
# ============================================================

def bar_def(bar_key: str) -> dict:
    """读取 bar 类型配置（ENEMY_BAR_CFG[bar_key]），无则 {}。"""
    cfg = _battle_cfg("enemy_bar").get(bar_key) if isinstance(_battle_cfg("enemy_bar"), dict) else None
    return cfg or {}


def bar_state(enemy: dict, bar_key: str, now: float | None = None) -> dict:
    """读取敌方 bar 状态（enemy.effects[bar:<key>]），无则初始化。

    结构：{"val": 0.0, "threshold": N, "trigger_count": 0, "_at": 时刻,
           "immune_until": 0.0}
      val           积蓄（float；展示 int()）
      threshold     当前阈值（触发后 ×threshold_inc，封顶 ×threshold_cap）
      trigger_count 触发次数
      _at           上次结算时刻（时间结息基准）
      immune_until  免疫窗口截止时刻（0.0 = 不在免疫）
    """
    ef = enemy.get("effects")
    if not isinstance(ef, dict):
        ef = {}
        enemy["effects"] = ef
    ekey = bar_effect_key(bar_key)
    bs = ef.get(ekey)
    if not isinstance(bs, dict):
        bd = bar_def(bar_key)
        bs = {
            "val": 0.0,
            "threshold": int(bd.get("threshold_base", 50) or 0),
            "trigger_count": 0,
            "_at": float(now or 0.0),
            # 初始免疫窗口 = 0（免疫只在触发后由 bar_trigger 设置）
            "immune_until": 0.0,
        }
        ef[ekey] = bs
    return bs


def bar_settle(enemy: dict, bar_key: str, now: float, logs: list | None = None) -> dict:
    """把条结算到 now：免疫到期出窗 + 积蓄按 dt 连续衰减（幂等）。

    蓄积衰减 = dt × decay_per_turn（小数累计，不再取整）——设计口径「每刻 −1.7」。
    """
    bd = bar_def(bar_key)
    if not bd:
        return {}
    bs = bar_state(enemy, bar_key, now)
    dt = float(now or 0.0) - float(bs.get("_at", 0.0) or 0.0)
    bs["_at"] = float(now or 0.0)
    if dt <= 0:
        return bs
    # 免疫到期 → 出窗（到期即可再触发）
    imm = float(bs.get("immune_until", 0.0) or 0.0)
    if imm and float(now or 0.0) >= imm:
        bs["immune_until"] = 0.0
    decay = float(bd.get("decay_per_turn", 0) or 0)
    if decay > 0 and float(bs.get("val", 0.0) or 0.0) > 0:
        bs["val"] = max(0.0, float(bs["val"]) - dt * decay)
        if logs is not None and bs["val"] <= 0:
            bs["val"] = 0.0
    return bs


def bar_gain(enemy: dict, bar_key: str, amount: float, logs: list | None = None,
             now: float | None = None) -> float:
    """积蓄注入：val += amount（封顶 max），返回新值。

    - 传 now → 先结算到当刻；免疫窗口内不积蓄（策划案「触发后 2 刻内不再积蓄」）
    - 触发当帧注入 = 0（`_no_inject_at` 帧戳，防「晕→追颅→又满→再晕」自锁）
    """
    bd = bar_def(bar_key)
    if not bd:
        return 0.0
    if now is not None:
        bar_settle(enemy, bar_key, now, logs)
    bs = bar_state(enemy, bar_key, now)
    if now is not None:
        if float(bs.get("immune_until", 0.0) or 0.0) > float(now):
            return float(bs.get("val", 0.0) or 0.0)
        if bs.get("_no_inject_at") == now:
            return float(bs.get("val", 0.0) or 0.0)
    mx = float(bd.get("max", 100) or 100)
    try:
        add = float(amount or 0)
    except Exception:
        add = 0.0
    bs["val"] = min(mx, float(bs.get("val", 0.0) or 0.0) + add)
    if logs is not None:
        logs.append(f"💥 破绽积蓄 +{int(add)}（{int(bs['val'])}/{int(mx)}）")
    return bs["val"]


def bar_should_trigger(enemy: dict, bar_key: str, now: float | None = None) -> bool:
    """是否应触发（val ≥ threshold 且在免疫窗口外）。"""
    bd = bar_def(bar_key)
    if not bd:
        return False
    bs = bar_state(enemy, bar_key, now)
    if now is not None and float(bs.get("immune_until", 0.0) or 0.0) > float(now):
        return False
    return float(bs.get("val", 0.0) or 0.0) >= float(bs.get("threshold", 0) or 0)


def bar_trigger(enemy: dict, bar_key: str, logs: list | None = None,
                now: float | None = None) -> bool:
    """执行触发：效果由调用方处理（本函数管理阈值递增/免疫/计数），返回是否触发。"""
    bd = bar_def(bar_key)
    if not bd:
        return False
    if not bar_should_trigger(enemy, bar_key, now):
        return False
    bs = bar_state(enemy, bar_key, now)
    # 阈值递增（防无限控）：threshold × threshold_inc，封顶 threshold_cap × base
    base = float(bd.get("threshold_base", 50) or 50)
    inc = float(bd.get("threshold_inc", 1.35) or 1.0)
    cap = float(bd.get("threshold_cap", 2.5) or 1.0)
    new_thr = floor(float(bs.get("threshold", base) or base) * inc)
    bs["threshold"] = int(min(floor(base * cap), new_thr))
    bs["trigger_count"] = int(bs.get("trigger_count", 0) or 0) + 1
    # 触发后清空积蓄 + 免疫窗口（绝对时刻）：策划案「触发后 N 刻内不再积蓄」
    bs["val"] = 0.0
    secs = float(bd.get("immune_secs", bd.get("immune_turns", 0)) or 0)
    bs["immune_until"] = float(now or 0.0) + secs if secs > 0 else 0.0
    # 自锁防护：触发当帧注入 = 0
    if bd.get("no_inject_on_trigger") and now is not None:
        bs["_no_inject_at"] = now
    if logs is not None:
        bname = bd.get("name", bar_key)
        logs.append(f"💢 【{bname}】触发！(第 {bs['trigger_count']} 次)")
    return True


def bar_preserve(enemy: dict, bar_key: str, pct: float | None = None) -> None:
    """阶段转换保留：val 保留 pct 比例（进度遗产）。"""
    bd = bar_def(bar_key)
    if not bd:
        return
    bs = bar_state(enemy, bar_key)
    p = float(pct if pct is not None else bd.get("phase_preserve_pct", 0.5) or 0.5)
    bs["val"] = float(int(float(bs.get("val", 0.0) or 0.0) * p))


# ============================================================
# 二、charge 蓄力三律
# ============================================================

def charge_def(skill_info: dict) -> dict:
    """读取技能电荷配置（charge dict / charge_cfg dict），无则 {}。

    v139：数据层统一用 charge_cfg 字段（云海弓手三律翻译），charge 保留旧蓄力 int。
    charge_def 优先读 charge（dict 才读），回退读 charge_cfg。
    """
    if not isinstance(skill_info, dict):
        return {}
    c = skill_info.get("charge")
    if isinstance(c, dict):
        return c
    cc = skill_info.get("charge_cfg")
    if isinstance(cc, dict) and cc:
        return cc
    return {}


def charge_state(player: dict) -> dict:
    """玩家电荷状态：{"stages": 0, "skill": str|None, "max": int}"""
    st = player.get("v139_charge")
    if not isinstance(st, dict):
        st = {"stages": 0, "skill": None, "max": 0}
        player["v139_charge"] = st
    return st


def charge_start(player: dict, skill_info: dict, logs: list | None = None) -> bool:
    """开始蓄力：设置电荷 0 阶。返回是否成功（技能有 charge 配置）。"""
    cd = charge_def(skill_info)
    if not cd:
        return False
    mx = int(cd.get("max", _cfg(_battle_cfg("charge"), "max", 3)) or 3)
    st = charge_state(player)
    st["stages"] = 0
    st["skill"] = skill_info.get("name")
    st["max"] = mx
    if logs is not None:
        sname = skill_info.get("name", "蓄力")
        logs.append(f"⏳ 开始蓄力【{sname}】(0/{mx} 阶)…")
    return True


def charge_tick(player: dict, skill_info: dict, logs: list | None = None) -> dict:
    """蓄力刻：+1 阶 + 边攒边打出伤。

    返回 {"staged": int, "dmg_mult": float, "released": bool}：
      staged    当前阶数
      dmg_mult  本刻边攒边打的伤害倍率（0.7/1.3/1.9 按阶）
      released  是否满阶强制释放（调用方执行释放逻辑）
    """
    cd = charge_def(skill_info)
    if not cd:
        return {"staged": 0, "dmg_mult": 0.0, "released": False}
    st = charge_state(player)
    mx = int(st.get("max", _cfg(_battle_cfg("charge"), "max", 3)) or 3)
    # v139：首次蓄力记录技能名（供受击打断/满阶释放识别），切技能自动重置阶数
    cur_skill = st.get("skill")
    if cur_skill and cur_skill != skill_info.get("name"):
        st["stages"] = 0
        st["max"] = mx
    st["skill"] = skill_info.get("name")
    st["stages"] = min(mx, int(st.get("stages", 0) or 0) + 1)
    stages = st["stages"]
    dmg_list = cd.get("dmg_per_stage", _cfg(_battle_cfg("charge"), "dmg_per_stage", [0.7, 1.3, 1.9]))
    dmg = float(dmg_list[min(stages - 1, len(dmg_list) - 1)]) if dmg_list else 0.0
    if logs is not None:
        sname = skill_info.get("name", "蓄力")
        logs.append(f"⚡ 蓄力【{sname}】{stages}/{mx} 阶，边攒边打出 ×{dmg}！")
    released = False
    if stages >= mx:
        released = bool(cd.get("force_release", _cfg(_battle_cfg("charge"), "force_release", True)))
        if logs is not None and released:
            logs.append(f"💥 蓄力满阶！【{sname}】强制释放！")
    return {"staged": stages, "dmg_mult": dmg, "released": released}


def charge_on_hit(player: dict, skill_info: dict, logs: list | None = None) -> bool:
    """受击：打断仅 -1 阶不清零（P3）。返回是否仍处于蓄力（stages > 0）。"""
    cd = charge_def(skill_info)
    if not cd:
        return False
    st = charge_state(player)
    if int(st.get("stages", 0) or 0) <= 0:
        return False
    pen = int(cd.get("interrupt_penalty", _cfg(_battle_cfg("charge"), "interrupt_penalty", 1)) or 1)
    st["stages"] = max(0, int(st.get("stages", 0) or 0) - pen)
    if logs is not None:
        sname = skill_info.get("name", "蓄力")
        logs.append(f"🔨 蓄力【{sname}】被打断！(剩 {st['stages']} 阶，不清零)")
    return int(st.get("stages", 0) or 0) > 0


def charge_release_power(skill_info: dict) -> dict:
    """满阶释放威力配置。返回 {"power": float, "extra": dict}。"""
    cd = charge_def(skill_info)
    if not cd:
        return {"power": 1.0, "extra": {}}
    return {
        "power": float(cd.get("release_power", _cfg(_battle_cfg("charge"), "release_power", 2.8)) or 1.0),
        "extra": cd.get("release_extra", _cfg(_battle_cfg("charge"), "release_extra", {}) or {}),
    }


def charge_clear(player: dict) -> None:
    """清除电荷状态（释放后/战斗结束）。"""
    player["v139_charge"] = {"stages": 0, "skill": None, "max": 0}
