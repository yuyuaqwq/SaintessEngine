# -*- coding: utf-8 -*-
"""引擎纯度门禁（框架契约）—— `saintess_engine/**` 只依赖「相对导入 + 标准库」。

这是**可分发性**的核心闸门：任何一条指向外部包的绝对 import，都会让框架
无法脱离原游戏单独分发（第三方 clone 后 import 即失败）。

断言（AST 静态分析，不做运行时 import）：
  1. 引擎 .py 的 **每一条绝对 import 都是标准库**（相对导入不限）
     —— 覆盖 `import x` / `import x.y` / `from x.y import z`
  2. 零动态导入穿透：`importlib.import_module("外部包")` / `__import__("外部包")`
  3. 公开 API 面完整（包门面 re-export 全量符号）
  4. 存档兼容：`Battle.from_state` / `to_state` 在 API 面内
  5. `actions.py` 零 kind 中文字面量常量（机制/名词不得进引擎）

运行：python tests/test_engine_purity.py（exit=0 全绿）
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
PKG_DIR = os.path.join(FW_ROOT, "saintess_engine")
PKG_NAME = "saintess_engine"

# 标准库集合（3.10+ 自带；旧解释器回落一个保守白名单）
try:
    STDLIB = set(sys.stdlib_module_names)
except AttributeError:                                        # pragma: no cover
    STDLIB = {"os", "sys", "re", "ast", "json", "math", "random", "copy",
              "typing", "dataclasses", "collections", "itertools", "functools",
              "importlib", "time", "traceback", "logging", "enum", "abc"}

# 公开 API 面（内容层/第三方实际消费的符号）
API_SYMBOLS = [
    "deal_damage", "state_def", "heal_actor", "Battle", "actor_alive",
    "act_apply", "cap_of", "actor_stats", "apply_effects", "now_of",
    "stats", "register_action", "config", "fire", "all_state_effects",
    "action_time", "initial_ct", "hostile_sides", "act_shield",
    "norm_stack", "effects", "heal_amount", "skill_pay_of", "make_actor",
    "get_effect_rules", "get_effect_actions",
]
# 私有 → 公开的 5 个符号（旧下划线名保别名：模块 → (公开名, 私有名)）
PROMOTED_ALIASES = [
    ("effects", "cap_of", "_cap_of"),
    ("effects", "norm_stack", "_norm_stack"),
    ("battle", "now_of", "_now_of"),
    ("actions", "heal_amount", "_heal_amount"),
    ("actions", "skill_pay_of", "_skill_pay_of"),
]

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


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
    for root, _dirs, files in os.walk(PKG_DIR):
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
    print("== 框架纯度门禁：saintess_engine/** 只依赖「相对导入 + 标准库」==")
    check("引擎包目录存在", os.path.isdir(PKG_DIR), PKG_DIR)

    bad, dyn, n = scan()
    check("扫描到引擎 .py 文件（≥13）", n >= 13, f"n={n}")
    check("零非标准库绝对 import（可分发性闸门）", not bad,
          "\n      " + "\n      ".join(bad))
    check("零动态导入穿透（importlib/__import__ 指向外部包）", not dyn,
          "\n      " + "\n      ".join(dyn))

    # actions.py 不得持有游戏 kind 中文字面量常量
    act = os.path.join(PKG_DIR, "actions.py")
    tree = ast.parse(open(act, encoding="utf-8").read(), filename=act)
    consts = {t.id for node in tree.body if isinstance(node, ast.Assign)
              for t in node.targets if isinstance(t, ast.Name)}
    KINDS = {"K_PHYS", "K_MAGI", "K_TRUE", "K_HEAL", "K_BUFF"}
    check("actions.py 零 kind 中文字面量常量", not (KINDS & consts),
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
    check(f"包门面 re-export 全量 {len(API_SYMBOLS)} 符号", not missing,
          f"missing={missing}")
    alias_bad = []
    for mod_name, pub, priv in PROMOTED_ALIASES:
        mod = getattr(_B2, mod_name, None)
        if not (hasattr(_B2, pub) and mod is not None and hasattr(mod, pub)
                and hasattr(mod, priv)
                and getattr(mod, priv) is getattr(mod, pub, None)):
            alias_bad.append(f"{mod_name}:{pub}/{priv}")
    check("5 私有符号已升公开且旧下划线名为同一对象别名", not alias_bad,
          f"bad={alias_bad}")
    check("存档兼容：Battle.from_state / to_state 在 API 面内",
          hasattr(_B2.Battle, "from_state") and hasattr(_B2.Battle, "to_state")
          and hasattr(_B2, "from_state") and hasattr(_B2, "to_state"))

    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
