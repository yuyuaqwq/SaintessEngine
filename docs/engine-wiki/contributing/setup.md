# 贡献指南：开发环境与跑测试

本页面向**改 `saintess_engine` 引擎的人**（不是用引擎的人）。用引擎请从
[../getting-started/installation.md](../getting-started/installation.md) 开始。

**归属先读**：本页默认你站在**框架仓 `framework-engine/`** 里 —— 读 `saintess_engine/` 的源码、
跑框架仓自己的测试。文中凡标「**游戏仓 / 奥兰迪亚侧**」的段落（AstrBot 的 uv python、
`tests/conftest.py`、`scripts/run_all_tests.py`、245 个测试文件、`tests/shim_astrbot` 等），
讲的都是**参考实现那一侧**的环境与工具，不是改引擎的必需条件：改引擎只需纯标准库 python。

## 环境

| 项 | 值 | 出处 |
|---|---|---|
| 解释器（**框架仓全量测试**） | 任意 **Python 3.11/3.12**（引擎只用标准库） | `saintess_engine/__pycache__/` 里并存 `cpython-311` / `cpython-312` |
| 解释器（**游戏仓 / 奥兰迪亚侧全量回归**） | **必须** AstrBot 的 uv python（带 `pypinyin`）：<br/>`C:/Users/yuyu/AppData/Roaming/uv/tools/astrbot/Scripts/python.exe` | 游戏仓 `scripts/run_all_tests.py:52` |
| 第三方依赖（引擎） | **零** | 见 [../getting-started/installation.md](../getting-started/installation.md) |
| 静态检查配置 | **无**（无 flake8/ruff/black/mypy/pyproject/setup.py） | `ls` 核实 |

工作目录：**框架仓根**（`framework-engine/`）。另一套工作目录假设
（`<plugin>/` = `data/plugins/dragonfall/`）是**游戏仓 / 奥兰迪亚侧**的，改引擎用不上。

## 三种跑法

### ① 单个测试文件（最快，开发期用这个）

```bash
cd framework-engine                          # 框架仓根
python tests/test_engine_purity.py           # 任选：tests/ 下每个 test_*.py 都能单跑
```

框架仓 `tests/` 目前 **52** 个 `test_*.py`（+ `run_all.py` 自己 + 夹具 `_domain_fixtures.py`）；
`python tests/run_all.py --list` 实测列出 **53** 个待跑文件 = 这 52 个 + 示例冒烟
`examples/minimal-game/tests/test_smoke.py`。每个都用
`sys.path.insert(0, FW_ROOT)` 自定位，末尾 `sys.exit(1 if 失败 else 0)`，**在哪个目录跑都行**。

> **游戏仓 / 奥兰迪亚侧**对照：那边 200+ 个测试文件同样是"可独立运行的脚本"形态
> （末尾 `sys.exit(1 if FAIL else 0)`），但得先 `cd data/plugins/dragonfall/`，例如
> `python tests/test_battle_n4_schedule.py`，典型输出：
>
> ```
> === N4 saintess_engine CTB 调度测试 ===
>   ✅ dot_next 登记 1.0
> ...
> === 结果 PASS=42 FAIL=0 ===
> ```

### ② 引擎纯度门禁（改引擎后**必跑**）

```bash
cd framework-engine
python tests/test_engine_purity.py
```

它做 AST 静态分析（不 import 运行），断言（框架仓**加强版**）：
① 引擎 `.py` 的**每条绝对 import 都必须是标准库**；② 零动态导入穿透
（`importlib.import_module` / `__import__`）；③ 公开 API 面完整（re-export 全量符号）；
④ 存档兼容（`Battle.from_state` / `to_state` 在 API 面内）；
⑤ `actions.py` 零 kind 中文字面量常量；另断言 5 个私有符号已升公开、旧下划线名是同一对象别名。
exit=0 全绿。**这条红了就等于破坏了引擎的可分发性。**

> 历史：拆仓前它在**游戏仓**叫 `tests/test_engine_no_content.py`（只查 6 类内容）；
> 随拆仓搬进框架仓并加强为「每条绝对 import 都断言是标准库」。

### ③ 全量回归

**框架仓（引擎全量 + 示例游戏冒烟）—— 改引擎跑这个**：

```bash
cd framework-engine
python tests/run_all.py [--list]        # --list 只列出将要运行的文件
```

（`tests/run_all.py`：跑 `tests/` 下全部 `test_*.py`，再跑
`examples/minimal-game/tests/test_smoke.py`。**纯标准库 python 即可**，无第三方依赖。）

**游戏仓 / 奥兰迪亚侧（参考实现全量回归）—— 那是游戏仓的事**：

```bash
cd data/plugins/dragonfall
python scripts/run_all_tests.py [--file tests/test_xxx.py] [--fail-fast]
                                [--jobs=N] [--serial]
                                [--skip=test_xxx.py[,test_yyy.py]] [--real-astrbot]
```

（游戏仓 `scripts/run_all_tests.py:5-6`）

机制（游戏仓 `scripts/run_all_tests.py:9-25`）：

- 每个测试文件 = **独立子进程 + 独立私有 DB**（`tests/.run_all_workers/` 下）
- 每轮先 `init_db` 建一次空白 schema 模板，各文件复制一份 → 表结构齐全且零残留
- 默认并行（按核数自适应 4~16），`--serial` 恢复串行（约 9 分钟）
- 默认注入 `tests/shim_astrbot`（行为等价的 astrbot 替身，全量 ~105s → ~27s）
- **串行槽**：硬编码共享库或自己私有库的文件先跑（`SERIAL_SLOT`，`:65-68`）

两条纪律（游戏仓 `scripts/run_all_tests.py:22-24`）：

1. **必须用 uv python**（否则缺 `pypinyin` 会挂）
2. **跑全量期间不要改源文件**（避免中间态误判）

### 测试规模参考（本次核实）

**框架仓**（`tests/`，改引擎时你打交道的全部）：

- **53** 个待跑文件（`python tests/run_all.py --list` 实测）= `tests/` 下 52 个 `test_*.py`
  + 示例游戏冒烟 `examples/minimal-game/tests/test_smoke.py`（`run_all.py` 会带上）
- 其中代表性的几条：`test_engine_purity.py`（纯度门禁）、`test_engine_neutral_fallback.py`
  （中性兜底：未挂配置不崩）、`test_editor_api.py`（编辑器 API）、`test_wiki_refs.py`
  （本 wiki 的 `file.py:行号` 引用门禁）、`test_editor_wiki.py` / `test_editor_wiki_pkg.py`
  （wiki 渲染与死链，后者连带锁 README 头部的引擎目录数字）

**游戏仓 / 奥兰迪亚侧**（参考实现的回归集，规模大得多）：

- `tests/test_*.py` 共 **245** 个文件
- 其中 saintess_engine 相关 **28** 个（`tests/test_battle_*.py`）
- 引擎专项：`test_engine_no_content.py`（门禁，**旧名** —— 已随拆仓迁入框架仓并改名为
  `tests/test_engine_purity.py`，游戏仓 `tests/` 里不再有这个文件）· `test_battle_coverage.py`（覆盖）
  · `test_battle_n3_effects.py`（效果系统）· `test_battle_n4_schedule.py`（调度）
  · `test_battle_n5_serialize.py`（存档）· `test_battle_n8_events.py`（事件总线）
  · `test_battle_n10_*`（落地各段：吸血/防御/反伤/元素/承伤属性/初始 ct/食物）

## 测试脚手架（`tests/conftest.py`）—— 游戏仓 / 奥兰迪亚侧

⚠️ 本节属于**参考实现那一侧**的测试基建。框架仓的 `tests/` **没有** `conftest.py`，
也不需要一个：每个测试文件自己 `sys.path.insert(0, FW_ROOT)` 后裸 `import saintess_engine`。
下面这些（`GWEN_GAME_DB` / `GWEN_TEST_MODE` / astrbot shim）只在写**奥兰迪亚**的测试时才用得上。

**新测试请从 conftest 复用，不要手抄模板**（游戏仓 `conftest.py:2-6` 原文）：

```python
from conftest import FakeEvent, run, clean_db, make_player, TEST_DB, PLUGIN_DIR
```

`conftest.py` 自动做三件事（`:24-38`）：

1. `GWEN_GAME_DB` → 独立测试库（**绝不触碰生产 `game_data.db`**）；
   用 `setdefault`，所以你可以预置自己的私有库名（`test_<名>.db`）
2. `GWEN_TEST_MODE=1`（测试模式下未知条件键直接 raise，防假绿）
3. 把 `qqbot/` 与插件根加进 `sys.path`

另：默认 shim astrbot（`GWEN_NO_SHIMMED_ASTRBOT=1` 退回真实 astrbot，对照验证用）。

⚠️ `tests/` 里还有大量 `_probe_*.py` / `_audit_*.py` / `_*.txt` 历史产物，
它们**不是测试**。`scripts/run_all_tests.py` 里有 `RETIRED_PROBES` 名单把退役探针排除。

## 引擎单测的最小写法（零内容）

引擎可以**零内容**跑 —— 在框架仓里，`saintess_engine/` 是自洽的，不需要任何游戏包：

```python
import os, sys, random
FW_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 框架仓根
sys.path.insert(0, FW_ROOT)

from ext_combat import Battle, make_actor
from saintess_engine import config
from saintess_engine import formulas as F

# 最小装配（否则伤害恒 0 / 战斗起不来 —— 见 getting-started/first-battle.md）
config.mount(formulas=F, kinds={...}, basic_fallback={...},
             skill_flat_fn=lambda: {...}, formula_skeleton_fn=lambda: {...},
             time_model_fn=lambda spd, base: base * math.sqrt(50.0 / max(float(spd or 0), 1.0)),
             action_base_fn=lambda action: {"defend": 0.6, "skill": 1.6}.get(action, 1.0))

random.seed(1234)      # 伤害有 ±15% 波动，精确断言必须定种子
```

> ⚠️ 对照（**游戏仓 / 奥兰迪亚侧**）：那边 `import game` 会触发 `game/__init__.py` 的
> 惰性装配登记（`game/bootstrap.py:196` 的 `install()`），首次读 hook 就把 `game.content`
> 拉进来 —— 那是游戏仓的接线。框架仓里没有 `game/` 包，裸 `import saintess_engine` 就是
> **真正的零内容**（框架仓 `tests/test_engine_neutral_fallback.py` 正是这条契约的回归）。

## 改引擎的流程

```
1. 读完 architecture/（尤其 design-decisions.md 的 10 条 ADR）
2. 改代码
3. python tests/test_engine_purity.py            ← 门禁必须先绿（框架仓）
4. python tests/test_engine_neutral_fallback.py  ← 相关专项（未装配不崩的契约）
5. python tests/run_all.py                       ← 引擎全量 + 示例游戏冒烟（纯标准库 python）
6. 若动了公开 API 面 → 同步 5 个私有别名的门禁断言（tests/test_engine_purity.py）
7. 若动了序列化 → 加一条旧档迁移断言
8. 若改了本 wiki → python tests/test_wiki_refs.py   ← `file.py:行号` 引用门禁
```

（可选）若改动会影响参考实现，再进**游戏仓**跑它自己的全量回归：

```bash
cd data/plugins/dragonfall && python scripts/run_all_tests.py   # 需 uv python
```

## 相关

- 代码约定 → [conventions.md](conventions.md)
- 版本与分发 → [release.md](release.md)
- 给自己的内容写断言 → [../guides/testing.md](../guides/testing.md)
