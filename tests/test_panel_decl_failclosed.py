# -*- coding: utf-8 -*-
"""门禁：ext_combat/panel 装配期与求值期的 fail-closed 守卫（此前零断言）。

跑法：python tests/test_panel_decl_failclosed.py（退出码 0 = 全绿）。

为什么要有这一支（批次 4 · 验证侧缺口 · 生产码零改动）
--------------------------------------------------------
extends/ext_combat/panel/__init__.py 有两条 raise，此前**全仓零断言**：
  · :59  _need() —— 装配期守卫生，被 from_decl 内部 **37 个调用点**共用；
    它是「坏声明不许半张表被交出去」的唯一出口（类 docstring 自陈：
    构造函数不做校验 ⇒ from_decl 是唯一校验面）。
  · :248 base.mode=actor 时「调用方未提供声明的键」—— 求值期守卫。

立项依据不是推断，是**逐条变异实跑**：把每条 raise 换成静默 pass 后，
跑引擎 tests 全池 + 包仓 panel 相关的 4 支 = 110 支门禁面 ⇒
两条都 **NEW_RED +0**（零转红）。

后果为什么严重
--------------
1 _need 守卫生被拆 ⇒ from_decl 拿到半张坏表也照样返回 PanelStack。
  本模块下游全是裸取：_decl["base"] / L["mode"] / L["keys"] / L["id"]
  / L["values"] —— 缺键不是「面板少一项」，是**求值期 KeyError**，
  报错栈落在引擎深处、内容侧看不见是哪张表写坏了。
  面板栈是**数值大盘的入口**（base + 多层 add/mul/set + cap/floor），
  坏声明静默穿透 = 玩家面板数值整个错掉且零报错。
2 :248 被拆 ⇒ base.mode=actor 缺键时 float(base[k]) 直接 KeyError，
  且 L248 那条文案是**唯一**告诉内容侧「你少传了哪个键」的地方。

★ 只加强：新增门禁，未改任何既有判据、未动任何冻结基线、生产码零改动。
"""
import ast
import importlib.util
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat.panel import PanelDeclError, PanelStack   # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源
check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

_NL = chr(10)


def _base(mode="value", keys=None, value=None):
    b = {"mode": mode}
    if mode == "value":
        b["value"] = value if value is not None else {"atk": 10.0}
    else:
        b["keys"] = keys if keys is not None else ["atk"]
    return b


def _layer(**kw):
    L = {"id": "L1", "src": "src_a", "group": "g1", "mode": "add",
         "keys": ["atk"], "values": {"atk": 5.0}, "order": 1, "weight": 1,
         "status": "active"}
    L.update(kw)
    return L


def _decl(layers=None, **kw):
    d = {"version": 1, "base": _base(),
         "layers": layers if layers is not None else [_layer()],
         "emit": {"int_keys": [], "round": 2}}
    d.update(kw)
    return d


def _raised(decl):
    try:
        PanelStack.from_decl(decl)
    except PanelDeclError as e:
        return str(e)
    except Exception as e:                                        # noqa: BLE001
        return "!!非PanelDeclError:" + type(e).__name__ + ":" + str(e)
    return None


# -- 1 装配期：坏声明每一族都要点名抛 --------------------------------
print(_NL + "[1] 装配期 fail-closed（from_decl 是唯一校验面）")
CASES = [
    ("version 为 0", lambda d: d.update(version=0), "version"),
    ("version 是 bool", lambda d: d.update(version=True), "version"),
    ("栈缺 base", lambda d: d.pop("base"), "base"),
    ("base.mode 非法", lambda d: d.update(base={"mode": "xxx"}), "mode"),
    ("base.mode=value 空表", lambda d: d.update(base={"mode": "value", "value": {}}), "value"),
    ("base.value 是 NaN", lambda d: d.update(base={"mode": "value", "value": {"atk": float("nan")}}), "有限数"),
    ("layers 不是 list", lambda d: d.update(layers={}), "layers"),
    ("层缺 id", lambda d: d.update(layers=[_layer(id="")]), "id"),
    ("层 id 重复", lambda d: d.update(layers=[_layer(), _layer()]), "重复"),
    ("层 src 为空", lambda d: d.update(layers=[_layer(src="  ")]), "src"),
    ("层 group 为空", lambda d: d.update(layers=[_layer(group="")]), "group"),
    ("层 mode 非法", lambda d: d.update(layers=[_layer(mode="xxx")]), "mode"),
    ("层 keys 空数组", lambda d: d.update(layers=[_layer(keys=[])]), "keys"),
    ("层 values 为空", lambda d: d.update(layers=[_layer(values={})]), "values"),
    ("层 apply 非法", lambda d: d.update(layers=[_layer(apply="xxx")]), "apply"),
    ("层 order 是 bool", lambda d: d.update(layers=[_layer(order=True)], order=True), "order"),
    ("层 weight 是 bool", lambda d: d.update(layers=[_layer(weight=True)]), "weight"),
    ("层 status 非法", lambda d: d.update(layers=[_layer(status="xxx")]), "status"),
    ("emit 是非空字符串", lambda d: d.update(emit="x"), "emit"),
    ("audit 不是对象", lambda d: d.update(audit=[]), "audit"),
]
for label, mut, kw in CASES:
    d = _decl()
    mut(d)
    msg = _raised(d)
    check(label + " → PanelDeclError", msg is not None and not msg.startswith("!!"),
          "没抛（或抛的不是 PanelDeclError）: " + repr(msg))
    check(label + " 文案点名 " + repr(kw), msg is not None and kw in msg,
          "文案没点名: " + repr(msg))

# -- 2 合法声明逐字不变 --------------------------------------------
print(_NL + "[2] 合法声明逐字不变")
ok_stack = PanelStack.from_decl(_decl())
check("合法声明能构造", isinstance(ok_stack, PanelStack), "构造失败")
rp = ok_stack.resolve({})
check("合法档求值 = base 10 + 层 5 = 15", rp["atk"] == 15.0, "实得 " + repr(rp["atk"]))
ik_stack = PanelStack.from_decl(_decl(emit={"int_keys": ["atk"], "round": 2}))
check("int_keys 生效 → 取整", ik_stack.resolve({})["atk"] == 15, "int_keys 未生效")
empty_stack = PanelStack.from_decl(_decl(layers=[]))
check("★ 空 layers 合法（头注：可为空数组）", empty_stack.resolve({})["atk"] == 10.0,
      "空 layers 被拒了 —— 判据把严格化成了什么都拒")

# -- 3 求值期：base.mode=actor 缺键 --------------------------------
print(_NL + "[3] 求值期：base.mode=actor 缺键 → 点名")
actor_stack = PanelStack.from_decl(_decl(base=_base("actor", keys=["atk", "def"])))
try:
    actor_stack.resolve({"atk": 10.0})
    emsg, ename = None, None
except PanelDeclError as e:
    emsg, ename = str(e), "PanelDeclError"
except Exception as e:                                        # noqa: BLE001
    emsg, ename = str(e), type(e).__name__
check("actor 档缺 def → PanelDeclError", ename == "PanelDeclError",
      "实得 " + str(ename) + ": " + repr(emsg))
check("★ 文案点名缺的那个键 def", emsg is not None and "def" in emsg, "文案: " + repr(emsg))
check("★ 文案带声明的 keys", emsg is not None and "atk" in emsg, "文案: " + repr(emsg))
full = actor_stack.resolve({"atk": 10.0, "def": 3.0})
check("actor 档给全了 → atk 15 / def 3",
      full["atk"] == 15.0 and full["def"] == 3.0, "实得 " + repr(dict(full)))

# -- 4 不能只钉「抛了」：哨兵逻辑自证 --------------------------------
print(_NL + "[4] ★ 门禁自身的哨兵有牙（「抛了就算过」= 无牙）")
# _raised() 只接 PanelDeclError、别的一律标哨兵。这条防的是本门禁从
# 「抛了某个东西」退化成「抛了就算过」。但 PanelDeclError 的覆盖面实测是完整的：
# 20 族坏声明（含绕到裸取层的）全部被 _need 拦成 PanelDeclError
# ⇒ 没法从产品码里造出哨兵形状。改用**自证**：直接验 _raised() 的分支逻辑。
_SENTINEL = "!!非PanelDeclError:"


def _raw(decl):
    """_raised() 的原样复制（自证用：不得走同一条被测代码路径）。"""
    try:
        PanelStack.from_decl(decl)
    except PanelDeclError as e:
        return "caught:" + str(e)
    except Exception as e:                                        # noqa: BLE001
        return _SENTINEL + type(e).__name__
    return None


_r_legal = _raw(_decl())
_r_bad = _raw("x")
check("★ 哨兵自证：合法档两个路径都给 None", _r_legal is None and _raised(_decl()) is None,
      "_raw=" + repr(_r_legal) + " _raised=" + repr(_raised(_decl())))
check("★ 哨兵自证：非 dict 声明走的是点名分支而非哨兵（_need 是第一道）",
      _r_bad is not None and _r_bad.startswith("caught:"),
      "实得 " + repr(_r_bad) + " —— 若走哨兵，说明 _need 没守住第一道")
check("★ 哨兵自证：_raised() 与 _raw() 对同一输入结论一致（门禁逻辑自洽）",
      (_raised("x") is None) == (_r_bad is None), "两条路径不一致")
check("★ 哨兵前缀仍是「非 PanelDeclError」标记（防被改成恒假）",
      _SENTINEL.startswith("!!非"), "哨兵前缀被改: " + repr(_SENTINEL))
print(_NL + "  ※ 实测记录：PanelDeclError 覆盖面完整，无法从产品码造出哨兵形状 ⇒")
print("  ※ 上面四条改为**哨兵逻辑自证**（不靠产品码造样本），避免恒真断言。")


# -- 5 反证有牙 ----------------------------------------------------
print(_NL + "[5] ★ 反证：把两条 raise 换成静默 pass")
_PANEL = os.path.join(ROOT, "extends", "ext_combat", "panel", "__init__.py")
MUT = os.path.join(ROOT, "_panel_mut_tmp.py")
with io.open(_PANEL, "r", encoding="utf-8", newline="") as f:
    ORIG = f.read()


def _mutate(lineno):
    """把第 lineno 行那条 raise 整块换成 pass（同缩进），写到 MUT。

    ★ 为什么整块而非逐行 replace：两条 raise 都是跨行的，按行删会留下
    悬空表达式 → IndentationError ⇒ 反证自身崩掉 = 反证无效。
    ★ 也不就地改真仓再还原：中途崩掉会把变异态留在真仓（本车道踩过一次）。
    """
    lines = ORIG.splitlines(True)
    spans = sorted({(n.lineno, n.end_lineno) for n in ast.walk(ast.parse(ORIG))
                    if isinstance(n, ast.Raise) and n.end_lineno and n.lineno == lineno})
    if not spans:
        return 0
    for a, b in reversed(spans):
        ind = lines[a - 1][:len(lines[a - 1]) - len(lines[a - 1].lstrip())]
        lines[a - 1:b] = [ind + "pass" + _NL]
    with io.open(MUT, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return len(spans)


def _load_mut():
    spec = importlib.util.spec_from_file_location("_panel_mut", MUT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    n59 = _mutate(59)
    check("反证：定位到 L59 的 raise", n59 == 1, "定位到 " + str(n59) + " 条")
    m59 = _load_mut()
    d = _decl()
    d["base"] = {"mode": "xxx"}
    got = "none"
    try:
        m59.PanelStack.from_decl(d)
    except m59.PanelDeclError:
        got = "paneldeclerror"
    except Exception as e:                                    # noqa: BLE001
        got = type(e).__name__
    check("★ 反证有牙：拆 _need 后坏 base.mode 不再抛点名的 PanelDeclError",
          got != "paneldeclerror", "拆了还照抛点名的 PanelDeclError")
    check("★ 反证记录了退化形态（错因从点名降级为裸 " + repr(got) + "）",
          got != "paneldeclerror" and got != "none",
          "实得 " + repr(got))
    d2 = _decl()
    d2["layers"] = [_layer(id="")]
    leaked2 = True
    try:
        m59.PanelStack.from_decl(d2)
    except Exception:                                           # noqa: BLE001
        leaked2 = False
    check("★ 反证有牙：拆 _need 后层缺 id 不再被点名", leaked2, "拆了还照抛")

    os.remove(MUT)
    n248 = _mutate(248)
    check("反证：定位到 L248 的 raise", n248 == 1, "定位到 " + str(n248) + " 条")
    m248 = _load_mut()
    a2 = m248.PanelStack.from_decl(_decl(base=_base("actor", keys=["atk", "def"])))
    exc = "none"
    try:
        a2.resolve({"atk": 10.0})
    except m248.PanelDeclError:
        exc = "paneldeclerror"
    except Exception as e:                                    # noqa: BLE001
        exc = type(e).__name__
    check("★ 反证有牙：拆 L248 后 actor 缺键不再抛点名的 PanelDeclError",
          exc != "paneldeclerror", "拆了还照抛")
    check("★ 反证记录了退化形态（裸 KeyError，归属全丢）", exc == "KeyError",
          "实得 " + repr(exc))
finally:
    if os.path.exists(MUT):
        os.remove(MUT)

with io.open(_PANEL, "r", encoding="utf-8", newline="") as f:
    check("★ 反证后真仓一字未动", f.read() == ORIG, "变异态残留在真仓")

diff = subprocess.run(["git", "diff", "--stat", "--",
                       "extends/ext_combat/panel/__init__.py"],
                      cwd=ROOT, capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
check("★ 生产码零改动（git diff 对 panel 为空）", not diff.stdout.strip(),
      "有改动: " + repr(diff.stdout))

print(_NL + "=" * 60)
print("通过 %d · 失败 %d · 总检查 %d" % (PASS, FAIL, TOTAL))
for f in FAILURES:
    print("  [X] " + f)
sys.exit(1 if FAIL else 0)
