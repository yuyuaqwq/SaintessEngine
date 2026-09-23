# 第 3 批并行搬迁 · 作业书（每路一份，读自己那一节）

## 背景

`C:\Users\yuyu\framework-engine` 是一个**通用文字游戏引擎**仓，正在做「包栈重构」：
把混在引擎里的**游戏原语**抽成**可插拔扩展包**，引擎只留通用件。
已完成两批（看样板就懂）：

```text
extends/ext_quest/      ← 从 extends/ext_quest/quest/ 搬来的（最简单，先看它）
  game.json             {"id":"ext_quest","kind":"extension","name":"…","desc":"…",
                         "engine":">=0.1","entry":"apply.py","created":"2026-09-23"}
  apply.py              def install_engine() -> None: …   （入口契约，可以什么都不做，但要说明为什么）
  README.md             这个包是什么 / 什么时候装它
  quest/                原 extends/ext_quest/quest/ 的内容（一个字没改）
  tests/                跟过来的门禁 + 一条「作为扩展包被数据包用起来」的端到端检查

extends/ext_combat/     ← 从 saintess_engine/{battle,gauge,formation,panel}/ 搬来的
  game.json 里多一行     "provides": {"battle": "ext_combat.battle.battle:Battle"}
  ★ 这是「能力提供者」声明：引擎只认「键 + 引用」，不认识"战斗"这个词。
    你的包如果**提供某种能力**（而不是只提供形状/工具）才需要它；不确定就别写。
```

## 环境须知（重要）

- 这台机器的 `terminal` 工具走 git-bash 且 `.bashrc` 有问题 —— **不要用 bash 命令**。
  一律用 `execute_code` 里的 Python（`os` / `shutil` / `io` / `ast`）做文件操作。
- **不要跑任何 git 命令**（6 路并发会撞 `index.lock`）。搬迁用 `shutil.move` 即可，
  主线的 `git add -A` 会自动把移动认成 rename。
- 编辑文本文件时一律 `io.open(path, encoding="utf-8", newline="")` 读写 —— 仓内是 **LF**，
  不带 `newline=""` 会把整个文件污染成 CRLF（**已经踩过一次，别再踩**）。

## 你这一路要干什么

把列在下面「你的模块」里的模块，从 `saintess_engine/` 搬到新扩展包 `extends/<包名>/<模块>/`。

**六路分工（只做自己那一行）**

| 路 | 包名 | 模块（每个都搬成 `extends/<包名>/<模块>/`） | 行数 |
|---|---|---|---|
| A | `ext_world` | `space`, `run` | 1,152 |
| B | `ext_life` | `collect`, `periodic`, `timers`, `unlock` | 1,161 |
| C | `ext_economy` | `trade`, `shelf`, `produce` | 906 |
| D | `ext_social` | `membership`, `presence` | 862 |
| E | `ext_loot` | `loot` | 938 |
| F | `ext_dialogue` | `dialogue` | 414 |

## 步骤

### ① 搬

```python
import os, shutil
ENG = r"C:/Users/yuyu/framework-engine"
os.makedirs(os.path.join(ENG, "extends/<包名>"), exist_ok=True)
for mod in ["<模块>", ...]:
    src = os.path.join(ENG, "saintess_engine", mod)
    dst = os.path.join(ENG, "extends/<包名>", mod)
    shutil.move(src, dst)
    # 删掉跟过去的 __pycache__
    for dp, dn, fn in os.walk(dst):
        if os.path.basename(dp) == "__pycache__":
            shutil.rmtree(dp, ignore_errors=True)
```

### ② 改「指向引擎」的导入

搬走之后，包内文件里原来写 `from ..config import …`（`..` = 引擎顶层）会失效 ——
因为新的 `..` 是 `extends/<包名>`。**这类导入要改成绝对导入**：

```text
from ..foo import x          →  from saintess_engine.foo import x
from .. import foo as f      →  from saintess_engine import foo as f
from ...bar import y         →  from saintess_engine.bar import y
```

**包内相对的（`from .` / `from ..<本包内的模块>`）一律不动。**

引擎里**仍然存在**的通用件（可安全写成 `saintess_engine.X`）：
`config` `domains` `package` `store` `command` `events` `clock` `container` `text`
`session` `log` `tlog` `records` `conditions` `bonus` `grant` `gates` `wire` `expr`
`formula` `host` `version` `_validators` `_sinkbase`

★ **本批正被搬走的 13 个模块**：`space run collect periodic timers unlock trade shelf
produce membership presence loot dialogue` —— 如果你的模块引用了**不属于你这一路**的那些，
**停下来报告**（别自己决定），因为那意味着两路之间真的有依赖，需要主线在 `game.json` 里
声明 `depends`。扫描发现本批 13 个模块之间互相引用是 **0 处**，所以正常情况下你不会遇到。

改用例：`from ..timers import X` 这种，若 `timers` 是你自己那一路的 → 包内相对路径照旧
（`from ..timers import X` 依然成立）；若不是 → 报告。

### ③ 建包清单

照 `extends/ext_quest/` 的三个文件写（内容要贴合你这一路的语义，别抄错名字）：

- `game.json` —— `id` / `kind: "extension"` / `name`（中文，说明这是什么能力）/
  `desc`（一两句）/ `engine: ">=0.1"` / `entry: "apply.py"` / `created: "2026-09-23"`
- `apply.py` —— `def install_engine() -> None:`，写清楚这包**为什么不需要注册任何东西**
  （纯形状/工具类）或**注册了什么**；照 `extends/ext_quest/apply.py` 的语气写注释
- `README.md` —— 一段话说清：这个包是什么、什么时候该装它、里面有哪些模块

### ④ 自检并报告

- 对你改过的每个 `.py` 跑 `ast.parse` 确认语法没问题
- 读出 `saintess_engine/__init__.py` 里**需要删掉的行与符号**（精确列出符号名，别删）
  —— 主线会统一改那个文件

## 不要动

`saintess_engine/__init__.py` · `tests/` · `editor/` · `examples/` · `games/` · `docs/` ·
其它 `extends/` 包 · 别跑 git · 别跑测试（主线统一跑全量）

## 报告格式（人话，简洁）

```text
搬了什么：<模块>（行数），新包路径 extends/<包名>/
改了哪些跨包导入：N 处，例：from ..config import X → from saintess_engine.config import X
遇到的跨路依赖：有/无（有就说清哪个模块引用了哪一路的哪个模块）
__init__.py 需要删的符号：<列出>
其它问题：…
```
