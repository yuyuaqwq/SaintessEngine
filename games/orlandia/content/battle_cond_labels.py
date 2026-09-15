# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**条件显示文案表**（逐字搬自游戏仓 `game/core/battle_cond_labels.py`，59 行）。

真源 = 技能详情面板「条件转化」行的文案源（46 键）：**纯数据 + lambda，零依赖、零 IO**，
故本文件 = 原文件正文逐字（不动一行），只加本头注。宿主 `game/core/battle_cond_labels.py`
现在是薄壳（一行再导出 `COND_LABELS`）。

分工（v181 拆分后的单源结构，照原注）：
* 判定在哪 → 游戏仓 `game/services/battle_cond_procs.py::COND_PREDICATES`（宿主）；
* 文案在哪 → 本模块 `COND_LABELS`（消费方：宿主 `game/commands/player.py` 技能详情）。

缺口：无（本模块零宿主耦合）。
"""
# -*- coding: utf-8 -*-
"""条件显示文案表 battle_cond_labels（技能详情面板「条件转化」行的文案源）。

分工（v181 拆分后的单源结构）：
- **判定**在哪 → `game/services/battle_cond_procs.py` 的 `COND_PREDICATES`
  （在战走装配层 `skill_cond_mult` 乘区钩子，挂 dmg_calc / heal_calc；引擎零改动）
- **文案**在哪 → 本模块 `COND_LABELS`（消费方：`game/commands/player.py` 技能详情）

历史：本表原与判定函数同处 `core/battle_conds.py`（v98.4 注册表）。v181 期间
判定侧整体迁往 battle_cond_procs（旧 `COND_CHECKS` 在 saintess_engine 零消费方、
且谓词读的是已删除的旧引擎 API），判定函数随之删除；**文案是本表唯一还活着的部分**，
故拆成独立模块。加条件类型 = 判定在 battle_cond_procs 加一行 + 文案在本表加一行。
"""
COND_LABELS = {
    "enemy_hp_low": lambda c: f"敌方血量<{int(c.get('hp_pct', 0.4) * 100)}%",
    "player_hp_low": lambda c: f"自身血量<{int(c.get('hp_pct', 0.3) * 100)}%",
    "enemy_hp_high": lambda c: f"敌方血量>{int(c.get('hp_pct', 0.7) * 100)}%",
    "player_hp_high": lambda c: f"自身血量>{int(c.get('hp_pct', 0.8) * 100)}%",
    "enemy_full_hp": lambda c: "敌方满血",
    "enemy_frozen": lambda c: "敌方被冻结",
    "enemy_stunned": lambda c: "敌方被眩晕",
    "enemy_silenced": lambda c: "敌方被沉默",
    "enemy_poison_stacks": lambda c: f"敌方中毒≥{c.get('stacks', 0)}层",
    "enemy_shaken_gt": lambda c: "敌方破绽/震慑中",
    "player_rage_form": lambda c: "狂暴形态中",
    "player_stance": lambda c: "守护姿态生效",
    "player_combo_stacks": lambda c: f"链值≥{c.get('stacks', 3)}",
    "enemy_marked": lambda c: "敌方被标记",
    "enemy_debuff": lambda c: "敌方有减益",
    "enemy_slowed": lambda c: "敌方减速中",
    "enemy_mark_full": lambda c: f"敌方{c.get('mech','')}印记已满{c.get('stacks',3)}层",
    "element_marks": lambda c: f"敌方{c.get('element','')}印记≥{c.get('stacks',0)}层",
    "player_shield": lambda c: "自身有护盾",
    "player_spd_up": lambda c: "自身加速中",
    "player_chi_stacks": lambda c: f"自身气力≥{c.get('stacks',0)}点",
    "player_res_stacks": lambda c: f"自身{c.get('res_key','')}≥{c.get('stacks',0)}",
    "player_mech_stacks": lambda c: f"自身{c.get('mech','')}层≥{c.get('stacks',0)}",
    "player_buffed": lambda c: "自身有增益",
    "player_untouched": lambda c: "本场未受击",
    "player_combo": lambda c: f"上一招·{c.get('last', '连招中')}",
    "player_first": lambda c: "先手行动",
    "speed_ratio": lambda c: f"速度比≥{c.get('ratio',1.5)}x",
    "enemy_hunt_mark": lambda c: "敌方有猎印",
    "enemy_hunt_full": lambda c: f"敌方猎印已满{c.get('stacks', 3)}层",
    "enemy_cursed": lambda c: "敌方带诅咒",
    "faith_full": lambda c: f"信念满{c.get('stacks', 10)}",
    "faith_lt": lambda c: f"信念<{c.get('stacks', 5)}",
    "enemy_broken": lambda c: "敌方被破防",
    "enemy_shaken_ratio": lambda c: f"敌方破绽每{c.get('step', 50)}点",
    "enemy_shaken_scale": lambda c: "敌方破绽越高",
    "guard_core": lambda c: "持有磐核",
    "enemy_def_high": lambda c: "敌方防御高",
    "melody_buff": lambda c: "当前旋律为增益系",
    "melody_stacks": lambda c: f"旋律强度≥{c.get('stacks', 4)}",
    "enemy_low_hp": lambda c: f"敌方血量<{int(c.get('hp_lt', c.get('hp_pct', 40)))}%",
    "enemy_marks": lambda c: f"敌方印记总层≥{c.get('stacks', 4)}",
    "revenge": lambda c: "已承伤",
    "stealth": lambda c: "潜行中",
}
