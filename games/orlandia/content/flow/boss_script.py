# -*- coding: utf-8 -*-
"""包内 Boss 剧本导演（`content/flow/boss_script.py`）—— 逐字搬自游戏仓
`game/commands/boss_script.py`（737 行），只改「import 层 + 宿主耦合 → 调用方传参」两类东西。

真源（只读，未改一行）：`qqbot/data/plugins/dragonfall/game/commands/boss_script.py`
对照/验收：`overnight/d3_flow_verify.py`（同一输入下与真源逐项相等）

① import 层改动（逐行对拍见验收【1】节）
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import content as C`（:27 / :475 / :487） | `_mods_of(data)` / `_insts_of(data)` | 宿主内容聚合层 → **包内 JSON 数据口**（默认口见 ②），可被调用方换 |
| `from ..data.boss_phases import merge_phase_config`（:193） | 调用方传 `phase_templates=` | 阶段模板表（`game/data/boss_phases.py` 的 `BOSS_PHASE_TEMPLATES`）**未进包** → 缺口 |
| `from saintess_engine.*`（:229 :408 :431 :718） | 同左 | 引擎侧；包可直接依赖 |
| `actor` / `st` / `battle` | 同左 | 本来就是调用方传的对象 |

② 宿主耦合替身接口（调用方传什么 / 缺省行为）
| 真源宿主耦合 | 包内替身 | 调用方传什么 | 缺省（不传） |
|---|---|---|---|
| `C.MONSTER_MODS` | `data.MONSTER_MODS` | 普通对象或 `dict`：怪 id → mods dict | 包内 `content/data/monster_roster.json[*].mods`（与真源 140 条逐项相等） |
| `C.INSTANCES` | `data.INSTANCES` | 同上：副本 id → 副本 dict | 包内 `content/data/instances.json` |
| `C.build_monster`（宿主 `game/core/drops.py:389`） | `build_monster=` | `callable(tpl_tuple, map_obj) -> mon dict` | **None** → 走真源自带的兜底（Boss×0.2，:494-504 原路径）；该构造器**未进包** = 缺口 |
| `..data.boss_phases.merge_phase_config` | `phase_templates=` | `callable(phase_id, overrides) -> dict` | **None** → 与真源 import 失败同分支（`_merged = None`） |
| 存档 `st["boss_script"]`（宿主持久化） | 同左 | 调用方给的普通 dict（宿主落库/序列化/迁移） | —— |
| `battle.script_hook` / `battle.on_event` 挂载（宿主 `instance_battle.py:206-224`） | 同左 | 宿主把 `make_script_hook(st[, …])` / `make_script_event(st[, …])` 挂到引擎 `Battle` | —— |

③ 文案缺口（**未改，逐字保留**）：真源的演出/日志文案全是硬编码 f-string，包内
`content/data/texts.json`（233 槽位）**没有**任何剧本槽位（无 `instance.剧本_*` 之类）。
按"无现成槽位先记缺口、不自造 API"处理 → 本文件不新增文案表，缺口清单见
`overnight/d3-flow-port.md` §4。真源行号（逐条可查）：
:180 阈值预告 / :202-203 转阶段演出 / :214 atk 提升 / :222 换招 / :302 开场 / :309 :316 :327
开场效果 / :366 :372 低血 / :404 叠层 / :412 治疗 / :426 狂暴 / :531 召唤 / :535 召唤联动 /
:588 连招 / :656 反伤 / :682 :689 打断 / :722 :730 :735 爪牙死亡。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))            # <pkg>/content/flow
_DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")      # <pkg>/content/data


def _read_json(name: str, default):
    """读包内数据域 `content/data/<name>`（缺文件/坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


class PackageData:
    """包内数据口（默认口）—— 真源 `game.content` 聚合层里剧本要用的两样东西。

    - `MONSTER_MODS` ≡ `monster_roster.json[<怪 id>]["mods"]`（怪 id → mods dict）
    - `INSTANCES`    ≡ `instances.json`（副本 id → 副本 dict，含 phases/mech/minions 内联）
    """

    def __init__(self, mods: dict, instances: dict):
        self.MONSTER_MODS = mods
        self.INSTANCES = instances


_DEFAULT_DATA = None


def _default_data() -> PackageData:
    global _DEFAULT_DATA
    if _DEFAULT_DATA is None:
        roster = _read_json("monster_roster.json", {}) or {}
        _DEFAULT_DATA = PackageData(
            {k: (v or {}).get("mods") for k, v in roster.items() if (v or {}).get("mods")},
            _read_json("instances.json", {}) or {},
        )
    return _DEFAULT_DATA


def _pick(obj, name: str, default=None):
    """数据口取值：认属性（对象）也认键（dict）；对象为空 → default。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _mods_of(data=None):
    return _pick(data if data is not None else _default_data(), "MONSTER_MODS", {}) or {}


def _insts_of(data=None):
    return _pick(data if data is not None else _default_data(), "INSTANCES", {}) or {}



def boss_script_cfg(st: dict, actor: dict, data=None):
    """解析 Boss 剧本配置（MONSTER_MODS 基准 + INSTANCES 副本覆盖，v178 E1/E2）。

    输入 actor（saintess_engine enemy side actor，monster_to_actor 透传 id/_inst_id）。
    返回 None（无 phases 剧本）或 cfg dict（含缺省 key，opening/triggers/chains
    供 P2+ 批读取；P1 只消费 phases）。
    """
    bid = actor.get("id") or actor.get("uid") or ""
    if not bid:
        return None
    try:
        mods = _mods_of(data).get(bid) or {}
        cfg = {
            "opening": mods.get("opening"),
            "triggers": mods.get("triggers") or {},
            "phases": list(mods.get("phases") or []),
            "chains": mods.get("chains"),
            "on_interrupt": mods.get("on_interrupt"),
            "on_minion_died": mods.get("on_minion_died"),
        }
        _mech = [x.strip() for x in str(mods.get("mech") or "").split(",") if x.strip()]
        # v178 E1：副本 Boss 带 _inst_id → 副本条目 phases/opening/triggers/chains 覆盖
        # （battle.py _boss_cfg 同款：副本优先，整体覆盖——v178 后 inst 内联是权威）
        iid = actor.get("_inst_id") or st.get("inst_id") or ""
        _insts = _insts_of(data)
        if iid and _insts.get(iid):
            inst2 = _insts[iid]
            for k in ("opening", "triggers", "phases", "chains"):
                if inst2.get(k) is not None:
                    cfg[k] = inst2[k]
            # v178 E2：mech token 并集去重（MONSTER_MODS + inst 内联，非覆盖）
            _inst_mech = [x.strip() for x in str(inst2.get("mech") or "").split(",")
                          if x.strip()]
            _mech = list(dict.fromkeys(_mech + _inst_mech))
        cfg["mech"] = _mech
        # 剧本要素门槛（P1 只认 phases；P2-P4 扩展后任一要素即可挂导演/观察者）
        _has_script = bool(cfg["phases"]) or bool(cfg["opening"]) or bool(cfg["chains"]) \
            or bool(cfg["on_interrupt"]) or bool(cfg["on_minion_died"]) \
            or any(t in _mech for t in ("phase_open", "player_low", "summon",
                                        "stacks", "heal", "enrage", "shield",
                                        "reflect"))
        if not _has_script:
            return None
        return cfg
    except Exception:
        return None


def _phase_threshold(phases: list, pc: int) -> float:
    """第 pc 阶段进下一阶段阈值（ratio 0-1）：有 phases[pc].min 用 min/100
    （设计 60%/30%），否则回退 0.5**(pc+1)（50%/25%）——旧 _phase_threshold 同款。"""
    if pc < len(phases):
        mn = (phases[pc] or {}).get("min")
        if mn is not None:
            try:
                return float(mn) / 100.0
            except Exception:
                pass
    return 0.5 ** (pc + 1)


def _phase_cleanse_negatives(actor: dict, logs: list) -> None:
    """转阶段净化：移除 effects 容器负面条目（preserve_debuffs=False 时）。
    P1 简化：只清明确标记的负面（无 cleanse 语义反向推断——不动控制/周期，
    防误清 Boss 自身状态）。全清变体等 P2 盘点 EFFECT_RULES 时细化。"""
    # P1 占位：V 系列负面键反向推断风险高，默认保留（preserve_debuffs=True 语义），
    # 模板显式 False 时清 adapt/减速等明确负面由 P2 盘点后实现
    return


def make_script_hook(st: dict, *, data=None, phase_templates=None,
                  build_monster=None):
    """导演帧闭包工厂：callable(battle, actor, logs) -> bool（True=拦截本刻行动）。

    只处理"当前行动 actor 是剧本 Boss"的情况（一次一帧只查当前行动者，
    天然避免多怪重复触发）。导演状态 st["boss_script"] 首次调用初始化。
    """
    def hook(battle, actor, logs):
        try:
            if int(actor.get("hp", 0) or 0) <= 0:
                return False
            if not _looks_like_boss(actor):
                return False
            cfg = boss_script_cfg(st, actor, data)
            if not cfg:
                return False
            bs = st.get("boss_script")
            if not isinstance(bs, dict):
                bs = st["boss_script"] = _new_script_state()
            bs["round_no"] = int(bs.get("round_no", 0) or 0) + 1
            _now = float(getattr(battle, "_now", 0) or 0)
            # P5：vulnerable 破绽到期清理（on_interrupt 联动时效）
            _check_vuln_expire(st, battle, actor, bs)
            # P2：开场技（第一帧 once）
            _check_opening(st, battle, actor, cfg, bs, _now, logs)
            # P2：条件反制（player_low 玩家低血追击）
            _check_player_low(st, battle, actor, cfg, bs, _now, logs)
            # P2：简单机制 token（stacks/heal/enrage/shield 补漏——phases 未覆盖的）
            _check_simple_mech(st, battle, actor, cfg, bs, _now, logs)
            # P3：召唤援军（CD 5 刻 / 上限 3 / v163 同图小怪模板）
            _check_summon(st, battle, actor, cfg, bs, _now, logs,
                          data=data, build_monster=build_monster)
            # P1：phases 转阶段（返回 True = 演出刻拦截本刻行动）
            _skip = _check_phases(st, battle, actor, cfg, bs, logs,
                                   phase_templates=phase_templates)
            # P4a：连招链 chains（仅在非演出刻帧推进——演出刻本刻不行动）
            if not _skip:
                _check_chains(st, battle, actor, cfg, bs, _now, logs)
            return _skip
        except Exception:
            return False
    return hook


def _looks_like_boss(actor: dict) -> bool:
    """剧本 Boss 快速判定：role=boss/is_boss 或带 _inst_id（副本 Boss 上下文）。"""
    if actor.get("role") == "boss" or actor.get("is_boss"):
        return True
    if actor.get("_inst_id"):
        return True
    return False


def _new_script_state() -> dict:
    return {
        "phase_count": 0,
        "round_no": 0,
        "summon_cd": 0,
        "summoned": [],
        "flags": {},
        "chain_i": 0,
        "chain_cd": 0,
    }


def _check_phases(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                  logs: list, *, phase_templates=None) -> bool:
    """phase 转阶段检查：血量 < 阈值 → 触发（演出/换招/atk 乘区/演出刻 skip）。

    对齐旧 _b_phase（battle_mech.py:698）：
    - 阈值：phases[pc].min（缺省 0.5^n）；pc<3
    - 阈值预告：pc>0 且血量在下一阈值 +3% 内 → 提前 warn（once）
    - 演出：phases[npc-1].script name/icon
    - 换招：add_skills 幂等 append 进 actor.skills + auto_act 切阶段主技能
    - atk 乘区：phases 条目/模板 atk_mult（覆盖式），无 → 旧行为 1+0.2×npc
    - 阶段模板：phase_id → boss_phases.merge_phase_config（preserve_debuffs 等）
    - 演出刻：返回 True（引擎 actor_auto 拦截本刻行动，照推 ct）
    """
    phases = cfg["phases"] or []
    pc = int(bs.get("phase_count", 0) or 0)
    if pc >= len(phases):
        return False
    hp = int(actor.get("hp", 0) or 0)
    mh = int(actor.get("max_hp", 1) or 1)
    if mh <= 0:
        return False
    ratio = hp / mh
    target = _phase_threshold(phases, pc)
    name = actor.get("name", "")
    # ---- 阈值预告（阶段 2/3 起）：接近下一阈值 +3% 提前 2 刻口径输出 ----
    if pc > 0:
        nxt = _phase_threshold(phases, pc)
        within = 0.03
        warned = (bs.setdefault("flags", {})).get("_phase_warned") or []
        if nxt <= ratio <= nxt + within and (pc + 1) not in warned:
            warned = list(warned) + [pc + 1]
            bs["flags"]["_phase_warned"] = warned
            logs.append(f"⚠️ 【{name}】的气息开始紊乱……似乎要进入更凶猛的阶段了！")
    if ratio >= target or pc >= 3:
        return False
    npc = pc + 1
    bs["phase_count"] = npc
    flags = bs.setdefault("flags", {})
    flags["_phase_warned"] = list(flags.get("_phase_warned") or []) + [npc]
    _ph = phases[npc - 1] if npc - 1 < len(phases) else {}
    # ---- 阶段模板合并（phase_id → boss_phases 模板 + 内联覆盖）----
    _merged = None
    try:
        _pid = (_ph or {}).get("phase_id")
        if _pid and phase_templates is not None:
            _merged = phase_templates(_pid, _ph)
    except Exception:
        _merged = None
    # ---- 演出文案 ----
    script = (_ph or {}).get("script") or (_merged or {}).get("script") or {}
    sname = script.get("name")
    icon = script.get("icon", "🔥")
    if sname:
        logs.append(f"{icon}【{name}】{sname}！")
    logs.append(f"🔥【{name}】进入第 {npc + 1} 阶段！力量再度攀升！")
    # ---- atk 乘区（覆盖式：entry/模板 atk_mult；无 → 旧行为 1+0.2×npc）----
    am = None
    if _merged is not None and (_merged.get("atk_mult") or 1.0) != 1.0:
        am = float(_merged.get("atk_mult"))
    if am is None and (_ph or {}).get("atk_mult") is not None:
        am = float(_ph["atk_mult"])
    if am is None:
        am = 1.0 + 0.2 * npc
    if abs(am - 1.0) > 0.001:
        _apply_atk_phase(actor, am, npc)
        logs.append(f"⚔️【{name}】攻击力提升至 {am:.2f} 倍！")
    # ---- 换招：add_skills 幂等 append + auto_act 切阶段主技能 ----
    adds = list((_merged or {}).get("add_skills") or (_ph or {}).get("add_skills") or [])
    for s in adds:
        if s and s not in (actor.get("skills") or []):
            actor["skills"] = list(actor.get("skills") or []) + [s]
    if adds:
        actor["auto_act"] = {"act": {"type": "skill", "skill": adds[0]}}
        logs.append(f"🎯【{name}】使出了新招【{adds[0]}】！")
    # ---- 异常净化（模板 preserve_debuffs=False 才清；默认保留 50% 语义 P1 简化为全保留）----
    if _merged is not None and _merged.get("preserve_debuffs") is False:
        _phase_cleanse_negatives(actor, logs)
    # ---- 阶段事件广播（v181 破绽条：挂敌身条按阶段保留部分积蓄——订阅方 bar_preserve）----
    # 引擎零知识：引擎只提供通用时机事件，条侧消费端在装配层（battle_bar_procs）
    try:
        from saintess_engine.battle.effect_triggers import fire as _fire
        _fire(battle, "phase", {"actor": actor, "phase": npc}, logs)
    except Exception:
        pass  # 阶段事件异常不阻断转阶段（容错铁律）
    # ---- 演出刻：本刻不行动（引擎 actor_auto 收到 True 拦截）----
    return True


def _apply_atk_phase(actor: dict, am: float, npc: int) -> None:
    """阶段 atk 乘区 → actor effects（面板快照型：stat/op/mult 内嵌，无需规则注册）。

    stats._apply_effects 折算：entry {stat:"atk", op:"mul", mult:am} → atk ×am；
    matk 同乘（旧行为 atk/matk +20%/阶段双乘）。key=boss_phase_atk 覆盖式
    （后阶段覆盖前阶段，非叠乘——模板 atk_mult 是相对常态的最终乘区）。
    """
    ef = actor.setdefault("effects", {})
    ef["boss_phase_atk"] = {"stat": "atk", "op": "mul", "mult": am, "stacks": 1,
                            "phase": npc}
    ef["boss_phase_matk"] = {"stat": "matk", "op": "mul", "mult": am, "stacks": 1,
                             "phase": npc}


# ============================================================
# P2：开场技 / 条件反制 / 简单机制 token
# 数值权威 = 04 章怪物图鉴二.5 机制表 + battle_config BUFF_STATS（旧 buff 强度）
# ============================================================

def _buff_stat_mult(effect: str):
    """旧 buff effect → 面板乘区（battle_config BUFF_STATS 同源值，零新数值）。"""
    _tbl = {
        "atk_up": ("atk", 1.30), "atk_up_strong": ("atk", 1.70),
        "mon_atk_up": ("atk", 1.30), "mon_atk_up_strong": ("atk", 1.70),
        "mon_atk_down": ("atk", 0.70), "atk_down": ("atk", 0.70),
    }
    return _tbl.get(effect)


def _temp_stat_mult(actor: dict, key: str, stat: str, mult: float, secs: float,
                    now: float) -> None:
    """临时乘区 buff（effects 面板快照型，expire=now+secs——引擎 _settle 到期删）。"""
    ef = actor.setdefault("effects", {})
    ef[key] = {"stat": stat, "op": "mul", "mult": float(mult), "stacks": 1,
               "expire": now + max(0.1, float(secs))}


def _check_opening(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                   now: float, logs: list) -> None:
    """开场技（mech phase_open / cfg.opening）：第一帧 once——演出 + effect 翻译。

    对齐旧 _b_opening（battle_mech.py:800）：r==1 且未 _open_played。
    effect 翻译（数值 battle_config BUFF_STATS）：
      atk_up/atk_up_strong → Boss atk ×1.30/×1.70，持续 power 刻（秒）
      mon_atk_down         → 玩家侧 atk ×0.70，持续 power 刻
      mortal_wound         → 玩家侧重创条目（saintess_engine 吸血批落地时消费减半；
                            当前装配吸血未迁 saintess_engine——条目先落预留）
    无 opening 配置的 phase_open token → 缺省咆哮演出（atk_up ×1.30）。
    """
    mech = cfg.get("mech") or []
    if "phase_open" not in mech:
        return
    if bs.get("round_no", 0) != 1:
        return
    flags = bs.setdefault("flags", {})
    if flags.get("_open_played"):
        return
    flags["_open_played"] = True
    op = cfg.get("opening") or {}
    if isinstance(op, str):
        op = {"name": op}
    name = op.get("name") or "咆哮"
    effect = str(op.get("effect") or "atk_up").lower()
    power = float(op.get("power", 2.0) or 2.0)
    bname = actor.get("name", "")
    logs.append(f"🌪️【{bname}】发出震天【{name}】！气势瞬间拉满！")
    _mult_info = _buff_stat_mult(effect)
    if _mult_info and effect in ("atk_up", "atk_up_strong", "mon_atk_up",
                                 "mon_atk_up_strong"):
        stat, mult = _mult_info
        _temp_stat_mult(actor, "boss_open_atk", stat, mult, power, now)
        _temp_stat_mult(actor, "boss_open_matk", "matk", mult, power, now)
        logs.append(f"⚡【{bname}】的{name}让攻击力提升了！")
    elif _mult_info and effect in ("mon_atk_down", "atk_down"):
        stat, mult = _mult_info
        for a in battle.sides_of("player"):
            if int(a.get("hp", 0) or 0) <= 0:
                continue
            _temp_stat_mult(a, "boss_open_atk_down", stat, mult, power, now)
        logs.append(f"🫁【{bname}】的{name}压制了你，攻击下降！")
    elif effect == "mortal_wound":
        # v1.3 重创：吸血/治疗偷取减半（saintess_engine 吸血批落地时消费此条目减半）
        for a in battle.sides_of("player"):
            if int(a.get("hp", 0) or 0) <= 0:
                continue
            ef = a.setdefault("effects", {})
            old = ef.get("mortal_wound") or {}
            ef["mortal_wound"] = {"stacks": 1,
                                  "expire": max(float(old.get("expire", 0) or 0),
                                                now + power)}
        logs.append(f"🤕【{bname}】的{name}重创了你！吸血效果减半（{int(power)} 刻）！")
    # 其他 effect：演出照出（P5 原语盘点标注，不静默吞）


def _check_player_low(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                      now: float, logs: list) -> None:
    """玩家低血追击（mech player_low / triggers.player_low）：任一存活玩家
    hp/max < 阈值 → 演出 + 本刻攻击加成 25%（旧 _b_player_low）。

    频率：once；triggers.player_low.cooldown=N 可重复（每 N 刻一次）。
    阈值：triggers.player_low.hp（缺省 0.30）。旧加成消费在伤害处（本刻）；
    saintess_engine 表达 = 临时 atk/matk ×1.25（expire 短——下次时刻推进即过期，
    仅本帧行动吃到）。
    """
    mech = cfg.get("mech") or []
    trig = (cfg.get("triggers") or {}).get("player_low") or {}
    if "player_low" not in mech and not trig:
        return
    thresh = float(trig.get("hp", 0.30) or 0.30)
    cooldown = int(trig.get("cooldown", 0) or 0)
    flags = bs.setdefault("flags", {})
    low = False
    for a in battle.sides_of("player"):
        mh = int(a.get("max_hp", 0) or 0)
        if mh <= 0:
            continue
        if int(a.get("hp", 0) or 0) / mh < thresh:
            low = True
            break
    if not low:
        return
    cd = int(flags.get("_low_hp_cd", 0) or 0)
    if flags.get("_low_hp_fired"):
        if cooldown <= 0:
            return
        if cd > 0:
            flags["_low_hp_cd"] = cd - 1
            return
        flags["_low_hp_cd"] = cooldown
        logs.append(f"☠️ 【{actor.get('name','')}】盯上了重伤的你，狞笑着扑来！(追击)")
        _temp_stat_mult(actor, "boss_low_atk", "atk", 1.25, 0.1, now)
        return
    flags["_low_hp_fired"] = True
    if cooldown > 0:
        flags["_low_hp_cd"] = cooldown
    logs.append(f"☠️ 【{actor.get('name','')}】盯上了重伤的你……本刻攻击大幅提升！")
    _temp_stat_mult(actor, "boss_low_atk", "atk", 1.25, 0.1, now)
    _temp_stat_mult(actor, "boss_low_matk", "matk", 1.25, 0.1, now)


def _check_simple_mech(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                       now: float, logs: list) -> None:
    """简单机制 token（04 章机制表，phases 未覆盖才补）：
      stacks：每 2 刻 +1（上限 5，每层 atk/matk +8%）
      heal  ：每 4 刻回复 8% 生命
      enrage：血量 <30%（一次）atk/matk +35%——若 phases 含 enrage 阶段则 phases 管
      shield：开战一次获得 20% 生命护盾（halve：盾存在受伤减半，landing 消费）
    """
    mech = cfg.get("mech") or []
    if not mech:
        return
    rn = int(bs.get("round_no", 0) or 0)
    mh = int(actor.get("max_hp", 1) or 1)
    hp = int(actor.get("hp", 0) or 0)
    name = actor.get("name", "")
    # ---- stacks：每 2 刻 +1（cap 5）----
    if "stacks" in mech and rn > 0 and rn % 2 == 0:
        n = int(bs.get("stacks_n", 0) or 0)
        if n < 5:
            n += 1
            bs["stacks_n"] = n
            mult = 1.0 + 0.08 * n
            ef = actor.setdefault("effects", {})
            ef["boss_mech_stacks_atk"] = {"stat": "atk", "op": "mul",
                                          "mult": mult, "stacks": 1}
            ef["boss_mech_stacks_matk"] = {"stat": "matk", "op": "mul",
                                           "mult": mult, "stacks": 1}
            logs.append(f"⚔️【{name}】气势攀升，攻击叠层＋1({n}/5)")
    # ---- heal：每 4 刻回复 8% ----
    if "heal" in mech and rn > 0 and rn % 4 == 0:
        try:
            from saintess_engine.battle.landing import heal_actor as _heal
            v = max(1, int(mh * 0.08))
            real = _heal(battle, actor, v, logs)
            if real > 0:
                logs.append(f"💚【{name}】愈合伤口，恢复 {real} 点生命！")
        except Exception:
            pass
    # ---- enrage：血<30% once（phases 含 enrage phase → 跳过，P1 已管）----
    if "enrage" in mech:
        _ph_ids = [str((p or {}).get("phase_id", "")) for p in (cfg.get("phases") or [])]
        if "enrage" not in _ph_ids and not bs.get("flags", {}).get("_enraged"):
            if mh > 0 and hp / mh < 0.30:
                bs.setdefault("flags", {})["_enraged"] = True
                ef = actor.setdefault("effects", {})
                ef["boss_enrage_atk"] = {"stat": "atk", "op": "mul",
                                         "mult": 1.35, "stacks": 1}
                ef["boss_enrage_matk"] = {"stat": "matk", "op": "mul",
                                          "mult": 1.35, "stacks": 1}
                logs.append(f"🔥【{name}】陷入狂暴，攻击大幅提升！(×1.35)")
    # ---- shield：开战一次 20% 护盾（halve 盾存在受伤减半）----
    if "shield" in mech and not bs.get("flags", {}).get("_shielded"):
        bs.setdefault("flags", {})["_shielded"] = True
        try:
            from saintess_engine import effects as _EF
            _EF.act_shield(battle, actor, actor, {"pct": 0.20, "halve": True,
                                                 "turns": 999}, logs)
        except Exception:
            pass


# ============================================================
# P3：召唤援军（mech summon / v163 口径）
# 数值权威 = 04 章机制表召唤行 + 旧 _summon_minions（battle.py:9791）：
# - CD 5 刻、单次 1 只、场上援军上限 3（含开怪自带爪牙，满员不再召）
# - 召唤物 = 该副本怪池同等级普通怪模板（INSTANCES[iid].minions[0].monster，
#   C.build_monster 构建），不从 Boss 比例缩放；非 instance 回落 Boss×0.2
# - 召唤物：uid 唯一、rank1/reach1、is_minion=True、is_boss/is_elite False、
#   mech=""（防多怪重复触发剧本）、auto_act 缺省普攻
# - 召唤物入场插 enemy side 队首（M-W2s 前排挡刀：存活第一名 = 新援军，
#   默认目标/a1 先打它——旧 append 尾部 = 后排不挡刀）
# - 召唤成功 → Boss 攻击联动（旧 mon_atk_up 2 刻 = atk×1.30，线上行为）
# ============================================================

def _check_summon(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                  now: float, logs: list, *, data=None,
                  build_monster=None) -> None:
    mech = cfg.get("mech") or []
    if "summon" not in mech:
        return
    rn = int(bs.get("round_no", 0) or 0)
    if rn <= 1:
        return
    # CD 5 刻（SUMMON_MINION_CD，旧 r>1 且 r%5==0）
    _last = int(bs.get("summon_last", 0) or 0)
    if rn - _last < 5:
        return
    # 场上援军上限 3（含开怪自带爪牙：enemy side 存活 is_minion）——v163 定稿值
    # （N10 前由 battle_mech SUMMON_MINION_CAP 改为导演本地数据，battle_mech 将删）
    _alive_min = [u for u in battle.sides_of("enemy")
                  if u.get("is_minion") and int(u.get("hp", 0) or 0) > 0]
    if len(_alive_min) >= 3:
        return
    # ---- 召唤物模板：INSTANCES[iid].minions[0].monster（v163）----
    _tpl = None
    _tpl_name = "爪牙"
    _iid = str(st.get("inst_id") or "") or ""
    _boss_name = actor.get("name", "首领")
    try:
        _insts = _insts_of(data)
        if _iid and _insts.get(_iid):
            _mcfg = (_insts[_iid].get("minions") or [])
            if _mcfg and isinstance(_mcfg[0].get("monster"), (list, tuple)) \
                    and len(_mcfg[0]["monster"]) >= 6:
                _tpl = _mcfg[0]["monster"]
                _tpl_name = _mcfg[0].get("name") or (_tpl[1] if len(_tpl) > 1 else "爪牙")
    except Exception:
        _tpl = None
    m = None
    if _tpl is not None and build_monster is not None:
        try:
            m = build_monster(_tpl, {"id": _iid or "x", "name": _iid or "x",
                                     "area": "instance"})
        except Exception:
            m = None
    if m is not None:
        m = dict(m)
    # 非 instance/无模板 → 回落 Boss×0.2（旧兜底路径）
    if m is None:
        m = {
            "name": "爪牙", "role": "dps", "hp": max(1, int(actor.get("max_hp", 1) * 0.2)),
            "max_hp": max(1, int(actor.get("max_hp", 1) * 0.2)),
            "atk": max(1, int(actor.get("atk", 1) * 0.4)),
            "def": 10, "matk": 10, "mdef": 10, "spd": 80,
            "lv": actor.get("lv", 1), "rank": 1, "reach": 1,
            "drops": [], "exp": 0, "gold": 0, "effects": {}, "shields": {},
        }
        _tpl_name = "爪牙"
    seq = int(bs.get("summon_seq", 0) or 0) + 1
    bs["summon_seq"] = seq
    m["uid"] = f"e_min_{int(bs.get('summon_base', 0) or 0) + seq}"
    m["side"] = "enemy"
    m["name"] = f"{_boss_name}的{_tpl_name}"
    m["rank"] = 1
    m["reach"] = 1
    m["is_minion"] = True
    m["is_boss"] = False
    m["is_elite"] = False
    m["mech"] = ""
    m["ct"] = float(now) + 2.0  # 站场不插队当前行动
    m["effects"] = dict(m.get("effects") or {})
    m["shields"] = dict(m.get("shields") or {})
    # 入 enemy side：走引擎公开 API Battle.add_actor(front=True)。
    # ⚠️ 此前是手工 `battle.sides.setdefault("enemy", []).insert(0, m)`——只入容器，
    #    不建 actor["_skill_index"]（技能索引仅 Battle 构造期建一次）→ 援军的 ms_* 技能
    #    解析不到技能 dict，静默退化为普攻（22/22 副本援军模板均带技能，线上全覆盖）。
    #    add_actor 补齐索引 + 排程，且尊重 actor 已带的正 ct（下面 m["ct"] 自设不重播）。
    # M-W2s：front=True 插 side 队首（前排挡刀）——存活序列第一名即召唤物，
    # 玩家无指定目标的攻击/a1 编号都先打它（死亡单位残留队首时亦先于其判定，
    # 存活序不变）。append 尾部 = 排到 Boss/旧爪牙身后（=后排）不挡刀，
    # 与日志「它挡在身前！」矛盾。
    battle.add_actor(m, "enemy", front=True)
    bs["summon_last"] = rn
    bs.setdefault("summoned", []).append(m["uid"])
    logs.append(f"👥【{actor.get('name','')}】召唤了【{m['name']}】！它挡在身前！")
    # Boss 攻击联动（旧 mon_atk_up 2 刻 = atk×1.30，线上行为——策划案文字 +20% 为概数）
    try:
        _temp_stat_mult(actor, "boss_summon_atk", "atk", 1.30, 2.0, now)
        logs.append(f"⚡【{actor.get('name','')}】攻击也提升了！")
    except Exception:
        pass


# ============================================================
# P4a：连招链 chains（固定技能序列轮换）
# 语义对齐旧 v178 E7（battle.py:7999）：seq 按序推进到头回绕；cd=整链打完
# 冷却刻数（0=无缝循环）；break=断链概率（<1 时概率中断回随机池，缺省 0 必中链）；
# 多链按 chain_idx 取模轮换。引擎状态存导演 bs（chain_pos/chain_idx/chain_until）。
# saintess_engine 表达 = 导演帧改 actor.auto_act → 本帧 actor_auto 读它出招。
# ============================================================

def _check_chains(st: dict, battle, actor: dict, cfg: dict, bs: dict,
                  now: float, logs: list) -> None:
    chains = cfg.get("chains")
    if not isinstance(chains, list) or not chains:
        return
    if actor.get("charging"):
        return  # 读条中不出链（v178：charging 时不消费链）
    rn = int(bs.get("round_no", 0) or 0)
    _until = int(bs.get("chain_until", 0) or 0)
    if rn < _until:
        return  # 整链冷却中
    ci = int(bs.get("chain_idx", 0) or 0)
    ch = chains[ci % len(chains)]
    seq = (ch.get("seq") or []) if isinstance(ch, dict) else []
    if not seq:
        return
    pos = int(bs.get("chain_pos", 0) or 0)
    if pos >= len(seq):
        pos = 0
        bs["chain_idx"] = ci + 1
        ch = chains[bs["chain_idx"] % len(chains)]
        seq = (ch.get("seq") or []) if isinstance(ch, dict) else []
        if not seq:
            return
    # 断链（break>0 概率中断，链状态清空回随机池——saintess_engine 回落普攻/auto_act 原值）
    _brk = float(ch.get("break", 0.0) or 0.0)
    if _brk > 0:
        import random as _rnd
        if _rnd.random() < _brk:
            bs["chain_pos"] = 0
            bs.pop("chain_until", None)
            return
    s = seq[pos]
    if s:
        actor["auto_act"] = {"act": {"type": "skill", "skill": s}}
        bs["chain_pos"] = pos + 1
        if pos + 1 >= len(seq):
            _cd = int(ch.get("cd", 0) or 0)
            # 整链打完冷却：until = 当前帧 + cd + 1（cd=0 无缝；cd=1 隔 1 帧）
            bs["chain_until"] = rn + _cd + 1
            logs.append(f"⚔️【{actor.get('name','')}】连招轮转，准备下一轮攻势！")


# ============================================================
# P4b：爪牙死亡联动 on_minion_died（观察者，on_event on_death 消费）
# 配置样例（MONSTER_MODS）：
#   {"effect": "heal_pct", "value": 0.03}    → Boss 回 3% max
#   {"effect": "stacks_clear", "value": 1}   → 清叠层（stacks token 联动）
#   {"effect": "atk_up", "value": 2}         → Boss 攻击提升 2 刻（atk×1.30）
# ============================================================

def make_script_event(st: dict, *, data=None, phase_templates=None,
                     build_monster=None):
    """剧本事件观察者：on_event 尾部通知（命令层组合进现有观察者链）。

    与导演帧（make_script_hook）正交：本观察者处理响应型联动（爪牙死亡等），
    帧处理轮询型机制（phases/opening/低血/召唤/chains）。
    """
    def on_event(battle, evt_name, ctx, logs):
        try:
            if evt_name == "on_death":
                dead = (ctx or {}).get("actor") or {}
                if not dead.get("is_minion"):
                    return
                # 找剧本 Boss（enemy side 非爪牙有 on_minion_died 配置）
                for a in battle.sides_of("enemy"):
                    if a is dead or a.get("is_minion"):
                        continue
                    if int(a.get("hp", 0) or 0) <= 0:
                        continue
                    cfg = boss_script_cfg(st, a, data)
                    if not cfg or not cfg.get("on_minion_died"):
                        continue
                    _minion_death_link(st, battle, a, cfg["on_minion_died"], logs)
            elif evt_name == "interrupt":
                # N5B5c P5：读条打断 → on_interrupt 剧本联动（Boss 被断 → 反噬/破绽）
                hit = (ctx or {}).get("actor") or {}
                if int(hit.get("hp", 0) or 0) <= 0:
                    return
                cfg = boss_script_cfg(st, hit, data)
                if not cfg or not cfg.get("on_interrupt"):
                    return
                _interrupt_link(st, battle, hit, cfg["on_interrupt"], logs)
            elif evt_name == "on_taken":
                # N10-B3：Boss mech reflect 被动反伤（对齐旧 _boss_dmg_filter reflect 段）
                # 触发：剧本 Boss 受击（非 dot 无 source）且血<25% → 反弹 15% 给攻击者。
                boss = (ctx or {}).get("actor") or {}
                src = (ctx or {}).get("source") or {}
                if not boss or not src:
                    return  # dot/环境伤无 source 不反射（v1.3 语义）
                if int(boss.get("hp", 0) or 0) <= 0 or int(src.get("hp", 0) or 0) <= 0:
                    return
                if boss is src:
                    return
                cfg = boss_script_cfg(st, boss, data)
                if not cfg:
                    return
                mech = cfg.get("mech") or []
                if "reflect" not in mech:
                    return
                _mh = int(boss.get("max_hp", 1) or 1)
                if _mh <= 0 or int(boss.get("hp", 0) or 0) / _mh >= 0.25:
                    return
                rb = int(int(ctx.get("dmg", 0) or 0) * 0.15)
                if rb <= 0:
                    return
                # 反伤保底 1 HP（永不致死——旧引擎设计取舍：反伤是代价不是处决，
                # 避免残血玩家被反弹补刀挫败；04 章机制表仅写"反弹 15%"）
                src["hp"] = max(1, int(src.get("hp", 1) or 1) - rb)
                logs.append(f"🩸【{boss.get('name', '首领')}】龙鳞反伤！你受到 {rb} 点反弹伤害！")
        except Exception:
            pass
    return on_event


def _interrupt_link(st: dict, battle, boss: dict, link, logs: list) -> None:
    """读条打断联动执行。link = {"effect": ..., "value": ..., "turns": ...}。
    配置样例（MONSTER_MODS on_interrupt）：
      {"effect": "freeze_self", "value": 1, "turns": 1}   → Boss 自冻结（skip 1 刻）
      {"effect": "vulnerable",  "value": 1.2, "turns": 2} → Boss 承伤 ×1.2（2 帧）
    """
    try:
        if not isinstance(link, dict):
            return
        eff = str(link.get("effect") or "")
        val = link.get("value")
        turns = int(link.get("turns", 1) or 1)
        bname = boss.get("name", "")
        now = float(getattr(battle, "_now", 0) or 0)
        if eff == "freeze_self":
            ef = boss.setdefault("effects", {})
            old = ef.get("boss_frozen") or {}
            ef["boss_frozen"] = {"mode": "skip",
                                 "expire": max(float(old.get("expire", 0) or 0),
                                               now + turns)}
            logs.append(f"🧊【{bname}】的读条被打破，僵直了 {turns} 刻！")
        elif eff == "vulnerable":
            boss["_dmg_taken_mult"] = float(val if val is not None else 1.2)
            bs = st.get("boss_script")
            if isinstance(bs, dict):
                rn = int(bs.get("round_no", 0) or 0)
                bs.setdefault("flags", {})["_vuln_until"] = rn + max(1, turns)
            logs.append(f"💔【{bname}】读条被断，破绽大开（承伤提升）！")
    except Exception:
        pass


def _check_vuln_expire(st: dict, battle, actor: dict, bs: dict) -> None:
    """导演帧：vulnerable 破绽到期清理（round_no 到点移除 _dmg_taken_mult）。"""
    try:
        flags = bs.get("flags") or {}
        until = int(flags.get("_vuln_until", 0) or 0)
        if not until:
            return
        if int(bs.get("round_no", 0) or 0) >= until:
            actor.pop("_dmg_taken_mult", None)
            flags.pop("_vuln_until", None)
    except Exception:
        pass


def _minion_death_link(st: dict, battle, boss: dict, link, logs: list) -> None:
    """爪牙死亡联动执行。link = {"effect": ..., "value": ...}。"""
    try:
        if not isinstance(link, dict):
            return
        eff = str(link.get("effect") or "")
        val = link.get("value")
        bname = boss.get("name", "")
        if eff == "heal_pct":
            pct = float(val if val is not None else 0.03)
            from saintess_engine.battle.landing import heal_actor as _heal
            v = max(1, int(int(boss.get("max_hp", 1) or 1) * pct))
            real = _heal(battle, boss, v, logs)
            if real > 0:
                logs.append(f"💀 爪牙倒下，【{bname}】汲取残魂恢复 {real} 点生命！")
        elif eff == "stacks_clear":
            bs = st.get("boss_script")
            if isinstance(bs, dict):
                bs["stacks_n"] = 0
                ef = boss.get("effects") or {}
                ef.pop("boss_mech_stacks_atk", None)
                ef.pop("boss_mech_stacks_matk", None)
            logs.append(f"💀 爪牙倒下，【{bname}】的叠层强化消散了！")
        elif eff == "atk_up":
            turns = int(val if val is not None else 2)
            _temp_stat_mult(boss, "boss_minion_atk", "atk", 1.30, turns,
                            float(getattr(battle, "_now", 0) or 0))
            logs.append(f"💀 爪牙倒下，【{bname}】悲愤交加，攻击提升了！")
    except Exception:
        pass
