# -*- coding: utf-8 -*-
"""CommandSpec.visible —— 取值只认 JSON 布尔，字符串 false 不再被 bool() 读成 true。

判据钉**性质**不钉源码形态（审计·批次4 · 台账 L293 第 7 条「静默兜底②」）：
  A 段 黑盒 —— "false" / "0" / "no" / None / 1 / [] 全部点名抛 TypeError
  B 段 合法面 —— 真正的 true/false 与缺键默认值逐字不变（钉「严格 ≠ 见谁都抛」）
  C 段 真实数据 —— 奥兰迪亚真包 commands.json 全量装载零问题（不得误伤生产面）
  D 段 有牙反证 —— 把校验退回 bool() 必报红，且报红点名的正是这批取值
"""
import io, json, os, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from saintess_engine.command import CommandRegistry, CommandSpec

PASS = FAIL = 0


def check(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS  %s" % label)
    else:
        FAIL += 1
        print("FAIL  %s %s" % (label, extra))


def spec(**kw):
    data = {"key": "k", "patterns": ["^探针$"], "desc": "d", "category": "系统", "usage": "u"}
    data.update(kw)
    return CommandSpec.from_dict(data)


# ---------- A 段：黑盒（真正的那条判据） ----------
# 方向一：字符串假值 —— bool() 会读成 True，声明的「不可见」会照常路由。
for raw in ("false", "False", "FALSE", "0", "no", "off", "true", "1", ""):
    try:
        s = spec(visible=raw)
        check(False, "A1 字符串 visible=%r 必须点名抛" % (raw,), "得到 visible=%r" % (s.visible,))
    except TypeError as e:
        msg = str(e)
        check("visible" in msg and "布尔" in msg,
              "A1 字符串 visible=%r 点名抛且说清是布尔" % (raw,), msg)
        check(raw in msg, "A1 字符串 visible=%r 点名里带原值" % (raw,), msg)

# 方向二：非布尔假值 —— bool() 会读成 False，声明的「可见」会静默消失。
for raw in (None, 0, [], {}, "", 0.0):
    try:
        s = spec(visible=raw)
        check(False, "A2 非布尔 visible=%r 必须点名抛" % (raw,), "得到 visible=%r" % (s.visible,))
    except TypeError as e:
        check("visible" in str(e), "A2 非布尔 visible=%r 点名抛" % (raw,), str(e))

# 数字 1/0：JSON 侧 1/0 与 true/false 不是同一个形状，一并点名。
for raw in (1, 0):
    try:
        spec(visible=raw)
        check(False, "A3 数字 visible=%r 必须点名抛" % (raw,))
    except TypeError:
        check(True, "A3 数字 visible=%r 点名抛" % (raw,))

# ---------- B 段：合法面逐字不变（钉「严格 ≠ 见谁都抛」） ----------
check(spec().visible is True, "B1 缺 visible = 默认可见")
check(spec(visible=True).visible is True, "B2 visible=true 逐字不变")
check(spec(visible=False).visible is False, "B3 visible=false 逐字不变")
check(spec(visible=False).to_dict()["visible"] is False, "B4 回写仍是布尔 false")
check("visible" not in spec(visible=True).to_dict(), "B5 可见声明回写不带 visible 键")

# 端到端：非法 visible 必须在**装载期**炸，而不是悄悄进路由。
try:
    CommandRegistry(name="t").load({"坏门": {"patterns": ["^进副本"], "visible": "false",
                                              "category": "系统", "desc": "d", "usage": "u"}})
    check(False, "B6 装载期即点名抛（不得悄悄进路由）")
except TypeError as e:
    check("坏门" not in str(e) and "visible" in str(e),
          "B6 装载期即点名抛", str(e))

# ---------- C 段：真实数据（不得误伤生产面） ----------
_CMDS = os.path.join(_ROOT, "games", "orlandia", "content", "data", "commands.json")
if os.path.exists(_CMDS):
    with io.open(_CMDS, encoding="utf-8") as fh:
        raw = json.load(fh)
    try:
        reg = CommandRegistry(name="orlandia.commands").load(raw)
        probs = reg.validate()
        check(True, "C1 真包 commands.json 全量装载零问题（%d 条声明）" % len(reg.specs()),
              str(probs))
        hidden = [s.key for s in reg.specs() if not s.visible]
        check(bool(hidden) and all(s.visible is False for s in reg.specs() if not s.visible),
              "C2 真包里不可见声明仍是布尔 False（%d 条）" % len(hidden))
    except TypeError as e:
        check(False, "C1 真包 commands.json 装载零问题", str(e))
else:
    check(False, "C0 真包 commands.json 找得到（判据不许在缺数据时恒绿）", _CMDS)

# ---------- D 段：有牙反证（把校验退回 bool() 必报红） ----------
# 真跑一次变异：临时换掉 _flag_of，看这批判据是否真的会因为它变红。
# ★ 变异落在**一次性副本**上，不写本仓（上一轮的教训：真仓变异 + 子进程 = 残留进程
#   轮流覆盖生产码）。这里改的是本进程内的类属性，作用域天然限于本文件。
_real = CommandSpec._flag_of.__func__ if hasattr(CommandSpec._flag_of, "__func__")         else CommandSpec._flag_of
try:
    CommandSpec._flag_of = staticmethod(lambda data, field: bool(data.get(field, True)))
    # 变异后 `spec(visible="false")` **不抛** ⇒ 正是 A1 组要抓的形态（bool("false") 是 True）
    # ⇒ A1 会当场报红。这就是「判据有牙」的含义：它咬的是**行为**，不是源码形态。
    still_silent = False
    try:
        spec(visible="false")
    except TypeError:
        still_silent = False
    else:
        still_silent = True
    check(still_silent, "D1 退回 bool() 后 A1 组当场报红（判据有牙）",
          "变异后竟然仍抛 —— 判据可能没咬到这条")
    # 合法面在变异下必须仍绿 —— 否则说明判据是「见谁都抛」。
    still_ok = (spec().visible is True and spec(visible=True).visible is True
                and spec(visible=False).visible is False)
    check(still_ok, "D2 变异下合法面仍绿（判据不是见谁都抛）")
finally:
    CommandSpec._flag_of = staticmethod(_real)
check(spec(visible=True).visible is True, "D3 还原后合法面复绿")

print("")
print("visible 取值判据：%d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
