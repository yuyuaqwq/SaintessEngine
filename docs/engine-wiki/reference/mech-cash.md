# 参考：`MECH_CASH` 机制兑现声明

> ⚠️ **边界声明**：这张表**不属于引擎**。它在你的内容规则模块里
> （参考实现：**游戏仓 / 奥兰迪亚侧**的 `game/data/battle2_rules.py:520`），由**你的装配器**读取并翻译成
> `actor["triggers"]`（参考实现：`game/services/class_mech_proc.py:2201` `apply_class_mech`，
> 装配分支在 `:2313-2374`）。引擎侧零代码认识 `MECH_CASH`。
>
> 它进 wiki 的原因：它是「主动技能的 mech 怎么兑现」这件事上，游戏仓 / 奥兰迪亚侧验证过的一套
> 完整约定（mode 语义、owner 方向、清层时机），照抄能省掉自己设计装配格式的成本。
> 下文出现的机制名（`finisher` / `arcane_burst` / 终结技 / 燃尽 …）都是**那只游戏的实例**，不是引擎名词。

## 一句话

技能数据写 `mech: "finisher"`；`MECH_CASH["finisher"]` 声明「**花掉 N 层 `lian_duan`，
每层 +10% 伤害，命中后清层**」；装配器在开战时把它翻成
`dmg_calc` 乘区触发器 + `skill_hit` 清层触发器。

## 声明字段

| 字段 | 必填 | 语义 | 装配器行为 |
|---|---|---|---|
| `mode` | ✅ | 兑现模式（见下） | 决定挂哪些事件、owner 方向 |
| `key` | ✅（`fury_enter` 除外） | 消费的叠层 key。**支持列表**（`["fire_mark","ice_mark",...]`，层数 = 各 key 之和，清层清全部） | 透传进触发器 |
| `per_layer` | ✖ | 每层伤害加成（`0.10` = 每层 +10%） | `dmg_mult_clear*` 用；可被 `upgrade` 加成 |
| `per_system` | ✖ | 每「系」加成（`per_system_clear*` 用） | 透传 |
| `clear` | ✖ | 命中后清层 | 为真 → 额外挂 `skill_hit` 清层触发器 |
| `clear_extra` | ✖ | 并列清层 `[{"owner": "caster"\|"target", "key": ...}]` | 透传进清层动作 |
| `name` | ✖ | 标签（日志用） | 进 `label` |
| `layer_label` / `unit` / `icon` | ✖ | 文案 flavor（日志 = `"{icon} {name}！…"`） | 透传 |
| `upgrade` | ✖ | `{"proc": "...", "per_layer_add": 0.06}`：学到带该 proc 的技能 → `per_layer` 增加 | 装配时查 `_learned_proc`（`class_mech_proc.py:2354-2358`） |
| `res` | ✖（`fury_enter` 必填） | 消耗的资源 key | 透传 |
| `note` | ✖ | 纯注释 | 不装配 |

`upgrade` 的注意点：它扫的是**主动技能**上的 `passive.proc`
（因为装配器只把 `kind=被动` 的技能当被动装，主动技上的 proc 不装触发器，
但可以当「学到即升级」的判据 —— `_learned_proc`，`class_mech_proc.py:1941`）。

## 五个 mode

| mode | owner 方向 | 挂的事件 | 语义 | 参考实现 |
|---|---|---|---|---|
| `dmg_mult_clear` | `caster`（缺省） | `dmg_calc` + （`clear` 时）`skill_hit` | 读/清 **caster** 的层 → 每层加伤 | `finisher` / `arcane_burst` / `guard_core_burst` |
| `dmg_mult_clear_target` | `target` | 同上 | 读/清 **target** 的层（印记/毒在敌身上） | `element_burst_all` / `poison_burst` / `poison_burst_finisher` |
| `per_system_clear_target` | `target` | `dmg_calc`（每系乘区）+ `skill_hit` | 每系独立乘区（`stacks >= 1` 的系才乘） | `element_burst_3` |
| `fury_enter` | `caster` | `act_cast` | 花 `res` 层 → 写 `effects[form]` 条目（进形态） | `zhan_yi_fury` |
| `heal_clear` | — | ⚠️ **装配器不处理** | 声明存在，但 `apply_class_mech` 的 mode 分派里没有它（`class_mech_proc.py:2350`）→ 走不动 | `faith_unload` |

### owner 方向的推导规则（不是字段）

```python
owner = "target" if mode.endswith("_target") else "caster"
```
（`class_mech_proc.py:2320`）

以及 `per_system_clear*` 由 `mode.startswith("per_system_clear")` 判
（`:2321`）。所以 **mode 名字的后缀有语义** —— 造新 mode 时命名要守这个约定，
否则 owner 会推错（错的方向 = 去读不存在的层 = 乘区恒 1 = 静默不生效）。

`owner` 是怎么生效的：装配器往效果 dict 里写 `"owner": "target"`
（`:2330-2331`），扩展动作 `mech_cash_dmg_mult` / `mech_cash_clear` 读它决定
「读自己的 `effects` 还是 `ctx["target"]` 的 `effects`」。

### `heal_clear` 的真相（重要）

声明里写着：

```python
"faith_unload": {
    "name": "卸负",
    "mode": "heal_clear",             # 技能内兑现（res_cost 数据通道，无事件钩子）
    "key": "faith", "amount": 3,
    "note": "兑现走 skills.py sk_xie_fu res_cost={faith:3} + kind=治疗 heal_formula",
},
```
（`game/data/battle2_rules.py:616-622`）

也就是说：**`heal_clear` 这个 mode 不是引擎/装配器的能力，而是一条「我们决定用别的
通道兑现」的记录**。真实兑现走技能数据的 `res_cost` + `kind=治疗`
（引擎原生路径：`actions._skill_usable` 预检 + `_spend_skill_cost` 扣层 + `_do_heal` 回血）。

⚠️ `MECH_CASH` docstring 里还列了 `bonus_clear`（「层数转附加伤害后清层」），
注释自承「**备用形态，R1b 未用**」（`game/data/battle2_rules.py:509-510`）——
装配器里同样没有它。**§`MECH_CASH` 的 mode 全集有 6 个，实际装配器支持 4 个。**

## 参考实现的 9 条声明

| mech | name | mode | key | per_layer / per_system | clear |
|---|---|---|---|---|---|
| `finisher` | 终结技 | `dmg_mult_clear` | `lian_duan` | 0.10（+`upgrade` 0.06） | ✅ |
| `arcane_burst` | 燃尽 | `dmg_mult_clear` | `arcane` | 0.15 | ✅ |
| `guard_core_burst` | 磐核 | `dmg_mult_clear` | `guard_core` | 0.7 | ✅ |
| `element_burst_all` | 元素迸发 | `dmg_mult_clear_target` | `[fire_mark, ice_mark, thunder_mark]` | 0.12 | ✅ |
| `element_burst_3` | 元素裁决 | `per_system_clear_target` | 同上 | `per_system` 0.20 | ✅ |
| `poison_burst` | 荆棘爆 | `dmg_mult_clear_target` | `poison` | 0.15 | ✅ |
| `poison_burst_finisher` | 毒爆 | `dmg_mult_clear_target` | `poison` | 0.14 | ✅（+`clear_extra` 清 caster `lian_duan`） |
| `zhan_yi_fury` | 狂暴 | `fury_enter` | `res: zhan_yi` | — | — |
| `faith_unload` | 卸负 | `heal_clear` | `faith` | — | — |

（`game/data/battle2_rules.py:520-623`）

三条值得逐字看的真实条目：

```python
"finisher": {
    "name": "终结技",
    "mode": "dmg_mult_clear",        # owner=caster（缺省）：读/清 caster effects
    "key": "lian_duan",              # 消费的叠层条目
    "per_layer": 0.10,               # 每层伤害 +10%（技能 info.per_stack 可覆盖：链舞 +6%）
    "upgrade": {"proc": "finisher_up", "per_layer_add": 0.06},
    "clear": True,                   # 命中后清层（info.keep_on_kill = 不清，技能级覆盖）
    "crit_at": 4,                    # 连段 ≥4 必定暴击（声明先行——crit roll 前钩子就绪后生效）
    "layer_label": "连段", "unit": "段", "icon": "🔪",
},
```
（`:521-532`）—— 注意 `crit_at` **不在装配器读取的字段里**：
注释自己写着「声明先行」，即**声明了但钩子还没做**（⚠️ 缺口）。同样，
`info.per_stack` / `info.keep_on_kill` 的「技能级覆盖」也需你的动作实现。

```python
"zhan_yi_fury": {
    "name": "狂暴",
    "mode": "fury_enter",            # 血祭：花 res 层战意 → 进入狂暴（无视 10 层门槛）
    "res": "zhan_yi",
    "label": "血祭", "icon": "🔥",
    # mech_val（技能数据 4）= 进入消耗的战意层数——兑现动作读 mech_val_field 扣层
},
```
（`:534-541`）—— `fury_enter` 是唯一不走叠层乘区的 mode；
它读技能数据的 `mech_val`（`mech_val_field`，`class_mech_proc.py:2344`）决定花几层。

```python
"poison_burst_finisher": {
    "name": "毒爆", "mode": "dmg_mult_clear_target", "key": "poison",
    "per_layer": 0.14, "clear": True,
    # desc 明写"结算后连段归零"：主清 target 毒层之外，并列清 caster 连段（clear_extra）
    "clear_extra": [{"owner": "caster", "key": "lian_duan"}],
    "layer_label": "毒", "icon": "☠️",
},
```
（`:590-599`）—— 一条技能同时清两边（敌身上的毒 + 自己身上连段）用 `clear_extra`。

## 装配后长什么样

`finisher`（`dmg_mult_clear`，`clear=True`）产出两个触发器：

```python
actor["triggers"]["dmg_calc"].append(
    {"action": "mech_cash_dmg_mult", "mech": "finisher", "key": "lian_duan",
     "per_layer": 0.10, "label": "终结技", "layer_label": "连段", "unit": "段", "icon": "🔪"})
actor["triggers"]["skill_hit"].append(
    {"action": "mech_cash_clear", "mech": "finisher", "key": "lian_duan"})
```
（`class_mech_proc.py:2359-2374`）

⚠️ `skill_hit` 的清层发生在**命中后**，所以增伤与清层天然有序
（`dmg_calc` 在伤害管线中、`skill_hit` 在其后）—— 这个顺序是**依赖事件时机**而非 list 顺序。

## 加一条自己的 MECH_CASH

```python
# game/data/battle2_rules.py
MECH_CASH["my_burst"] = {
    "name": "我的引爆",
    "mode": "dmg_mult_clear_target",     # 层在敌身上
    "key": "my_mark",
    "per_layer": 0.20,
    "clear": True,
    "layer_label": "印记", "unit": "层", "icon": "💥",
}
```

前置条件（缺一个就静默不生效）：

1. 技能数据里 `"mech": "my_burst"`
2. `EFFECT_RULES["my_mark"]` 存在（否则层数读不到、cap 不设限）
3. 有东西往目标身上叠 `my_mark`（渠道 / 技能 mech / 触发器）
4. `apply_class_mech(actor)` 在开战仪式里被调用（否则 triggers 不装配）
5. 层数读 float 还是 int —— 参考实现用 `_stacks_float`（小数层保真，
   `class_mech_proc.py:553-554`）；你的动作要自己决定

## 相关

- 动作里的乘区写法 → [../guides/write-a-mechanic.md](../guides/write-a-mechanic.md)
- 被动 proc（另一张装配表） → [passive-proc.md](passive-proc.md)
- 声明驱动的原理 → [../concepts/declaration-tables.md](../concepts/declaration-tables.md)
