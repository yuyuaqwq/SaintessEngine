# 插件骨架 + 最小示例游戏 ——《铆炉回声》

> 一个**完整的第三方游戏插件骨架**：不读引擎内部、不碰《奥兰迪亚》任何文件，
> 只照 `docs/engine-wiki/` 的公开契约写，就能跑通一场战斗。
> 这是「框架可分发」的验收物：**换一套 content = 新游戏，引擎零改动**。

内容与《奥兰迪亚》完全无关（自创职业 / 资源 / 机制 / 词表），
静态 + 运行期双重门禁保证**零** `game.data` / `game.services` / `game.content_rules` /
`game.content` 依赖 —— 见 `tests/test_smoke.py::test_purity`。

---

## 1. 怎么跑

```bash
PY="C:/Users/yuyu/AppData/Roaming/uv/tools/astrbot/Scripts/python.exe"

# ① 跑一场战斗并打印日志（20 行内的 main.py）
"$PY" examples/minimal-game/main.py

# ② 冒烟测试 + 纯度自检（20 项，exit 0 全绿）
"$PY" examples/minimal-game/tests/test_smoke.py

# ③ 让**宿主骨架**对本包开一场战斗（宿主侧口径；那半边 = content/bridge.py）
#    场景 JSON（挑职业 / 敌组）属内容策略、由调用方给，例：
#      {"btype":"monster","player":{"name":"阿铆","class_name":"cls_kiln","level":6},
#       "enemies":[{"uid":"e-1","key":"rustmite"},{"uid":"e-2","key":"ironbuoy"}]}
"$PY" examples/host-skeleton/adapter_cli.py --package examples/minimal-game \
    --db /tmp/mg.db --scenario /tmp/mg-scenario.json --seed 20260913   # 输入 /battle
```

零第三方依赖（只用标准库 + 引擎），Python 3.11 / 3.12 实测。

## 2. 目录与各部分作用

```
examples/minimal-game/
├─ README.md              本文：怎么跑 / 各部分作用 / 为什么这样设计 / 踩到的坑
├─ main.py                20 行跑完一场战斗：造 actor → Battle(sides=…) → auto_run → 打印
├─ game.json              包清单（id / name / engine 要求 / domains / entry）—— 编辑器当包打开的凭据
├─ editor/
│  └─ domains.json        本游戏的**域声明**（编辑器扩展面的真源，见第 8 节）
├─ schemas/               本包自带的 JSON Schema（每个域一份，覆盖声明的全部域）
│  ├─ skill.schema.json  classes.schema.json  monsters.schema.json
│  ├─ effect_rules.schema.json  passive_proc.schema.json
│  └─ mech_verbs.schema.json          ← 「本包自己新增的域」的那份
├─ content/               你的游戏内容（整包 = 一个"插件"）
│  ├─ __init__.py         公开入口：apply_game_content / install_engine（import 即接管引擎）
│  ├─ apply.py            唯一装配入口，幂等：
│  │                        install_engine()      全局挂 hook + 声明表
│  │                        apply_game_content()  单个 actor 挂 资源渠道/机制/被动
│  ├─ bridge.py           ★ **战斗构造半边**（宿主 run_battle 要的那一半，可选半边）：
│  │                        build_sides(player, enemies) → {player:[actor], enemy:[actor]}
│  │                        存档 dict / 场景数据 → 引擎 actor；缺它宿主 fail-closed（拒绝静默空跑）
│  ├─ data/
│  │  ├─ rules.py         声明表：EFFECT_RULES / EFFECT_ACTIONS / MECH_CASH / PASSIVE_PROC
│  │  │                   + KIND_NAMES（kind 词表）+ FORMULA_SKELETON / SKILL_FLAT（公式参数）
│  │  ├─ skills.py        技能：普攻 / 玩家技能 / 怪物技能 + 引擎 skill_lookup 接口
│  │  ├─ classes.py       职业：面板参数 + panel_fn 实现 + build_player 工厂
│  │  ├─ monsters.py      怪物模板 + build_monster 工厂
│  │  └─ mech_verbs.json  ★ 编辑器侧的机制动词目录（本包自己新增的域，见第 8 节）
│  └─ mech/
│     └─ actions.py       本游戏的机制动词（@register_action）：res_gain / heat_vent / backdraft
└─ tests/
   └─ test_smoke.py       冒烟测试（战斗/渠道/机制/技能/控制/被动/装配/纯度）
```

> `content/data/`、`content/mech/` 没有 `__init__.py` —— 依赖 Python 3.3+ 的隐式
> 命名空间包（`content` 是常规包，子目录自动可导入）。想更保守就各加一个空 `__init__.py`。

## 3. 它在演示什么：加机制的完整三段式

```
① 写动词（能力）            ② 写名词声明（翻译）              ③ 装配到 actor（触发条件）
@register_action(...)      EFFECT_ACTIONS / EFFECT_RULES      actor["triggers"]
mech/actions.py            data/rules.py                      apply.py
```

- **① 动词**：`mech/actions.py` 的 `heat_vent`（普攻命中后按「炉温」层数追加贯穿伤害并耗层）、
  `res_gain`（资源渠道攒层）、`backdraft`（受击反击）。全部只 import `saintess_engine` 的公开 API。
- **② 声明**：`rules.py` 四张表。其中 `EFFECT_ACTIONS`（名词→动词）与 `EFFECT_RULES`
  （cap / stat_scale / period / consume）**引擎直接消费**；`MECH_CASH` / `PASSIVE_PROC`
  **引擎不读**，由本包的装配器翻成 triggers（这就是"第三方自己定装配约定"）。
- **③ 装配**：`apply.py` 把 channels / 机制 / 被动声明翻成 `actor["triggers"]`，幂等。

战斗里能看到的完整机制链（main.py 实测日志）：

```
💥 铆壳浮标 受到 29 点伤害！      ← 普攻（技能管道）
✦ kiln 3/6（+1）                 ← 资源渠道：channels.attack_hit → res_gain → 引擎 apply 动词
💥 铆壳浮标 受到 9 点伤害！        ← 自定义机制：heat_vent 追伤（landing.deal_damage 收口）
♨️ 炉温喷涌：3 层炉温追加 9 点贯穿伤害！
✦ 消耗 2 点 kiln（剩余 1）        ← consume 动词（引擎内置）
💫 铆炉匠·阿铆 被【clamp】控制，无法行动！  ← 名词 clamp → EFFECT_ACTIONS → apply mode=skip
🔥 回火：铆炉匠·阿铆 反击 铆壳浮标 10 点伤害！  ← PASSIVE_PROC → on_taken → backdraft
🔥 铆炉匠·阿铆 受 rust 2 层影响，损失 4 生命   ← EFFECT_RULES.rust.period（DOT）
```

## 4. 为什么这样设计

1. **方向只有一个：内容 → 引擎。** 本包 `import saintess_engine`（引擎公开 API），
   引擎不 import 本包。挂配置只走 `config.mount()` / `config.load_game_rules()`，
   拿事件数值走 `actor["triggers"]` + `battle._fire_ctx`，改状态走引擎动词。
2. **引擎需要 12 项装配**（不是文档里「最小 5 项」，那是"能打出普攻伤害"的下界）：
   `formulas` / `kinds` / `panel_fn` / `skill_lookup` / `monster_skill_fn` / `basic_skill_fn` /
   `basic_fallback` / `formula_skeleton_fn` / `skill_flat_fn` / `skill_up_fn` /
   `skill_level_of_fn` + 两张规则表。写成 `install_engine()` 一处、幂等。
3. **必须自己接管注入面。** 本仓库 `import saintess_engine` 会触发 `game/__init__.py` 登记
   《奥兰迪亚》的惰性装配器；若第三方不覆盖，第一次读 hook 就会把整份奥兰迪亚内容拉起来。
   所以 `install_engine()` 首要动作是 `config.register_hook_provider(自己的装配器)`。
   骨架在 `content/__init__.py` 里 **import 即 install**，让"接管"先于一切引擎使用。
4. **`apply_game_content(actor)` 是唯一的内容入口**（幂等）：引擎侧只认 `actor` 上的
   数据，不认本包的表；本示例用它挂 资源渠道 → 机制 → 被动（顺序即契约：机制要读到
   本次命中刚 +1 的层数，所以排在渠道之后）。
5. **零第三方依赖**：只用标准库，方便拷进任何项目。

## 5. 本游戏内容一览（★ 与奥兰迪亚刻意不同）

| 维度 | 《奥兰迪亚》 | 《铆炉回声》（本示例） |
|---|---|---|
| 题材 | 剑与魔法的奥兰迪亚大陆 | 深海铆井平台的蒸汽机械 |
| 职业 | 剑士 / 法师 / 游侠 / 牧师 / 拳师… | **铆炉匠** `cls_kiln` / **哨鸣师** `cls_whistle` |
| 职业资源 | 战意 / 信念 / 磐核 / 能量 / 信仰 | **炉温** `kiln`（cap 6，每层 +2% 攻击）/ **回声** `echo`（cap 4） |
| 资源攒取 | 渠道表 + 内容侧装配器 | 同骨架自写的 `channels` → `res_gain`（普攻命中 +1；被拘束受击 +1） |
| 核心机制 | 磐核兑现 / 破绽条 / 旋律… | **炉温喷涌**：普攻命中后 ≥3 层炉温 → 追加 `层数×3` 贯穿伤害，耗 2 层 |
| kind 词表 | 物理 / 魔法 / 真伤 / 治疗 / 增益 | **冲击 / 灼热 / 贯穿 / 充能 / 调律**（引擎零 kind 字面量） |
| 名词→动词 | 70+ 内容动词 | `clamp`（铁钳拘束，mode=skip）+ 3 个自写动词 |
| DOT | 燃烧 / 流血 / 中毒… | **锈蚀** `rust`（每刻 1.5% 最大生命 × 层数，跳 3 次） |
| 被动 | 大量职业被动 | **回火**（受击后按攻击力 35% 反击来源） |
| 怪物 | 野狼 / 石像鬼… | **锈苔爬虫**（锈钉喷射）/ **铆壳浮标**（铁钳拘束） |
| 普攻兜底 | `{"name": "攻击", …}` | `{"name": "应急撬棍", …}` |

## 6. ★ 写骨架时踩到的坑 / 文档缺口（逐条，按痛的顺序）

1. **控制类名词必须显式写 `key` 与 `on: "target"`——文档示例照抄会静默失效。**
   `wiki/reference/declaration-tables.md` 与 `PLUGIN_SKELETON_SPEC.md` 给的示例是
   `{"stun": [{"action": "apply", "mode": "skip"}]}`。照抄后：
   - `act_apply` 的 key 取自 `params.key | tag | mech`，裸触发器 `{"type": "clamp"}` 三者都没有
     → **直接 return，静默 no-op**（无日志、无异常）；
   - `apply` 的 `on` 缺省是 `"caster"` → 即使 key 有了，也会**把「拘束」挂到施法者自己身上**
     （我第一版实测：怪给自己上了 1 刻拘束）。
   奥兰迪亚的真实表每一条都写全 `{"action": "apply", "key": X, "on": "target", "turns": N}`
   —— 这三件套该写进示例与 `effect-actions.md` 的必填字段说明里。
2. **「资源渠道（channels）：内容侧怎么写最小装配器」没有可抄的样例。**
   `guides/add-a-resource.md` 把消费者直接指向奥兰迪亚的
   `game/services/class_mech_proc.py`（第三方拿不到、也不该依赖）。骨架里最费劲的一段
   （声明 channels → 翻成 triggers → 自写动词 → 引擎 apply 动词）全靠自己设计；建议 wiki
   补一个「第三方版渠道装配器」的最小实现（30 行），或干脆把 `res_gain` 这类通用动词上提为引擎件。
3. **从「最小 5 项 hook」到「带职业/技能/怪物的完整装配集」之间没有文档。**
   `getting-started/first-battle.md` 的 5 项最小集很好用，但要用技能表/职业面板/怪物技能，
   另外 7 项（`skill_lookup` / `monster_skill_fn` / `basic_skill_fn` / `panel_fn` /
   `skill_up_fn` / `skill_level_of_fn` / 两张规则表）的**契约只能读源码补**：比如
   `formula_skeleton_fn` 返回的 dict 里`skill_growth.power_per_lv_divisor` 等键是硬要求
   （缺了在伤害链深处 `KeyError`），文档只说"给参数表"。建议在 `reference/api.md` 每个
   hook 后附**一个可直接粘贴的最小返回值样例**。
4. **AI 谓词集没有「资源 ≥ N」，且 `cd_ok` 会活锁。** 实测第一次跑出的是一场
   `defeat` + 刷屏「核心资源不足」：我按直觉把玩家 AI 写成
   `{"when": {"cd_ok": "sk_rivet"}, "then": {"type": "skill", ...}}`，结果是
   **技能因 `res_cost` 不足被 `_skill_usable` 拦下 → 提前 return，冷却根本没被设置 →
   `cd_ok` 永远为真 → 每回合都尝试同一个永远放不出的技能 → 玩家 0 输出直到被打死**。
   这条组合陷阱（拦截点在设冷却之前 + AI 只看 cd_ok）值得写进 `reference/api.md` 或
   `guides/write-a-mechanic.md`；引擎侧建议补一个 `res_ge` 谓词，或让被拦的技能也占冷却。
5. **引擎不强制冷却。** `do_skill` 只**写** `actor["cooldown"]`，不检查是否在冷却中；
   `human_act` / AI 都能在 CD 内照放。而 `reference/api.md` 说 `_skill_usable` 是
   「学习/蓝/核心资源/**冷却**」检查——函数体里其实只有 res_cost 检查。文档与实现不一致，
   第三方会以为 CD 有引擎兜底。建议二选一：改文档，或在 `do_skill` 里补 CD 拦截。
6. **技能名解析规则没写。** `human_act("skill", name)` / AI 的 `then.skill` 走
   `actor["_skill_index"]`（引擎塞了 **skill id 与显示名双键**），但"填哪个"文档没说；
   填错时 `do_skill` 静默 `return []`（`_index_one_actor` 整体 try/except pass），
   表现是"怪站着不动/技能空放"，极难排查。我踩过：给只带 `ms_rustspit` 的怪塞
   `ms_clamp` → 全程静默。建议 wiki 明确「两者皆可，但 key 必须出现在 `actor.skills` 且能被
   `skill_lookup` 解析」，并在 `_index_one_actor` 失败时至少写一条 debug 日志。
7. **`_fire_ctx` 单槽覆盖：你自己的动作会把自己刚读的槽冲掉。**
   `backdraft` 在读 `source` 后调用 `deal_damage`，而 `deal_damage` 内部又会 `fire`
   （taken_calc / on_taken）→ 覆盖单槽。事件总线的文档说了"必须同步读完"，但没提示
   **"接着调引擎动词会再 fire 一次"** 这个自反场景。建议在 `concepts/event-bus.md` 补一句
   「凡是在扩展动作里再落地一次伤害/治疗，先把 `_fire_ctx` 需要的字段读进局部变量」。
8. **玩家面板有两个真相源（裸字段 vs panel_fn），文档没点明分工。**
   `stats.actor_stats()` 对有 `class_name` 的 actor **重算** `panel_fn`，但
   `actor_alive()` / DOT 的 `max_hp` / AI 的血量比 读的是**裸字段** `actor["hp"]/["max_hp"]`。
   也就是说内容侧必须自己保证两套数字一致（我在 `build_player` 里用同一个 panel 同时填
   字段与 actor），引擎不会用 panel 结果回写，也没有类似 `make_player` 的官方工厂。
   建议 wiki 在 `concepts/actor-model.md` 明确这条分工，或提供官方 actor 工厂。
9. **幂等装配没有框架支持。** `apply_game_content` 的幂等得自己写（我用了
   `_append_once`）。`guides/write-a-mechanic.md` 只给了"用 setdefault + 去重"的原则。
   骨架里给了可抄的 `_append_once`。
10. **hook 名拼错静默忽略，且没有"装配完整性"自检。** 文档反复提醒"写错不报错、开发期开
    `strict=True`"，但 `strict` 只在**链深处首次访问**时抛。骨架的做法是
    `test_engine_mounts` 逐名 `config.get_hook(name) is not None` 点名核对（11 项）——
    建议把这个自检做成引擎侧的一个 `config.assert_configured(names)` 辅助函数，人人都要写一遍。
11. **`skill_up_fn` / `skill_level_of_fn` 的"不做成长"该怎么填没写。** 我填
    `lambda info: {}` 与 `lambda player, name: 1` 是靠读 `formulas.py` 才敢确定安全
    （`skill_power_mult` 读 `_skill_up(info).get("p", 0)` → 0 即无成长）。
    `reference/api.md` 的"不装配的行为"列有"返回 1（未升级兜底）"，但没给"显式装配成无成长"的写法。
12. **没有可运行的样例工程（只有文档片段）。** 全篇 wiki 的代码块都靠人拼；拼的过程中
    "这里到底要不要 `key` / `on` / `turns`"是最费时间的试错（见第 1 条）。
    本目录就是建议的那个样例：**把 `examples/minimal-game/` 作为分发物的一部分**，
    并在 wiki 首页 `getting-started/` 直接指向它。

## 7. 已知限制（刻意不做，避免骨架变重）

- 不做技能等级成长（`skill_up_fn` 恒 `{}`，全部技能 Lv.1）。
- 不做 AOE / 蓄力 / 挂敌身条 / 召唤 / 存档续战（引擎都支持，留给你按 wiki 扩展）。
- `MECH_CASH` 留空：本游戏的资源兑现直接用引擎原生 `res_cost` + 自写的 `heat_vent` 动词，
  刻意**不采用**这套约定（`PASSIVE_PROC` 则采用了，用来演示"内容侧约定"的两种态度）。
- 玩家自动战斗用普攻（`auto_run`）；主动技能与资源扣减由 `tests/test_smoke.py` 里
  `human_act("skill", "过载铆钉")` 显式驱动（原因见第 6 节坑 4）。
- 不做结算 / 掉落半边（`content/settlement.py` / `content/loot.py`）：宿主 `run_battle`
  照常跑完并把这半边记**桩**（`stubs`）——两者属策略，留给按 wiki 扩展。
- 包内冒烟（20 项）不覆盖 `content/bridge.py`（那条链要宿主在场）；宿主侧实证 =
  第 1 节第 ③ 条 `examples/host-skeleton/adapter_cli.py --package examples/minimal-game`。

## 8. ★ 编辑器扩展：本包自带域（**最小样板**）

「编辑器认识哪些域」的答案**在包里**（`editor/domains.json`），不在框架里 —— 所以
**加一个域 = 只改本包 3 个文件**，框架一行不改。本目录就是那个最小样板，照它抄就行：

| 文件 | 干什么 | 本目录里的例子 |
|---|---|---|
| `editor/domains.json` | 域声明（`kind` 决定落 `content/data/` 还是 `content/rules/`） | 6 个域；其中 `mech_verbs` 是**本包自己新增的域**（框架默认集里没有） |
| `schemas/<域>.schema.json` | 单条形状 → 校验 + 表单渲染；**不给 = 该域不校验** | 6 份，覆盖声明的**全部**域（`classes` 那份是「框架默认集里本来无 schema，本包补上」的示范） |
| `content/data|rules/<域>.json` | 数据本身（`{条目 key: 条目对象}`） | `content/data/mech_verbs.json`（3 个机制动词） |

三件小事，别踩：

1. **`{"$builtin": false}`** 写在 `editor/domains.json` 顶层 —— 「本包的域就这些，不要框架默认集兜底」。
   不写（缺省 `true`）时编辑器会把框架那 19 个默认域也列出来兜底（第三方包 / 坏包友好）。
   本示例写了它，所以编辑器里**只出现本包的 6 个域**。
2. `schema` 写的是**包内相对路径**；解析顺序 = `<pkg>/schemas/<值>` → `<pkg>/<值>` →
   框架 `schemas/<值>` → 不校验。想让哪个域严格，就在包内自带一份。
3. `mech_verbs.json` 是**编辑器侧**的表（列清单 / 校验用）；**运行时的真源仍是
   `content/mech/actions.py`**。想让运行时也读它，在 `content/apply.py` 里 `json.load` 一下即可
   （示例刻意不做：保持「运行时 = content/*.py 单源」，避免两处定义漂移）。

验收门禁：`python tests/test_editor_step3_pkg_first.py`（框架仓）—— 里面把框架那份内置默认集
**整个置空**后仍要求 orlandia 完整可编，并钉住本样板包的 6 域「能列 / 能存 / 自带 schema 全覆盖」。
规格全文：`docs/engine-wiki/reference/package-format.md` §十。
