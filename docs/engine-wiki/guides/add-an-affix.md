# 指南：加一个词条 / 装备特效

## 先明确一件事：引擎没有「词条」概念

`saintess_engine/` 里没有 `affix`、没有 `equip`、没有 `proc_stack`。
引擎只有三样东西：

1. `actor["triggers"]`（事件 → 效果声明）
2. `actor["bonus"]`（面板/上限/消耗的平行数值容器）
3. `register_action`（你可以注册任意动词）

**词条/装备特效是这三样的组合**。本页讲《奥兰迪亚》（游戏仓侧的参考实现）内容侧总结出的两种成熟形态
（原文：`game/services/battle_we_procs.py:1-4` 的「N9 形态 2」），
第三方可以直接照抄这套形态，也可以自己造。

## 形态 1：纯声明（能用引擎原生动词表达）

最简单的一类：**开战时给个 buff / 给个盾 / 给层数**。
不用写任何代码，只要往 `triggers` 里塞一条指向**已有动词**的条目。

```python
def equip_flat_affix(actor, affix_data):
    trig = actor.setdefault("triggers", {})
    for ev, entries in affix_data.items():
        trig.setdefault(ev, []).extend(entries)
```

《奥兰迪亚》的第一批装备特效就是这么做的：「起手类纯动词 key（`proc_shield` 起手 2 +
`proc_buff` 起手 6），验证『读表 → 事件映射 → triggers 装配 → 引擎 fire』管线」
（`game/services/battle_equip_proc.py:16-18`）。

## 形态 2：族扩展动作（有分支逻辑时）

有「条件/概率/多步副作用」的特效，注册一个 `we_xxx` 族动词
（`game/services/battle_we_procs.py:1-14` 的原文约定）：

```python
@register_action("we_affix_dot")
def we_affix_dot(battle, caster, target, params, logs):
    """命中附带流血：roll chance → 挂 DOT 层。"""
    ...
```

族动作的约定（与引擎动词同签名，另有四条自约）：

| 约定 | 说明 | 出处 |
|---|---|---|
| 读事件数值用 `battle._fire_ctx` | `dmg` / `is_crit` / `overflow` / `source` 在那里 | `game/services/battle_we_procs.py:10-11` |
| 持久状态写 `actor["ext"]` | 「CD/次数/标记等持久状态写 `actor["ext"]`（引擎绝不读，扩展动作自管）」 | `game/services/battle_we_procs.py:12` |
| 数值全读 `params` | 「数值权威：全部读 params；缺字段 = 无此行为」 | `game/services/battle_we_procs.py:14-15` |
| 内部叠层用局部 helper | 例 `_add_stacks(actor, key, amount, cap)` 走 `effects[key].stacks` | `game/services/battle_we_procs.py:49-55` |

⚠️ `actor["ext"]` 有一个**必须知道**的性质：它会**随存档落盘**
（`serialize._serialize_actor` 不剥 `ext`，只剥 `_skill_index`，`serialize.py:31`）。
所以「本次战斗的 CD」用 `ext` 是安全的；如果你的 `ext` 里放了不可 JSON 化的东西，
存档时 `json.dumps` 会抛 —— `serialize.state_to_json` 用了 `default=str` 兜底
（`serialize.py:123`），结果是静默变成字符串。

## 事件映射：旧事件名 → 引擎事件名

如果你的特效数据表用的是自己的事件词汇表，写一张映射表（照抄这张，
`game/services/battle_equip_proc.py:26-44`）：

```python
_EVENT_MAP = {
    "battle_start": ("battle_start",),
    "hit":          ("attack_hit", "skill_hit"),   # 「命中」展开成普攻+技能两个事件
    "skill_hit":    ("skill_hit",),
    "skill_cast":   ("act_cast",),
    "taken":        ("on_taken",),
    "heal":         ("on_heal",),
    "turn_start":   ("turn_start",),
    "threshold":    ("threshold",),
    "crit":         ("crit",),
    "kill":         ("on_kill",),
    "enemy_act":    ("act_done",),                 # 敌方行动后 → 全员广播 + 效果侧自判敌我
}
```

```python
def map_event(old_ev):
    return _EVENT_MAP.get(old_ev, (old_ev,))       # 不在表内 = 假定已是引擎事件名，直通
```
（`game/services/battle_equip_proc.py:47-51`）

**为什么 `hit` 要展开成两个事件**：引擎把「普攻命中」(`attack_hit`) 与「技能命中」
(`skill_hit`) 分成两个事件（`actions.py:486` 按 `info["_basic"]` 选）。
你的数据表只写「命中」时，得同时挂两个。

**为什么 `enemy_act` 映射到 `act_done`**：`act_done` 是**不带 subject 的广播事件**
（`ctx["acted"]` 才是行动者，`battle.py:584-589`），所以「敌方行动后我叠减速」
这类特效要在动作里**自己判敌我**（例：`we_act_done_slow`）。

## 词条的三种数值通道

词条数值可以落在三个地方，选错了就不生效：

| 通道 | 写哪里 | 谁消费 | 适合 |
|---|---|---|---|
| `triggers` 参数 | `{"type": "we_xxx", "pct": 0.2}` | 你自己的族动作 | 一次性/有条件的效果 |
| `actor["bonus"]["panel"]` | 面板增幅 dict | `stats._player_base_stats` 把它传给 `panel_fn`（`stats.py:95-109`） | 常驻面板增幅 |
| `actor["bonus"]["cap"]` | `{资源key: +N}` | `effects._cap_of`（`effects.py:75`） | 资源上限词条 |
| `actor["bonus"]["cost"]` | `{mp_pct, mp_flat, res, when}` | `actions._skill_pay_of`（`actions.py:272`） | 消耗折扣词条 |

`bonus.panel` 的形态由**你的** `panel_fn` 决定（引擎只是把它当不透明 dict 透传）。
`bonus.cap` / `bonus.cost` 的形态是引擎定的，有确切读取点。

## `bonus.cost`：消耗折扣（引擎原生支持）

```python
actor["bonus"]["cost"] = {
    "mp_pct": 0.10, "mp_flat": 5,                  # 顶层 = 无条件域
    "res": {"energy": 0.05},                       # 按资源 key 的折扣
    "when": [                                      # 条件域（按技能判）
        {"mp_pct": 0.20, "judge": {"mech_prefix": ["arcane"]}},
    ],
}
```

读取与折算在 `_skill_pay_of`（`actions.py:272-307`），两条硬规则（`actions.py:242-248` 注释）：

```
pay = max(1, floor(声明 × (1 - Σpct)) - Σflat)
```

- **折扣只减不增**；声明消耗 >0 的技能**保底扣 1**（不许白嫖）
- `floor` 向下取整（玩家受益方向）；无折扣 → 返回值与声明完全一致（行为零变化）

`when` 的判据由 `_cost_judge_hit`（`actions.py:252`）实现，支持三个谓词：
`element`（技能有元素）、`mech_prefix`（技能 mech 前缀）、
`name_contains`（技能显示名含子串）。多个谓词是 **OR**；空 judge = 恒命中。

## 一个完整可抄的最小词条

「攻击时 20% 概率让目标流血，每刻 5% 生命，3 跳」：

```python
# ① 规则表：声明 DOT 的行为（引擎直接消费）
EFFECT_RULES["affix_bleed"] = {
    "cap": 3, "on": "target",
    "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.05,
               "pct_boss": 0.02, "turns": 3},
}

# ② 名词声明：把词条名词翻成引擎动词（用引擎原生 apply，无需注册）
EFFECT_ACTIONS["affix_bleed_hit"] = [
    {"action": "apply", "op": "add", "key": "affix_bleed", "on": "target",
     "amount": 1, "chance": 0.2},
]
```
（真实同款：`game/data/battle_rules.py:366-370` 的 `affix_bleed`）

```python
# ③ 装配：命中事件 → 名词
def equip_affix_bleed(actor):
    actor.setdefault("triggers", {}).setdefault("skill_hit", []).append(
        {"type": "affix_bleed_hit"})
    actor.setdefault("triggers", {}).setdefault("attack_hit", []).append(
        {"type": "affix_bleed_hit"})
```

`chance: 0.2` 由 `apply_effects` 的通用 roll 消费（`effects.py:185-191`），
不需要你写 roll 代码。`op="add"` + `key` 走叠层，cap 由规则表的 `cap: 3` 管。

## 面板词条（常驻增幅）

```python
actor.setdefault("bonus", {}).setdefault("panel", {})["my_affix_atk"] = 0.10
```

⚠️ 这是**你**的 `panel_fn` 要认识的格式，不是引擎格式。引擎只做
`_tb = (actor.bonus.panel or battle.title_bonus or {})` 然后
`fn(class_name, level, equipment, tier, attributes, evolve_path, _tb, race)`
（`stats.py:95-109`）。所以词条面板必须和你的面板公式一起设计。

另一条更省事的路：**用 `effects` 面板快照**。开战时写
`actor["effects"]["atk_up"] = {"stacks": 1, "expire": None, "stat": "atk", "op": "mul", "mult": 1.1}`
—— `stats._apply_effects` 的快照分支会直接吃掉它（`stats.py:68-80`），
不需要改 `panel_fn`。《奥兰迪亚》的开战祝福就是这么翻译的
（`game/services/battle_bridge._battle_boons_to_effects`，`game/services/battle_bridge.py:49`）。

## 相关

- 效果声明 schema → [../reference/effect-rules.md](../reference/effect-rules.md)
- 名词→动词 → [../reference/effect-actions.md](../reference/effect-actions.md)
- 乘区钩子（条件增伤/减伤类词条） → [write-a-mechanic.md](write-a-mechanic.md)
