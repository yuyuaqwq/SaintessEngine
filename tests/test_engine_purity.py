# -*- coding: utf-8 -*-
"""框架纯度门禁（框架契约）—— 包 `saintess_engine` 的每个模块只依赖「相对导入 + 标准库」。

**被守的包（2026-09-11 模块化重排后）**：`saintess_engine/` —— 单一包、多模块并列：

  基础      config.py / domains.py
  扩展包    extends/ext_combat（战斗，12 模块）· extends/ext_quest（任务）
  通用原语  expr/ gauge/ formation/（2026-09-13 P4 下沉：中文 kind 词表 kinds/ 已归内容侧）
  运行时    store/ command/ events/ clock/ container/ session/

纯度契约对**全部子模块一致** —— 整包可拷进第三方项目、可独立分发。

这是**可分发性**的核心闸门：任何一条指向外部包的绝对 import，都会让框架
无法脱离原游戏单独分发（第三方 clone 后 import 即失败）。

断言（AST 静态分析，不做运行时 import）：
  1. 包内 .py 的 **每一条绝对 import 都是标准库**（相对导入不限）
     —— 覆盖 `import x` / `import x.y` / `from x.y import z`
  2. 零动态导入穿透：`importlib.import_module("外部包")` / `__import__("外部包")`
  3. 公开 API 面完整（包门面 re-export 全量符号）
  4. 存档兼容：`Battle.from_state` / `to_state` 在 API 面内
  5. 扩展包 `ext_combat/battle/actions.py` 零 kind 中文字面量常量（机制/名词不得进框架）

运行：python tests/test_engine_purity.py（exit=0 全绿）
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)

# 被守的包：单一包（模块化重排后，全部能力都是它的并列子模块）
ENGINE_DIR = os.path.join(FW_ROOT, "saintess_engine")
EXT_DIR = os.path.join(FW_ROOT, "extends")      # 扩展包仓内目录（ext_combat / ext_quest）
if EXT_DIR not in sys.path:
    sys.path.insert(0, EXT_DIR)
ENGINE_NAME = "saintess_engine"
PKG_DIRS = (ENGINE_DIR,)

# 兼容旧引用名
PKG_DIR = ENGINE_DIR
PKG_NAME = ENGINE_NAME

# 标准库集合（3.10+ 自带；旧解释器回落一个保守白名单）
try:
    STDLIB = set(sys.stdlib_module_names)
except AttributeError:                                        # pragma: no cover
    STDLIB = {"os", "sys", "re", "ast", "json", "math", "random", "copy",
              "typing", "dataclasses", "collections", "itertools", "functools",
              "importlib", "time", "traceback", "logging", "enum", "abc"}

# 公开 API 面（内容层/第三方实际消费的符号）
API_SYMBOLS = [
    # 引擎门面 = **通用件**（2026-09-23 包栈重构：战斗符号随 ext_combat 迁出引擎，
    # 它们现在由 `from ext_combat import Battle, make_actor, …` 提供）。
    "config", "get_effect_rules", "get_effect_actions",
    "Package", "PackageError", "PackageStack", "load_stack", "probe_stack",
    "Host",
    "Space", "LootTable", "TierTable",
    "Admission", "Progress", "Roster", "Rule", "Verdict",
    "Dialogue", "Cursor",
    "CommandRegistry", "CommandSpec", "TextTable", "TextSpec", "safe_format",
    "TLog", "Record", "KindTable",
]
# 私有 → 公开的 5 个符号（cap_of / norm_stack / now_of / heal_amount / skill_pay_of）
# 已随战斗迁到扩展包 `ext_combat`（2026-09-23），这条门禁现在归那边 —— 这里留空表。
PROMOTED_ALIASES = []

# 门面转出的子模块（`getattr(包, 名)` 取到对应模块）—— 只列**通用件**
MODULE_ATTRS = [
    ("domains", "domains"),
    ("expr", "expr"),
    ("store", "store"), ("command", "command"), ("events", "events"),
    ("clock", "clock"), ("log", "log"), ("tlog", "tlog"), ("space", "space"), ("loot", "loot"),
    ("run", "run"), ("container", "container"), ("session", "session"),
    ("dialogue", "dialogue"), ("presence", "presence"),
]

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _iter_dynamic_imports(node):
    if isinstance(node, ast.Call):
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if fname in ("import_module", "__import__"):
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    yield a.value


def _root_of(dotted: str) -> str:
    return (dotted or "").split(".")[0]


def scan():
    """返回 (非标准库绝对 import 列表, 动态导入违规列表, 扫描文件数)。"""
    bad, dyn, n = [], [], 0
    for pkg_dir in PKG_DIRS:
        if not os.path.isdir(pkg_dir):
            continue
        for root, _dirs, files in os.walk(pkg_dir):
            if "__pycache__" in root:
                continue
            for fn in sorted(files):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, FW_ROOT).replace("\\", "/")
                n += 1
                tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.level:                           # 相对导入：允许
                            continue
                        r = _root_of(node.module)
                        if r and r not in STDLIB:
                            bad.append(f"{rel}:{node.lineno}: from {node.module} import ...")
                    elif isinstance(node, ast.Import):
                        for a in node.names:
                            r = _root_of(a.name)
                            if r and r not in STDLIB:
                                bad.append(f"{rel}:{node.lineno}: import {a.name}")
                    for s in _iter_dynamic_imports(node):
                        r = _root_of(s)
                        if r and r not in STDLIB:
                            dyn.append(f"{rel}:{node.lineno}: 动态导入 {s!r}")
    return bad, dyn, n


def main():
    print("== 框架纯度门禁：saintess_engine/**（含全部子模块）只依赖「相对导入 + 标准库」==")
    for pkg_dir in PKG_DIRS:
        check(f"包目录存在：{os.path.basename(pkg_dir)}", os.path.isdir(pkg_dir), pkg_dir)

    bad, dyn, n = scan()
    check("扫描到包内 .py 文件（≥30）", n >= 30, f"n={n}")

    # 幽灵目录：删掉源文件后残留的 __pycache__ 会让「包目录数」虚高
    # （2026-09-12 实测：模块化重排后 support/ 只剩 .pyc，导致 wiki 数字门禁红，
    #   更危险的是它可被 Python 当命名空间包导入 → 幽灵 import 路径）
    ghosts = []
    for name in sorted(os.listdir(ENGINE_DIR)):
        d = os.path.join(ENGINE_DIR, name)
        if (os.path.isdir(d) and name != "__pycache__"
                and not os.path.exists(os.path.join(d, "__init__.py"))):
            ghosts.append(name)
    check("包内无幽灵子目录（每个子目录都有 __init__.py）", not ghosts,
          f"残留={ghosts}（无源文件的目录应整个删掉）")
    check("零非标准库绝对 import（可分发性闸门）", not bad,
          "\n      " + "\n      ".join(bad))
    check("零动态导入穿透（importlib/__import__ 指向外部包）", not dyn,
          "\n      " + "\n      ".join(dyn))

    # battle/actions.py 不得持有游戏 kind 中文字面量常量
    # 战斗已迁成扩展包（2026-09-23）：这条判据跟着文件走，仍钉「不许持有游戏 kind 中文字面量」
    act = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py")
    tree = ast.parse(open(act, encoding="utf-8").read(), filename=act)
    consts = {t.id for node in tree.body if isinstance(node, ast.Assign)
              for t in node.targets if isinstance(t, ast.Name)}
    KINDS = {"K_PHYS", "K_MAGI", "K_TRUE", "K_HEAL", "K_BUFF"}
    check("battle/actions.py 零 kind 中文字面量常量", not (KINDS & consts),
          f"残留={sorted(KINDS & consts)}")

    # 注入面存在（内容侧装配契约）
    csrc = open(os.path.join(PKG_DIR, "config.py"), encoding="utf-8").read()
    for hook in ("formulas", "panel_fn", "skill_lookup", "monster_skill_fn",
                 "basic_skill_fn", "basic_fallback", "kinds"):
        check(f"config 注入面含 hook {hook!r}", f'"{hook}"' in csrc)

    # 公开 API 面
    if FW_ROOT not in sys.path:
        sys.path.insert(0, FW_ROOT)
    import importlib
    _B2 = importlib.import_module(PKG_NAME)
    missing = [s for s in API_SYMBOLS if not hasattr(_B2, s)]
    check("战斗符号已不在引擎门面（2026-09-23 迁成扩展包 ext_combat）",
          not any(hasattr(_B2, s) for s in ("Battle", "make_actor", "deal_damage")),
          "引擎门面仍有战斗符号")
    check(f"包门面 re-export 全量 {len(API_SYMBOLS)} 符号", not missing,
          f"missing={missing}")
    alias_bad = []
    for mod_name, pub, priv in PROMOTED_ALIASES:
        mod = _B2 if mod_name is None else importlib.import_module(f"{PKG_NAME}.{mod_name}")
        if not (hasattr(_B2, pub) and mod is not None and hasattr(mod, pub)
                and hasattr(mod, priv)
                and getattr(mod, priv) is getattr(mod, pub, None)):
            alias_bad.append(f"{mod_name}:{pub}/{priv}")
    check("5 私有符号已升公开且旧下划线名为同一对象别名", not alias_bad,
          f"bad={alias_bad}")

    # 门面转出全部子模块（模块化重排：`from saintess_engine import <模块>` 可用）
    mod_bad = []
    for attr, dotted in MODULE_ATTRS:
        if not hasattr(_B2, attr):
            mod_bad.append(attr)
            continue
        sub = importlib.import_module(f"{PKG_NAME}.{dotted}")
        if getattr(_B2, attr) is not sub:
            mod_bad.append(f"{attr}!={dotted}")
    check(f"门面转出全部 {len(MODULE_ATTRS)} 个子模块（属性即模块对象）", not mod_bad,
          f"bad={mod_bad}")

    # 存档兼容（`Battle.from_state` / `to_state`）随战斗迁到扩展包 —— 这条判据跟着走
    _ext_ok = False
    try:
        _C = importlib.import_module("ext_combat")
        _ext_ok = (hasattr(_C.Battle, "from_state") and hasattr(_C.Battle, "to_state")
                   and hasattr(_C, "from_state") and hasattr(_C, "to_state"))
    except Exception:                                          # noqa: BLE001
        _ext_ok = False
    check("存档兼容：Battle.from_state / to_state 在扩展包（ext_combat）API 面内", _ext_ok)

    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
