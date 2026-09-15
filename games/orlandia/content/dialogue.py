# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 多轮对话引擎（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/dialogue.py`（131 行）。本模块 = 那个模块的**实现本体**
（`get_dialogue` / `dialogue_node` / `check_need` / `visible_options` / `_story_to_line` /
`node_text` / `is_end` 逐字搬）；宿主 `game/core/dialogue.py` 只剩再导出
（`core/__init__.py:46` 的 6 个 import 名 + 测试的 `check_need` 零改动）。

纯逻辑，不碰 DB/QQ —— 与本模块真源同一条纪律（数据在 `data/dialogues.py`，
命令层负责读写会话状态与落地 action）。

正文改动面（**只有三类**）
--------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `from .. import content as C` → `C.DIALOGUES.get(npc_id)` | 包内域读口 `_dialogues()`（读 `content/data/dialogues.json`） | ★ 数据读口（I1）：`dialogues` 有同名域且**逐键逐值 == 真源**（实测 `deep equal: True`，39 键；域为字典序、消费按 key 取 ⇒ 顺序无语义），与 `content/talk_actions.py:127` / `content/quests_flow.py:254` 同款读法 |
| `from ..log_setup import LOG`（模块级） | `content/obs.py::log()`（B2-C4：包内唯一日志取用口，fail-closed）；调用点 `LOG.warning(...)` → `obs.log().warning(...)` | 宿主日志层**不搬**（平台件；接口表第 10 行） |
| `from ..data import MAIN_QUESTS`（`node_text` 内） | `_main_quests()`：包内 `quests` 域 `source=="main"` 子集 | 真源写法是「按 id 扫表」（`next(q for q in MAIN_QUESTS if q["id"] == mid)`）⇒ 顺序无语义；与 `content/quests_flow.py:264`（`_Dom.MAIN_QUESTS`）**同一口径**（实测 70 条 id 全等 + 逐条逐值相等） |

`from .dialogue_conds import CONDITIONS` 原样保留（包内直取；它已随本线进包）。

缺口登记：宿主聚合层 `C.DIALOGUES` 现在**只剩这一条读路**已被本模块绕开；`C` 上其余
符号不在本模块读点内。`MAIN_QUESTS` 的宿主侧真源（`game/data/quests.py`）仍留宿主，
B14 切读点时按 `quests` 域统一处置。

等价证据：`overnight/w1213_b13l3_snap.py`（D1–D10 共 15 例：变体 / text_from 的 giver 校验 /
side_menu 三态 / 未知条件键 raise / 数据面计数）· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛）。

    与 `content/talk_actions.py:48` / `content/quests_flow.py:62` 同款小门面。
    """
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {} if default is None else default


_DIALOGUES = None
_MAIN_QUESTS = None


def _dialogues() -> dict:
    """包内 `dialogues` 域（真源 `C.DIALOGUES`，逐键逐值等同）。"""
    global _DIALOGUES
    if _DIALOGUES is None:
        _DIALOGUES = _read_domain("dialogues")
    return _DIALOGUES


def _main_quests() -> list:
    """包内 `quests` 域的主线子集（真源 `from ..data import MAIN_QUESTS`）。

    真源消费方式全是「按 id 扫表」⇒ 顺序无语义（与 `content/quests_flow.py:264` 同口径）。
    """
    global _MAIN_QUESTS
    if _MAIN_QUESTS is None:
        raw = _read_domain("quests")
        _MAIN_QUESTS = [v for v in raw.values() if v.get("source") == "main"]
    return _MAIN_QUESTS


# ============================================================
# 日志取件口（B2-C4 收口）—— `content/obs.py` = 包内唯一 LOG/tlog 取用口（fail-closed）
# ============================================================
from . import obs                                 # noqa: E402


def get_dialogue(npc_id: str):
    """返回 NPC 的对话树(dict)或 None(未配置多轮对话 → 走旧单轮逻辑)"""
    dlg = _dialogues().get(npc_id)          # 真源 `C.DIALOGUES.get(npc_id)`
    return dlg if dlg else None


def dialogue_node(dlg, node_id: str):
    """取对话树中的节点；不存在回退到 start 节点"""
    nodes = dlg.get("nodes", {})
    if node_id in nodes:
        return nodes[node_id]
    return nodes.get(dlg.get("start"), {})


def check_need(need, ctx: dict) -> bool:
    """判断选项条件是否满足。ctx = {player, quests, flags}

    v98.3：条件判定全数据化 → core/dialogue_conds.py CONDITIONS 注册表。
    need 支持的键（quest_done/quest_active/quest_pending/quest_ready/side_ready/
    quest_any_active/apprentice/not_apprentice/is_novice/not_novice/class_any/
    evolve_ready）见该文件；
    v113 增补：race_is/hidden_unlocked/hidden_current/not_hidden_current/side_available。
    加新条件类型 = register 一个函数（~5 行），本文件零改动。
    """
    if not need:
        return True
    from .dialogue_conds import CONDITIONS      # 包内直取（真源同位置 `from .dialogue_conds import …`）
    for k, v in need.items():
        fn = CONDITIONS.get(k)
        if fn is None:
            # v104 M21 P1：未注册条件键 → 生产放行但告警（防数据笔误静默变永远可见）；
            # 测试环境（GWEN_GAME_DB 指向 test 库）直接 raise，让单测抓出笔误
            import os
            _db = os.environ.get("GWEN_GAME_DB", "")
            _msg = (f"[dragonfall] 对话条件未注册键 need[{k!r}]={v!r}："
                    f"数据笔误？已按'永远可见'放行，请检查 dialogues.py")
            # v110.5 X3：显式判定测试环境——既看私有库名含 "test"（旧约定兼容），
            # 也认 GWEN_TEST_MODE=1（本轮私有库名不含 "test" 时测试行为漂移的根因）。
            _test = ("test" in os.path.basename(_db).lower()
                     or os.environ.get("GWEN_TEST_MODE") == "1")
            if _test:
                raise ValueError(_msg)
            obs.log().warning(_msg)
            continue  # 未知条件放行（向后兼容，旧数据不崩）
        if not fn(ctx, v):
            return False
    return True


def visible_options(dlg, node, ctx: dict) -> list:
    """过滤出当前可见的选项(need 不满足的隐藏)

    v127.6 side_menu 动态菜单：选项带非空 'side_menu' 键时，调用命令层注入的
    ctx['side_menu_expand'](opt) 回调，将该选项展开成一组动态子选项
    （每个子选项自带 text/next/action，如『接『支线名』(目标)』）；
    未注入回调、need 不满足、或展开为空 → 该选项整体不出现
    （无活儿可接时不显示菜单）。core 层保持纯逻辑、零 DB，回调由命令层注入。
    """
    out = []
    for opt in node.get("options", []):
        if opt.get("side_menu") is not None:
            if not check_need(opt.get("need"), ctx):
                continue
            expand = ctx.get("side_menu_expand")
            subs = expand(opt) if expand else []
            if subs:
                out.extend(subs)
            continue  # 未注入回调/展开为空 → 跳过该选项
        if check_need(opt.get("need"), ctx):
            out.append(opt)
    return out


_STORY_PREFIX = re.compile(r"^[^：:]{1,20}[：:]\s*")


def _story_to_line(raw: str) -> str:
    """任务 story/ending 文本 → NPC 台词（v101.23d A 级：text_from 自动生成）

    格式多为『NPC名：台词』或『NPC名：『台词』』（少数叙事型『老约翰交给玩家一封信：『…』』）。
    规则：剥 NPC 名前缀 → 取 『』/“” 引号内 → 都没有就原样降级（叙事型也能念）。
    """
    if not raw:
        return ""
    body = _STORY_PREFIX.sub("", raw.strip())
    m = re.match(r"^[“『](.+)[”』]$", body.strip())
    return m.group(1) if m else body


def node_text(node, ctx: dict) -> str:
    """节点台词：texts 条件变体优先（need 满足的第一个），否则默认 text；
    v101.23d：text_from 支持——节点写 {"text_from": "story"} 时，无变体匹配则
    从『当前主线任务』的 story 字段自动生成接取台词（giver 校验，防串台）。
    多任务 NPC 加新任务 = 纯数据，quest_talk 台词自动跟任务走，不用手写变体。"""
    for variant in node.get("texts") or []:
        if check_need(variant.get("need"), ctx):
            return variant["text"]
    src = node.get("text_from")
    if src in ("story",):
        quests = ctx.get("quests") or {}
        mid = quests.get("main_quest")
        if mid:
            # 真源此处 `from ..data import MAIN_QUESTS` → 包内 quests 域主线子集（同口径）
            MAIN_QUESTS = _main_quests()
            mq = next((q for q in MAIN_QUESTS if q["id"] == mid), None)
            if mq and (not mq.get("giver") or mq.get("giver") == ctx.get("npc_id")):
                auto = _story_to_line(mq.get("story", ""))
                if auto:
                    return auto
    return node.get("text", "……")


def is_end(node_id: str) -> bool:
    """__end__ 是结束对话的哨兵节点"""
    return node_id == "__end__"
