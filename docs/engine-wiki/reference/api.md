# 参考：公开 API

坐标格式 `文件:行号`（`函数名`）。⚠️ 行号会漂移 —— 以**函数名**为准检索。
本页给签名与语义；原理见 [../concepts/](../concepts/README.md)，任务怎么做见
[../guides/](../guides/write-a-mechanic.md)。本页不重复那两处的内容。

## 1. 包门面：`battle2/__init__.py`

S2 固化（`docs/ENGINE_CONTENT_SPLIT_PLAN.md` §5）：把内容层**实际消费的 26 个符号**
全量 re-export，并保留模块级 `config` / `effects` / `stats`
（`__init__.py:30-43`）。

```python
# Actor / 战斗主体
Battle · ActCtx · make_actor · actor_ext · actor_alive
# 伤害落地 / 治疗
deal_damage · heal_actor
# 效果系统
act_apply · act_shield · apply_effects · register_action · cap_of · norm_stack
# 面板
actor_stats · stats
# 规则 / 配置
state_def · all_state_effects · get_effect_actions · get_effect_rules · config
# 事件 / 时间轴
fire · action_time · initial_ct
# 阵营
hostile_sides
# 行动结算工具
heal_amount · skill_pay_of
# 序列化
from_state · to_state
```

`__all__` 就是上面这份（`__init__.py:45-66`）。门禁
`tests/test_engine_purity.py` 会逐个断言这些符号存在，并断言 **5 个私有符号
已升公开且旧下划线名是同一对象别名**：

| 模块 | 公开名 | 旧别名 |
|---|---|---|
| `effects` | `cap_of` | `_cap_of` |
| `effects` | `norm_stack` | `_norm_stack` |
| `battle` | `now_of` | `_now_of` |
| `actions` | `heal_amount` | `_heal_amount` |
| `actions` | `skill_pay_of` | `_skill_pay_of` |

（别名赋值处：`effects.py:80-81`、`battle.py:31`、`actions.py:305`、`actions.py:763`）

## 2. `Battle`（`battle.py:34`）

### 构造

```python
Battle(btype="monster", sides=None, title_bonus=None, dmg_mult=1.0, pet=None,
       st=None, hostile_map=None, target_picker=None, on_event=None,
       action_override=None, script_hook=None, seed_ct=True, **kwargs)
```
（`battle.py:35-40`）

| 参数 | 语义 | 引擎内消费者 |
|---|---|---|
| `btype` | 战斗类型标签 | **只在一处读**：`landing._lv_pressure` 判 `== "pvp"` 跳过等级压制（`landing.py:155`） |
| `sides` | `{阵营名: [actor]}`，**唯一入口** | 全引擎 |
| `title_bonus` | 面板增幅 dict（整场一份） | `stats._player_base_stats`：`actor.bonus.panel or battle.title_bonus or {}`（`stats.py:96-97`） |
| `hostile_map` | `{side: [敌对 side]}` | `actors.hostile_sides`（`actors.py:200-202`）；缺省 = 除自己外全部阵营 |
| `dmg_mult` | 全局伤害倍率 | ⚠️ **仅赋值，无消费方**（`battle.py:60`） |
| `pet` | 宠物数据 | ⚠️ **仅赋值，无消费方**（`battle.py:61`） |
| `st` | （旧参数） | ⚠️ **仅存在于签名，函数体从未引用** |
| `target_picker` | `callable(battle, actor) -> actor\|None`；自动 actor 行动前问「打谁」 | `Battle.actor_auto`（`battle.py:378-382`） |
| `on_event` | `callable(battle, event, ctx, logs)`，事件总线尾部观察者 | `effect_triggers.fire`（`effect_triggers.py:112-117`） |
| `action_override` | `callable(battle, action, actor, skill_name, target) -> (logs, cast)`；接管非内置行动 | `Battle.act`（`battle.py:465-472`） |
| `script_hook` | `callable(battle, actor, logs) -> bool`；自动 actor 行动前的前置导演钩子，返回 True = 拦截本刻 | `Battle.actor_auto`（`battle.py:333-340`） |
| `seed_ct` | `True` = 播种初始 ct；`from_state` 传 `False` | `battle.py:91-94` |
| `**kwargs` | **静默吞掉未知参数** | — |

构造期做三件事：拷贝 sides（`:66-69`）→ 建技能索引（`_index_skills`，`:151`）→
播种 ct（`_seed_ct_one`，`:100`）。

**普通属性**（可直接读写）：`sides`（dict）、`hostile_map`、`result`（`None|"victory"|"defeat"|"fled"`）、
`winner_side`、`killed_actors`（list）、`_now`、`_p_acts`、`_started`、`_fire_ctx`。
另有 `_cast_ctx` / `_target_ctx` / `_events` 三个**只初始化、无消费方**的字段
（`battle.py:73-74, 82`）。

### 查询

| 方法 | 位置 | 返回 |
|---|---|---|
| `sides_of(side)` | `battle.py:184` | 该阵营 actor 列表（**拷贝**，改它不影响战斗） |
| `hostile_of(side)` | `battle.py:187` | `actors.hostile_actors` 的结果（敌对存活 actor） |
| `focus()` | `battle.py:191` | `sides["player"]` 里第一个 `human_controlled` 存活 actor；兜底找 `kind == "player"` 的存活者；无则 `None` |
| `alive_actors()` | `battle.py:202` | 全阵营存活 actor |
| `alive_sides()` | `battle.py:208` | 有存活 actor 的阵营名列表 |

### 运行期注册

```python
add_actor(actor: dict, side: str, front: bool = False) -> dict      # battle.py:217
```
入 sides（`front=True` 插队首）→ 建技能索引 → 播种 ct → 返回 actor。
用于召唤 / 援军 / 变身。原文强调「引擎零游戏知识：不认识随从/召唤/亡灵/援军，
只做注册 + 索引 + 排程」（`battle.py:227`）。

### 行动入口

```python
human_act(action, skill_name, actor=None, target=None, target_side=None)
    -> (logs: list, ended: bool, who: dict | None)                   # battle.py:244
advance(logs: list) -> dict | None                                   # battle.py:293
auto_run(logs: list, max_steps: int = 500) -> None                    # battle.py:302
actor_auto(actor: dict, ctx_target=None) -> (logs, ended)             # battle.py:318
act(ctx: ActCtx) -> (logs, ended)                                     # battle.py:398
```

- `human_act`：命令层唯一入口。`actor` 缺省用 `focus()`。战斗已结束 → `(["战斗已结束！"], True, None)`。
  出手后（且未结束）会 `_after_act` 推 ct + `advance` 到下一个决策点（`battle.py:269-289`）
- `advance`：`schedule.advance` 的薄包装，返回下一个该决策的人控 actor
- `auto_run`：全自动（人控 actor 也普攻）；`guard` 上限 `max_steps`。
  ⚠️ 全仓调用点**只在 `tests/`** —— 内容侧零调用，实质是测试/AI 仿真辅助；
  生产路径是 `human_act` + `advance`（见 [_selfcheck.md](../_selfcheck.md)）
- `actor_auto`：单个自动 actor 的行动帧。顺序 = 剧本钩子 → `auto_act` 显式招 →
  `ai.resolve_ai_move` → 普攻；行动后 `act_count += 1` 并推 ct
- `act`：统一行动执行（人类/AI/随从都走这里）
- ⚠️ **`human_act` 不校验 ct**，时机由命令层负责（见
  [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)）

### 内部方法（`_` 前缀，内容层有引用）

| 方法 | 位置 | 内容层引用数（全仓 grep） |
|---|---|---|
| `_seed_ct_one` / `_index_one_actor` / `_index_skills` | `battle.py:100/117/151` | 仅引擎内 |
| `_do_defend` / `_do_flee` | `battle.py:493/458` | 仅引擎内 |
| `_ensure_battle_started` | `battle.py:506` | 仅引擎内 |
| `_on_actor_dead(actor, logs=None)` | `battle.py:521` | `landing._apply_damage` 调（`landing.py:309`） |
| `_check_side_end` | `battle.py:539` | 仅引擎内 |

### 序列化

```python
to_state() -> dict                    # battle.py:566 → serialize.to_state
Battle.from_state(st) -> Battle       # battle.py:572（classmethod）→ serialize.from_state
```

## 3. 模块级公开函数

### `actors.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `make_actor(uid, name, side, kind="monster", human_controlled=False, class_name=None, level=1, equipment=None, skills=None, learned_skills=None, auto_act=None, **stats)` | `:58` | 造同构 actor；额外键透传；播种全部战斗状态键 |
| `ActCtx(caster, action="attack", skill_name=None, info=None, target=None, target_side=None, scope="single")` | `:19` | 行动上下文 dataclass |
| `actor_alive(actor)` / `actor_dead(actor)` | `:151` / `:156` | `hp > 0` |
| `effects_of(actor)` | `:160` | 读 `effects` 容器（非 dict → `{}`） |
| `actor_ext(actor)` | `:168` | 读 `ext`（惰性播种） |
| `actor_side_of(battle, actor)` | `:178` | 查阵营（以 `battle.sides` 权威，`actor.side` 兜底） |
| `hostile_sides(battle, side)` | `:193` | 敌对阵营名列表（**S2 公开 API**） |
| `hostile_actors(battle, side)` | `:206` | 敌对阵营存活 actor |

### `effects.py`

| 符号 | 位置 | 语义 |
|---|---|---|
| `ACTION_HANDLERS` | `:87` | 动词注册表（dict，全局单表） |
| `EFFECT_HANDLERS` | `:89` | **同一张表的旧别名** |
| `register_action(key)` | `:95` | 装饰器：注册动词 |
| `resolve_actions(name)` | `:107` | 名词 → 动作列表（查 `EFFECT_ACTIONS`；找不到按动词处理；都没有 → `[]`） |
| `apply_effects(battle, caster, target, effects, logs)` | `:137` | **执行效果列表**（含 chance roll + 参数合并） |
| `apply_action(battle, caster, target, action, params, logs)` | `:180` | 便捷包装 |
| `effects_from_skill(info, lv, caster_side_is_player=True)` | `:188` | 技能 `mech`/`mech2` → effect 列表（第三个参数**函数体从未使用**） |
| `norm_stack` / `cap_of` | `:80` / `:81` | 见门面表 |
| 动词 `act_apply` | `:269` | `apply` |
| 动词 `act_consume` | `:406` | `consume` |
| 动词 `act_shield` | `:433` | `shield` |
| 动词 `act_cleanse` / `act_cleanse_all` | `:479` / `:507` | `cleanse` / `cleanse_all` |
| 动词 `act_heal` | `:515` | `heal` |
| 动词 `act_interrupt` | `:552` | `interrupt` |
| 动词 `act_damage` | `:570` | `damage` |

### `landing.py`

```python
deal_damage(battle, source, target, amount, logs, dmg_kind="", defend_reduce=None, element="") -> int
# landing.py:23
heal_actor(battle, target, amount, logs, source=None, label="") -> int
# landing.py:328
```

两个都是**落地唯一收口**。内部子函数（无外部引用）：`_lv_pressure`（`:146`）、
`_roll_dodge`（`:178`）、`_apply_taken_reductions`（`:202`）、`_apply_death_guard`（`:237`）、
`_apply_damage`（`:270`）、`_apply_heal_mods`（`:367`）。

### `schedule.py`

| 符号 | 位置 | 语义 |
|---|---|---|
| `action_time(spd, base=1.0) -> float` | `:32` | `base × sqrt(50/spd)` |
| `initial_ct(spd, base=1.0) -> float` | `:41` | 开局第一动等待 = `action_time` |
| `next_ct(battle, actor, base=1.0) -> float` | `:46` | ⚠️ **无调用方**（实际推进走 `_after_act`） |
| `action_base_of(action) -> float` | `:58` | defend→0.6 / skill→1.6 / 其他→1.0 |
| `advance(battle, logs, max_steps=200) -> ("player", actor) \| ("over", None)` | `:71` | 推进到下一个决策点 |
| `_after_act(battle, actor, action)` | `:143` | 行动后推 ct |
| `_advance_time(battle, dt, logs)` | `:156` | 加时钟 → 结算 → 广播 `time_advance` |
| `_settle_time_effects(battle, logs)` | `:175` | effects 到期 / shields 到期 / 周期跳 |

常量：`CAST_ATK=1.0`（`:22`）· `CAST_SKILL=1.6`（`:23`）· `CAST_DEFEND=0.6`（`:24`）·
`CAST_ITEM=1.0`（`:25`，⚠️ 无消费者）· `SPD_REF=50.0`（`:26`）·
`HOT_INTERVAL=1.0`（`:29`，⚠️ 无消费者）。

### `stats.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `actor_stats(battle, actor) -> dict` | `:19` | **聚合面板**（伤害/速度/暴击都读它） |
| `actor_max_hp(battle, actor)` | `:136` | 便捷 |
| `actor_spd(battle, actor)` | `:140` | 便捷（CTB 用） |
| `actor_crit(battle, actor)` | `:144` | 便捷 |
| `_apply_effects(st, actor)` | `:40` | effects → 面板折算（`stat_scale` + 快照） |
| `_player_base_stats(battle, actor)` | `:85` | 走 `panel_fn` |
| `_monster_base_stats(actor)` | `:113` | 直读字段 |

### `config.py`

见 [../concepts/config-injection.md](../concepts/config-injection.md) 的 13 hook 表。
公开函数：`EngineNotConfigured`（`:20`）· `set_config`（`:83`）· `load_game_rules`（`:89`）·
`register_defaults_loader`（`:95`）· `register_hook_provider`（`:101`）·
`load_game_defaults`（`:107`，兼容 shim）· `get_effect_actions`（`:119`）·
`get_effect_rules`（`:124`）· `state_def`（`:129`）· `set_hook`（`:142`）· `mount`（`:148`）·
`get_hook`（`:154`）· `unconfigured(name, default)`（`:185`）· `formulas()`（`:244`）·
`kind_of(name)`（`:254`）· `skill_info_of`（`:262`）· `skill_by_key`（`:270`）·
`monster_skill_of`（`:278`）· `mech_cfg`（`:286`）· `bar_prefix`（`:294`）。
`strict`（`:71`）与 `_NullFormulas`（`:191`）是模块级属性。

### `effect_triggers.py`

```python
EVENTS: tuple        # effect_triggers.py:48 —— 26 个事件名
fire(battle, event: str, ctx: dict, logs: list) -> None    # :57
```

`fire` 的完整语义（subject 过滤 / `_owner` 注入 / `_fire_ctx` / 容错）见
[../concepts/event-bus.md](../concepts/event-bus.md)。

### `state_effects.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `state_def(key) -> dict` | `:13` | `get_effect_rules().get(key) or {}` |
| `stat_scale_of(key, value, stat) -> float` | `:18` | `1 + n×系数`；**只在测试里被引用** |
| `all_state_effects() -> dict` | `:27` | 全部规则表 |

### `serialize.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `to_state(battle)` | `:36` | Battle → dict |
| `from_state(st)` | `:59` | dict → Battle |
| `state_to_json(state)` | `:117` | `json.dumps(..., ensure_ascii=False, default=str)` |
| `json_to_state(raw)` | `:121` | `json.loads` |
| `_STRIP_KEYS` | `:33` | `{"_skill_index"}` |

### `actions.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `do_attack(battle, ctx)` | `:49` | 普攻 = 走 basic_skill 的技能管道 |
| `do_skill(battle, ctx)` | `:62` | 技能主入口（校验 → 扣费 → 冷却 → kind 分派） |
| `resolve_basic_skill(class_name)` | `:30` | basic_skill 查询 + 兜底 |
| `heal_amount` / `_heal_amount(st, actor, info, lv)` | `:722` / `:673` | 治疗量公式 |
| `skill_pay_of` / `_skill_pay_of(actor, info)` | `:264` / `:225` | 技能实际消耗（折扣折算点） |
| `_skill_usable(battle, actor, info, logs)` | `:121` | 可用性预检（`res_cost` 不足拦截） |
| `_spend_skill_cost(actor, info)` | `:148` | 扣蓝 / 扣资源 / `consume_all` |
| `_single_target_pipeline(battle, actor, target, info, lv, _no_lifesteal=False)` | `:332` | 单目标完整伤害管线 |
| `_deal_aoe(battle, actor, target, info, total)` | `:292` | AOE 逐目标独立结算 |
| `_consume_hit_buffs(battle, actor, logs)` | `:426` | 出手消费型效果 |
| `_settle_lifesteal(...)` | `:562` | 吸血结算（cap 30%，`mortal_wound` ×0.5） |
| `_deal_hit(battle, actor, target, dmg, defend_reduce=None, element="")` | `:525` | 命中落地薄包装 |
| `_do_heal` / `_do_buff` | `:621` / `:729` | 治疗 / 增益技能结算 |
| `_aoe_falloff_apply(logs)` | `:483` | ⚠️ **占位：原样返回 logs**（`aoe_falloff` 实际未生效） |

### `ai.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `normalize_ai(actor)` | `:27` | 旧格式 `{weights, skill_chance}` → 新格式，写回 `actor["ai"]` |
| `eval_when(battle, actor, when)` | `:116` | 守卫谓词（AND） |
| `resolve_ai_move(battle, actor)` | `:151` | 选动作（`priority` / `weighted`），返回 `then` 或 `None`（回落） |

守卫谓词全集：`self_hp_lt` · `self_hp_gt` · `hostile_lowest_hp_lt` · `round_mod: [N, R]` ·
`cd_ok`。**未知谓词 → `False`**（`ai.py:177`，防拼写漂移）。`when={}` 恒真。

### `formulas.py`（引擎自带纯公式模块）

| 函数 | 位置 |
|---|---|
| `skill_formula_expr(info, level=1)` / `skill_formula_expr_for_seg(seg, level=1)` | `:60` / `:83` |
| `skill_max_level(info=None)` | `:98` |
| `skill_power_mult(level, info=None)` | `:105` |
| `skill_flat_value(player_lv, skill_lv, info=None)` | `:114` |
| `skill_buff_turns(level, base=3, info=None)` | `:136` |
| `skill_cond_mult(cond, level, info=None)` | `:153` |
| `skill_mech_val(info, level)` | `:163` |
| `skill_lifesteal_pct(info, level)` | `:173` |
| `skill_learn_cost(need_lv)` | `:183` |
| `skill_level_of(player, skill_name)` | `:191` |
| `skill_expr_preview(info, level, stats=None)` | `:204` |
| `calc_damage(atk, def_, is_crit=False, variance=0.15, pierce=False, pene_pct=0.0, pene_flat=0, dmg_type="phys")` | `:258` |
| `resolve_formula(formula, stats, target_def, target_mdef, is_crit=False, pene_phys=0.0, pene_magi=0.0, pene_flat_phys=0, pene_flat_magi=0, variance=0.15, mult=1.0, target_max_hp=None, randomize=True)` | `:289` |
| `skill_mp_pay_of(actor_or_player, info)` | `:373` |
| `SKILL_MAX_LEVEL = 5` | `:26` |

⚠️ 本模块**依赖 4 个 hook**（`formula_skeleton_fn` / `skill_flat_fn` / `skill_up_fn` /
`skill_level_of_fn`）。直接 `mount(formulas=formulas)` 而不装常量表会在链深处崩 ——
见 [../concepts/config-injection.md](../concepts/config-injection.md) 的三档行为表。

## 4. `support/` 通用件

### `support/formula_expr.py` — 安全表达式解释器

| 函数 | 位置 |
|---|---|
| `compile_expr(expr) -> code` | `:42` |
| `eval_expr(code, vars_=None) -> float` | `:135` |
| `build_vars(stats, player_lv=0, skill_lv=0, target_max_hp=..., base=...)` | `:179` |
| `expr_or(value, fallback)` | `:208`（⚠️ 无外部引用） |
| `translate_expr(expr)` | `:235` |
| `ExprError` | `:38` |
| `VARIABLE_WHITELIST` | `:20` |

无第三方依赖：手写 tokenizer + 调度场（`_TOKEN_RE` `:25`、`_PREC` `:34`）。
变量白名单在 `VARIABLE_WHITELIST`。中文变量名别名表 `_VAR_CN`（`:218`）。

### `support/formation.py` — 站位 / 射程纯函数

| 函数 | 位置 |
|---|---|
| `MAX_RANKS = 3` | `:12` |
| `alive_units(units)` | `:15` |
| `front_rank(units)` | `:20` |
| `reachable_units(attacker, units)` | `:28`（⚠️ 无外部引用） |
| `select_target(attacker, units, threat=None, exclude_uid=None, threat_mode="front")` | `:34` |
| `select_aoe_targets(attacker, units, scope)` | `:83`（AOE 唯一引擎消费者：`actions._deal_aoe`，`actions.py:356`） |
| `pick_by_policy(policy, units, threat=None, fallback=None)` | `:122` |
| `compact(units)` | `:161` |
| `numbered_units(units)` | `:191` |
| `formation_view(units, side="enemy")` | `:209` |

### `support/skill_kinds.py` — kind 语义枚举

`SkillKind`（`:25`，值 `PHYS/MAGI/HEAL/BUFF/PASSIVE/SUMMON/TRUE/TAUNT`）·
`is_damage_kind(kind)`（`:77`）· `is_kind(kind, target)`（`:88`）· `seg_of(kind)`（`:97`）·
`lifesteal_channel_of(kind)`（`:110`）。

⚠️ 这个模块的枚举值**写死了中文**（`PHYS = "物理"` … `TAUNT = "嘲讽"`，`skill_kinds.py:27-34`），
而引擎主路径已改用 `config.kind_of(name)` 注入（`config.py:235`）。
两者是**两套 kind 词表**，若你的内容用别的语言/词表，`skill_kinds` 的 `is_kind` /
`is_damage_kind` / `seg_of` 就不适用于你的数据。第三方可只用 `config.kind_of`。
（`support/skill_kinds.py` 是 S3「通用件归位」时从 `game/core/` 搬进来的，
搬动时未做 kind 去字面量化 —— 见 [_selfcheck.md](../_selfcheck.md)）

### `support/battle_bars.py` — 挂敌身条 + 蓄力三律

| 函数 | 位置 | 语义 |
|---|---|---|
| `bar_effect_key(bar_key)` | `:64` | `前缀 + bar_key`（前缀来自 `config.bar_prefix()`） |
| `bar_def(bar_key)` | `:73` | 条配置（来自 `config.mech_cfg`） |
| `bar_state(enemy, bar_key, now=None)` | `:79` | 读条状态（惰性建） |
| `bar_settle(enemy, bar_key, now, logs=None)` | `:110` | 结算到当刻 |
| `bar_gain(enemy, bar_key, amount, logs=None, ...)` | `:135` | 推条 |
| `bar_should_trigger(enemy, bar_key, now=None)` | `:164` | 是否该触发 |
| `bar_trigger(enemy, bar_key, logs=None, ...)` | `:175` | 触发（写 `trigger_count` / `immune_until`） |
| `bar_preserve(enemy, bar_key, pct=None)` | `:204` | 阶段转换保留条 |
| `charge_def(skill_info)` | `:218` | 蓄力配置 |
| `charge_state(player)` | `:235` | 蓄力状态 |
| `charge_start(player, skill_info, logs=None)` | `:244` | 起蓄力 |
| `charge_tick(player, skill_info, logs=None)` | `:260` | 蓄力推进 |
| `charge_on_hit(player, skill_info, logs=None)` | `:294` | 命中时（若配） |
| `charge_release_power(skill_info)` | `:310` | 释放倍率 |
| `charge_clear(player)` | `:321` | 清蓄力 |

⚠️ **6 个 `charge_*` 函数全部零外部引用**（全仓 grep）——「蓄力三律」在这套引擎里
没有实际消费者。条状态存在 `actor.effects[config.bar_prefix() + key]`，
所以它随存档序列化、并能被 `EFFECT_RULES` 声明折算。

## 5. 声明表与扩展点（不是引擎 API，但第三方最常用）

| 名称 | 物理位置 | 消费者 |
|---|---|---|
| `EFFECT_ACTIONS` | 你的规则模块 | `effects.resolve_actions`（引擎） |
| `EFFECT_RULES` | 你的规则模块 | `state_effects.state_def`（引擎） |
| `MECH_CASH` | 你的规则模块 | 你的装配器（**引擎不读**） |
| `PASSIVE_PROC` | 你的规则模块 | 你的装配器（**引擎不读**） |
| `BAR_INJECT_FIELDS` / `BAR_STATE_PREFIX` | 你的规则模块 | 装配器 + `config.bar_prefix` |

详见 [../concepts/declaration-tables.md](../concepts/declaration-tables.md) 与
[effect-actions.md](effect-actions.md) · [effect-rules.md](effect-rules.md) ·
[mech-cash.md](mech-cash.md) · [passive-proc.md](passive-proc.md)。

## 6. 公开但当前无消费方的 API（诚实清单）

写文档时逐项 grep 核实。**它们不会报错，但也不起作用**：

| 名称 | 位置 | 状态 |
|---|---|---|
| `schedule.next_ct` | `schedule.py:46` | 有定义、无调用方 |
| `state_effects.stat_scale_of` | `state_effects.py:18` | 仅测试引用 |
| `support.formation.reachable_units` | `formation.py:28` | 零外部引用 |
| `support.formula_expr.expr_or` | `formula_expr.py:208` | 零外部引用 |
| `support.battle_bars.charge_*`（6 个） | `battle_bars.py:244-321` | 零外部引用 |
| `actions._aoe_falloff_apply` | `actions.py:524` | 占位实现（原样返回 logs） |
| `config.set_hook` | `config.py:123` | 零外部引用（都走 `mount`） |
| `effects.resolve_actions` | `effects.py:107` | 零外部引用（引擎内部调用） |
| `ai.eval_when` | `ai.py:152` | 零外部引用（`resolve_ai_move` 内部调） |
| `Battle.dmg_mult` / `pet` / `st` / `_cast_ctx` / `_target_ctx` / `_events` | `battle.py:60-82` | 只写不读 |
| `Battle.DEFAULT_CT_WAIT` | `battle.py:22` | 常量无消费者 |
| `schedule.CAST_ITEM` / `HOT_INTERVAL` | `schedule.py:25/29` | 常量无消费者 |

完整缺口（含声明表里的死字段）→ [../_selfcheck.md](../_selfcheck.md)。
