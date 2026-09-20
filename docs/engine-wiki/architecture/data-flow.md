# 数据流：一次行动从 `human_act` 到落地

本页给**逐函数调用链**（带 `文件:行号`）。事件在什么位置被喊出来，用 `⚡` 标出。

## 全链总览

```
命令层
  └─ Battle.human_act(action, skill_name, actor, target)        battle.py:271
       ├─ ActCtx(caster, action, skill_name, target, ...)       actors.py:20
       ├─ Battle.act(ctx)                                       battle.py:432
       │    ├─ _ensure_battle_started()                         battle.py:597   ⚡ battle_start
       │    ├─ fire("turn_start")                               battle.py:459   ⚡
       │    ├─ 控制消费（mode=skip → 早退；no_skill → 技能转普攻） battle.py:464-491 ⚡ on_act_consume
       │    ├─ fire("act_begin")                                battle.py:493   ⚡
       │    ├─ _p_acts += 1                                     battle.py:451
       │    ├─ 分派：
       │    │    attack → actions.do_attack                      actions.py:50
       │    │    skill  → actions.do_skill                       actions.py:63
       │    │    defend → Battle._do_defend                      battle.py:581
       │    │    flee   → Battle._do_flee                        battle.py:588
       │    │    其他   → Battle.action_override 注入点           battle.py:504
       │    ├─ fire("act_done")                                 battle.py:571   ⚡
       │    └─ _check_side_end()                                battle.py:630
       └─ 若未结束且 action ∈ {attack, skill, defend} 或 override 被消费：
            ├─ schedule._after_act(battle, caster, action)      schedule.py:359  推 ct
            └─ Battle.advance(logs)                             battle.py:324
                 └─ schedule.advance（推时钟 + 自动 actor 行动）  schedule.py:282
```

## 展开 1：`advance` 的循环

```
schedule.advance(battle, logs, max_steps=200)                     schedule.py:282
  while battle.result is None and guard < 200:
    fp   = _next_player_due(battle)     # ct 最小的 human_controlled 存活者   :113
    auto = _next_auto_due(battle)       # ct 最小的自动 actor                :128
    if fp is None and auto is None: return ("over", None)
    if fp 先到点（fp[1] <= auto[1] + 1e-9）:
        _advance_time(battle, fp[1] - battle._now, logs)           :156
        return ("player", fp[0])      # 交还控制权，等真人输入
    else:
        _advance_time(battle, auto[1] - battle._now, logs)
        logs.append("—— {name} 行动 ——")
        battle.actor_auto(actor)                                       battle.py:349
```

`_advance_time(battle, dt, logs)`（`schedule.py:373`）内部：

```
battle._now += dt
_settle_time_effects(battle, logs)                                  schedule.py:283
   ├─ for 每个存活 actor:
   │    ├─ effects 到期 → pop + ⚡ buff_expire                        schedule.py:406
   │    ├─ shields 到期（expire_at <= now）→ pop                      schedule.py:451-461
   │    └─ 周期跳（period）:
   │         首次 → dot_next[key] = now + interval（不跳）             schedule.py:494-497
   │         到点 → while now >= dot_next（最多 20 跳）:
   │             dir=damage → ⚡ dot_calc → landing.deal_damage → ⚡ dot_tick   :285/:292/:297
   │             dir=heal   → landing.heal_actor（+ mana_pct）        :301-320
   │             dir=mana   → 直接加 mp                                :321-330
   │             dir=gain   → effects[key].stacks ±= amount（clamp，静默） :331-350
   │             限时（turns）→ 跳够清层                                :351-359
fire("time_advance", {"dt": dt, "now": battle._now})                schedule.py:406 ⚡
```

## 展开 2：`do_attack` → `do_skill` → 伤害管线

`Battle.act` 回调 `do_attack`，后者**把自己改写成一次技能施放**（普攻 = 职业 `basic_skill`）：

```
actions.do_attack(battle, ctx)                                      actions.py:50
  info = resolve_basic_skill(actor["class_name"])                    actions.py:31
         ├─ hook basic_skill_fn(class_name)（内容侧）
         └─ 回落 hook basic_fallback / 结构化兜底
  info["_basic"] = True            # 用来选 attack_hit vs skill_hit
  sub = ActCtx(action="skill", skill_name=info["name"], info=info, ...)
  → actions.do_skill(battle, sub)                                   actions.py:63

actions.do_skill(battle, ctx)                                       actions.py:63
  1. info 空 → return []
  2. 玩家（有 class_name）→ _skill_usable(...)                       actions.py:142
       └─ res_cost 条目存在且 stacks < 需求 → 拦截 + 日志，return
  3. _spend_skill_cost(actor, info)                                 actions.py:195
       ├─ mp 扣减（pay = _skill_pay_of 折算）
       ├─ res_cost 扣 effects[key].stacks
       └─ consume_all → ef.pop(key)
  4. cd > 0 → actor["cooldown"][name] = now + cd（cd_mult 取态声明最小） :83-100
  5. ⚡ fire("act_cast", {actor, target, info})                       actions.py:105
  6. kind 分派（比较的是 config.kind_of 注入的值）:
       kind == heal → _do_heal(...)     → heal_calc ⚡ → landing.heal_actor → on_heal ⚡
       kind == buff → _do_buff(...)     → apply_effects（effect 名词）
       否则（攻击） → 目标解析 → _attack_damage_pipeline(...)
```

```
actions._attack_damage_pipeline(battle, actor, target, info, lv)    actions.py:327
  if info["aoe"] → _deal_aoe(...)                                   actions.py:339
        scope = "all" | info["aoe"]
        enemies = 敌对 side 全部 actor
        targets = support.formation.select_aoe_targets(...)
        for t in targets: _single_target_pipeline(..., _no_lifesteal=True)
  else → _single_target_pipeline(...)                               actions.py:379

actions._single_target_pipeline(battle, actor, target, info, lv)     actions.py:379
  1. _consume_hit_buffs(battle, actor, logs)                        actions.py:478
       └─ 遍历 effects 里带 "hit" 子键的条目 → 累积 dmg_mult/guaranteed_crit/bonus_atk_pct
          → ⚡ on_hit_consume → pop 条目
  2. st  = stats.actor_stats(battle, actor)                          stats.py:18
     est = stats.actor_stats(battle, target)
  3. _st_mult = st["_state_dmg_mult"]（来自 stat_scale.dmg_mult）
  4. is_crit = hit_buffs.guaranteed_crit or random() < st["crit"]
     lucky   = is_crit and random() < 0.30
  5. multi = info["hits"] or info["multi"] or 1
  6. 段循环 → _skill_seg_damage(...)  每个段算一次
       ├─ expr 段：config.formulas().skill_formula_expr → resolve_formula(...)
       └─ 非 expr：config.formulas().calc_damage(atk|matk × power + skill_flat, def|mdef, ...)
  7. total *= _st_mult；total *= hit_buffs.dmg_mult
  8. ⚡ fire("dmg_calc", {actor, target, dmg, is_crit, info, mult:1.0})  actions.py:422-428
       └─ 读回 battle._fire_ctx["mult"] → total *= mult
  9. _deal_hit(battle, actor, target, total, defend_reduce, element)   actions.py:573
       └─ landing.deal_damage(...)                                  landing.py:26
 10. _settle_lifesteal(...)（非 AOE）                               actions.py:610
       └─ rate = min(lifesteal 类面板, 0.30)，真伤不吸，mortal_wound ×0.5
          → landing.heal_actor → on_heal ⚡
 11. bonus_atk_pct > 0 → 再 _deal_hit 一段附伤
 12. _apply_hit_effects(...) → effects_from_skill(info, lv) → apply_effects   actions.py:523
 13. ⚡ fire("attack_hit"|"skill_hit")，然后若是暴击 ⚡ fire("crit")    actions.py:422-466
```

## 展开 3：`landing.deal_damage` 的落地顺序（顺序有语义）

```
landing.deal_damage(battle, source, target, amount, logs, dmg_kind, defend_reduce, element)
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. amount <= 0 → 0                                                       │
│ 2. _lv_pressure(battle, source, target, dmg)          landing.py:210     │
│      btype == "pvp" → 不压；任一方无 level → 不压                          │
│      低打高：前 3 级 ×0.95，之后 ×0.90，封顶 ×0.30                         │
│      高打低：每级 ×1.02 连乘（封顶 50 级）                                 │
│ 3. 元素免疫 / 弱点 / 元素抗性（仅 element 非空）        landing.py:81-108     │
│      element_immune 含该元素 → 直接 return 0                              │
│      element_weak[el] > 1 → ×倍率                                        │
│      elem_res / abyss_res（dark 吃 abyss_res）cap 0.5 → 减伤              │
│ 4. ⚡ fire("taken_calc", {actor: target, dmg, mult: 1.0})   landing.py:79-90 │
│      → 读回 mult → dmg *= mult                                            │
│ 5. target["_dmg_taken_mult"] > 1 → dmg *= 它           landing.py:92-99    │
│ 6. _roll_dodge(battle, target, logs)                   landing.py:242     │
│      dodge 面板 cap 0.40 → 命中则 return 0（整个伤害免掉）                 │
│ 7. defending → dmg *= (1 - defend_reduce or 0.5)       landing.py:155-161  │
│ 8. _apply_taken_reductions(dmg_kind)                   landing.py:267     │
│      phys → phys_reduce cap 0.40；magi → magic_reduce cap 0.40            │
│      block 概率 cap 0.40 → 减半                                          │
│ 9. effects 里带 wake_on_hit 的态 → pop（打醒）+ 日志    landing.py:169-181  │
│10. charging 有 skill → 清 + ⚡ fire("interrupt")        landing.py:193-130  │
│11. _apply_damage(battle, target, dmg, logs, source)    landing.py:342     │
│      ├─ 护盾吸收（遍历 shields，按 value 扣减，耗尽即 pop）                 │
│      ├─ hp 扣减                                                          │
│      ├─ hp <= 0 → _apply_death_guard(...)（濒死保护）   landing.py:308     │
│      │     effects["death_guard"].stacks > 0 → hp 拉回 guard_hp_pct      │
│      │     （+heal_pct 额外治疗，走 heal_actor）→ 层 -1                    │
│      ├─ 仍 <= 0 → Battle._on_actor_dead(...)           battle.py:612       │
│      │       killed_actors.append / 清 defending+charging                 │
│      │     ⚡ fire("on_death", {actor, target})                            │
│      │     source 非 None → ⚡ fire("on_kill", {actor: source, ...})       │
│      └─ 否则：日志「受到 N 点伤害」                                        │
│12. 未死 → ⚡ fire("on_taken", {actor, target, source, dmg})   landing.py:203 │
└──────────────────────────────────────────────────────────────────────────┘
返回 real（实际扣血）
```

⚠️ 第 6 步（闪避）的位置有注释明确说明：**「位置在 defending 前（对齐旧顺序：
闪避 → 防御格挡；闪避免伤不打断蓄力——招被闪开）」**（`landing.py:154`）。
改顺序会改变「闪避是否省下防御姿态/是否打断读条」这类语义。

## 展开 4：事件在链上的位置（一次普攻）

```
turn_start ─→ act_begin ─→ act_cast ─→ dmg_calc
                                        └→ taken_calc
                                           ├→ interrupt（若破读条）
                                           ├→ on_kill + on_death（若致死）
                                           └→ on_taken（未死）
             ─→ attack_hit ─→ crit（若是暴击）
             ─→ act_done
             …（advance 期间）… buff_expire / dot_calc / dot_tick / time_advance
```

`caster` 缺省 = 声明者本人（`effect_triggers.py:109`），所以 `on_taken` 里的
`on=caster` 效果作用于**受击者自己**；要作用于攻击者请用 `ctx["source"]`。

## 五条「读代码时最容易看错」的细节

| 细节 | 事实 | 依据 |
|---|---|---|
| 普攻不是独立的伤害路径 | 它把自己改写成一次 `action="skill"` 的施放 | `actions.py:57-60` |
| 技能索引进 `_skill_index` 且**失败不阻断** | 索引空 → 技能静默空放 | `battle.py:141-164` |
| `act_done` 不带 `actor` 键 | 所以它是全员广播；行动者放在 `ctx["acted"]` | `battle.py:566-571` |
| 被控跳过时 `act()` **提前 return**，`act_done` 不 fire | 推 ct 由调用方做 | `battle.py:482-491` |
| `_fire_ctx` 会被嵌套 fire 覆盖 | 需要 save/restore | `game/services/class_mech_proc.py:238-244`（游戏仓侧） |

## 相关

- 模块依赖图 → [README.md](README.md)
- 事件语义 → [../concepts/event-bus.md](../concepts/event-bus.md)
- 时间轴 → [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)
