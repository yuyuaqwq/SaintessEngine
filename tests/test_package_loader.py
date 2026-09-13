# -*- coding: utf-8 -*-
"""游戏包加载器门禁（`saintess_engine/package.py`）。

守的是**包内相对导入**这条命门：在此之前三处加载器都按顶层 `import apply` 加载，
包内写 `from .mech import actions` 会炸（或被 `except ImportError` 吞掉 → **动作静默不注册**，
表现是"战斗里什么都没发生"）。本门禁在**子进程**里真加载一个带 `content/mech/` 的包，
断言：① 加载成功且走的是 `package` 式导入；② 那个动作**真的注册进了引擎**。

顺带守错误路径：缺 game.json / 入口不存在 / 版本不满足 / 缺 install_engine() —— 都必须
`ok=False` 且给出**可读**错误（不抛栈给调用方）。

跑法：python tests/test_package_loader.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

PASS = 0
FAIL = 0
FAILURES = []

APPLY_SRC = '''# -*- coding: utf-8 -*-
"""探针包：**用相对导入**引自己的 mech（旧加载器会炸在这行）。"""
from saintess_engine import config as config
from .mech import actions          # noqa: F401  ← 包内相对导入：这就是本门禁要守的
from . import rules_meta


def install_engine() -> None:
    config.register_hook_provider(lambda: None)
    import saintess_engine.battle.formulas as formulas
    config.mount(formulas=formulas)
    config.load_game_rules(rules_meta)
'''

MECH_SRC = '''# -*- coding: utf-8 -*-
from saintess_engine import register_action


@register_action("probe_relative_verb")
def probe_relative_verb(battle, caster, target, params, logs):   # noqa: ARG001
    """探针动作：只证明「被注册」。"""
    logs.append("probe")
'''

RULES_SRC = '''# -*- coding: utf-8 -*-
"""声明表（探针）：install_engine 走 load_game_rules 挂的就是它。"""
EFFECT_RULES = {"probe_rule": {"name": "探针规则"}}
EFFECT_ACTIONS = {}
'''


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def make_pkg(root: str, *, manifest=None, with_entry=True, with_mech=True, apply_src=APPLY_SRC):
    os.makedirs(os.path.join(root, "content", "mech"), exist_ok=True)
    man = {"id": "probe", "name": "探针包", "engine": ">=0.1", "entry": "content/apply.py",
           "domains": ["items"]}
    man.update(manifest or {})
    with open(os.path.join(root, "game.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False)
    if with_entry:
        with open(os.path.join(root, "content", "apply.py"), "w", encoding="utf-8") as f:
            f.write(apply_src)
        with open(os.path.join(root, "content", "rules_meta.py"), "w", encoding="utf-8") as f:
            f.write(RULES_SRC)
    if with_mech:
        with open(os.path.join(root, "content", "mech", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(root, "content", "mech", "actions.py"), "w", encoding="utf-8") as f:
            f.write(MECH_SRC)


def run_probe(pkg_dir: str) -> dict:
    """在**子进程**里加载（模块状态干净；`content` 这个名字会被 sys.modules 缓存）。"""
    probe = (
        "import json, sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from saintess_engine import package as P\n"
        f"info = P.load({pkg_dir!r})\n"
        "from saintess_engine.battle.effects import ACTION_HANDLERS, action_names\n"
        "import saintess_engine.config as C\n"
        "print('__R__' + json.dumps({"
        "'ok': info['ok'], 'style': info['import_style'], 'installed': info['installed'],"
        "'errors': [e[:120] for e in info['errors']], 'actions': action_names(),"
        "'rules': len(C.get_effect_rules() or {}), 'loaded': info['manifest'].get('id')"
        "}, ensure_ascii=False))\n")
    pr = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                        timeout=240, cwd=os.path.dirname(pkg_dir))
    line = ""
    for ln in (pr.stdout or "").splitlines():
        if ln.startswith("__R__"):
            line = ln[5:]
    try:
        return json.loads(line)
    except Exception:                                          # noqa: BLE001
        return {"ok": False, "errors": [(pr.stderr or "")[-300:]], "actions": []}


def main():
    print("== 游戏包加载器门禁（saintess_engine/package.py）==")
    import saintess_engine.package as P        # noqa: PLC0415

    # 1. 正常包（带 content/mech + 相对导入）→ 加载成功、动作注册、规则表挂上
    good = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_good")
    make_pkg(good)
    r = run_probe(good)
    check("① 加载成功（ok=True）", r.get("ok") is True, str(r)[:200])
    check("★ 走的是 `package` 式导入（相对导入可用）", r.get("style") == "package", r.get("style"))
    check("★ 包内 mech 的动作**真的注册进了引擎**",
          "probe_relative_verb" in (r.get("actions") or []), str(r.get("actions"))[-160:])
    check("`load_game_rules` 挂上的规则表非空（装配不只是「没报错」）",
          (r.get("rules") or 0) >= 1, f"rules={r.get('rules')}")
    check("返回里带上清单 id（调用方能确认加载的是哪个包）", r.get("loaded") == "probe", r.get("loaded"))

    # 2. 旧写法包（顶层 import apply、包内不做相对导入）→ 仍要能加载（退回 top-level）
    legacy = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_legacy")
    legacy_apply = (
        "import json, os\n"
        "import saintess_engine.config as config\n"
        "def install_engine():\n"
        "    import saintess_engine.battle.formulas as formulas\n"
        "    config.mount(formulas=formulas)\n"
        "def apply_game_content(actor):\n"
        "    return actor\n")
    make_pkg(legacy, with_mech=False, apply_src=legacy_apply)
    r2 = run_probe(legacy)
    check("② 旧写法（无相对导入）仍能加载，且标出来是 top-level",
          r2.get("ok") is True and r2.get("style") in ("package", "top-level"), str(r2)[:160])

    # 3. 错误路径：都要 ok=False + 可读错误（不抛栈）
    bad_dir = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_nomanifest")
    os.makedirs(os.path.join(bad_dir, "content"), exist_ok=True)
    check("③ 缺 game.json → ok=False 且错误里带路径",
          P.load(bad_dir)["ok"] is False and "game.json" in " ".join(P.load(bad_dir)["errors"]),
          str(P.load(bad_dir)["errors"])[:120])

    noentry = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_noentry")
    make_pkg(noentry, with_entry=False)
    check("④ 声明了 entry 但文件不存在 → ok=False 且说明「声明了就必须有」",
          P.load(noentry)["ok"] is False and "入口不存在" in " ".join(P.load(noentry)["errors"]),
          str(P.load(noentry)["errors"])[:120])

    oldver = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_oldver")
    make_pkg(oldver, manifest={"engine": ">=99.0"})
    check("⑤ 版本不满足 → ok=False（装配半个引擎比不装配更难查）",
          P.load(oldver)["ok"] is False and "不满足" in " ".join(P.load(oldver)["errors"]),
          str(P.load(oldver)["errors"])[:120])

    noinst = os.path.join(tempfile.mkdtemp(prefix="fw_pkgload_"), "probe_noinst")
    make_pkg(noinst, with_mech=False, apply_src="X = 1\n")
    check("⑥ 缺 install_engine() → ok=False 且指出缺的是哪个约定函数",
          P.load(noinst)["ok"] is False and "install_engine" in " ".join(P.load(noinst)["errors"]),
          str(P.load(noinst)["errors"])[:120])

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ·", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
