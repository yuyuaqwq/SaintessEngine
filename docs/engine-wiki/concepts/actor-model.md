# actor 同构数据模型

## 一句话

**引擎里只有一种实体：`dict`。** 玩家、怪、Boss、召唤物、变身形态没有类型差异，
只有字段值的差异。引擎逻辑**只用字段值，不按字段猜身份**（`actors.py:8` 的原文）。

## 为什么这么设计

旧引擎用「玩家分支 / 怪分支」两套代码处理同一件事（`_player_stats` vs `_enemy_stats`、
`_actor_skill` vs 玩家技能路径），结果是：**同一个机制要写两遍**，且第二遍经常忘。
同构化的收益：

- 一个机制动作对玩家和怪同时生效，不需要「怪也能用」的额外适配
- `add_actor()` 加援军/召唤物时不需要给调度器注册新类型（`battle.py:217`）
- 序列化不需要按类型分派（`serialize._serialize_actor` 对任何 actor 一视同仁，`serialize.py:53`）

代价：**身份信息全靠字段**。要表达「这是 Boss」就写 `is_boss=True` 或 `role="boss"`
（引擎真读这两个的地方：控制时长减半 `effects.py:305`、DOT 的 `pct_boss` 档 `schedule.py:268`、
`is_boss`/`role` 也在部分内容侧判定里被读）。

## 字段全集

`make_actor`（`actors.py:58`）产生的字段分四组。

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

⚠️ 这些是**裸值**。战斗内的「有效面板」要经 `stats.actor_stats()`（`stats.py:19`）
聚合：有 `class_name` → 调 `panel_fn` hook 重算职业面板；无 → 直读字段；
然后叠加 `effects` 里的面板修正。**伤害/速度/暴击都读聚合面板，不读裸字段**
（例：`schedule._after_act` 用 `stats.actor_spd`，`schedule.py:143`）。

> 唯一的数值兜底：`stats._monster_base_stats` 里 `crit` 缺省取 **0.05**（`stats.py:122`），
> 而 `make_actor` 播种的是 0.0（`actors.py:98`）。这两处不一致，见
> [_selfcheck.md](../_selfcheck.md)。

### ③ 战斗可变状态（构造时已播种）

| 字段 | 形态 | 说明 |
|---|---|---|
| `effects` | `{key: entry}` | **单容器**：增益/减益/DOT/控制/标记/职业资源/挂敌身条**全在这里** |
| `shields` | `{key: {"value","expire_at","halve"}}` | 承伤资源，**独立容器**（不是 effects 条目） |
| `cooldown` | `{技能名: 绝对时刻}` | 调度资源，**独立容器** |
| `charging` | dict \| None | 蓄力态（被打断时清） |
| `defending` | bool | 防御姿态（`deal_damage` 里减伤 50%，`landing.py:102`） |
| `ct` | float | **下次可行动时刻**（绝对时刻，见 [ctb-schedule.md](ctb-schedule.md)） |
| `poi_buff` | any | 透传字段，引擎不读 |
| `triggers` | `{事件名: [效果 dict]}` | 事件声明（见 [event-bus.md](event-bus.md)） |
| `act_count` | int | 个体行动计数，`actor_auto` 每动 +1（`battle.py:391`） |
| `dot_next` / `dot_jumps` | `{key: 数值}` | 周期结算的运行期辅助（`schedule.py:228-229` 惰性建） |

**为什么 `shields` / `cooldown` 不进 `effects`**：它们**不是状态**。
护盾是「承伤时按值扣减的资源」，冷却键是「还能不能再放」的调度表——
把护盾塞进 `effects` 会让「净化」把盾一起清掉、让面板折算把盾值当减伤算。
设计原话见 `actors.py:112-115`。

### ④ 配置 / 能力

| 字段 | 说明 |
|---|---|
| `class_name` | 有值 → `stats` 走职业面板公式；**这是引擎唯一的「身份→行为」分支**，但它是配置读取，不是类型分派 |
| `level` | 等级。⚠️ 引擎不认 `lv`（`actors.py:79`），旧数据的 `lv` 必须由你的桥翻译 |
| `equipment` | 装备 dict，透传给 `panel_fn` |
| `skills` | 技能 key 列表（构造 Battle 时索引进 `_skill_index`） |
| `learned_skills` | 已学技能列表（**引擎不读**，是给你的装配器扫的，如《奥兰迪亚》的 `_learned_mech_skills`） |
| `auto_act` | 自动行动配置（`actor_auto` 读它，`battle.py:346`） |
| `ai` | 通用怪 AI 决策数据（`ai.normalize_ai` / `resolve_ai_move` 读） |
| `_skill_index` | 技能名/index → 技能 dict。**不进存档**（`serialize._STRIP_KEYS`，`serialize.py:33`） |

### ⑤ 三个扩展区（引擎绝不读）

| 区域 | 位置 | 用途 |
|---|---|---|
| `ext` | `actor["ext"]`，`actor_ext()` 惰性播种（`actors.py:168`） | 你的机制自定义状态（名字空间自管） |
| `bonus` | `actor["bonus"]["panel" / "cap" / "cost"]` | 外部数值增幅聚合（引擎读 `bonus.cap` / `bonus.cost` / `bonus.panel`） |
| `triggers` | 见上 | 事件声明 |

`ext` 的原文约定（`actors.py:133-134`）：**「引擎绝不读；职业/机制自定义状态放这里，
命名空间自管」**。

`bonus` 是「平行容器哲学」：引擎把它当**纯数值增量**读，不认识里面的语义。
三个子域各有确切消费者：

| 子域 | 消费者 | 语义 |
|---|---|---|
| `bonus.panel` | `stats._player_base_stats`（`stats.py:96`） | 面板增幅 dict，透传给 `panel_fn` |
| `bonus.cap` | `effects._cap_of`（`effects.py:71`） | `{资源key: 上限增量}`，纯 flat int 加在 `EFFECT_RULES[key].cap` 上 |
| `bonus.cost` | `actions._bonus_cost_of`（`actions.py:237`） | 技能消耗折扣（`mp_pct`/`mp_flat`/`res` + `when` 判据） |

### 其余透传字段

`make_actor(**stats)` 里没被上面消费的任何键都会**原样留在 actor 上**
（`actors.py:137-139`）。这就是 `rank` / `reach` / `is_boss` / `exp` / `gold` /
`drops` / `element_immune` / `element_weak` / `phys_reduce` / `magic_reduce` 的来路。
它们由**引擎的具体规则**按键读取，不需要在 `make_actor` 里声明。

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

`__post_init__`（`actors.py:30`）做两件防御：
`action="skill"` 但 `info` 为空时从 `caster["_skill_index"]` 补；
`scope` 为空但给了 `target_side` 时推导。

**为什么用 dataclass 而不是传一堆参数**：设计目标是「消灭隐式全局目标」。
旧引擎把当前目标存战斗对象上，AOE 与多段结算时互相踩。现在每次行动一个 ctx，
显式传 `caster` / `target`（`actors.py:6-7`）。

## Sides：唯一容器

`sides = {阵营名: [actor, ...]}`（普通 dict，没有封装类）。设计原因：**动态遍历**。
调度（`schedule._next_player_due` / `_next_auto_due`）、序列化（`serialize.to_state`）、
事件广播（`fire` 遍历全部 sides）都在运行期直接遍历它，所以 `add_actor` 不需要
通知任何人（`battle.py:227-229`）。

阵营敌对关系由 `hostile_sides`（`actors.py:193`）决定：优先读 `battle.hostile_map[side]`，
没有则「除自己外的全部阵营」。**引擎不预设玩家/怪身份**。

## 相关

- 效果条目的内部形态 → [effects.md](effects.md)
- `triggers` 何时被读 → [event-bus.md](event-bus.md)
- 完整字段的 API 逐项 → [../reference/api.md](../reference/api.md)
