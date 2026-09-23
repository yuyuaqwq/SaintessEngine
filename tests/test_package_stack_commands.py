# -*- coding: utf-8 -*-
"""包栈级指令聚合门禁（B1：**扩展包也能带命令**）。

背景：`PackageStack.command_declarations()` / `command_handlers()` / `guard_hooks()`
原先只转发数据包（`return self.game.…`）⇒ 扩展包带不了命令 —— 抽包时「副本/经济/社交」
那半边系统（命令文本/守卫/取参）只能留在数据包里，可复用规模被砍掉一大块。

本门禁钉住新的**逐层合并**口径（与 `providers()` / `domain_decl()` 同源：近数据包者胜）：

  · 扩展包声明的 key 会出现在包栈表里（合并生效）
  · 数据包同 key 覆盖扩展包（数据包是最终真源）
  · **两个扩展包**声明同 key ⇒ `PackageError`（不静默覆盖 —— 谁提供必须唯一）
  · 处理器/守卫钩子同款合并；`resolve_handler` 能解析扩展包命名空间（`ext_a.*`）

外加两条**反证**（证明判据有牙：退回旧实现必红）。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.package import PackageError, load_stack   # noqa: E402
from _check import bind_check                                  # noqa: E402

FAILS: list = []
PASSED = 0
check = bind_check(globals(), "PASSED", failures="FAILS")


# ============================================================
# 临时包（自包含；与游戏无关的演示命令）
# ============================================================

_EXT_A = {
    "game.json": json.dumps({
        "id": "ext_a", "kind": "extension", "name": "演示扩展包 A",
        "desc": "带命令的扩展包（B1 门禁用）", "engine": ">=0.1",
        "entry": "apply.py", "created": "2026-09-24T00:00:00",
    }, ensure_ascii=False, indent=2),
    "apply.py": (
        'def install_engine():\n'
        '    """纯形状库：没有引擎级装配。"""\n'
        '    return None\n'
    ),
    "data/commands.json": json.dumps({
        "pack_solo": {"patterns": ["^包测(?:\\s*|$)"], "desc": "扩展包自带指令",
                      "category": "测试", "order": 1},
        "shared": {"patterns": ["^共享甲(?:\\s*|$)"], "desc": "扩展包版本",
                   "category": "测试", "order": 2},
    }, ensure_ascii=False, indent=2),
    "commands.py": (
        'def pack_ping(env=None):\n'
        '    """扩展包的处理器。"""\n'
        '    return ["pack-pong"]\n'
        '\n'
        'COMMANDS = {"pack_solo": {"handler": "ext_a.commands:pack_ping"}}\n'
    ),
    "guards.py": (
        'def demo_guard(env=None, player=None):\n'
        '    """扩展包的守卫钩子。"""\n'
        '    return None\n'
        '\n'
        'GUARDS = {"demo_guard": demo_guard}\n'
    ),
}

_EXT_B = {
    "game.json": json.dumps({
        "id": "ext_b", "kind": "extension", "name": "演示扩展包 B",
        "desc": "与 A 撞同一条命令 key（冲突用例）", "engine": ">=0.1",
        "entry": "apply.py", "created": "2026-09-24T00:00:00",
    }, ensure_ascii=False, indent=2),
    "apply.py": 'def install_engine():\n    return None\n',
    "data/commands.json": json.dumps({
        "pack_solo": {"patterns": ["^包测乙(?:\\s*|$)"], "desc": "B 包的同一个 key",
                      "category": "测试", "order": 3},
    }, ensure_ascii=False, indent=2),
}

_GAME = {
    "game.json": json.dumps({
        "id": "demo-game", "name": "演示数据包", "desc": "B1 门禁用最小数据包",
        "engine": ">=0.1", "entry": "content/apply.py",
        "depends": ["ext_a"], "domains": ["commands", "texts"],
        "created": "2026-09-24T00:00:00",
    }, ensure_ascii=False, indent=2),
    "content/apply.py": (
        'def install_engine():\n'
        '    """数据包装配入口（无 hook）。"""\n'
        '    return {"installed": True}\n'
        '\n'
        'def apply_game_content(actor: dict):\n'
        '    return actor\n'
        '\n'
        'def initial_save(uid, ctx=None):\n'
        '    return {"uid": uid}\n'
    ),
    "content/data/commands.json": json.dumps({
        "shared": {"patterns": ["^共享乙(?:\\s*|$)"], "desc": "数据包版本（应覆盖扩展包）",
                   "category": "测试", "order": 9},
        "game_only": {"patterns": ["^只有数据包(?:\\s*|$)"], "desc": "数据包独有",
                      "category": "测试", "order": 10},
    }, ensure_ascii=False, indent=2),
    "content/commands.py": (
        'def game_ping(env=None):\n'
        '    return ["game-pong"]\n'
        '\n'
        'COMMANDS = {"game_only": {"handler": "content.commands:game_ping"}}\n'
    ),
}


def _write(root: str, files: dict) -> str:
    for rel, src in files.items():
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
    return root


def _tree(tmp: str, *with_exts: str) -> tuple:
    """搭一棵 `<tmp>/extends/ext_* + <tmp>/games/demo-game`，返回 (game_dir, ext_root)。

    数据包的 `depends` = **传进来的全部扩展包** —— 扩展包只有被 depends 才进加载计划
    （`plan_stack` 的依赖解析），不是「目录里有就装」。
    """
    ext_root = os.path.join(tmp, "extends")
    os.makedirs(ext_root, exist_ok=True)
    for name in with_exts:
        _write(os.path.join(ext_root, name), _EXT_A if name == "ext_a" else _EXT_B)
    files = dict(_GAME)
    manifest = json.loads(files["game.json"])
    manifest["depends"] = list(with_exts)
    files["game.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
    game_dir = _write(os.path.join(tmp, "games", "demo-game"), files)
    return game_dir, ext_root


def main() -> int:
    print("=== 包栈指令聚合门禁（扩展包带命令 · 分层合并 · 冲突 fail-closed）===")
    tmp = tempfile.mkdtemp(prefix="stack_cmds_")

    # ---------------------------------------------------------------- 1. 合并生效
    game_dir, ext_root = _tree(tmp, "ext_a")
    stack = load_stack(game_dir, exts=[ext_root])
    decls = stack.command_declarations()
    check("扩展包声明的指令进包栈声明表（pack_solo）",
          "pack_solo" in decls, sorted(decls))
    check("数据包自己那条照旧在（game_only）", "game_only" in decls, sorted(decls))
    check("两条包的声明合并成一张表（pack_solo + game_only + shared）",
          {"pack_solo", "game_only", "shared"} <= set(decls), sorted(decls))
    check("数据包覆盖扩展包同 key（shared 取数据包版本）",
          (decls.get("shared") or {}).get("patterns") == ["^共享乙(?:\\s*|$)"],
          decls.get("shared"))

    # ---------------------------------------------------------------- 2. 处理器 / 守卫
    handlers = stack.command_handlers()
    check("扩展包的处理器表进包栈（pack_solo → ext_a.commands:pack_ping）",
          (handlers.get("pack_solo") or {}).get("handler") == "ext_a.commands:pack_ping",
          handlers.get("pack_solo"))
    check("数据包处理器照旧在（game_only）", "game_only" in handlers, sorted(handlers))
    check("resolve_handler 能解析扩展包命名空间（ext_a.commands:pack_ping）",
          callable(stack.resolve_handler("ext_a.commands:pack_ping")), None)
    check("resolve_handler 能解析数据包命名空间（content.commands:game_ping）",
          callable(stack.resolve_handler("content.commands:game_ping")), None)
    check("守卫钩子也逐层合并（demo_guard）",
          "demo_guard" in (stack.guard_hooks() or {}), sorted(stack.guard_hooks() or {}))

    # ---------------------------------------------------------------- 3. 冲突 fail-closed
    tmp2 = tempfile.mkdtemp(prefix="stack_cmds_conflict_")
    game_dir2, ext_root2 = _tree(tmp2, "ext_a", "ext_b")
    stack2 = load_stack(game_dir2, exts=[ext_root2])
    try:
        stack2.command_declarations()
        err = None
    except PackageError as exc:
        err = str(exc)
    check("两个扩展包声明同 key ⇒ PackageError（不静默覆盖）", bool(err), err)
    check("冲突报错点名两个包（可定位）",
          bool(err) and "ext_a" in err and "ext_b" in err, err)
    check("冲突只卡撞 key 的那层：处理器表不受影响（能读）",
          isinstance(stack2.command_handlers(), dict), None)

    # ---------------------------------------------------------------- 4. 反证（判据有牙）
    # ① 退回旧实现（只转发数据包）⇒ 扩展包声明必然消失 ⇒ 上面第一条判据必红
    from saintess_engine.package import PackageStack
    old = PackageStack.command_declarations
    try:
        PackageStack.command_declarations = lambda self: self.game.command_declarations()
        reverted = load_stack(game_dir, exts=[ext_root]).command_declarations()
    finally:
        PackageStack.command_declarations = old
    check("反证① 退回「只转发数据包」⇒ 扩展包声明的 pack_solo 消失（判据必红）",
          "pack_solo" not in reverted, sorted(reverted))
    check("反证① 同时数据包那条仍在（证明差异只在扩展包那一层）",
          "game_only" in reverted, sorted(reverted))

    # ② 去掉冲突检测（改成后写覆盖）⇒ 撞 key 不再报错 ⇒ 冲突判据必红
    old_merge = PackageStack._merge_command_layer
    try:
        def _no_guard(self, attr, what):
            out = {}
            for pkg in self.packages:
                out.update({str(k): v for k, v in (getattr(pkg, attr)() or {}).items()})
            return out
        PackageStack._merge_command_layer = _no_guard
        silent = load_stack(game_dir2, exts=[ext_root2]).command_declarations()
    finally:
        PackageStack._merge_command_layer = old_merge
    check("反证② 去掉冲突检测 ⇒ 撞 key 变成静默后写覆盖（pack_solo 变成 B 包版本）",
          (silent.get("pack_solo") or {}).get("patterns") == ["^包测乙(?:\\s*|$)"],
          silent.get("pack_solo"))

    print("\n通过 %d / 失败 %d" % (PASSED, len(FAILS)))
    if FAILS:
        for line in FAILS:
            print("❌ %s" % line)
        return 1
    print("✅ 包栈指令聚合口径全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
