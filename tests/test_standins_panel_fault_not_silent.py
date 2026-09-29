# -*- coding: utf-8 -*-
"""门禁：StandIns 的 final_stats 面板故障不许被压成空 dict（审计晚到批 · 引擎面）。

★ 判据按 AST 取「真的语句」，不用文本 grep —— 否则注释里引用的旧写法会造成假红
  （上一版 E1 就是被我自己写的注释文本打红的）。
"""
import ast, io, os, sys

ROOT = r"C:/Users/yuyu/framework-engine"
sys.path.insert(0, ROOT)
from saintess_engine import config
from saintess_engine.config import EngineNotConfigured
from saintess_engine.host.outcome import StandIns

PASS, FAIL, FAILS = [], [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        FAILS.append(name + (" | " + str(extra) if extra else ""))


class Pkg:
    domains = ()


class Host:
    seed = 7

    def clock(self):
        return 1.0


def mk(**player):
    p = {"uid": "u1", "class_name": "战士", "level": 3}
    p.update(player)
    return StandIns(Pkg(), Host(), p)


def boom(*a, **k):
    raise ValueError("panel 形状不对")


def good(*a, **k):
    return {"max_hp": 100, "atk": 12}


def _thrown(fn):
    try:
        return None, fn()
    except BaseException as exc:
        return exc, None


# ---- ① 正常档逐字节不变 -------------------------------------------------
config.set_hook("panel_fn", good)
si = mk()
check("A1 正常档 final_stats 原样交付", si["final_stats"] == {"max_hp": 100, "atk": 12}, si["final_stats"])
check("A2 正常档键真实存在（不是 __missing__）", "final_stats" in si)

# ---- ② 面板真故障 → fail-closed 抛，不再是空 dict ----------------------
config.set_hook("panel_fn", boom)
exc, got = _thrown(lambda: mk()["final_stats"])
check("B1 面板炸了必须抛（不得静默给值）", exc is not None, "静默给了 %r" % (got,))
check("B2 抛的是 EngineNotConfigured", isinstance(exc, EngineNotConfigured), type(exc).__name__)
check("B3 异常链保留原异常（from exc，不吞因）",
      isinstance(getattr(exc, "__cause__", None), ValueError), repr(getattr(exc, "__cause__", None)))
check("B4 报错文案点名接面 final_stats", "final_stats" in str(exc), str(exc))
check("B5 报错文案说清为何不给空表", "空表" in str(exc), str(exc))

# ---- ③ 缺 hook 仍是合法：走 __missing__ 的 None（这一支不许被牵连） -----
_saved = config.get_hook("panel_fn")
config.set_hook("panel_fn", None)
exc, got = _thrown(lambda: mk()["final_stats"])
check("C1 没配 panel_fn 时不抛（合法中性值）", exc is None, repr(exc))
check("C2 没配 panel_fn 时 final_stats 为 None", got is None, repr(got))
config.set_hook("panel_fn", _saved)

# ---- ④ 四种「形状类」坏形状逐个都包成同一条 fail-closed ---------------
for maker, label in (
    (lambda: (_ for _ in ()).throw(KeyError("class_name")), "KeyError"),
    (lambda: (_ for _ in ()).throw(AttributeError("x")), "AttributeError"),
    (lambda: (_ for _ in ()).throw(TypeError("x")), "TypeError"),
    (lambda: (_ for _ in ()).throw(IndexError("x")), "IndexError"),
):
    config.set_hook("panel_fn", maker)
    exc, got = _thrown(lambda: mk()["final_stats"])
    check("D %s 包成同一条 fail-closed" % label, isinstance(exc, EngineNotConfigured),
          "%s / 静默给了 %r" % (type(exc).__name__, got))

# ---- ⑤ 非「形状类」故障：不被吞掉也不被包错，原样向上（零静默） -------
def boom_zero(*a, **k):
    return 1 / 0


config.set_hook("panel_fn", boom_zero)
exc, got = _thrown(lambda: mk()["final_stats"])
check("E1 公式自身算错（ZeroDivisionError）也不被静默成空表",
      exc is not None and not isinstance(exc, EngineNotConfigured), "%s / %r" % (type(exc).__name__, got))
config.set_hook("panel_fn", good)

# ---- ⑥ 源码面（AST）：except 体里不许再给 final_stats 赋空 dict ---------
src = io.open(os.path.join(ROOT, "saintess_engine/host/outcome.py"), encoding="utf-8").read()
tree = ast.parse(src)
bad_assign, wide = [], []
for node in ast.walk(tree):
    if not isinstance(node, ast.ExceptHandler):
        continue
    ty = ast.unparse(node.type) if node.type else "bare"
    if ty in ("Exception", "BaseException"):
        wide.append((node.lineno, ty))
    for st in ast.walk(node):
        if isinstance(st, ast.Assign):
            for tg in st.targets:
                if ast.unparse(tg) == "self['final_stats']" or ast.unparse(tg) == 'self["final_stats"]':
                    bad_assign.append((st.lineno, ast.unparse(st.value)))
check("F1 except 分支里不再给 final_stats 赋任何兜底值", not bad_assign, bad_assign)
check("F2 except 分支只收窄到形状类异常（不吞宽异常）", not wide, wide)

for n in PASS:
    print("  PASS %s" % n)
for n in FAILS:
    print("  FAIL %s" % n)
print("PASS %d FAIL %d" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
