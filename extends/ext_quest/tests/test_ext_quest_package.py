# -*- coding: utf-8 -*-
"""`ext_quest` 作为**扩展包**被数据包用起来 —— 端到端门禁。

守的是「搬出去之后真的还能用」这一条：一个数据包只要在 `game.json` 里声明
`"depends": ["ext_quest"]`，包栈加载后 `import ext_quest.quest` 就可用；
**没声明**时它不在 `sys.path` 上（扩展包不靠全局副作用泄漏给别人）。

跑法：`python extends/ext_quest/tests/test_ext_quest_package.py`
（或随 `python tests/run_all.py` 一起跑）
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))      # extends/ext_quest/tests
PKG_ROOT = os.path.dirname(_HERE)                       # extends/ext_quest
EXT_BASE = os.path.dirname(PKG_ROOT)                    # extends（扩展包搜索路径）
ROOT = os.path.dirname(EXT_BASE)                        # framework-engine（引擎仓根）
for _p in (ROOT, EXT_BASE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check  # noqa: E402

passed = failed = 0
DETAIL = []
check = bind_check(globals(), "passed", "failed", "DETAIL")

GAME_ENTRY = '''# -*- coding: utf-8 -*-
def install_engine() -> None:
    return None


def apply_game_content(actor):
    return actor
'''


def make_game(root, *, depends):
    os.makedirs(os.path.join(root, "content"), exist_ok=True)
    man = {"id": "probe_game", "name": "探针数据包", "engine": ">=0.1", "entry": "content/apply.py"}
    if depends:
        man["depends"] = list(depends)
    with open(os.path.join(root, "game.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False)
    with open(os.path.join(root, "content", "apply.py"), "w", encoding="utf-8") as f:
        f.write(GAME_ENTRY)
    return root


PROBE = '''
import json, sys
sys.path.insert(0, {root!r})
from saintess_engine.package import load_stack
out = {{}}
try:
    stack = load_stack({game!r}, exts=[{ext!r}])
    out["ids"] = stack.ids
    out["ok"] = True
except Exception as e:
    out["ok"] = False
    out["err"] = "%s: %s" % (type(e).__name__, e)
try:
    from ext_quest.quest import Objective, Objectives, Quest, QuestLog, parse_needs
    out["import"] = "ok"
    out["all"] = sorted([Objective.__name__, Objectives.__name__, Quest.__name__,
                         QuestLog.__name__, parse_needs.__name__])
except Exception as e:
    out["import"] = "%s: %s" % (type(e).__name__, e)
print("__R__" + json.dumps(out, ensure_ascii=False))
'''


def run_probe(game, ext_base=EXT_BASE):
    code = PROBE.format(root=ROOT, game=game, ext=ext_base)
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        timeout=240, cwd=ROOT)
    line = ""
    for ln in (pr.stdout or "").splitlines():
        if ln.startswith("__R__"):
            line = ln[5:]
    try:
        return json.loads(line)
    except Exception:                                          # noqa: BLE001
        return {"ok": False, "err": (pr.stderr or "")[-400:]}


def main():
    print("== ext_quest 作为扩展包：端到端门禁 ==")
    tmp = tempfile.mkdtemp(prefix="fw_extquest_")
    game_on = make_game(os.path.join(tmp, "with_dep"), depends=["ext_quest"])
    game_off = make_game(os.path.join(tmp, "without_dep"), depends=[])

    r = run_probe(game_on)
    check("① 数据包声明 depends 后：包栈加载成功", r.get("ok") is True, str(r)[:300])
    check("② 栈里含扩展包（拓扑序：扩展包在前、数据包在后）",
          r.get("ids") == ["ext_quest", "probe_game"], str(r.get("ids")))
    check("③ 数据包能 import 到本包（命名空间 = 目录名 ext_quest）",
          r.get("import") == "ok", str(r.get("import")))
    check("④ 本包的公开面原样在（搬出引擎没丢东西）",
          r.get("all") == ["Objective", "Objectives", "Quest", "QuestLog", "parse_needs"],
          str(r.get("all")))

    r2 = run_probe(game_off)
    check("⑤ 不声明 depends 时：包栈仍能加载（扩展包是可选件）", r2.get("ok") is True, str(r2)[:200])
    check("⑥ 不声明 depends 时：只剩数据包自己一个", r2.get("ids") == ["probe_game"], str(r2.get("ids")))

    print("\n===== 结果：通过 %d / 共 %d =====" % (passed, passed + failed))
    for f in DETAIL:
        print("  ·", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
