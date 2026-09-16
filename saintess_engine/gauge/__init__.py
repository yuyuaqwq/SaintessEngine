# -*- coding: utf-8 -*-
"""通用件 - gauge（v181 通用挂敌身资源条）

把《云海猎团》职业融合提炼的通用机制实现为纯函数模块：
  enemy_bar  挂敌身资源条（bar_key 与显示名由内容侧声明）
   —— 积蓄挂在敌方身上，**容器 = actor.effects（V 系列统一单容器）**，
      键 = `data/battle_rules.BAR_STATE_PREFIX + bar_key`（如 `bar:shaken`）；
      独立于异常免疫，阈值递增防无限控、触发后免疫窗口、
      阶段转换保留部分进度

历史（2026-09-11 死代码清理）：本模块原有第二节「蓄力三律（charge）」共 7 个
函数（读技能电荷配置 / 状态 / 起蓄 / 跳刻 / 命中 / 释放威力 / 清除）已删除——
它是《云海猎团》弓手·时咒的职业机制，随 v151/v153 职业体系重做与
core_resources.py（v181.M-R2c）退役，**全仓零消费方**（内容侧从未有技能声明
电荷配置字段）。设计口径与数值留档
docs/archive/REFACTOR_v181_CLASS_MECH_ASSEMBLY.md『v139 形态层设计留档』章
+ git 历史；要恢复请按「内容动作 + 引擎 config 查表」的插件形态重写，别复活本段。

时间制（v181 改造）：
- 积蓄/衰减**按刻连续结算**（`bar_settle(host, key, now)`：dt × decay_per_turn，
  val 内部小数、展示取整），不再「每个宿主行动扣一次」
- 免疫窗口 = **绝对时刻**（`immune_until`）：期内不积蓄、不触发，到期即可再触发
- 所有公开 API 接受可选 `now`（`battle._now` 口径）；传了才结算/才受免疫约束，
  不传 = 纯读写（序列化检查、静态探针等无时钟上下文）

数据驱动铁律：
- 不写任何职业特判（不出现 class_name 字符串比较）
- 所有数值从 battle_config ENEMY_BAR_CFG 读（或调用方传入）
- 无配置 = 默认不启用
- 状态存 actor.effects 命名空间键（随战斗序列化）

⚠️ 条条目不带 `stacks` / `stat` / `mult` / `mode` / `expire` / `period`——
避开 effects 容器的四种自动化（到期清理 / 周期跳 / 面板折算 / 控制消费），
见 tests/test_numeric_bar_decay.py 容器安全断言。

S3 通用件归位（docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md §6.5 / §7-S3）：
本体自 game/core/battle_bars.py 迁入引擎（saintess_engine/），**读点改 config
注入面**——`config.mech_cfg(name)` / `config.bar_prefix()` 由内容侧装配
（game/bootstrap.py）注入，引擎零 game.data import（门禁 test_engine_no_content.py）。
（S3 前这里是 importlib 延迟直读 data.battle_config/data.battle_rules——
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
    - 触发当帧注入 = 0（`_no_inject_at` 帧戳，防「控制→积蓄→又满→再控」自锁）
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
        logs.append(f"💥 {bar_key} 积蓄 +{int(add)}（{int(bs['val'])}/{int(mx)}）")
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
