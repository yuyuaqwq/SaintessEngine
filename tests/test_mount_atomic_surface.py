# -*- coding: utf-8 -*-
"""`config.mount` 批量挂载必须**事务性**（审计 afix1 第 27 轮）。

★ 起因（黑盒实跑复现，改前）：`mount` 旧写法是逐个 `set_hook`，
  于是一个拼错的名字会把**这一批前面那些合法 hook 留在已装状态**：
  实跑 `mount(action_base_fn=..., pannel_fn=...)` ⇒ 抛 `UnknownHook`，
  而 `action_base_fn` 已装上 ⇒ 注入面停在**半装**的中途状态。
  这正是 `set_hook` 上面那段取证想防的那一类（拼错一个字母 ⇒ 装配看起来成功、
  实则注入面残缺），只是从「整条没装」换成了「装了一半」，且**不留任何痕迹**。

判据只加强零放宽：
  A 段 = 坏名不留半装（黑盒真跑，逐个位置都试）
  B 段 = 坏名仍抛 UnknownHook 且消息点名（fail-closed 契约没被削弱）
  C 段 = 全合法时真装上（正向，证明不是「什么都不装」糊弄过去）
  D 段 = 实现形状：整批校验在**动 _HOOKS 之前**（AST，不靠行号）
  E 段 = 非法路径绝不能把 _HOOKS 改坏（逐键值对拍）
"""
import sys, ast, inspect
import saintess_engine.config as CFG

OK = FAIL = 0
def check(cond, label):
    global OK, FAIL
    if cond:
        OK += 1; print("PASS", label)
    else:
        FAIL += 1; print("FAIL", label)

GOOD = "action_base_fn"

def probe(order):
    """按 order 试挂载，返回 (抛出的异常 or None, **抛错那一刻** GOOD 的值)。

    ★ 好名那一格必须在 except 里读：finally 复原若先跑，A 段就改成量复原后的值，
      恒等于 base ⇒ 「没留下半装」在旧代码上也 PASS = 恒绿废判据。
    """
    base = CFG._HOOKS.get(GOOD)
    CFG._HOOKS[GOOD] = None                    # 归零，让「装上没装上」可辨
    try:
        if order == "bad_first":
            CFG.mount(**{"pannel_fn": object(), GOOD: object()})
        elif order == "bad_last":
            CFG.mount(**{GOOD: object(), "pannel_fn": object()})
        elif order == "two_bad":
            CFG.mount(**{"pannel_fn": object(), "effeсt_rules": object()})
        return None, CFG._HOOKS.get(GOOD)
    except Exception as e:                      # noqa: BLE001
        return e, CFG._HOOKS.get(GOOD)         # ★ 抛错当场读，不等 finally
    finally:
        CFG._HOOKS[GOOD] = base                 # 复原，不污染进程级单例

# ---------- A 坏名不留半装 ----------
for order, name in (("bad_first", "A1 坏名在前"), ("bad_last", "A2 ★ 坏名在后")):
    e, at_raise = probe(order)
    check(e is not None and at_raise is None,
          "%s ⇒ 抛错且好名**未**留下半装" % name)

e, at_raise = probe("two_bad")
check(e is not None and at_raise is None,
      "A3 两个坏名 ⇒ 抛错且好名未留下半装")

# A4 ★ 同一格里再钉一次「抛错那一刻好名是 None」，与 A2 互为咬合点：
#   旧实现（逐个抛）在这一格会读到 object ⇒ 本行红。修复后两格同值。
e, at_raise = probe("bad_last")
check(at_raise is None,
      "A4 ★ 抛错那一刻好名仍是 None（旧实现此处读到 object ⇒ 本行会红）")

# ---------- B 仍抛 UnknownHook 且点名（fail-closed 契约没被削弱） ----------
e, _ = probe("bad_last")
check(type(e).__name__ == "UnknownHook", "B1 仍是 UnknownHook（没有降级成别的）")
check("pannel_fn" in str(e), "B2 消息点名坏名 pannel_fn")
check("panel_fn" in str(e), "B3 消息带纠正建议 panel_fn（同名近形）")

e, _ = probe("bad_first")
check("pannel_fn" in str(e), "B4 坏名在前时也点名同一个名字（整批校验，不是逐个）")

# ---------- C 全合法时真装上（正向） ----------
base = CFG._HOOKS.get(GOOD)
try:
    CFG.mount(**{GOOD: object()})
    check(CFG._HOOKS.get(GOOD) is not None,
          "C1 全合法 ⇒ 真装上（不是「什么都不装」糊弄）")
    check(base is None or base is not CFG._HOOKS.get(GOOD),
          "C2 全合法 ⇒ 旧值被新值覆盖（幂等覆写语义不变）")
finally:
    CFG._HOOKS[GOOD] = base

# ---------- D 实现形状：整批校验在动 _HOOKS 之前 ----------
_t = ast.parse(inspect.getsource(CFG.mount))
_fn = _t.body[0]                     # ★ getsource 拿到的是整个 def，要先取出函数体
assert isinstance(_fn, ast.FunctionDef), "getsource 顶层不是 FunctionDef"
body = [s for s in _fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
first_write = None
first_raise = None
for i, st in enumerate(body):
    for n in ast.walk(st):
        if isinstance(n, ast.Raise) and first_raise is None:
            first_raise = i
        # 写 _HOOKS：Subscript 赋值
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                   and t.value.id == "_HOOKS" and first_write is None:
                    first_write = i
check(first_raise is not None, "D1 mount 体内有 raise（不是靠别的路径抛）")
check(first_write is not None, "D2 mount 体内有直接写 _HOOKS（否则 C 段就无从通过）")
check(first_raise is not None and first_write is not None and first_raise < first_write,
      "D3 ★ raise 出现在写 _HOOKS **之前**（事务性；顺序反了就退化成旧行为）")

# ---------- E 非法路径绝不能把 _HOOKS 改坏 ----------
snapshot = dict(CFG._HOOKS)
try:
    CFG.mount(**{"pannel_fn": object()})
except Exception:                               # noqa: BLE001
    pass
check(CFG._HOOKS == snapshot,
      "E1 只给坏名 ⇒ _HOOKS 逐键全等（没偷偷改任何别的 hook）")

print("RESULT ok=%d fail=%d" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
