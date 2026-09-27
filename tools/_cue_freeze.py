# -*- coding: utf-8 -*-
"""cue 迁移**冻结尺子**（对拍判据）—— `tools/_cue_freeze.py`。

用途
----
把「结算里直接拼玩家可见文案」改成「结算发事件、表现由内容侧订阅」（cue 解耦）的
路上，**唯一判据**就是这个尺子：同一份固定操作脚本在两棵代码树上各跑一遍，
三通道必须一致 ——

    ① `logs`        逐字节 sha256（"\n".join(logs) 的 sha256）
    ② `to_state()`  逐键 diff（floag round6 归一化后拍平）
    ③ 逐 cue 计数表  每个 cue key 被渲染了多少次

它**不依赖 cue 形状**（那一批还没落地）：今天只采「logs + state + 计数表」，
采法是在 `Battle(text=…)` 的注入面上挂一个**计数鸭子表**（实现 `render_or(key, default, **slots)`），
`render_via` 与 `self._t` 两条渲染路都从这一口过 ⇒ 都能被数到；且返回
`safe_format(default, slots)` ⇒ 输出与「未注入」**逐字节相同**（对拍基线 = 不注入）。

用法
----
    python tools/_cue_freeze.py --before <树> --after <树> [--inject reorder|drop] [--json out.json]

    三道自洽反证（必跑）：
      python tools/_cue_freeze.py --before T --after T                    # 必须 GREEN（尺子自洽/确定性）
      python tools/_cue_freeze.py --before T --after T --inject reorder   # 必须 RED （换序有牙）
      python tools/_cue_freeze.py --before T --after T --inject drop      # 必须 RED （缺表现有牙）

退出码：0 = 全绿；1 = 红（附原因）；2 = 用法/环境错。

确定性
------
* 每组固定 `random.seed(seed)`（引擎的战斗随机全走全局 `random`）+ 固定脚本 + 28 步；
* 父进程只派活与比对，两棵树各自在**独立子进程**里采集（同模块不可双载），
  子进程 `PYTHONHASHSEED=0`（排除 set/dict 哈希序这个变量）；
* 同一棵树连跑两次必须逐字节相同 —— 不同 ⇒ **先修尺子**，不看代码。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCHEMA = "cue-freeze/1"
STEPS = 28                     # 每组步数（写死）
SEEDS = (1, 2, 3, 4, 5)        # 固定随机种子 × 5 组战斗
VOLATILE = ("turn_time", "wall_time", "ts", "monotonic")   # 归一化时剔掉的易变键


# ============================================================
# 场景表（纯数据；「固定操作脚本」的真源）
# ============================================================
# 每一步一个 op：
#   ["act",  uid, action, skill]      出手（Battle.human_act 公开入口；action=flee/dance 也走它）
#   ["mob",  uid, action, skill]      显式编排某个敌人的这一手（写 auto_act → Battle.actor_auto）
#   ["dmg",  src_uid, tgt_uid, amount, dmg_kind, element]   引擎落地口 deal_damage
#   ["verb", 动词名, caster_uid, target_uid, {params}]      引擎效果动词（effects.act_*，公开注册表）
#   ["state", uid, key, value]        写 actor.effects[key]（int → {"stacks":n}；dict → 原样）
#   ["field", uid, key, value]        写 actor 顶层字段（如 immune_dots 名单）
#   ["adv", n]                        推进 n 拍（Battle.advance → 时间/DOT/回复/自动 actor）
#   ["land", uid|null]                把「该 actor 已登记的待发行动」推到落地（settle_landing；
#                                     advance 会一路跑到下一个决策点，出手就停在当刻 ⇒ 落地被挂起）

def _rep(n: int, *ops):
    """把 ops 重复 n 遍 → 列表（便于把 28 步写清楚）。"""
    out = []
    for _ in range(n):
        out.extend([list(o) for o in ops])
    return out


def scenarios():
    """5 组固定战斗（种子 1..5）。每组脚本长度必须 == STEPS。"""
    g = []

    # ---- G1 · 普攻/技能/防御 循环 + 杂兵阵亡（down / on_kill）+ 逃跑/终局收尾 ----
    g.append({
        "gid": 1, "seed": 1, "name": "G1 循环出手·杂兵阵亡·逃跑·终局",
        "player": ("cls_kiln", "p1", "铆炉匠甲", 6, 900),
        "allies": [],
        "enemies": [
            {"key": "rustmite", "uid": "e1", "hp": 2400, "fields": {}},
            {"key": "rustmite", "uid": "e2", "hp": 8, "fields": {}},
        ],
        # 起手给满初始资源（否则技能一直卡在资源不足、冷却这条线采不到）
        # 24 步循环（attack→skill→skill：第二发撞冷却 ⇒ skill_cd）
        # + 收尾 4 步：逃跑 → 推进让逃跑落地（core.fled）→ 再出手（core.finished）
        "script": [["state", "p1", "kiln", 6]]
        + _rep(5, ["act", "p1", "attack", None], ["act", "p1", "skill", "过载铆钉"],
               ["act", "p1", "skill", "过载铆钉"], ["act", "p1", "attack", None])
        + [["act", "p1", "attack", None], ["act", "p1", "skill", "过载铆钉"],
           ["act", "p1", "skill", "过载铆钉"], ["act", "p1", "attack", None],
           ["act", "p1", "flee", None], ["land", "p1"], ["act", "p1", "attack", None]],
    })

    # ---- G2 · 控制链（铁钳拘束 → 整手跳过，每回合都放）+ 技能冷却 ----
    g.append({
        "gid": 2, "seed": 2, "name": "G2 控制链·技能冷却",
        "player": ("cls_kiln", "p1", "铆炉匠甲", 7, 900),
        "allies": [],
        "enemies": [
            {"key": "ironbuoy", "uid": "e1", "hp": 2400,
             "fields": {"dodge": 0.40}, "auto": ["skill", "ms_clamp"]},
            {"key": "rustmite", "uid": "e2", "hp": 2400, "fields": {}},
        ],
        "script": _rep(7, ["act", "p1", "attack", None], ["act", "p1", "skill", "过载铆钉"],
                       ["act", "p1", "skill", "过载铆钉"], ["act", "p1", "defend", None]),
    })

    # ---- G3 · 灼热侧 + 锈蚀 DOT + 沉默（no_skill 控制）+ 未知动作 ----
    g.append({
        "gid": 3, "seed": 3, "name": "G3 灼热·锈蚀 DOT·沉默·未知动作",
        "player": ("cls_whistle", "p2", "哨鸣师乙", 7, 900),
        "allies": [],
        "enemies": [
            {"key": "rustmite", "uid": "e1", "hp": 2400,
             "fields": {}, "auto": ["skill", "ms_rustspit"]},
        ],
        # 20 步循环 + 8 步收尾：挂沉默态 → 连放技能被禁 → 未知动作
        "script": _rep(5, ["act", "p2", "skill", "共鸣脉冲"], ["act", "p2", "attack", None],
                       ["act", "p2", "defend", None], ["act", "p2", "attack", None])
        + [["state", "p2", "rig_silence", {"mode": "no_skill", "expire": 999999.0}],
           ["act", "p2", "skill", "共鸣脉冲"], ["act", "p2", "skill", "共鸣脉冲"],
           ["act", "p2", "attack", None], ["act", "p2", "defend", None],
           ["act", "p2", "skill", "共鸣脉冲"], ["act", "p2", "attack", None],
           ["act", "p2", "dance", None]],
    })

    # ---- G4 · 两侧多单位（友军 + 三敌）+ 引擎效果动词全走一遍 ----
    g.append({
        "gid": 4, "seed": 4, "name": "G4 两侧多单位·引擎动词",
        "player": ("cls_kiln", "p1", "铆炉匠甲", 6, 900),
        "allies": [("cls_whistle", "a1", "哨鸣师丙", 6, 900)],
        "enemies": [
            {"key": "ironbuoy", "uid": "e1", "hp": 2000,
             "fields": {"block": 0.60}, "auto": ["attack", None]},
            {"key": "rustmite", "uid": "e2", "hp": 2000,
             "fields": {}, "auto": ["skill", "ms_rustspit"]},
            {"key": "rustmite", "uid": "e3", "hp": 2000,
             "fields": {}, "auto": ["attack", None]},
        ],
        "script": [
            # 1-8：两侧交替出手（玩家 + 友军，各有 4 手）
            ["act", "p1", "attack", None], ["act", "a1", "skill", "共鸣脉冲"],
            ["act", "p1", "defend", None], ["act", "a1", "attack", None],
            ["act", "p1", "attack", None], ["act", "a1", "attack", None],
            ["act", "p1", "skill", "过载铆钉"], ["act", "a1", "defend", None],
            # 9-28：引擎效果动词（公开注册动作）逐个走一遍
            ["verb", "act_shield", "p1", "p1", {"key": "rig_shield", "value": 300, "turns": 12}],
            ["verb", "act_apply", "p1", "p1", {"key": "reduce", "value": 0.45, "turns": 4}],
            ["verb", "act_apply", "p1", "p1", {"key": "rig_mark", "turns": 3}],
            ["verb", "act_apply", "p1", "p1", {"key": "rig_hit", "turns": 3,
                                              "hit": {"dmg_mult": 1.2}}],
            ["verb", "act_apply", "p1", "p1", {"key": "rig_boost", "turns": 3,
                                              "stat": "atk", "mult": 1.2}],
            ["verb", "act_apply", "p1", "p1", {"key": "rig_stack", "op": "set", "amount": 3}],
            ["verb", "act_consume", "p1", "p1", {"key": "rig_stack", "amount": 9}],
            ["verb", "act_consume", "p1", "p1", {"key": "rig_stack", "amount": 2}],
            ["verb", "act_heal", "p1", "p1", {"value": 120}],
            ["verb", "act_damage", "p1", "e3", {"value": 30}],
            ["verb", "act_cleanse", "p1", "p1", {}],
            ["verb", "act_cleanse", "p1", "p1", {}],
            ["state", "e1", "cc_immune", {"expire": 999999.0, "stacks": 1}],
            ["verb", "act_apply", "p1", "e1", {"key": "rig_ctrl", "mode": "skip",
                                              "turns": 2, "on": "target"}],
            ["field", "e1", "immune_dots", ["rust"]],
            ["verb", "act_apply", "p1", "e1", {"key": "rust", "on": "target",
                                              "op": "set", "amount": 1}],
            ["mob", "e3", "skill", "ms_rustspit"],
            ["verb", "act_interrupt", "p1", "e3", {}],
            ["state", "p1", "death_guard", 1],
            ["dmg", "e1", "p1", 99999, "true", ""],
        ],
    })

    # ---- G5 · 承伤分支全开：格挡(blocked_amount) / 物免 / 魔抗 / 元素免疫·弱点·抗性 /
    #          护盾吸收 / 挡刀 / 治疗 / 闪避 ----
    g.append({
        "gid": 5, "seed": 5, "name": "G5 承伤分支全开",
        "player": ("cls_kiln", "p1", "铆炉匠甲", 6, 600),
        "allies": [],
        "enemies": [
            # 靶子甲：元素免疫/弱点/抗性 + 物免 + 魔抗 + 格挡 + 闪避（全走 actor 数据字段）
            {"key": "rustmite", "uid": "e1", "hp": 2400,
             "fields": {"element_immune": ["fire"], "element_weak": {"ice": 2.0},
                        "elem_res": 0.30, "phys_reduce": 0.30, "magic_reduce": 0.30,
                        "block": 1.00, "dodge": 0.40}},
            # 靶子乙：薄血 + 挂「守护者」→ 挡刀（guard_cover）
            {"key": "rustmite", "uid": "e2", "hp": 40, "fields": {"guard_uid": "e3"}},
            {"key": "rustmite", "uid": "e3", "hp": 2400,
             "fields": {}, "auto": ["skill", "ms_rustspit"]},
        ],
        "script": [
            ["act", "p1", "defend", None],                      # core.defend（开防御窗口）
            ["dmg", "e1", "p1", 60, "phys", ""],                # blocked_amount
            ["dmg", "e1", "p1", 60, "magi", ""],                # blocked_amount（窗口未到己手）
            ["dmg", "p1", "e1", 60, "", "fire"],                # element_immune
            ["dmg", "p1", "e1", 60, "", "ice"],                 # element_weak + resist_reduce
            ["dmg", "p1", "e1", 60, "phys", ""],                # phys_immune
            ["dmg", "p1", "e1", 60, "magi", ""],                # magic_resist
            ["verb", "act_shield", "p1", "p1", {"key": "g5_shield", "value": 300, "turns": 12}],
            ["dmg", "e1", "p1", 80, "phys", ""],                # shield_absorb
            ["dmg", "p1", "e2", 20, "phys", ""],                # guard_cover
            ["dmg", "p1", "e2", 40, "phys", ""],                # guard_cover
            ["field", "p1", "heal_share_uid", "e3"],            # 治疗转移指向
            ["verb", "act_heal", "p1", "p1", {"value": 120}],   # healed + heal_shared
            # 撤掉转移 + 造 mp 容器（持续恢复那一跳要真落到自己身上）
            ["field", "p1", {"heal_share_uid": None, "max_mp": 200, "mp": 10}],
            ["state", "p1", "rig_hot", {"stacks": 1, "period": {
                "dir": "heal", "interval": 1.0, "turns": 9,
                "heal_pct": 0.05, "mana_pct": 0.05}}],
            ["adv", 3],                                         # regen_hp + regen_mp（+DOT）
            ["verb", "act_cleanse", "p1", "p1", {}],            # cleansed / cleanse_none
            ["act", "p1", "attack", None],
            ["verb", "act_apply", "p1", "p1", {"key": "g5_hit", "turns": 3,
                                              "hit": {"dmg_mult": 1.2}}],
            ["act", "p1", "attack", None],                      # effect_on（出手消费 hit）
            ["dmg", "p1", "e1", 60, "", "ice"],
            ["act", "p1", "defend", None],
            ["dmg", "e1", "p1", 60, "phys", ""],
            ["verb", "act_damage", "p1", "e2", {"value": 30}],  # effects.damaged
            ["state", "p1", "death_guard", 1],
            ["dmg", "e1", "p1", 99999, "true", ""],             # landing.death_guard
            ["field", "p1", {"human_controlled": False, "kind": "npc"}],
            ["act", None, "attack", None],                      # core.no_actor（无焦点）
        ],
    })

    for sc in g:
        if len(sc["script"]) != STEPS:
            raise AssertionError("G%d 脚本 %d 步 != %d" % (sc["gid"], len(sc["script"]), STEPS))
    if len(g) != len(SEEDS):
        raise AssertionError("场景数 %d != 种子数 %d" % (len(g), len(SEEDS)))
    return g


# ============================================================
# 采集（在**子进程**里跑；父进程只用 stdlib 派活 + 比对）
# ============================================================

def _setup_path(tree: str) -> None:
    """把目标树的三个根插进 sys.path（示例内容包 / 扩展包 / 引擎）。"""
    for p in (os.path.join(tree, "examples", "minimal-game"),
              os.path.join(tree, "extends"),
              tree):
        p = os.path.normpath(p)
        if p not in sys.path:
            sys.path.insert(0, p)


class SpyText:
    """计数鸭子表 —— 口径 = 引擎的 `render_or(text, key, default, **slots)`。

    引擎两条渲染路（`Battle._t` 与模块级 `render_via`）都从 `render_or` 走，
    `text` 非 None 就调 `text.render_or(key, default, **slots)` ⇒ 本类即唯一计数点。
    返回 `safe_format(default, slots)` ⇒ 与「未注入」逐字节相同。

    ⚠️ 口径声明：本尺子的「逐 cue 计数表」= `render_or` 这一口的 key 计数。
    后续批次若把渲染口换成别的形状（如内容侧直接 `text.render(key, **payload)`），
    必须**同批扩展本类**（那不是判据变化，是采集面跟着形状走），并在报告里写明。
    """

    def __init__(self):
        self.counts: dict = {}
        self.rendered: list = []          # [(key, 渲染出的那一行), ...] 按渲染序

    def render_or(self, key, default, /, **slots):
        from saintess_engine.text import safe_format
        line = safe_format(default, slots)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.rendered.append((key, line))
        return line


def _norm(value):
    """状态归一化：float → round6；剔易变键；其余原样（保插入序）。"""
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _flat(value, prefix="", out=None):
    """拍平：path → 标量（逐键 diff 用）。"""
    if out is None:
        out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            _flat(v, "%s.%s" % (prefix, k) if prefix else str(k), out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flat(v, "%s[%d]" % (prefix, i), out)
    else:
        out[prefix or "<root>"] = value
    return out


#: 引擎侧键化调用点扫描（与设计案 §5② 同款正则；只做**信息面**，不做判据）
_KEY_RX = re.compile(r'(?:render_via|render_or)\(\s*(?:[A-Za-z_][\w\.]*\s*,\s*)?"([^"]+)"')
_T_RX = re.compile(r'self\._t\(\s*"([^"]+)"')


def _key_inventory(tree: str):
    """扫目标树 extends/ext_combat 的键化调用点 → (唯一点位表, key 集合)。"""
    root = os.path.join(tree, "extends", "ext_combat")
    keys = {}
    if not os.path.isdir(root):
        return keys
    for dp, _dirs, files in os.walk(root):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            with open(p, encoding="utf-8") as fh:
                flat = re.sub(r"\s+", " ", fh.read())
            rel = os.path.relpath(p, tree).replace("\\", "/")
            for m in list(_KEY_RX.finditer(flat)) + list(_T_RX.finditer(flat)):
                keys.setdefault(m.group(1), []).append(rel)
    return keys


def collect(tree: str, inject: str = "none") -> dict:
    """对一棵树跑完 5×28，返回可 JSON 化的采集结果。"""
    _setup_path(tree)

    import random
    from ext_combat import Battle, deal_damage, settle_landing
    from ext_combat.battle import effects as _eff
    from content import apply_game_content
    from content.data.classes import build_player
    from content.data.monsters import build_monster

    groups = []
    for sc in scenarios():
        random.seed(sc["seed"])
        spy = SpyText()

        def _mk_player(spec):
            cls, uid, name, level, hp = spec
            a = build_player(cls, uid, name, level=level)
            apply_game_content(a)
            a["max_hp"] = a["hp"] = int(hp)
            return a

        p_main = _mk_player(sc["player"])
        allies = [_mk_player(s) for s in sc["allies"]]
        enemies = []
        for es in sc["enemies"]:
            e = build_monster(es["key"], es["uid"])
            apply_game_content(e)
            for k, v in (es.get("fields") or {}).items():
                e[k] = v
            if es.get("hp"):
                e["max_hp"] = e["hp"] = int(es["hp"])
            if es.get("auto"):
                _act, _sk = es["auto"]
                e["auto_act"] = {"act": {"type": _act, "skill": _sk}}
            enemies.append(e)

        battle = Battle(btype="monster",
                        sides={"player": [p_main] + allies, "enemy": list(enemies)},
                        text=spy)

        sink = []          # 逐行原始文本
        origin = []        # 每行对应的 cue key（None = 非 cue 行）
        cursor = 0         # spy.rendered 消费游标（按序 FIFO 匹配）

        def _append(lines):
            nonlocal cursor
            for ln in lines or ():
                key = None
                for j in range(cursor, len(spy.rendered)):
                    if spy.rendered[j][1] == ln:
                        key = spy.rendered[j][0]
                        cursor = j + 1
                        break
                sink.append(ln)
                origin.append(key)

        for op in sc["script"]:
            kind = op[0]
            if kind == "act":
                actor = battle.find_actor(op[1])
                got, _ended, _who = battle.human_act(op[2], op[3], actor=actor)
                _append(got)
            elif kind == "mob":
                actor = battle.find_actor(op[1])
                actor["auto_act"] = {"act": {"type": op[2], "skill": op[3]}}
                got, _ended = battle.actor_auto(actor)
                _append(got)
            elif kind == "dmg":
                buf = []
                deal_damage(battle, battle.find_actor(op[1]), battle.find_actor(op[2]),
                            int(op[3]), buf, dmg_kind=str(op[4] or ""),
                            element=str(op[5] or ""))
                _append(buf)
            elif kind == "verb":
                fn = getattr(_eff, op[1], None)
                if fn is None:
                    raise ValueError("未知引擎动词：%r" % (op[1],))
                buf = []
                fn(battle, battle.find_actor(op[2]), battle.find_actor(op[3]), dict(op[4]), buf)
                _append(buf)
            elif kind == "state":
                actor = battle.find_actor(op[1])
                val = op[3]
                actor.setdefault("effects", {})[op[2]] = (
                    {"stacks": int(val)} if isinstance(val, int) else dict(val))
            elif kind == "field":
                actor = battle.find_actor(op[1])
                if isinstance(op[2], dict):
                    for _k, _v in op[2].items():
                        actor[_k] = _norm(_v)
                else:
                    actor[op[2]] = _norm(op[3])
            elif kind == "adv":
                buf = []
                for _ in range(int(op[1])):
                    battle.advance(buf)
                _append(buf)
            elif kind == "land":
                buf = []
                settle_landing(battle, buf, battle.find_actor(op[1]))
                _append(buf)
            else:
                raise ValueError("未知 op：%r" % (op,))

        # —— 反证开关：在**采完之后**人为制造「表现层变了」——
        # 只动 **G1 一组、一处**（最小扰动）：证明「哪怕少/换一行也报红」，
        # 而不是靠大面积破坏把判据压红。
        if inject != "none" and sc["gid"] == SEEDS[0]:
            if inject == "reorder":
                for i in range(len(sink) - 1):
                    if sink[i] != sink[i + 1]:
                        sink[i], sink[i + 1] = sink[i + 1], sink[i]
                        origin[i], origin[i + 1] = origin[i + 1], origin[i]
                        break
            elif inject == "drop":
                for i in range(len(sink) - 1, -1, -1):
                    if origin[i]:
                        k = origin.pop(i)
                        sink.pop(i)
                        spy.counts[k] -= 1
                        if spy.counts[k] <= 0:
                            spy.counts.pop(k, None)
                        break
            else:
                raise ValueError("未知 --inject：%r" % (inject,))

        state = _norm(battle.to_state())
        non_cue = [ln for ln, o in zip(sink, origin) if o is None]
        groups.append({
            "gid": sc["gid"], "seed": sc["seed"], "name": sc["name"],
            "logs": sink,
            "logs_sha256": hashlib.sha256("\n".join(sink).encode("utf-8")).hexdigest(),
            "cue_counts": {k: spy.counts[k] for k in sorted(spy.counts)},
            "renders_total": len(spy.rendered),
            "unmatched_renders": [t for (_k, t) in spy.rendered[cursor:]][:5],
            "non_cue_count": len(non_cue),
            "non_cue_samples": sorted(set(non_cue))[:5],
            "state": state,
            "state_flat": _flat(state),
        })

    inv = _key_inventory(tree)
    observed = set()
    for g in groups:
        observed |= set(g["cue_counts"])
    return {"schema": SCHEMA, "tree": os.path.abspath(tree),
            "tree_head": _head_of(tree), "inject": inject, "steps": STEPS,
            "key_inventory": {k: sorted(set(v)) for k, v in sorted(inv.items())},
            "key_inventory_n": len(inv),
            "observed_keys": sorted(observed),
            "uncovered_keys": sorted(set(inv) - observed),
            "groups": groups}


def _head_of(tree: str) -> str:
    try:
        out = subprocess.run(["git", "-C", tree, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip() or "?"
    except Exception:
        return "?"


# ============================================================
# 比对
# ============================================================

def _diff_state(fb: dict, fa: dict):
    """逐键 diff：返回 [(path, 归因类别, 明细), ...]。"""
    diffs = []
    for k in sorted(set(fb) | set(fa)):
        b_got, a_got = k in fb, k in fa
        if not b_got or not a_got:
            diffs.append((k, "结构差异",
                          "只有 %s 有：%r" % ("before" if b_got else "after",
                                             fb.get(k, fa.get(k)))))
            continue
        b, a = fb[k], fa[k]
        if b == a:
            continue
        if isinstance(b, str) or isinstance(a, str) or isinstance(b, bool) \
                or isinstance(a, bool) or b is None or a is None:
            kind = "文本差异" if (isinstance(b, str) or isinstance(a, str)) else "类型/字面差异"
            diffs.append((k, kind, "before=%r → after=%r" % (b, a)))
            continue
        try:
            delta = float(a) - float(b)
        except (TypeError, ValueError):
            diffs.append((k, "不可比差异", "before=%r → after=%r" % (b, a)))
            continue
        if abs(delta) <= 1e-6:
            diffs.append((k, "浮点尾差(≤1e-6)", "before=%r → after=%r" % (b, a)))
        else:
            diffs.append((k, "数值差异 Δ=%+.6g" % delta, "before=%r → after=%r" % (b, a)))
    return diffs


def compare(before: dict, after: dict) -> dict:
    """三通道对拍：logs 逐字节 / 逐 cue 计数表 / to_state 逐键。"""
    res = {"logs": [], "counts": [], "state": [], "n_state_keys": 0,
           "n_ok_sha": 0, "n_groups": 0, "notes": [], "zero_count": []}
    gb = {g["gid"]: g for g in before["groups"]}
    ga = {g["gid"]: g for g in after["groups"]}
    res["n_groups"] = len(gb)
    if set(gb) != set(ga):
        res["notes"].append("组号集合不一致：before=%s after=%s" % (sorted(gb), sorted(ga)))

    for gid in sorted(set(gb) & set(ga)):
        bg, ag = gb[gid], ga[gid]

        # ① logs 逐字节 sha256
        if bg["logs_sha256"] == ag["logs_sha256"]:
            res["n_ok_sha"] += 1
            res["logs"].append((gid, "PASS", "%s（%d 行）"
                                % (bg["logs_sha256"], len(bg["logs"]))))
        else:
            first = None
            for i in range(max(len(bg["logs"]), len(ag["logs"]))):
                b = bg["logs"][i] if i < len(bg["logs"]) else "<缺行>"
                a = ag["logs"][i] if i < len(ag["logs"]) else "<缺行>"
                if b != a:
                    first = (i, b, a)
                    break
            res["logs"].append((gid, "FAIL",
                                "sha %s ≠ %s｜行数 %d vs %d｜首差 #%d：before=%r after=%r"
                                % (bg["logs_sha256"][:12], ag["logs_sha256"][:12],
                                   len(bg["logs"]), len(ag["logs"]),
                                   (first[0] if first else -1),
                                   (first[1] if first else ""),
                                   (first[2] if first else ""))))

        # ② 逐 cue 计数表
        cb, ca = bg["cue_counts"], ag["cue_counts"]
        miss = sorted(set(cb) - set(ca))
        extra = sorted(set(ca) - set(cb))
        bad = sorted(k for k in (set(cb) & set(ca)) if cb[k] != ca[k])
        for k, v in sorted(cb.items()):
            if v <= 0:
                res["zero_count"].append("G%d:%s=%d" % (gid, k, v))
        for k, v in sorted(ca.items()):
            if v <= 0:
                res["zero_count"].append("G%d:%s=%d(after)" % (gid, k, v))
        if not miss and not extra and not bad:
            res["counts"].append((gid, "PASS", "%d 键全等（渲染 %d 次）"
                                  % (len(cb), bg["renders_total"])))
        else:
            res["counts"].append((gid, "FAIL",
                                  "缺键 %s｜多键 %s｜计数不等 %s"
                                  % (miss or "-", extra or "-",
                                     ["%s %d→%d" % (k, cb[k], ca[k]) for k in bad] or "-")))

        # ③ to_state 逐键
        diffs = _diff_state(bg["state_flat"], ag["state_flat"])
        res["n_state_keys"] += len(bg["state_flat"])
        res["state"].append((gid, "PASS" if not diffs else "FAIL",
                             "%d 键，差 %d" % (len(bg["state_flat"]), len(diffs)), diffs))

        # 诊断面（不是判据）
        if bg["unmatched_renders"] or ag["unmatched_renders"]:
            res["notes"].append("G%d：渲染了但没进 logs 的行 before=%d after=%d"
                                % (gid, len(bg["unmatched_renders"]),
                                   len(ag["unmatched_renders"])))
        if bg["non_cue_count"] != ag["non_cue_count"]:
            res["notes"].append("G%d：非 cue 行数 before=%d after=%d"
                                % (gid, bg["non_cue_count"], ag["non_cue_count"]))

    res["covered"] = sorted(set(before.get("observed_keys") or ()))
    res["uncovered"] = sorted(before.get("uncovered_keys") or ())
    res["inventory_n"] = before.get("key_inventory_n") or 0
    res["verdict"] = ("RED" if (res["n_ok_sha"] != res["n_groups"]
                                or any(s[1] == "FAIL" for s in res["counts"])
                                or any(s[1] == "FAIL" for s in res["state"])
                                or res["zero_count"]) else "GREEN")
    return res


# ============================================================
# 报告
# ============================================================

def render_report(before: dict, after: dict, res: dict, inject: str) -> str:
    L = []
    add = L.append
    add("=" * 78)
    add("cue 冻结尺子 · 对拍报告（%s）" % SCHEMA)
    add("=" * 78)
    add("before : %s  @%s" % (before["tree"], before["tree_head"]))
    add("after  : %s  @%s" % (after["tree"], after["tree_head"]))
    add("脚本   : %d 组 × %d 步（种子 %s）  --inject %s"
        % (res["n_groups"], before["steps"], list(SEEDS), inject))
    add("")
    add("[1/3] logs 逐字节 sha256（%d 组必须全等）" % res["n_groups"])
    for gid, st, info in res["logs"]:
        add("   %s G%d  %s" % ("√" if st == "PASS" else "×", gid, info))
    add("")
    add("[2/3] 逐 cue 计数表（逐键相等，且每条 ≥1）")
    for gid, st, info in res["counts"]:
        add("   %s G%d  %s" % ("√" if st == "PASS" else "×", gid, info))
    for line in res["zero_count"]:
        add("   × 计数为 0 的键：%s" % line)
    add("")
    add("[3/3] to_state 逐键 diff（%d 键）" % res["n_state_keys"])
    for gid, st, info, diffs in res["state"]:
        add("   %s G%d  %s" % ("√" if st == "PASS" else "×", gid, info))
        for path, kind, detail in diffs[:40]:
            add("        [%s] %s: %s" % (kind, path, detail))
        if len(diffs) > 40:
            add("        … 另有 %d 条" % (len(diffs) - 40))
    add("")
    add("附 · 覆盖（信息面，非判据）")
    add("   引擎侧键化调用点唯一 key：%d；本尺子打到：%d"
        % (res["inventory_n"], len(res["covered"])))
    if res["uncovered"]:
        add("   未打到（%d）：%s" % (len(res["uncovered"]), ", ".join(res["uncovered"])))
    for g in before["groups"]:
        add("   非 cue 行 G%d：%d 行（样本：%s）"
            % (g["gid"], g["non_cue_count"],
               " ／ ".join(g["non_cue_samples"]) or "-"))
    for line in res["notes"]:
        add("   ! %s" % line)
    add("")
    add("-" * 78)
    add("判据：logs sha256 全等 %d/%d · 计数表 %d/%d · state 差异 %d 键"
        % (res["n_ok_sha"], res["n_groups"],
           sum(1 for s in res["counts"] if s[1] == "PASS"), res["n_groups"],
           sum(len(s[3]) for s in res["state"])))
    add("verdict: %s" % res["verdict"])
    if res["verdict"] == "RED":
        add("红因：")
        if res["n_ok_sha"] != res["n_groups"]:
            add("   · logs 不是逐字节相同（顺序/增删/文案变）")
        for gid, st, info in res["counts"]:
            if st == "FAIL":
                add("   · G%d 逐 cue 计数表不等：%s" % (gid, info))
        for gid, st, info, diffs in res["state"]:
            if st == "FAIL":
                add("   · G%d to_state 有 %d 键差异（见上）" % (gid, len(diffs)))
        for line in res["zero_count"]:
            add("   · 计数 0（该组没打到它 ⇒ 等价性未验证）：%s" % line)
    add("-" * 78)
    return "\n".join(L)


# ============================================================
# CLI
# ============================================================

_MSYS_RX = re.compile(r"^/([A-Za-z])/(.*)$")


def _norm_path(p: str) -> str:
    """git-bash 风格 `/c/Users/...` → 原生 `C:/Users/...`。

    原生程序（python.exe 自身）不做 MSYS 路径转换，传 `/c/...` 会「不是目录」，
    这里一次性抹平，免得尺子在 git-bash 里被路径坑。
    """
    m = _MSYS_RX.match(str(p or ""))
    return (m.group(1).upper() + ":/" + m.group(2)) if m else str(p)


def _collect_subprocess(tree: str, inject: str, out_path: str) -> None:
    """在独立解释器里采集一棵树（两棵树必须各自新进程：同名模块不可双载）。"""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, os.path.abspath(__file__),
           "--collect", os.path.abspath(tree), "--out", out_path,
           "--inject", inject]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace", timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError("采集失败（%s）：\n%s\n%s"
                           % (tree, proc.stdout[-2000:], proc.stderr[-4000:]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="cue 迁移冻结尺子（logs / state / 逐 cue 计数表 三通道对拍）")
    ap.add_argument("--before", help="基线工作区路径")
    ap.add_argument("--after", help="待验工作区路径")
    ap.add_argument("--inject", default="none", choices=("none", "reorder", "drop"),
                    help="反证开关：reorder=对调两条日志 / drop=丢掉一条日志")
    ap.add_argument("--json", default=None, help="对拍结果 JSON 输出路径（留档）")
    ap.add_argument("--collect", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--out", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    # ---- 内部模式：采集一棵树 ----
    if args.collect:
        if not args.out:
            print("--collect 需要 --out", file=sys.stderr)
            return 2
        data = collect(args.collect, inject=args.inject)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=1)
        print("collected %s" % os.path.abspath(args.collect))
        return 0

    if not args.before or not args.after:
        ap.error("--before 与 --after 都要给（同树自洽也照样给两次）")
    args.before, args.after = _norm_path(args.before), _norm_path(args.after)
    if args.json:
        args.json = _norm_path(args.json)
    for t in (args.before, args.after):
        if not os.path.isdir(t):
            print("不是目录：%s" % t, file=sys.stderr)
            return 2

    tmp = tempfile.mkdtemp(prefix="cuefreeze_")
    try:
        pb, pa = os.path.join(tmp, "before.json"), os.path.join(tmp, "after.json")
        _collect_subprocess(args.before, "none", pb)
        _collect_subprocess(args.after, args.inject, pa)
        with open(pb, encoding="utf-8") as fh:
            before = json.load(fh)
        with open(pa, encoding="utf-8") as fh:
            after = json.load(fh)
        res = compare(before, after)
        print(render_report(before, after, res, args.inject))
        if args.json:
            _jdir = os.path.dirname(os.path.abspath(args.json))
            if _jdir and not os.path.isdir(_jdir):
                os.makedirs(_jdir, exist_ok=True)
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({
                    "schema": SCHEMA,
                    "before": {"tree": before["tree"], "head": before["tree_head"]},
                    "after": {"tree": after["tree"], "head": after["tree_head"]},
                    "inject": args.inject,
                    "steps": before["steps"], "seeds": list(SEEDS),
                    "verdict": res["verdict"],
                    "logs_sha256": {str(g["gid"]): g["logs_sha256"] for g in before["groups"]},
                    "logs_sha256_after": {str(g["gid"]): g["logs_sha256"] for g in after["groups"]},
                    "logs_lines": {str(g["gid"]): len(g["logs"]) for g in before["groups"]},
                    # ★ 留档：基线侧的逐行原始文本 + 归一化状态逐键表（下批对拍直接可查）
                    "logs": {str(g["gid"]): g["logs"] for g in before["groups"]},
                    "state_flat": {str(g["gid"]): g["state_flat"] for g in before["groups"]},
                    "non_cue": {str(g["gid"]): {"count": g["non_cue_count"],
                                                "samples": g["non_cue_samples"]}
                                for g in before["groups"]},
                    "cue_counts": {str(g["gid"]): g["cue_counts"] for g in before["groups"]},
                    "cue_counts_union": {k: sum(g["cue_counts"].get(k, 0) for g in before["groups"])
                                         for k in res["covered"]},
                    "checks": {"groups": res["n_groups"],
                               "logs_pass": res["n_ok_sha"],
                               "counts_pass": sum(1 for s in res["counts"] if s[1] == "PASS"),
                               "state_keys": res["n_state_keys"],
                               "state_diffs": sum(len(s[3]) for s in res["state"]),
                               "zero_count": res["zero_count"],
                               "notes": res["notes"]},
                    "coverage": {"inventory_n": res["inventory_n"],
                                 "covered": res["covered"], "uncovered": res["uncovered"]},
                    "state_diff_detail": [{"gid": gid, "path": p, "kind": k, "detail": d}
                                          for gid, _st, _i, dd in res["state"]
                                          for (p, k, d) in dd],
                }, fh, ensure_ascii=False, sort_keys=True, indent=1)
            print("json → %s" % args.json)
        return 0 if res["verdict"] == "GREEN" else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
