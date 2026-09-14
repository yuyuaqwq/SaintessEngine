# -*- coding: utf-8 -*-
"""包内 misc 命令族（`content/cmds_misc.py`）—— B18-L1 终态形状（真源 `overnight/B18_TERMINAL_SHAPE.md` §1）。

宿主 `game/commands/misc.py` 的 5 条命令**整块进包**（守卫 / 取参 / 业务 / 渲染）；
宿主只剩 `@declared("<key>")` + 一行 `_BRIDGE.run(...)`。

* 帮助 `help_cmd`      主题表 + 11 份面板 + 兜底回执（包内 `misc_cmds.help_reply`）；
                       参数解析（`[At:…]` 剥离 +「帮助/help」前缀）**也进包** —— 用 `env.text`
                       （引擎已 strip），逐字 = 旧宿主那两行正则/前缀循环。
* 新手指引 `game_tip`  整段文案（包内 `misc_cmds.GAME_TIP`）。
* 签到 `signin`        认领/运势/幸运符/金币/节日（`misc_cmds.signin_start`）+ 周奖励档位
                       （`core.quality_tiers.QUALITY_TIERS.pick_weights(_wq, rng=random)`，
                       与旧宿主同一行、同一随机流）+ **十条 `signin.*` 文案进包**。
* 成就 `achievements`  面板拼装（`misc_cmds.achievement_panel`）+「领取」回执（`claim_reply`）。
* 意见 `feedback_cmd`  校验/频控/入库（`feedback_precheck` / `feedback_submit`）；
                       Hermes webhook 通知仍走**宿主能力口**（`shell._notify_hermes` = 宿主集成，
                       不是游戏内容），且只在 `HERMES_WEBHOOK_URL` 已配置时才创建协程
                       （默认关闭 ⇒ 与旧的 `await` 路径**零差异**；开启时不再阻塞回话，见报告缺口）。

数据面：一律走**包内门面**（B14 口径，不新增 `C.<数据名>` 读点）——
`catalog_legacy.SIGNIN_CONFIG` / `catalog_items.MATERIALS` / `catalog_b143.QUALITY` /
`catalog_quests.ACHIEVEMENTS`；宿主侧只剩函数（`C.resolve` / `C.generate_equip` /
`C.claim_achievement_rewards` / `C.achievement_points`）与存储层 `db` 替身。
"""
from __future__ import annotations

import asyncio
import datetime
import inspect
import os
import random
import re
import time
import uuid

from . import misc_cmds as _M
from . import texts as T
from .catalog_b143 import QUALITY
from .catalog_items import MATERIALS
from .catalog_legacy import SIGNIN_CONFIG
from .catalog_quests import ACHIEVEMENTS
from .commands import register
from .world_cmds import C, _host_attr, db

__all__ = ["help_cmd", "game_tip", "signin", "achievements", "feedback_cmd"]


def _shell(env):
    """取宿主壳（过渡期能力口）——缺了直接抛，不静默空跑。"""
    shell = (getattr(env, "state", None) or {}).get("shell")
    if shell is None:
        raise RuntimeError("misc 命令缺宿主壳（env.state['shell']）——包内实现取不到取参/提示口")
    return shell


def _log():
    """日志口 = 宿主 `log_setup.LOG`（唯一日志入口）；取不到时退回 stdlib logger（编辑器/裸跑）。"""
    try:
        return _host_attr("log_setup", "LOG")
    except Exception:                                        # noqa: BLE001
        import logging
        return logging.getLogger("orlandia.cmds_misc")


def _spawn_background(awaitable, label):
    """把宿主侧「发了就好、不要结果」的协程交给事件循环（本形状的命令实现不能真挂起）。

    唯一调用点 = 意见箱的 Hermes webhook 通知。没有运行中的事件循环（离线工具）→ 显式丢弃并留痕，
    不静默吞掉一个「会永久 pending 的协程」。
    """
    if not inspect.isawaitable(awaitable):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        _log().warning("[dragonfall] %s 无事件循环可跑，已跳过（不影响主流程）", label)
        return
    task = loop.create_task(awaitable)
    task.add_done_callback(
        lambda t: None if t.cancelled() or t.exception() is None
        else _log().warning("[dragonfall] %s 失败(不影响主流程): %s", label, t.exception()))


# ============================================================
# 命令实现（5 条）
# ============================================================
@register("help_cmd")
def help_cmd(env):
    """『帮助 [主题]』：剥 `[At:…]` 前缀 +「帮助/help」指令词 → 主题面板 / 总览。"""
    msg = re.sub(r"^\[At:[^\]]*\]\s*", "", env.text or "")
    arg = ""
    for prefix in ("帮助", "help"):
        if msg.startswith(prefix):
            arg = msg[len(prefix):].strip()
            break
    return [_M.help_reply(arg)]


@register("game_tip", guards=("hook:player",))
def game_tip(env):
    """『游戏提示』新手引导（纯文案）。"""
    return [_M.GAME_TIP]


@register("signin", guards=("hook:player",))
def signin(env):
    """『签到』：原子认领 → 运势 → 金币 → 节日 → 每 7 天档位奖励（行序 = 旧命令体逐行）。"""
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    # F1 P1-4 原子签到认领 + 每日运势 + 幸运符消解 + 金币/节日口径全在 `misc_cmds.signin_start`。
    # 幸运符的**材料键**在这里给：包内 materials 域不存在（键集无法从 items 域反推），
    # 这一行就是真源 `C.resolve("materials", 幸运符)` + `key in C.MATERIALS` 的原样表达。
    _luck = C.resolve("materials", _M.LUCK_MATERIAL_NAME)
    st = _M.signin_start(group_id, qq_id, today, yesterday, SIGNIN_CONFIG,
                         _luck if _luck in MATERIALS else None)
    if st is None:
        return [T.static("signin.already")]
    streak, total, fortune = st["streak"], st["total"], st["fortune"]
    gold = st["gold"]
    # C8：认领为前置原子步骤已成功，此处结果构建/落库若抛错不重试认领（防重领），
    # 只回执最小成功提示，避免「已领签到但零回执」的静默失败。
    try:
        db.update_player(group_id, qq_id, gold=player["gold"] + gold)
        lines = [
            T.text("signin.title", total=total, streak=streak),
            T.text("signin.gold", gold=gold),
        ]
        # v87 / v185：运势显示（文案在文案表；这里只把「运势键」映射到「文案键」）
        _FORTUNE_TEXT = {"大吉": "signin.fortune_big", "平": "signin.fortune_flat",
                         "小凶": "signin.fortune_bad"}
        lines.append(T.static(_FORTUNE_TEXT.get(fortune, "signin.fortune_flat")))
        if fortune == "小凶":
            # vF3：小凶无预警提示——金币 -10% 早知道（概率/数值不变），可用幸运符消解或明日重roll
            lines.append(T.static("signin.bad_tip"))
        if st["festival"]:
            lines.append(T.static("signin.festival"))
        # 每 7 天额外奖励
        if streak % 7 == 0:
            # v184：档位抽取问唯一真相源 QUALITY_TIERS（权重行按档位序对齐，
            # 未列档位权重 0 → 只可能出 green/blue/purple，与旧 random.choices 同随机流）
            # ⚠️ 本行字面被 `tests/test_v184_loot_tiers.py` 源码级绑定钉住（该门禁已按
            #    B18 口径把「壳 + 包内 cmds_* 实现」两侧拼接读，判据不削弱）；取件保持
            #    **函数内惰性解析**（宿主 `core/quality_tiers` 薄壳再导出 = 包内同一对象，
            #    包加载早于它就绪 ⇒ 不能在 import 期取）。
            from .quality_tiers import QUALITY_TIERS
            _wq = dict(zip(("green", "blue", "purple"),
                           SIGNIN_CONFIG["week_quality_weights"]))
            q = QUALITY_TIERS.pick_weights(_wq, rng=random)
            equip = C.generate_equip(random.choice(["weapon", "armor", "ring"]), player["level"], q)
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", equip)
            lines.append(T.text("signin.week_reward", streak=streak,
                                color=QUALITY[equip["quality"]]["color"],
                                name=equip["name"]))
        return lines
    except Exception:                                        # noqa: BLE001
        return [T.static("signin.broken")]


@register("achievements", guards=("hook:player",))
def achievements(env):
    """『成就 [分类]』/『成就 领取』。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    raw = shell._strip_cmd(env.raw, "成就").strip()
    # v101.22 成就奖励手动领取：『成就 领取』（发放实现仍在宿主 core：`claim_achievement_rewards`）
    if raw.startswith("领取"):
        lines, err = C.claim_achievement_rewards(group_id, qq_id)
        return [_M.claim_reply(lines, err)]
    try:
        rows = db.get_achievements(group_id, qq_id)
        unlocked = {r["ach_key"] for r in rows}
        claimed = {r["ach_key"] for r in rows if r.get("claimed")}
    except Exception:                                        # noqa: BLE001
        unlocked, claimed = set(), set()
    # 分类筛选 / 进度 / 奖励文案拼装全在 `misc_cmds.achievement_panel`；
    # 表与成就点由宿主给（源列表序 + `core/achievements.py:achievement_points`）。
    lines = _M.achievement_panel(raw, ACHIEVEMENTS, unlocked, claimed,
                                C.achievement_points(qq_id))
    lines.append("")
    lines.append(shell._tip("achievement"))
    return lines


@register("feedback_cmd")
def feedback_cmd(env):
    """玩家意见箱：『意见 <内容>』收集群友建议，供鱼鱼/格温后续改动参考。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    args = shell._strip_cmd(env.raw, "意见").strip()
    _now_ts = time.time()
    # 参数校验（空 / ≤200 字）+ 30 秒频控 + 入库全在 `misc_cmds`（`feedback_precheck`/`feedback_submit`）
    reject = _M.feedback_precheck(args, qq_id, _now_ts)
    if reject:
        return [reject]
    try:
        res = _M.feedback_submit(group_id, qq_id, args, _now_ts)
        # 主动通知 Hermes（格温本体）：默认关闭（`HERMES_WEBHOOK_URL` 未设 ⇒ 连协程都不建 = 与旧路径零差异）
        if os.environ.get("HERMES_WEBHOOK_URL"):
            _spawn_background(shell._notify_hermes(group_id, qq_id, args, "feedback"),
                              "hermes-webhook")
        return [res["text"]]
    except Exception as e:                                   # noqa: BLE001
        _log().warning(f"[dragonfall] 意见保存失败: {e}")
        return [_M.MSG_SAVE_FAIL]
