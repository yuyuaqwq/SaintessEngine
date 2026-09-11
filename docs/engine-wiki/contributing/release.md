# 贡献指南：版本与分发

> ⚠️ **诚实标注**：引擎**当前还没有独立的版本号、没有 CHANGELOG、没有发布流程**
> —— 拆仓已把引擎变成**独立可分发仓 `framework-engine`**，但版本/发布仪式还没补上。
> 本页写的是「现状 + 分发前必须过完的清单」，不是既有流程的复述。
> 未取证项列在文末与 [_selfcheck.md](../_selfcheck.md)。

## 现状：引擎怎么被"版本化"

| 层面 | 现状 |
|---|---|
| 插件版本 | `metadata.yaml` 的 `version: 0.105.0`（**游戏仓 / 奥兰迪亚侧**的插件元数据，不是引擎的） |
| 引擎版本 | **无独立版本号**。拆仓前引擎的变更以插件版本 + 文档文件名里的编号体现（如 `REFACTOR_v181P4_*`） |
| 仓库 | **已拆仓**：引擎在独立仓 `framework-engine`（顶层 `saintess_engine/`），游戏内容在游戏仓 `dragonfall`（`game/data/`、`game/services/` 等）—— 两者不再同仓 |
| 分发形态 | 已落地为 **git submodule 源码分发**：游戏仓 `dragonfall` 以 `framework/` submodule（固定 commit）引用框架仓；第三方可直接 clone 框架仓或只拷 `saintess_engine/`。拆仓方案与历史见**游戏仓**文档 `dragonfall/docs/ENGINE_CONTENT_SPLIT_PLAN.md` §6/§7 |
| CHANGELOG | **无** |
| 兼容性承诺 | **无**（没有 semver 约定、没有弃用期策略） |

## 分发形态的三种候选

| 形态 | 做法 | 适合 |
|---|---|---|
| **拷目录** | 复制框架仓顶层的 `saintess_engine/` 进你的项目（包名保持 `saintess_engine`） | 只需一份、不跟上游 |
| **git submodule** | 挂框架独立仓 `framework-engine`（**已是游戏仓 `dragonfall` 的现用形态**） | 跟上游更新 / 提 PR |
| **PyPI 包** | 需要先加 `pyproject.toml` 与 `__version__` | 公共复用 |

前两种**已是现实**（框架仓本身就是"顶层 `saintess_engine/` 可分发包"的形态，拷贝已实测跑通：见
[../getting-started/installation.md](../getting-started/installation.md)）；
第三种需要先补下面「分发前清单」的第 1、2 项。

## 分发前必须过的清单

### A. 边界（架构）—— 拆仓后状态

- [x] **反向依赖已断**（原 15 条 `引擎→内容` import 边）—— 门禁
      `tests/test_engine_purity.py`（**框架仓**；加强版：每条绝对 import 都断言是标准库）可验（S1 起点 commit `d5e323e`）
- [x] **公开 API 面已固化**（26 符号 re-export + 5 个私有符号升公开保别名，S2）
- [x] **通用件已归位**（`formula_expr` / `formation` / `skill_kinds` / `battle_bars` → **模块化重排后**为顶层并列子包 `expr/` · `gauge/` · `formation/` · `kinds/`，S3）
- [x] **`game/engine.py` 已拆**（S5'，commit `5eae164`）—— 过渡 shim 已随拆仓删净
      （S9-2）；**游戏仓 / 奥兰迪亚侧**的装配入口是 `game/content_rules/apply.py`
- [x] **内容侧单一装配入口已收敛**（S7，commit `50eb8dc`：`apply_game_content`，**游戏仓侧**）
- [x] **引擎包改名**（S4 曾议 `game/battle2` → `game/engine`）—— **已随拆仓定案：不改名**，
      包名保持 `saintess_engine`，物理位置 = 框架仓顶层 `saintess_engine/`
- [x] **拆仓库 / submodule**（S8）—— **已完成**：引擎独立为 `framework-engine`；游戏仓
      `dragonfall/.gitmodules` 的 `framework` → 框架仓（固定 commit）
- [x] **收口清理过渡 shim**（S9）—— 已完成（S9-2 删净：`game/engine.py` 已删；
      `battle_bars` / `formation` / `formula_expr` / `skill_kinds` 等已归位框架仓
      （现 `saintess_engine/{expr,gauge,formation,kinds}/`））
- [ ] **语义残留未清**（门禁只是 import 门禁）。未清的 4 项：
  - `kinds/` 的中文枚举值（`kind_meta` 表，`kinds/__init__.py:27-34`）→ 应改为
    从 `config.kind_of` 注入，或明确标为「参考实现专用」
  - `landing` / `stats` 里的固定效果 key（`death_guard` · `heal_amp_pct` · `heal_down` ·
    `_anti_heal_pct` · `sleep`）
  - `effects.act_apply` 里的 `if key == "reduce"`
  - `battle._check_side_end` 里的 `"player"` 阵营名（`battle.py:555`）
  （完整表见 [../architecture/boundaries.md](../architecture/boundaries.md) 的「边界瑕疵」）
- [ ] **缺失消费方的声明清理**（`on_threshold` / `debuff_scale` / `wake_on_hit` /
      `tag` / `period.type` / `period.per_layer` / `period.dmg_type`）——
      要么实现消费，要么从参考实现的数据里删掉（现在它们会让第三方误以为可用）

### B. 可分发工程性

- [ ] **加版本号**：`saintess_engine/__init__.py` 里加 `__version__`，
      或框架仓的 `pyproject.toml`
- [ ] **加元数据**：Python 版本要求（当前未声明）、许可证、仓库地址
- [x] **拆出可独立运行的测试**：框架仓已有「零内容」的引擎自测集 —— 门禁
      `tests/test_engine_purity.py`（加强版）+ `tests/test_engine_neutral_fallback.py`
      （中性兜底：未挂配置不崩），一条命令跑完：`python tests/run_all.py`（**纯标准库 python 即可**）。
      （**游戏仓 / 奥兰迪亚侧**另有 28 个 `test_battle2_*.py`，其中仍有依赖内容侧
      （`config.load_game_defaults()`）的，那些留在游戏仓回归里。）
- [x] **去掉对仓库路径的假设**：框架仓的测试与示例只按框架仓自身根目录定位
      （如 `tests/test_engine_purity.py` 的 `FW_ROOT`），**不依赖**任何游戏仓路径。
      带 `PLUGIN_DIR` / `QQBOT_DIR` 路径推导（`dragonfall/` → `plugins/` → `data/` → `qqbot/`）
      的 `tests/conftest.py` 属于**游戏仓 / 奥兰迪亚侧**，框架仓没有这个文件。
- [x] **文档**：本 wiki（`docs/engine-wiki/`）已随引擎迁入框架仓 —— 就是你现在读的这份
      （游戏仓的 `docs/` 只留游戏侧文档）
- [x] **示例工程**：已有 `examples/minimal-game/`（《铆炉回声》：第三方视角的最小游戏，
      自带纯度门禁 `tests/test_smoke.py`）；另附编辑器演示包 `games/my_game/`

### C. 兼容性承诺（建议一次定下）

当前**没有**任何承诺。若要发布，建议至少约定：

| 变更类型 | 承诺 |
|---|---|
| `EVENTS` 元组增删 | **破坏性**（事件名是协议）；删事件要留一个版本的兼容 fire |
| `Battle` 公开方法签名 | 破坏性；加参数只能加在末尾且带默认值 |
| `to_state` 字段 | 加字段 = 兼容（旧档缺字段走默认）；**改字段语义 = 破坏性**（需要迁移） |
| 引擎动词的行为 | 破坏性（内容层依赖语义） |
| 新增 hook | 兼容 |
| `support/` 的函数 | 视为公开（已在 `__init__` 之外被引用），改动需评估 |

## 迁移期的两条实务建议

1. **引擎侧与内容侧分开发版本**。插件版本 `0.105.0` 仍同时覆盖两者（那是**游戏仓**
   的 `metadata.yaml`），导致「引擎改了但内容没跟上」和「内容改了」无法区分 ——
   拆仓只完成了**物理**分离，版本面还没分开。
2. **保留 `docs/ENGINE_CONTENT_SPLIT_PLAN.md` 的 S1–S3 门禁作为回归锚**
   （它每步都有机器可验断言；该文档在**游戏仓**）。拆仓时门禁已一起搬走：
   从 `tests/test_engine_no_content.py` 加强为框架仓的 `tests/test_engine_purity.py`
   —— 它是分发包的**自证文件**。

## 未取证 / 待确认

- 引擎的实际最低 Python 版本（只有 `__pycache__` 里的 3.11/3.12 痕迹）
- 是否已有计划中的分发形态：**submodule 已落地**（游戏仓 `dragonfall/.gitmodules` 的
  `framework` → 框架仓）；框架仓自身**没有** `.gitmodules`（它不引用任何外部仓），
  PyPI 形态仍无计划证据
- 是否存在内部约定的版本号方案（注释里的 `v181` 系列编号是否等价 semver 未知）
- commit 类型约定（无 CONTRIBUTING / 无钩子 —— 见 [conventions.md](conventions.md) §9）

完整清单 → [../_selfcheck.md](../_selfcheck.md)

## 相关

- 边界与迁移方案 → [../architecture/boundaries.md](../architecture/boundaries.md)
- 拿引擎的三种方式 → [../getting-started/installation.md](../getting-started/installation.md)
- 测试与回归 → [setup.md](setup.md)
