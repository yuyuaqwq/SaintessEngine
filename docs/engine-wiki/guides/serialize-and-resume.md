# 指南：存档与续战

## 一句话

```python
state = battle.to_state()            # → 纯 JSON 可序列化 dict（sides-only）
saintess_engine = Battle.from_state(state)   # ← 重建 Battle / sides / actors / 时刻 / 胜负
```

入口：`serialize.to_state`（`serialize.py:34`）/ `serialize.from_state`（`serialize.py:57`），
包门面也 re-export 了模块级 `to_state` / `from_state`（`saintess_engine/__init__.py:41`），
`Battle.to_state` / `Battle.from_state` 是类方法包装（`battle.py:656/532`）。
**两条路等价**，内容层两种都在用（游戏仓侧拆仓前的迁移计划 `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` §5 记了
`B2.from_state` 与 `Battle.from_state` 两种形态）。

## 存档结构

```python
{
  "type": "monster",              # battle.btype
  "now": 3.41,                    # 全局时钟（绝对时刻）
  "p_acts": 5,                    # 行动点计数（展示用）
  "result": None,                 # None | "victory" | "defeat" | "fled"
  "winner_side": None,
  "sides": {"player": [actor, ...], "enemy": [actor, ...]},
  "hostile_map": {...},
  "title_bonus": {...},
  "killed": ["e1", "e2"],         # 击杀记录（**uid 列表**，不是对象）
  "flags": {},                    # 预留（当前恒 {}）
}
```

⚠️ **恢复的构造参数不完整**：`from_state` 只回传 `btype` / `sides` / `title_bonus` /
`hostile_map` / `seed_ct=False`（`serialize.py:64-74`）——
其余构造参数**全部丢失**：`pet` / `dmg_mult` / `target_picker` / `on_event` /
`action_override` / `script_hook`。这些钩子需要在恢复后**自己重新挂**。
（`text=`（v186 文案表）是**可选关键字参数**：`Battle.from_state(state, text=table)` 与
构造注入同口径；不传 = 未注入 ⇒ 战斗日志走调用点兜底模板，逐字节 = 历史内联串。）

```python
b2 = Battle.from_state(state)
b2.target_picker = my_picker        # 恢复后手动补
b2.script_hook = my_director
```

另：`flags` 字段写入恒为 `{}`（`serialize.py:47`），**不落盘任何战斗级一次性标记**。
如果你需要「本场只触发一次」的状态，得放在 actor 上（`effects` / `ext`）。

## actor 序列化：几乎全字段带走

`_serialize_actor`（`serialize.py:51`）只**剥一个键**：

```python
_STRIP_KEYS = {"_skill_index"}      # serialize.py:31 —— 运行时索引，恢复时重建
```

**其它一切原样落盘**，包括 `effects` / `shields` / `cooldown` / `triggers` / `ext` /
`bonus` / `dot_next` / `dot_jumps` / `act_count` / 任意透传自定义字段。
这意味着：

- 好处：你的自定义状态（放 `ext`）**自动**持久化，不需要写序列化代码
- 风险：**不可 JSON 化的东西会让存档炸**。`state_to_json` 有 `default=str` 兜底
  （`serialize.py:123`），会把奇怪对象静默变成字符串 —— 恢复后类型就变了。
  所以 `ext` 里只放基本类型 / dict / list

**实际会出现在存档里的「非内容字段」清单**（知道有这些，排查时才不会以为中邪）：

| 字段 | 来源 | 说明 |
|---|---|---|
| `_content_applied` | 内容侧 `apply_game_content` 的幂等标记（`game/content_rules/apply.py:81`） | 会落盘（原文自记：游戏仓侧拆仓计划的收口步 S9 若要清掉需改引擎 `serialize.py`） |
| `dot_next` / `dot_jumps` | 引擎周期结算辅助（`schedule.py:434-435`） | 落盘是**续战能对上**的原因，别手删 |
| `_dmg_taken_mult` | 上层直写（例 `commands/boss_script.py:684`） | 承伤乘区（`landing.py:92-99` 读） |
| `act_count` | `actor_auto` 每动 +1（`battle.py:425`） | AI `round_mod` 谓词读它 |
| `reduce_left` | `effects.act_apply`（`effects.py:463`） | ⚠️ 无消费者 |

## 恢复时的三个隐式决定

```python
def from_state(st, *, text=None):
    b = Battle(..., seed_ct=False)      # ① 不重播初始 ct
    b._now = float(st.get("now", 0) or 0)
    b._started = True                   # ② 不再 fire battle_start
    ...
```
（`serialize.py:57-80`）

### ① `seed_ct=False`

构造 Battle 时默认会**播种每个 actor 的初始 ct**（`Battle.__init__:91-94`）。
恢复路径必须关闭它：存档里的 `ct` 是战斗进行到一半的真实值，
重播会把它按速度重算成「刚开局」——续战起手顺序直接错乱。
（原注释：`actors.py` 的 ct 已随存档反序列化，不重播，`serialize.py:72-73`）

### ② `_started=True`

`battle_start` 事件是**整场一次**的（`_ensure_battle_started`，`battle.py:596`），
它承载「起手效果 / 词条套装 / 仪式祝福」。恢复的战斗已经在开战之后，
再 fire 一次会让起手 buff **双份**。

### ③ `killed` 用 uid 找回

```python
for uid in (st.get("killed") or []):
    for acts in b.sides.values():
        for a in acts:
            if a.get("uid") == uid:
                b.killed_actors.append(a)
```
（`serialize.py:83-88`）

⚠️ 用的是**对象引用**重建：从 squad 里找 `uid` 相同的 actor。注释说
「找不到跳过——已从 sides 移除的阵亡单位」（`serialize.py:81`）。
但**引擎其实从不把阵亡 actor 从 `sides` 移除**（`_on_actor_dead` 只 append 进
`killed_actors`，`battle.py:611-627`；`_check_side_end` 也不删）。
所以正常情况下找得到；「找不到」只在外部手工删过 sides 时才发生。

## 旧档迁移：`_deserialize_actor`

`_deserialize_actor`（`serialize.py:92`）对新档是几乎透明的（只补空容器），
但它包含**唯一一处存档迁移代码**：

```python
_bns = actor.get("bonus")
if not isinstance(_bns, dict) or "panel" not in _bns:
    actor["bonus"] = {
        "panel": dict(actor.get("stat_bonus") or actor.get("title_bonus") or {}),
        "cap":   dict(actor.get("cap_bonus") or {}),
        "cost":  {},
    }
    actor.pop("stat_bonus", None)
    actor.pop("cap_bonus", None)
    actor.pop("title_bonus", None)
```
（`serialize.py:104-113`）

历史：`bonus` 容器统一之前，面板增幅散在 `stat_bonus` / `cap_bonus` / `title_bonus`
三个旧键上。这段代码把旧档**一次性**迁进 `bonus` 分域并**清掉旧键**。
设计原则写在 docstring：**「存档数据迁移，非引擎读源回落 —— 引擎读源一律 `bonus` 分域
get 兜底；新档 actor 已带 bonus 容器则原样」**（`serialize.py:95-97`）。

### 给你的迁移约定

1. **迁移只写在 `_deserialize_actor` 里**，一处，加 `if 旧特征:` 分支
2. **迁完就 pop 旧键**，不留兼容壳（本仓库「不留兼容壳」的纪律，
   见 [../contributing/conventions.md](../contributing/conventions.md)）
3. **绝不改引擎的读源路径做兼容** —— 那会让「零默认值」失效并永久拖欠技术债
4. 补一个「旧档 JSON → `from_state` → 断言新形态」的测试

引擎包 `saintess_engine/` 之外，游戏仓侧也有一个例子可以照抄：`tests/test_legacy_schema_migration.py`。
它测的是 DB schema 迁移（不是 saintess_engine 存档），但迁移测试的写法一样。

## 循环引用：为什么击杀记录存 uid

`serialize.py:7`：「actor 全字段可 JSON 化；**无循环引用（召唤物 owner 存 uid）**」。
同一个原则适用于你的自定义字段：**别把 actor 对象塞进另一个 actor 的字段**，
存 `uid`。否则 `json.dumps` 直接 `Circular reference detected`。

## 落库的最简形态

引擎不含任何持久化代码。内容侧的用法是「把 `to_state()` 的 dict JSON 化，存进
`battle_state.state` 字段」：

```python
from saintess_engine.serialize import state_to_json, json_to_state

raw = state_to_json(battle.to_state())      # serialize.py:122
...
battle = Battle.from_state(json_to_state(raw))   # serialize.py:126
```

## 续战正确性 checklist

存/续一次后，逐条核对：

1. `now` 一致吗？（`b3._now == b1._now`）
2. 每个 actor 的 `ct` 一致吗？（不一致 = `seed_ct` 没关掉）
3. 起手 buff 会不会翻倍？（翻倍 = `battle_start` 被重放，检查 `_started`）
4. `effects` 里的 `expire` 是绝对时刻，与 `now` 一起恢复 —— 到点会正常消失吗？
5. `dot_next` / `dot_jumps` 恢复了吗？（丢了会让周期结算首跳延迟重新开始）
6. 你的 `target_picker` / `script_hook` / `on_event` 重新挂了吗？
7. `bonus` 三个子域都在吗？（旧档必须过 `_deserialize_actor` 迁移）
8. `killed` 列表长度对吗？

## 相关

- `Battle` 构造参数逐个语义 → [../reference/api.md](../reference/api.md)
- 时间轴与 `ct` → [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)
- 写迁移测试 → [testing.md](testing.md)
