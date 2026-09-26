# 参考：公开 API

坐标格式 `文件:行号`（`函数名`）。⚠️ 行号会漂移 —— 以**函数名**为准检索。
本页给签名与语义；原理见 [../concepts/](../concepts/README.md)，任务怎么做见
[../guides/](../guides/write-a-mechanic.md)。本页不重复那两处的内容。

## 0. 三层与「要哪个符号从哪拿」（2026-09-23 包栈重构后）

本仓现在是三层，依赖方向严格单向（门禁 `tests/test_layering.py` 钉死）：

```text
引擎    saintess_engine/      通用件，零游戏词汇
扩展包  extends/ext_*/       可插拔的游戏能力（能互相依赖）
数据包  games/<包>/          一款游戏的内容（只允许一个）      ← 依赖方向：数据包 → 扩展包 → 引擎
```

**§1 是引擎门面，里面只有通用件**；`Battle` / `Space` / `LootTable` / `Dialogue` 这些
游戏级形状**不在引擎里** —— 各自在扩展包的门面，形状与当年在引擎里时相同，只是换了包名：

```python
from saintess_engine import Host, load_stack, config                 # 引擎通用件
from ext_combat import Battle, make_actor, deal_damage, actor_stats  # 战斗（CTB / 结算 / 效果 / 面板）
from ext_world import Space, Admission, Roster                       # 空间与准入链
from ext_loot import LootTable, TierTable, pick_weighted             # 掉落池 / 档位阶梯
from ext_dialogue import Dialogue, Cursor                            # 对话树与会话游标
```

| 要哪些符号 | 从哪 import | 数据包 `game.json` 里写 |
|---|---|---|
| `Battle` `ActCtx` `make_actor` `actor_alive` `deal_damage` `heal_actor` `apply_effects` `act_shield` `actor_stats` `state_def` `all_state_effects` `fire` `action_time` `initial_ct` `recover_time` `hostile_sides` `heal_amount` `skill_pay_of` `from_state` `to_state`（＋ `battle` / `gauge` / `formation` / `panel` 子模块） | `ext_combat` | `"depends": ["ext_combat"]` |
| `Space` `MESH` `Admission` `Rule` `Verdict` `Progress` `Roster` | `ext_world` | `"depends": ["ext_world"]` |
| `Tally` `TierBoard` `PeriodCounter` `Cooldown` `Timers` `Unlocks` `Locked` | `ext_life` | `"depends": ["ext_life"]` |
| `Shelf` `Jobs` `Job` `DailyLimit` `settle_sale` | `ext_economy` | `"depends": ["ext_economy"]` |
| `RoleSlots` `Contribution` `Applications` `Presence` `Lookup` | `ext_social` | `"depends": ["ext_social"]` |
| `LootTable` `TierTable` `pick_weighted` `pick_many` `draw_slots` `count_for` | `ext_loot` | `"depends": ["ext_loot"]` |
| `Dialogue` `Cursor` | `ext_dialogue` | `"depends": ["ext_dialogue"]` |
| 任务账本（`quest/` 子模块） | `ext_quest` | `"depends": ["ext_quest"]` |

装法只有一句：`"depends": ["ext_xxx"]`（包栈按拓扑序装好；扩展包搜索路径见
[package-format.md](package-format.md)）。**域跟着消费端走**（`effect_rules` / `passive_proc`
住在 `ext_combat`，`maps` / `instances` 住在 `ext_world`，`drop_pools` 住在 `ext_loot`）。

**坐标约定**：`文件:行号` 里的文件是**包内模块名** —— §2–§4 除 `config.py` 与 `expr/` 是引擎件外，
其余都指 `extends/ext_combat/…` 下的模块（`battle.py` = `extends/ext_combat/battle/battle.py`，
`gauge/` `formation/` 同属 `ext_combat`）。

## 1. 包门面：`saintess_engine/__init__.py`

2026-09-23 包栈重构后，**引擎门面只剩通用件**（`__all__`：`saintess_engine/__init__.py:50-61`）；
战斗 / 空间 / 掉落 / 对话这些游戏级符号随着各自的模块迁进了**扩展包**（对照表见 §0），
引擎门面不再 re-export 它们。「S2 固化」那份历史口径（内容层实际消费的 26 个符号全量 re-export，
见 `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` §5）**整体搬到了扩展包 `ext_combat` 的门面**。

```python
# 版本
__version__ · VERSION_INFO · version
# 包栈 / 包 / 宿主
Package · PackageError · PackageStack · load_stack · Host
# 指令 / 文案 / 流水
CommandRegistry · CommandSpec · TextSpec · TextTable · safe_format · KindTable · Record · TLog
# 规则 / 配置
config · get_effect_actions · get_effect_rules
# 门面转出的子模块
clock · command · container · domains · events · expr · host · log · session · store · text · tlog
```

门禁 `tests/test_engine_purity.py` 逐个断言上面这批**通用件**符号存在（`API_SYMBOLS`），
并断言包内每条绝对 import 都是标准库。
要 `Battle` / `deal_damage` / `apply_effects` / `actor_stats` / `fire` … 的那批符号，
现在写 `from ext_combat import Battle`（同形门面，见 §0）。
「5 个私有符号已升公开且旧下划线名是同一对象别名」这条断言的归属也跟着符号一起搬去扩展包 `ext_combat`：

| 模块 | 公开名 | 旧别名 |
|---|---|---|
| `effects` | `cap_of` | `_cap_of` |
| `effects` | `norm_stack` | `_norm_stack` |
| `battle` | `now_of` | `_now_of` |
| `actions` | `heal_amount` | `_heal_amount` |
| `actions` | `skill_pay_of` | `_skill_pay_of` |

（这五个符号都在扩展包 `ext_combat` 里；别名赋值处：`effects.py:86-87`、`battle.py:30`、
`battle/actions.py:334`、`battle/actions.py:814`）

## 2. `Battle`（扩展包 `ext_combat` · `battle.py:34`）

### 构造

```python
Battle(btype="monster", sides=None, title_bonus=None, dmg_mult=1.0, pet=None,
       st=None, hostile_map=None, target_picker=None, on_event=None,
       action_override=None, script_hook=None, seed_ct=True, **kwargs)
```
（`battle.py:35-39`）

| 参数 | 语义 | 包内消费者 |
|---|---|---|
| `btype` | 战斗类型标签 | **只在一处读**：`landing._lv_pressure` 判 `== "pvp"` 跳过等级压制（`landing.py:239`） |
| `sides` | `{阵营名: [actor]}`，**唯一入口** | 全包（`ext_combat`） |
| `title_bonus` | 面板增幅 dict（整场一份） | `stats._player_base_stats`：`actor.bonus.panel or battle.title_bonus or {}`（`battle/stats.py:95-96`） |
| `hostile_map` | `{side: [敌对 side]}` | `actors.hostile_sides`（`actors.py:202-204`）；缺省 = 除自己外全部阵营 |
| `dmg_mult` | 全局伤害倍率 | ⚠️ **仅赋值，无消费方**（`battle.py:77`） |
| `pet` | 宠物数据 | ⚠️ **仅赋值，无消费方**（`battle.py:78`） |
| `st` | （旧参数） | ⚠️ **仅存在于签名，函数体从未引用** |
| `target_picker` | `callable(battle, actor) -> actor\|None`；自动 actor 行动前问「打谁」 | `Battle.actor_auto`（`battle.py:432-436`） |
| `on_event` | `callable(battle, event, ctx, logs)`，事件总线尾部观察者 | `effect_triggers.fire`（`effect_triggers.py:117-122`） |
| `action_override` | `callable(battle, action, actor, skill_name, target) -> (logs, cast)`；接管非内置行动 | `Battle.act`（`battle.py:513-521`） |
| `script_hook` | `callable(battle, actor, logs) -> bool`；自动 actor 行动前的前置导演钩子，返回 True = 拦截本刻 | `Battle.actor_auto`（`battle.py:377-386`） |
| `seed_ct` | `True` = 播种初始 ct；`from_state` 传 `False` | `battle.py:97-100` |
| `**kwargs` | **静默吞掉未知参数** | — |

构造期做三件事：拷贝 sides（`:66-69`）→ 建技能索引（`_index_skills`，`:151`）→
播种 ct（`_seed_ct_one`，`:100`）。

**普通属性**（可直接读写）：`sides`（dict）、`hostile_map`、`result`（`None|"victory"|"defeat"|"fled"`）、
`winner_side`、`killed_actors`（list）、`_now`、`_p_acts`、`_started`、`_fire_ctx`。
（`_cast_ctx` / `_target_ctx` / `_events` 三个只初始化、无消费方的字段已于 2026-09-11 删除；
`dmg_mult` / `pet` / `st` 三个构造参数同期删除——注意 `dmg_mult` 是「调用方在用、实现没读」的
静默失效功能，不是死字段，见 `_selfcheck.md` §0.4。）

### 查询

| 方法 | 位置 | 返回 |
|---|---|---|
| `sides_of(side)` | `battle.py:223` | 该阵营 actor 列表（**拷贝**，改它不影响战斗） |
| `hostile_of(side)` | `battle.py:226` | `actors.hostile_actors` 的结果（敌对存活 actor） |
| `focus()` | `battle.py:226` | `sides["player"]` 里第一个 `human_controlled` 存活 actor；兜底找 `kind == "player"` 的存活者；无则 `None` |
| `alive_actors()` | `battle.py:241` | 全阵营存活 actor |
| `alive_sides()` | `battle.py:243` | 有存活 actor 的阵营名列表 |

### 运行期注册

```python
add_actor(actor: dict, side: str, front: bool = False) -> dict      # battle.py:256
```
入 sides（`front=True` 插队首）→ 建技能索引 → 播种 ct → 返回 actor。
用于召唤 / 援军 / 变身。原文强调「引擎零游戏知识：不认识随从/召唤/亡灵/援军，
只做注册 + 索引 + 排程」（`battle.py:266`）。
（引文里的「引擎」是该模块的原文；2026-09-23 起这个模块属扩展包 `ext_combat`，纪律即「本包零游戏知识」）。

### 行动入口

```python
human_act(action, skill_name, actor=None, target=None, target_side=None)
    -> (logs: list, ended: bool, who: dict | None)                   # battle.py:279
advance(logs: list) -> dict | None                                   # battle.py:337
auto_run(logs: list, max_steps: int = 500) -> None                    # battle.py:346
actor_auto(actor: dict, ctx_target=None) -> (logs, ended)             # battle.py:362
act(ctx: ActCtx) -> (logs, ended)                                     # battle.py:452
```

- `human_act`：命令层唯一入口。`actor` 缺省用 `focus()`。战斗已结束 → `(["战斗已结束！"], True, None)`。
  出手后（且未结束）会 `_after_act` 推 ct + `advance` 到下一个决策点（`battle.py:273-293`）
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
| `_seed_ct_one` / `_index_one_actor` / `_index_skills` | `battle.py:115/117/151` | 仅包内 |
| `_do_defend` / `_do_flee` | `battle.py:612/458` | 仅包内 |
| `_ensure_battle_started` | `battle.py:628` | 仅包内 |
| `_on_actor_dead(actor, logs=None)` | `battle.py:645` | `landing._apply_damage` 调（`landing.py:401`） |
| `_check_side_end` | `battle.py:665` | 仅包内 |

### 序列化

```python
to_state() -> dict                    # battle.py:692 → serialize.to_state
Battle.from_state(st, *, text=None)   # battle.py:688（classmethod）→ serialize.from_state
```

## 3. 模块级公开函数（除 `config.py` 外都在扩展包 `ext_combat`）

下面每节的文件都指包内模块（§0 坐标约定）；`ext_combat` 门面把其中的公开名原样转出，
所以 `from ext_combat import make_actor` 与门面表 §0 一致。

### `actors.py`

| 函数 | 位置 | 语义 |
|---|---|---|
| `make_actor(uid, name, side, kind="monster", human_controlled=False, class_name=None, level=1, equipment=None, skills=None, learned_skills=None, auto_act=None, **stats)` | `:60` | 造同构 actor；额外键透传；播种全部战斗状态键 |
| `ActCtx(caster, action="attack", skill_name=None, info=None, target=None, target_side=None, scope="single")` | `:20` | 行动上下文 dataclass |
| `actor_alive(actor)` / `actor_dead(actor)` | `:153` / `:158` | `hp > 0` |
| `effects_of(actor)` | `:162` | 读 `effects` 容器（非 dict → `{}`） |
| `actor_ext(actor)` | `:170` | 读 `ext`（惰性播种） |
| `actor_side_of(battle, actor)` | `:180` | 查阵营（以 `battle.sides` 权威，`actor.side` 兜底） |
| `hostile_sides(battle, side)` | `:195` | 敌对阵营名列表（**S2 公开 API**） |
| `hostile_actors(battle, side)` | `:208` | 敌对阵营存活 actor |

### `effects.py`

| 符号 | 位置 | 语义 |
|---|---|---|
| `ACTION_HANDLERS` | `:93` | 动词注册表（dict，全局单表） |
| `register_action(key)` | `:96` | 装饰器：注册动词 |
| `resolve_actions(name)` | `:139` | 名词 → 动作列表（查 `EFFECT_ACTIONS`；找不到按动词处理；都没有 → `[]`） |
| `apply_effects(battle, caster, target, effects, logs)` | `:169` | **执行效果列表**（含 chance roll + 参数合并） |
| `effects_from_skill(info, lv, caster_side_is_player=True)` | `:217` | 技能 `mech`/`mech2` → effect 列表（第三个参数**函数体从未使用**） |
| `norm_stack` / `cap_of` | `:86` / `:87` | 见门面表 |
| 动词 `act_apply` | `:330` | `apply` |
| 动词 `act_consume` | `:518` | `consume` |
| 动词 `act_shield` | `:551` | `shield` |
| 动词 `act_cleanse` / `act_cleanse_all` | `:602` / `:636` | `cleanse` / `cleanse_all` |
| 动词 `act_heal` | `:644` | `heal` |
| 动词 `act_interrupt` | `:683` | `interrupt` |
| 动词 `act_damage` | `:711` | `damage` |

### `landing.py`

```python
deal_damage(battle, source, target, amount, logs, dmg_kind="", defend_reduce=None, element="") -> int
# landing.py:28
heal_actor(battle, target, amount, logs, source=None, label="") -> int
# landing.py:437
```

两个都是**落地唯一收口**。内部子函数（无外部引用）：`_lv_pressure`（`:221`）、
`_roll_dodge`（`:254`）、`_apply_taken_reductions`（`:281`）、`_apply_death_guard`（`:323`）、
`_apply_damage`（`:358`）、`_apply_heal_mods`（`:370`）。

### `schedule.py`

| 符号 | 位置 | 语义 |
|---|---|---|
| `action_time(spd, base=None) -> float` | `:94` | **转发内容侧时间模型**（`time_model_fn`）；`base=None` → 默认行动类别的基准耗时 |
| `initial_ct(spd, base=None) -> float` | `:94` | 开局第一动等待 = `action_time` |
| `next_ct(battle, actor, base=None) -> float` | `:110` | ⚠️ **无调用方**（实际推进走 `_after_act`） |
| `action_base_of(action) -> float` | `:120` | **转发内容侧基准表**（`action_base_fn`）；未知类别回落 `DEFAULT_ACTION` |
| `recover_time(spd, base=None) -> float` | `:137` | **转发内容侧第二段时间模型**（`recover_model_fn`）；`base=None` → 默认行动类别的第二段基准 |
| `recover_base_of(action) -> float` | `:129` | **转发内容侧第二段基准表**（`recover_base_fn`）；未知类别回落 `DEFAULT_ACTION` |
| `advance(battle, logs, max_steps=200) -> ("player", actor) \| ("over", None)` | `:285` | 推进到下一个决策点 |
| `_after_act(battle, actor, action)` | `:362` | 行动后推 ct |
| `_advance_time(battle, dt, logs)` | `:421` | 加时钟 → 结算 → 广播 `time_advance` |
| `_settle_time_effects(battle, logs)` | `:456` | effects 到期 / shields 到期 / 周期跳 |

常量：`DEFAULT_ACTION = "attack"`（`:32`，通用类别键：未知动作类别回落到它那一项）。
**包内已无** `CAST_ATK` / `CAST_SKILL` / `CAST_DEFEND` / `SPD_REF` 等时间/基准常量 ——
公式形状与基准数值归内容侧（装配面见 [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md) §公式）。
`recover_time` / `recover_base_of` 与出招同口径（T14：只做「两段相加」，
「没有第二段」= 内容侧显式声明 0，不兜底）；`recover_time` 由扩展包 `ext_combat` 门面导出
（引擎门面不再有游戏级符号，见 §0）。

未装配 `time_model_fn` / `action_base_fn` / `recover_model_fn` / `recover_base_fn`
→ 对应的 `action_time` / `action_base_of` / `recover_time` / `recover_base_of` 抛
`config.EngineNotConfigured`（fail-closed，无默认公式）。

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

见 [../concepts/config-injection.md](../concepts/config-injection.md) 的 22 hook 表。
公开面（引擎侧只剩「注入面 + 严格模式」这几个）：
`EngineNotConfigured`（`:20`）· `strict`（`:103`）· `set_config`（`:114`）· `get_config`（`:123`）·
`register_hook_provider`（`:132`）· `set_hook`（`:142`）· `mount`（`:155`）· `get_hook`（`:161`）·
`unconfigured(name, default)`（`:192`）。
★ 原先那一串「游戏配置取件面」（`load_game_rules` / `get_effect_rules` / `state_def` /
`formulas()` / `kind_of` / `monster_skill_of` …）**已随第 7 批搬进扩展包** —— 现在住
`ext_combat.battle.game_config`（包内写 `from ext_combat.battle import game_config`）。
2026-09-25 校准：本段原先把这批已搬走的名字留着并带着旧行号，按源码逐条重写。
`_NullFormulas`（`:199`）是模块级私有属性（未装配时的中性公式面）。

### `effect_triggers.py`

```python
EVENTS: tuple        # effect_triggers.py:53 —— 26 个事件名
fire(battle, event: str, ctx: dict, logs: list) -> None    # :62
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
| `from_state(st)` | `:57` | dict → Battle |
| `state_to_json(state)` | `:122` | `json.dumps(..., ensure_ascii=False, default=str)` |
| `json_to_state(raw)` | `:126` | `json.loads` |
| `_STRIP_KEYS` | `:31` | `{"_skill_index"}` |

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
| `normalize_ai(actor)` | `:30` | 旧格式 `{weights, skill_chance}` → 新格式，写回 `actor["ai"]` |
| `eval_when(battle, actor, when)` | `:156` | 守卫谓词（AND） |
| `resolve_ai_move(battle, actor)` | `:193` | 选动作（`priority` / `weighted`），返回 `then` 或 `None`（回落） |

守卫谓词全集：`self_hp_lt` · `self_hp_gt` · `hostile_lowest_hp_lt` · `round_mod: [N, R]` ·
`cd_ok`。**未知谓词 → `False`**（`ai.py:182`，防拼写漂移）。`when={}` 恒真。

### `formulas.py`（扩展包 `ext_combat` 内的纯公式模块）

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

## 4. 引擎通用件与已归扩展包的形状

### `expr/__init__.py` — 安全表达式解释器（**引擎件**）

| 函数 / 名字 | 位置 |
|---|---|
| `compile_expr(expr) -> code` | `:143` |
| `eval_expr(code, vars_=None) -> float` | `:249` |
| `build_vars(stats, player_lv=0, skill_lv=0, target_max_hp=..., base=...)` | `:326` |
| `expr_or(value, fallback)` | `:347`（⚠️ 无外部引用） |
| `translate_expr(expr)` | `:366` |
| `declared_vars()` · `variable_names()` · `labels_of()` | `:84` · `:111` · `:356` |
| `_DEFAULT_EXPR_VARS` | `:45` |
| `ExprError` | `:139` |

无第三方依赖：手写 tokenizer + 调度场（`_TOKEN_RE` `:116`、`_PREC` `:125`）。
★ **变量表归内容侧声明**（E4 · 2026-09-25）：引擎只留两个读口 —— `declared_vars()`
（有哪些变量 / 各自的取值来源 `stat`·`input`·`const` / 显示名，中文名也在表里，旧 `_VAR_CN` 已并入）
与 `variable_names()`；表由 `config.mount(expr_vars_fn=...)` 声明，不装配则整表取
`_DEFAULT_EXPR_VARS`（= 历史那一份，逐条相同 ⇒ 一字不变）。旧名 `VARIABLE_WHITELIST` 已删。

### `formation/` — 站位 / 射程纯函数（扩展包 `ext_combat`，`from ext_combat import formation`）

| 函数 | 位置 |
|---|---|
| `MAX_RANKS = 3` | `:12` |
| `alive_units(units)` | `:15` |
| `front_rank(units)` | `:20` |
| `reachable_units(attacker, units)` | `:28`（⚠️ 无外部引用） |
| `select_target(attacker, units, threat=None, exclude_uid=None, threat_mode="front")` | `:34` |
| `select_aoe_targets(attacker, units, scope)` | `:83`（AOE 唯一消费者：`actions._deal_aoe`，`battle/actions.py:391`） |
| `pick_by_policy(policy, units, threat=None, fallback=None)` | `:122` |
| `compact(units)` | `:161` |
| `numbered_units(units)` | `:191` |
| `formation_view(units, side="enemy")` | `:209` |

### ~~`skill_kinds` 模块~~ — kind 语义枚举 **（2026-09-13 P4 下沉：本模块已不在引擎里）**

引擎包内**没有** kind 词表模块：`SkillKind` 枚举（值 `PHYS/MAGI/HEAL/BUFF/PASSIVE/SUMMON/TRUE/TAUNT`）·
`is_damage_kind(kind)` · `is_kind(kind, target)` · `seg_of(kind)` · `lifesteal_channel_of(kind)`
已整体下沉到**内容侧**（游戏仓 `game/data/kinds.py`；奥兰迪亚内容包 `content/mech/kinds.py`
是同内容同源的副本）。原实现里的中文枚举值（`PHYS = "物理"` … `TAUNT = "嘲讽"`）随之离开引擎。

引擎主路径一律经 `config.kind_of(name)` 注入（`config.py:271`）读 kind 值 —— 第三方内容
自带词表即可，不受任何语言限制。
（历史上该模块是 S3「通用件归位」时从 `game/core/` 搬进引擎的；P4 实测引擎内部**零消费者**，
故按「机制归引擎、词表归内容」的边界原则迁回内容侧 —— 见
[_selfcheck.md](../_selfcheck.md) B1 行）

### `gauge/` — 挂敌身条 + 蓄力三律（扩展包 `ext_combat`，`from ext_combat import gauge`）

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
（`charge_def` / `charge_state` / `charge_start` / `charge_tick` / `charge_on_hit` /
`charge_release_power` / `charge_clear` **已于 2026-09-11 全部删除**——「蓄力三律」是
《云海猎团》弓手/时咒的职业机制，全仓零消费方，与「引擎零内容知识」冲突。
设计口径留档游戏仓 `docs/archive/REFACTOR_v181_CLASS_MECH_ASSEMBLY.md`。）

条状态存在 `actor.effects[config.bar_prefix() + key]`，
所以它随存档序列化、并能被 `EFFECT_RULES` 声明折算。

## 5. 声明表与扩展点（内容侧声明，**不在引擎里**，但第三方最常用）

| 名称 | 物理位置 | 消费者 |
|---|---|---|
| `EFFECT_ACTIONS` | 你的规则模块 | `effects.resolve_actions`（`ext_combat`） |
| `EFFECT_RULES` | 你的规则模块 | `state_effects.state_def`（`ext_combat`） |
| `MECH_CASH` | 你的规则模块 | 你的装配器（**引擎不读，`ext_combat` 也不读**） |
| `PASSIVE_PROC` | 你的规则模块 | 你的装配器（**引擎不读，`ext_combat` 也不读**） |
| `BAR_INJECT_FIELDS` / `BAR_STATE_PREFIX` | 你的规则模块 | 装配器 + `config.bar_prefix` |

**域跟消费端走**（2026-09-23 起）：`effect_rules` / `passive_proc` 住在扩展包 `ext_combat`，
`maps` / `instances` 住在 `ext_world`，`drop_pools` 住在 `ext_loot`：数据包要用哪个域，
就在 `game.json` 里 `"depends": ["<那个包>"]`。分层 = 引擎默认集（`commands` / `texts` / `tlogs`）
→ 该包 `depends` 的扩展包 → 包自己的声明；编辑器与装载口共用同一份
（`saintess_engine.domains.layered_decls`）。

详见 [../concepts/declaration-tables.md](../concepts/declaration-tables.md) 与
[effect-actions.md](effect-actions.md) · [effect-rules.md](effect-rules.md) ·
[mech-cash.md](mech-cash.md) · [passive-proc.md](passive-proc.md)。

## 6. 公开但当前无消费方的 API（诚实清单）

写文档时逐项 grep 核实。**它们不会报错，但也不起作用**：
下表除 `expr.expr_or` / `config.set_hook`（引擎件）外，符号都在扩展包 `ext_combat` 里：

| 名称 | 位置 | 状态 |
|---|---|---|
| `schedule.next_ct` | `schedule.py:48` | 有定义、无调用方 |
| `state_effects.stat_scale_of` | `state_effects.py:18` | 仅测试引用 |
| `formation.reachable_units` | `formation/__init__.py:28` | 零外部引用 |
| `expr.expr_or` | `expr/__init__.py:221` | 零外部引用 |
| ~~`gauge.charge_*`（6 个）~~ | — | **已删**（2026-09-11） |
| ~~`actions._aoe_falloff_apply`~~ | — | **已删**（2026-09-11；AOE falloff 不实现） |
| `config.set_hook` | `config.py:148` | 零外部引用（都走 `mount`） |
| `effects.resolve_actions` | `effects.py:140` | 零外部引用（`effects` 内部调用） |
| `ai.eval_when` | `ai.py:159` | 零外部引用（`resolve_ai_move` 内部调） |
| ~~`Battle.dmg_mult` / `pet` / `st` / `_cast_ctx` / `_target_ctx` / `_events`~~ | — | **已删**（2026-09-11） |
| ~~`Battle.DEFAULT_CT_WAIT`~~ | — | **已删**（2026-09-11） |
| ~~`schedule.CAST_ITEM` / `HOT_INTERVAL`~~ | — | **已删**（2026-09-11） |

完整缺口（含声明表里的死字段）→ [../_selfcheck.md](../_selfcheck.md)。
