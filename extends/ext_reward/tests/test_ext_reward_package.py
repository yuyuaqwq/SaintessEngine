# -*- coding: utf-8 -*-
"""`ext_reward` 扩展包门禁（B4a：流水采集半边从数据包抽进扩展包）。

钉四件事：

1. **包契约**：`game.json` 的 `id` / `kind` / `entry` 自洽，`install_engine()` 是**显式空实现**
   （纯形状库 —— 不留含糊空壳）。
2. **形状可用**：`from ext_reward.tlog_collect import BattleTLog, EVENT_KINDS, REPRO_KEYS`
   三个名字都在，且 `EVENT_KINDS` 非空（映射表骨架）。
3. ★ **可拔插红线**：`BattleTLog(tlog=None)` ⇒ `attach()` 原样返回战斗对象、不挂任何属性、
   `flush()` 不碰 sink（**零行为**）；给了 sink ⇒ `flush()` 真的落到 sink（证明这条红线
   不是「两边都不动」的空断言）。
4. ★ **可换游戏**：本包（含子目录）的 `.py` **零 import 数据包**（`content` / `content.*`）——
   AST 扫描 + 一条反证（合成一段 `from content import x` 的源码 ⇒ 扫描器必须报红）。

跑法：python extends/ext_reward/tests/test_ext_reward_package.py
"""
from __future__ import annotations

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(HERE)                       # extends/ext_reward
FW_ROOT = os.path.dirname(os.path.dirname(PKG_DIR))   # 引擎仓根
for _p in (HERE, FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check                          # noqa: E402

PASS = 0
FAILS: list = []
check = bind_check(globals(), "PASS", failures="FAILS")


# ---------------------------------------------------------------- 层级扫描（判据 ④）
def content_imports(src: str) -> list:
    """源码里所有「导入数据包」的模块名（`content` / `content.*`）。"""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ["<语法错误>"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names
                    if a.name == "content" or a.name.startswith("content.")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:                                # `from . import …` 相对导入：包内局部的活
                continue
            if mod == "content" or mod.startswith("content."):
                out.append(mod)
    return out


def pack_sources() -> list:
    out = []
    for dp, dn, fn in os.walk(PKG_DIR):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def main() -> int:
    print("=== ext_reward 扩展包门禁（包契约 · 形状可用 · 零行为红线 · 零数据包依赖）===")

    # ------------------------------------------------------------ 1. 包契约
    with open(os.path.join(PKG_DIR, "game.json"), encoding="utf-8") as f:
        man = json.load(f)
    check("game.json id == ext_reward（目录名 = id = 命名空间）", man.get("id") == "ext_reward", man.get("id"))
    check("kind == extension（扩展包）", man.get("kind") == "extension", man.get("kind"))
    check("entry == apply.py（包根入口惯例）", man.get("entry") == "apply.py", man.get("entry"))

    from ext_reward.apply import install_engine
    check("install_engine() 存在（入口模块 = 包根 apply.py）", callable(install_engine), None)
    check("install_engine() 是显式空实现（返回 None，不往引擎塞东西）",
          install_engine() is None, None)

    # ------------------------------------------------------------ 2. 形状可用
    from ext_reward.tlog_collect import BattleTLog, EVENT_KINDS, REPRO_KEYS
    check("BattleTLog / EVENT_KINDS / REPRO_KEYS 三个名字都在",
          bool(BattleTLog) and bool(EVENT_KINDS) and bool(REPRO_KEYS),
          (type(EVENT_KINDS).__name__, type(REPRO_KEYS).__name__))
    check("EVENT_KINDS 是非空映射（映射表骨架在包里、具体键名由数据包给值）",
          isinstance(EVENT_KINDS, dict) and len(EVENT_KINDS) > 0, len(EVENT_KINDS or ()))

    # ------------------------------------------------------------ 3. 零行为红线
    class _Sink:
        def __init__(self):
            self.emits = []
            self.flushes = 0

        def emit(self, kind, **fields):
            self.emits.append((kind, fields))

        def flush(self):
            self.flushes += 1

    class _Battle:
        """最小战斗替身：只提供 `attach()` 会碰的两处（其余一律 AttributeError）。"""

        def __init__(self):
            self.on_event = lambda *a, **k: None
            self.human_act = lambda *a, **k: None
            self._dispatch_pending = lambda *a, **k: None

    off = _Battle()
    col_off = BattleTLog(None)
    same = col_off.attach(off)
    check("tlog=None ⇒ enabled 为假", col_off.enabled is False, col_off.enabled)
    check("tlog=None ⇒ attach() 原样返回战斗对象（同一对象）", same is off, None)
    check("tlog=None ⇒ 不往战斗对象挂采集器", not hasattr(off, "_battle_tlog"),
          sorted(vars(off)))
    check("tlog=None ⇒ 不包 human_act（包装标记不存在）",
          not getattr(off.human_act, "_battle_tlog_wrapped", False), None)
    col_off.flush()
    check("tlog=None ⇒ flush() 是空操作（不碰 sink）", True, None)

    sink = _Sink()
    col_on = BattleTLog(sink)
    ba = _Battle()
    col_on.attach(ba)
    col_on.flush()
    check("给了 sink ⇒ enabled 为真（插拔面真的通）", col_on.enabled is True, col_on.enabled)
    check("给了 sink ⇒ attach() 把采集器挂在战斗对象上", getattr(ba, "_battle_tlog", None) is col_on,
          None)
    check("给了 sink ⇒ flush() 真的落到 sink", sink.flushes == 1, sink.flushes)

    # ------------------------------------------------------------ 4. 可换游戏（零数据包依赖）
    bad = []
    for path in pack_sources():
        with open(path, encoding="utf-8") as f:
            hits = content_imports(f.read())
        if hits:
            bad.append((os.path.relpath(path, PKG_DIR), hits))
    check("本包 .py 里零 import 数据包（content / content.*）—— 换游戏不用改本包",
          not bad, bad)
    check("扫描面覆盖到本包全部 .py（≥3 个：apply / tlog/__init__ / tlog/collect）",
          len(pack_sources()) >= 3, [os.path.relpath(p, PKG_DIR) for p in pack_sources()])

    # 反证：合成一段「import 数据包」的源码 ⇒ 扫描器必须报红（判据有牙）
    proof = content_imports("from content import catalog_items\nimport content.texts\n")
    check("反证：扫描器对 `from content import …` / `import content.*` 报红",
          sorted(proof) == ["content", "content.texts"], proof)
    check("反证：包内相对导入（`from . import x`）不算数据包依赖",
          content_imports("from . import collect\n") == [], None)

    print("\n通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        for line in FAILS:
            print("❌ %s" % line)
        return 1
    print("✅ ext_reward 包门禁全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
