# actor 同构数据模型

## 一句话

**引擎里只有一种实体：`dict`。** 玩家、怪、Boss、召唤物、变身形态没有类型差异，
只有字段值的差异。引擎逻辑**只用字段值，不按字段猜身份**（`actors.py:8` 的原文）。

## 为什么这么设计

旧引擎用「玩家分支 / 怪分支」两套代码处理同一件事（`_player_stats` vs `_enemy_stats`、
`_actor_skill` vs 玩家技能路径），结果是：**同一个机制要写两遍**，且第二遍经常忘。
同构化的收益：

- 一个机制动作对玩家和怪同时生效，不需要「怪也能用」的额外适配
- `add_actor()` 加援军/召唤物时不需要给调度器注册新类型（`battle.py:275`）
- 序列化不需要按类型分派（`serialize._serialize_actor` 对任何 actor 一视同仁，`serialize.py:51`）

代价：**身份信息全靠字段**。要表达「这是 Boss」就写 `traits=["boss"]`（标签名随内容侧起，
引擎**不认识 Boss 这个概念**）—— 引擎只提供 `traits.of(actor)` / `traits.has(actor, name)` /
`traits.has_any(actor, names)` 三个只读判据，**名单为空 ⇒ 一律 False**（不声明 = 这条规则不适用于任何人）。
「谁带标签才吃哪条规则」由声明给：控制时长减半看该状态的 `ctrl_half_traits`（`effects.py:378-379`）、
DOT 折扣档看该周期的 `trait_tags`（`schedule.py:652`）。旧字段 `is_boss` / `role` 引擎**已不再读**
（2026-09-25 E3 已删）—— 内容侧仍可自己读它们，那是内容侧的事。

## 字段全集

`make_actor`（`actors.py:62`）产生的字段分四组。

### ① 身份 / 数据标签

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | str | 唯一标识（召唤物 owner 用 uid 引用，避免循环引用） |
| `name` | str | 显示名 |
| `side` | str | 所属阵营名（与 `battle.sides` 的键一致；权威判定见 `actor_side_of`） |
| `kind` | str | **纯数据标签**，默认 `"monster"`；引擎不按它分支 |
| `human_controlled` | bool | 唯一决定「谁需要真人输入」的字段（`Battle.focus`、`schedule._next_player_due` 读它） |

### ② 面板基础字段（构造时给的静态值）

`hp` / `max_hp` / `mp` / `max_mp` / `atk` / `matk` / `def` / `mdef` / `spd` /
`crit` / `dodge` / `crit_dmg` / `luck` / `tenacity` / `block` / `pene` / `race`

⚠️ 这些是**裸值**。战斗内的「有效面板」要经 `stats.actor_stats()`（`stats.py:18`）
聚合：有 `class_name` → 调 `panel_fn` hook 重算职业面板；无 → 直读字段；
然后叠加 `effects` 里的面板修正。**伤害/速度/暴击都读聚合面板，不读裸字段**
（例：`schedule._after_act` 用 `stats.actor_spd`，`schedule.py:498`）。

> 唯一的数值兜底：`stats._monster_base_stats` 里 `crit` 缺省取 **0.05**（`stats.py:145`），
> 而 `make_actor` 播种的是 0.0（`actors.py:102`）。这两处不一致，见
> [_selfcheck.md](../_selfcheck.md)。

### ③ 战斗可变状态（构造时已播种）

| 字段 | 形态 | 说明 |
|---|---|---|
| `effects` | `{key: entry}` | **单容器**：增益/减益/DOT/控制/标记/职业资源/挂敌身条/**窗口态**（如防御姿态 `effects["defend"]`，条目自带 `until` 边界声明）**全在这里**，**承伤资源（护盾）也在**（收口第 2 批并入：一条声明了 `absorb` 的带 `value` 条目） |
| `cooldown` | `{技能名: 绝对时刻}` | 调度资源，**独立容器**（它不是「状态」，是行动记账） |
| `charging` | dict \| None | 蓄力态（被打断时清） |
| `ct` | float | **下次可行动时刻**（绝对时刻，见 [ctb-schedule.md](ctb-schedule.md)） |
| `poi_buff` | any | 透传字段，引擎不读 |
| `triggers` | `{事件名: [效果 dict]}` | 事件声明（见 [event-bus.md](event-bus.md)） |
| `act_count` | int | 个体行动计数，`actor_auto` 每动 +1（`battle.py:475`） |
| `dot_next` / `dot_jumps` | `{key: 数值}` | 周期结算的运行期辅助（`schedule.py:645-646` 惰性建） |

**为什么 `cooldown` 不进 `effects`**：它**不是状态**，是「还能不能再放」的调度表，
与「现在身上有什么」无关（按技能名索引，条目模型也表达不了）。

**承伤资源为什么进 `effects`（收口第 2 批 · 2026-09-28 的反转）**：护盾原先是**独立容器**，
理由是「把盾塞进 effects 会让净化把盾清掉、让面板折算把盾值当减伤算」。收口后两条都不成立：
· **净化**只清「有 `period`（非 gain）/ `on==target` / `cleanse` 声明」的条目（`effects.act_cleanse`），
  护盾条目一个都不声明 ⇒ **净化不会碰它**（要清就内容侧给 `cleanse: true`）；
· **面板折算**只读 `stacks` / `stat` / `mult` / `stat_scale`，`value` 不参与面板（`stats._apply_effects`）。
真正的收益是**到期/清除只有一条通路**：原先护盾有自己的到期段（`schedule` 第 2 段），
是同一个容器的逻辑的**副本**（第二本账）；并进来之后到期走容器那一段、只发一次事件。
是否「吸收」由**内容侧声明**决定（`EFFECT_RULES[key].absorb`，可挂在父级 tag 上一族继承），
引擎不认「哪个 key 是盾」。

### ④ 配置 / 能力

| 字段 | 说明 |
|---|---|
| `class_name` | 有值 → `stats` 走职业面板公式；**这是引擎唯一的「身份→行为」分支**，但它是配置读取，不是类型分派 |
| `level` | 等级。⚠️ 引擎不认 `lv`（`actors.py:83`），旧数据的 `lv` 必须由你的桥翻译 |
| `equipment` | 装备 dict，透传给 `panel_fn` |
| `skills` | 技能 key 列表（构造 Battle 时索引进 `_skill_index`） |
| `learned_skills` | 已学技能列表（**引擎不读**，是给你的装配器扫的，如《奥兰迪亚》的 `_learned_mech_skills`） |
| `auto_act` | 自动行动配置（`actor_auto` 读它，`battle.py:422`） |
| `ai` | 通用怪 AI 决策数据（`ai.normalize_ai` / `resolve_ai_move` 读） |
| `_skill_index` | 技能名/index → 技能 dict。**不进存档**（`serialize._STRIP_KEYS`，`serialize.py:31`） |

### ⑤ 三个扩展区（引擎绝不读）

| 区域 | 位置 | 用途 |
|---|---|---|
| `ext` | `actor["ext"]`，`actor_ext()` 惰性播种（`actors.py:170`） | 你的机制自定义状态（名字空间自管） |
| `bonus` | `actor["bonus"]["panel" / "cap" / "cost"]` | 外部数值增幅聚合（引擎读 `bonus.cap` / `bonus.cost` / `bonus.panel`） |
| `triggers` | 见上 | 事件声明 |

`ext` 的原文约定（`actors.py:135-136`）：**「引擎绝不读；职业/机制自定义状态放这里，
命名空间自管」**。

`bonus` 是「平行容器哲学」：引擎把它当**纯数值增量**读，不认识里面的语义。
三个子域各有确切消费者：

| 子域 | 消费者 | 语义 |
|---|---|---|
| `bonus.panel` | `stats._player_base_stats`（`stats.py:99`） | 面板增幅 dict，透传给 `panel_fn` |
| `bonus.cap` | `effects._cap_of`（`effects.py:79`） | `{资源key: 上限增量}`，纯 flat int 加在 `EFFECT_RULES[key].cap` 上 |
| `bonus.cost` | `actions._bonus_cost_of`（`actions.py:293`） | 技能消耗折扣（`mp_pct`/`mp_flat`/`res` + `when` 判据） |

### 其余透传字段

`make_actor(**stats)` 里没被上面消费的任何键都会**原样留在 actor 上**
（`actors.py:139-141`）。这就是 `rank` / `reach` / `traits` / `exp` / `gold` /
`drops` / `element_immune` / `element_weak` / `phys_reduce` / `magic_reduce` 的来路。
它们由**引擎的具体规则**按键读取，不需要在 `make_actor` 里声明。
其中**唯一**参与身份判定的是 `traits`（内容侧写的标签数组）—— 引擎只做
`traits.of` / `traits.has` / `traits.has_any`；`is_boss` / `role` 这类旧身份字段
**引擎已不再读**（2026-09-25 E3 已删），只由内容侧自己消费。

## 标签机制（tag registry / 一次查询）

`extends/ext_combat/battle/tags.py` —— 三件东西，引擎零游戏名词：

| 件 | API | 说明 |
|---|---|---|
| **注册表** | `register` / `register_many` / `registered` | 内容侧声明过的 tag 名（`EFFECT_RULES` 的键在 `load_game_rules` 时自动登记 + `DEFAULT_SLOTS` 的槽位名）。查询**不要求**先注册（状态条目自己就是标签），注册表是词表/审计面 |
| **统一面** | `of(actor)` / `sources_of(actor, tag)` | 一个查询面看**三个来源**：`actor["traits"]`（身份标签）∪ `effects` 容器条目 key（状态）∪ 条目 `grants`（一条状态授多个 tag）。撤销 = 条目没了即没了，不另开接口 |
| **查询** | `has`（层级）/ `has_exact` / `has_any` / `has_all` / `match` | `has(actor, "control")` **父级查得到子级**（命中 `control.stun`，按 `.` 边界；不反向） |
| **槽位** | `slot("immune_control")` → tag 名 | 引擎固定词汇表的**名字归内容侧声明**（装配面 `tag_slots_fn`）；未装配 = 内建缺省，未知名 ⇒ `KeyError`（fail-closed） |
| **前缀带行为** | `rule_of(tag)` → `(声明, 生效那一级)` | 声明表按层级继承：**精确优先**，缺就逐级往父级找（`control.stun` 未声明 ⇒ 用 `control` 的）。`state_def()` 已改成走它 ⇒ 一族 tag 的共同行为在父级写一次，子级只写差异；全都没有 ⇒ `{}`（零兜底） |

口径：空 tag / 空名单 ⇒ 一律 `False`（不声明 = 这条规则不适用于任何人）。
`traits.*` 保留为**精确面**（扁平身份标签，现行行为一字不动）；要层级或全来源就用 `tags.*`。
已经按槽位收口的两处读点：控制免疫（`effects.py` 的 `immune_control`）、DOT 免疫名单
（`effects.py` 的 `immune_dots`）。

## 属性写口：`hp` / `mp` / `ct` 只有一个写入口

收口前，引擎里 12 处写点各写各的钳制（`mp` 扣费有 `max(0,…)` 也有 `max(1,…)`、`hp` 三处口径
各不同、`ct` 完全裸写）—— 同一条规则各写一遍，且已经不一致。现在全部走
`extends/ext_combat/battle/attributes.py`：

| 件 | 形状 | 说明 |
|---|---|---|
| **唯一写口** | `set_current(actor, key, value, *, reason, battle)` / `add_current(...)` | `key` 不在 `("hp","mp","ct")` ⇒ `KeyError`（走错地方当场炸）；值没变 ⇒ 不写、不叫钩子 |
| **内建边界** | `ceiling` / `floor_of` | 下限一律 ≥0 · 上限 `hi = max(上限, 现在值)`：**只在抬值方向生效**（现在值没越界 ⇒ 就是 `min(max_hp,…)`，与 heal/regen 路逐字相同；已越界的脏数据**不压回** —— 实测 `test_host_skeleton` 的合成 fixture `hp=300 > max_hp=203` 会被严格上限翻掉胜负）。`ct` 无上限。**保命类下限（`max(1,…)`）不是内建规则** —— 那是机制行为，调用方算完再传 |
| **类型保持** | 按**入参类型**落值 | int 进 int 出、float 进 float 出 —— 冻结对拍逐字节相同靠这条 |
| **预改钩子** | `attr_pre_fn(actor, key, value, ctx)` | 未装配 ⇒ 不存在；返回变换后的值，`None` = 交回内建规则；**不做拦截语义** |
| **后改钩子** | `attr_post_fn(actor, key, old, new, ctx)` | 只在值真变了时调用（响应/记账位）；抛错上抛 |
| **机器门禁** | `tests/test_attrs_write_port.py` | 引擎代码里**不得再出现对 `hp`/`mp`/`ct` 的下标直接赋值**（白名单一处报价 dict，条数恒 1）⇒ 漏改一处当场红 |

`reason` 是引擎词（`damage` / `heal` / `cost` / `regen` / `schedule_seed` / `schedule_after_act` /
`death_guard`），只用于记账与排障，**不是**游戏名词。面板派生值（`max_hp`/`atk`…）是重算出来的、
`traits` 是构造期数据、`effects[key].stacks` 已由 `actors.open_entry` 收口 —— 三者**都不走写口**。

## `ActCtx`：一次行动的上下文

```python
@dataclass
class ActCtx:                       # actors.py:19
    caster: dict                    # 谁在行动
    action: str = "attack"          # attack|skill|defend|flee|use_item|auto|任意自定义
    skill_name: Optional[str] = None
    info: Optional[dict] = None     # 技能/动作配置（技能 dict）
    target: Optional[dict] = None   # 单目标
    target_side: Optional[str] = None
    scope: str = "single"           # single|all|front|side:<name>|self
```

`__post_init__`（`actors.py:32`）做两件防御：
`action="skill"` 但 `info` 为空时从 `caster["_skill_index"]` 补；
`scope` 为空但给了 `target_side` 时推导。

**为什么用 dataclass 而不是传一堆参数**：设计目标是「消灭隐式全局目标」。
旧引擎把当前目标存战斗对象上，AOE 与多段结算时互相踩。现在每次行动一个 ctx，
显式传 `caster` / `target`（`actors.py:6-7`）。

## Sides：唯一容器

`sides = {阵营名: [actor, ...]}`（普通 dict，没有封装类）。设计原因：**动态遍历**。
调度（`schedule._next_player_due` / `_next_auto_due`）、序列化（`serialize.to_state`）、
事件广播（`fire` 遍历全部 sides）都在运行期直接遍历它，所以 `add_actor` 不需要
通知任何人（`battle.py:292-294`）。

阵营敌对关系由 `hostile_sides`（`actors.py:206`）决定：优先读 `battle.hostile_map[side]`，
没有则「除自己外的全部阵营」。**引擎不预设玩家/怪身份**。

## 相关

- 效果条目的内部形态 → [effects.md](effects.md)
- `triggers` 何时被读 → [event-bus.md](event-bus.md)
- 完整字段的 API 逐项 → [../reference/api.md](../reference/api.md)
