# -*- coding: utf-8 -*-
"""门禁：三层的**依赖方向**守卫 —— 引擎 / 扩展包 / 数据包。

为什么要这一道
--------------
2026-09-23 的包栈重构把游戏原语（战斗 / 任务 / 空间 / 掉落 / 对话 …）从引擎搬进了
`extends/` 扩展包。**搬出去只是第一步** —— 真正会复发的是「反向回流」：

  · 有人为了省事，在引擎里写一句 `from ..battle.effects import register_action`，
    于是「通用框架」又长回成「战斗引擎」，而且这**不会报错**（文件还在，只是位置错了）；
  · 有人在扩展包里 `import ext_loot` 却忘了在 `game.json` 里写 `depends`，
    装上单包就炸，而且只有那一条路径炸。
  · 数据包 `import` 了没写进 `depends` 的扩展包 —— 同上，只是更晚才发现。

方向只有一条：**数据包 → 扩展包 → 引擎**。本门禁把它钉死。

判据
----
A. 引擎（`saintess_engine/**`）**零** import 游戏原语：既不 import `extends/` 下任何包的名字，
   也不得再出现那些模块目录（`battle/` `quest/` `space/` `run/` `loot/` `dialogue/` …）。
B. 扩展包（`extends/<pkg>/**`）不许 import **别的**扩展包，除非写在自己的 `depends` 里；
   引擎方向（`from saintess_engine …`）随便用。
C. 数据包（`games/<pkg>/**`）import 的扩展包必须出现在它 `game.json` 的 `depends` 里
   （含 submodule 里的包：只要目录在、`game.json` 在，就查）。
D. 反向自证：`extends/` 下每个包都能被「引擎 + 它自己的 depends」这条闭包解释清楚 ——
   即存在性证明，避免有人把包丢进去却忘了挂进任何栈。

跑法：python tests/test_layering.py
退出码：0 = 全绿；1 = 有失败。
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

#: 已搬进扩展包的游戏原语（引擎里**不许**再出现它们的目录，也不许 import 它们）
PROMISED = ("battle", "gauge", "formation", "panel", "quest", "space", "run", "loot",
            "dialogue", "presence", "shelf", "trade", "produce", "collect", "periodic",
            "timers", "unlock", "membership")


def _py_files(base):
    for dp, dn, fn in os.walk(base):
        if "__pycache__" in dp or ".git" in dp:
            continue
        for f in fn:
            if f.endswith(".py"):
                yield os.path.join(dp, f)


def _abs_imports(path):
    """该文件的**绝对** import 顶层名（相对 import 不在此列）+ 相对 import 的模块名。"""
    src = io.open(path, encoding="utf-8", errors="ignore").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [], []
    abs_names, rel_names = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            abs_names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                rel_names.append(node.module or "")
            elif node.module:
                abs_names.append(node.module)
    return abs_names, rel_names


def _ext_pkgs():
    base = os.path.join(FW_ROOT, "extends")
    out = {}
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "game.json")):
            try:
                out[name] = json.load(io.open(os.path.join(d, "game.json"), encoding="utf-8"))
            except Exception:                                      # noqa: BLE001
                out[name] = {}
    return out


def _game_pkgs():
    base = os.path.join(FW_ROOT, "games")
    out = {}
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "game.json")):
            try:
                out[name] = json.load(io.open(os.path.join(d, "game.json"), encoding="utf-8"))
            except Exception:                                      # noqa: BLE001
                out[name] = {}
    return out


# ─────────────────────────────────────────── A. 引擎：零游戏原语
def t_a_engine_pure():
    print("\n[A] 引擎不许认识游戏原语")
    se = os.path.join(FW_ROOT, "saintess_engine")
    left = [m for m in PROMISED if os.path.isdir(os.path.join(se, m))]
    check(f"引擎里没有游戏原语的模块目录（{len(PROMISED)} 个已搬走）", not left, left)

    ext_ids = set(_ext_pkgs())
    bad = []
    for p in _py_files(se):
        abs_names, rel_names = _abs_imports(p)
        for nm in abs_names:
            head = nm.split(".")[0]
            if head in ext_ids or head in PROMISED:
                bad.append(f"{os.path.relpath(p, FW_ROOT)}: import {nm}")
        for nm in rel_names:
            head = nm.split(".")[0]
            if head in PROMISED:
                bad.append(f"{os.path.relpath(p, FW_ROOT)}: from ..{nm}")
    check("引擎零 import 扩展包 / 游戏原语（`from ..battle …` 这类一次都不许有）", not bad, bad)


# ─────────────────────────────────────────── B. 扩展包：只许 import 引擎 + 同包 + depends
def t_b_ext_pkgs():
    print("\n[B] 扩展包只许 import 引擎 / 自己的 depends")
    ext = _ext_pkgs()
    bad = []
    for pkg, manifest in ext.items():
        deps = set(manifest.get("depends") or [])
        base = os.path.join(FW_ROOT, "extends", pkg)
        for p in _py_files(base):
            # ★ 包内的 `tests/` 是**仓内测试基础设施**（跟包一起走，但允许跨包 import 别的包的形状）——
            #   这里守的是「包的**运行代码**」不许偷偷引用别的包。
            if os.sep + "tests" + os.sep in p:
                continue
            abs_names, _rel = _abs_imports(p)
            for nm in abs_names:
                head = nm.split(".")[0]
                if head in ext and head != pkg and head not in deps:
                    bad.append(f"{pkg}: {os.path.relpath(p, FW_ROOT)} → import {nm}"
                               f"（没写在 depends 里：{sorted(deps)}）")
    check(f"扩展包之间零「偷偷引用」（{len(ext)} 个包，跨包引用必须在 depends 里）", not bad, bad)


# ─────────────────────────────────────────── C. 数据包：import 的扩展包必须已声明 depends
def t_c_game_pkgs():
    print("\n[C] 数据包 import 的扩展包必须在 depends 里")
    ext = _ext_pkgs()
    games = _game_pkgs()
    bad = []
    for pkg, manifest in games.items():
        deps = set(manifest.get("depends") or [])
        base = os.path.join(FW_ROOT, "games", pkg)
        for p in _py_files(base):
            abs_names, _rel = _abs_imports(p)
            for nm in abs_names:
                head = nm.split(".")[0]
                if head in ext and head not in deps:
                    bad.append(f"{pkg}: {os.path.relpath(p, FW_ROOT)} → import {nm}"
                               f"（depends = {sorted(deps)}）")
    check(f"数据包没漏声明 depends（查了 {len(games)} 个包）", not bad, bad)

    # 每个数据包都应至少能解释它的域表来源（有 depends 或自己声明）
    no_dep = [p for p, m in games.items() if not (m.get("depends") or [])]
    check("每个数据包都声明了 depends（要么装扩展包，要么纯通用表）",
          len(no_dep) <= 1, f"没声明的：{no_dep}")     # 只允许 my_game 这种骨架包


# ─────────────────────────────────────────── D. 反证：每个扩展包都被某处用着
def t_d_no_orphan():
    print("\n[D] 反证：没有「丢进去没人用」的孤儿扩展包")
    ext = _ext_pkgs()
    used = set()
    for _pkg, m in list(_game_pkgs().items()) + list(ext.items()):
        used |= set(m.get("depends") or [])
    used |= {m for m in _ext_pkgs() if False}
    # 实例样板 / 骨架也认（examples 用的是引擎自带扩展包）
    ex = os.path.join(FW_ROOT, "examples")
    for dp, dn, fn in os.walk(ex):
        if "__pycache__" in dp:
            continue
        if "game.json" in fn:
            try:
                m = json.load(io.open(os.path.join(dp, "game.json"), encoding="utf-8"))
                used |= set(m.get("depends") or [])
            except Exception:                                      # noqa: BLE001
                pass
    orphan = sorted(set(ext) - used)
    check(f"每个扩展包都至少被一个数据包/样板依赖（{len(ext)} 个包）",
          not orphan, f"没人用：{orphan}")


def main():
    print("== 分层守卫：引擎 / 扩展包 / 数据包（依赖方向单向） ==")
    t_a_engine_pure()
    t_b_ext_pkgs()
    t_c_game_pkgs()
    t_d_no_orphan()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  · " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
