#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：文案模板表（saintess_engine.text.template）。

三条不变量：
  1. **渲染安全**：未知占位符**原样保留**、模板语法坏掉也不抛（玩家可见文案不丢）。
  2. **缺失可测**：`missing()`（请求过没定义）/ `unused()`（定义了没请求）双向自检，
     对应「迁移待办」与「死文案」两类问题。
  3. **可拔插**：未装载的表渲染返回 key（或 fallback），**行为零变化**；
     `render_or` 支持渐进迁移（新文案走表、旧的先内联默认串）。
"""
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)

from saintess_engine.text import TextSpec, TextTable, extract_params, safe_format  # noqa: E402
from saintess_engine.text.template import _KeepUnknown  # noqa: E402  L1452 对拍用

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


print("== 文案模板表门禁 ==")

# ---------------------------------------------------------------- 1. 装载
print("\n【1. 装载：三种形态】")
t = TextTable(name="t")
t.load({
    "hit": "命中 {n} 点",
    "miss_you": {"value": "你受到 {n} 点伤害", "desc": "受击", "category": "战斗"},
    "plain": "纯文本",
})
check("装载 3 条", len(t) == 3, len(t))
check("简写形态（key→模板）", t.get("hit") == "命中 {n} 点")
check("dict 形态带 desc/category", t.spec("miss_you").category == "战斗")
check("list 形态", len(TextTable.from_data([{"key": "a", "value": "A"},
                                            {"key": "b", "value": "B"}])) == 2)
check("by_category 分组", list(t.by_category()) == ["", "战斗"], list(t.by_category()))
try:
    t.register(TextSpec(key="hit", value="X"))
    check("同 key 重复 → 抛错", False, "没抛")
except ValueError:
    check("同 key 重复 → 抛错", True)

# ---------------------------------------------------------------- 2. 渲染
print("\n【2. 渲染：插槽 / 未知槽保留 / 容错】")
check("正常渲染", t.render("hit", n=5) == "命中 5 点", t.render("hit", n=5))
check("未知占位符原样保留（不抛）",
      t.render("miss_you", m=1) == "你受到 {n} 点伤害", t.render("miss_you", m=1))
check("多余槽无害", t.render("hit", n=1, extra="x") == "命中 1 点")
check("渲染后 key 记为已请求", "hit" in t.keys())
check("render_or：表里有 → 用表值", t.render_or("hit", "备用 {n}", n=2) == "命中 2 点")
check("render_or：表里没有 → 用调用方默认串（渐进迁移）",
      t.render_or("brand_new", "新文案 {a}", a=9) == "新文案 9")
check("render_or 未命中仍记账（进 missing）", "brand_new" in t.missing())

check("safe_format：无占位符原样", safe_format("无需插值") == "无需插值")
check("safe_format：坏模板不抛（原样返回）", safe_format("{unclosed", {"x": 1}) == "{unclosed")
check("safe_format：None slots 原样返回", safe_format("a {b}") == "a {b}")
check("safe_format：未知槽保留", safe_format("{a}-{b}", {"a": 1}) == "1-{b}")
check("safe_format：带格式说明的未知槽不抛", isinstance(safe_format("{x:>5}", {"y": 1}), str))

# ---- L1452：`safe_format` 的第二支是恒不可达死分支（已删）
# 对拍判据：**两支的可达性必须完全一致** —— 只有在「format_map 失败但 format 能成功」
# 这种格子上，第二支才可能改变输出；枚举常见形态逐格判定，若将来 str.format 的失败集合
# 真的分叉了（例如某种占位符只在 format_map 下失败），本条会**立刻报红**并点名。
def _fmt_map(tpl, slots):
    try:
        return tpl.format_map(_KeepUnknown(dict(slots)))
    except Exception:
        return None


def _fmt_star(tpl, slots):
    try:
        return tpl.format(**dict(slots))
    except Exception:
        return None


_TPLS = [
    "{name}", "{}", "{0}", "{name} {age}", 
    "{name!r}", "{name:>5}", "{name:d}", "{a[b]}", "{a.b}",
    "{{esc}}", "{missing}", "{missing:d}", "{missing.attr}", "{name:>{width}}",
    "{name:{width}.2f}", "{a[0]}", "{a[0][1]}", "{}{}", "{name!s:>10}", "{a}",
    "{ }", "{:>3}", "{name:x}", "{name:,.2f}", "{unclosed",
]
_VALS = ["v", "", 0, 1, 3.5, None, True, [1, 2], {"a": 1}, (1, 2)]
_diverge = []
_pairs = 0
for _t in _TPLS:
    for _k in (None, "name", "a", "missing", "0", "width", " "):
        for _v in _VALS:
            _s = {} if _k is None else {_k: _v}
            _r1 = _fmt_map(_t, _s)
            _r2 = _fmt_star(_t, _s)
            _pairs += 1
            if _r1 is None and _r2 is not None:
                _diverge.append((_t, dict(_s)))
check("L1452：format_map 失败但 format 成功 = 0 组（删掉的死分支确实恒不可达）",
      len(_diverge) == 0, _diverge[:3])
check("L1452：对拍样本非空（避免判据空转恒绿）", _pairs > 1000, _pairs)
check("safe_format：坏模板仍原样返回（删死分支后唯一退路未丢语义）",
      safe_format("{name:d}", {"name": "abc"}) == "{name:d}")
check("safe_format：未知槽仍保留字面量（活路径未受影响）",
      safe_format("{name}-{miss}", {"name": "A"}) == "A-{miss}")
check("extract_params：去重保序 + 跳过转义",
      extract_params("{a} {b} {a} {{lit}}") == ("a", "b"),
      extract_params("{a} {b} {a} {{lit}}"))
check("extract_params：属性/下标取根名",
      extract_params("{m.atk} {l[0]}") == ("m", "l"), extract_params("{m.atk} {l[0]}"))

# ---------------------------------------------------------------- 3. 缺失行为
print("\n【3. 缺失 key 的四种行为（可拔插语义）】")
zero = TextTable()
check("空表：渲染返回 key 本身（零变化）", zero.render("some.key") == "some.key")
fb = TextTable(fallback="（暂无文案）{x}")
check("fallback 串：渲染兜底文案", fb.render("nope", x=1) == "（暂无文案）1", fb.render("nope", x=1))
got = {}
om = TextTable(on_miss=lambda k, s: got.setdefault("k", k) and "回调兜底")
check("on_miss 回调优先级高于 fallback", om.render("nope") == "回调兜底", om.render("nope"))
check("on_miss 收到 key", got.get("k") == "nope", got)
strict = TextTable(strict=True)
try:
    strict.render("nope")
    check("strict：缺失 → 抛 KeyError（CI 用）", False, "没抛")
except KeyError:
    check("strict：缺失 → 抛 KeyError（CI 用）", True)
check("strict 命中时不抛", TextTable({"a": "A"}, strict=True).render("a") == "A")

# ---------------------------------------------------------------- 4. 自检
print("\n【4. 自检：missing / unused / validate / audit】")
au = TextTable({"used": "U{x}", "never": "N"})
au.render("used", x=1)
au.render("ghost", x=1)
check("missing 记录请求过未定义", au.missing() == ("ghost",), au.missing())
check("unused 记录定义过没请求", au.unused() == ("never",), au.unused())
check("audit 汇总", au.audit()["total"] == 2 and au.audit()["missing"] == ["ghost"])

bad = TextTable({"empty": {"value": ""},
                 "badre": {"value": "{unclosed"},
                 "mismatch": {"value": "{a}", "params": ["a", "b"]},
                 "extra": {"value": "{a} {z}", "params": ["a"]}})
probs = bad.validate()
check("报告「模板为空」", any("empty" in p and "为空" in p for p in probs), probs)
check("报告「语法非法」", any("badre" in p and "非法" in p for p in probs), probs)
check("报告「声明了模板没有的占位符」", any("mismatch" in p and "没有" in p for p in probs), probs)
check("报告「用了未声明的占位符」", any("extra" in p and "未声明" in p for p in probs), probs)
check("正常表 validate 为空", TextTable({"ok": "A {x}"}).validate() == [])

# ---------------------------------------------------------------- 5. 回写 / 统计
print("\n【5. 回写与统计】")
orig = TextTable({"a": "A {x}", "b": {"value": "B", "desc": "说明", "category": "类"}})
rt = TextTable.from_data(orig.to_data())
check("to_data → 重载 round-trip 稳定",
      rt.get("a") == "A {x}" and rt.spec("b").desc == "说明" and rt.spec("b").category == "类")
check("to_data 自动补 params", "params" in orig.to_data()[0], orig.to_data()[0])
st = TextTable({"a": "A"})
st.render("a")
st.render("zzz")
st.reset_stats()
check("reset_stats 清空记账（长驻进程按轮统计）",
      st.missing() == () and st.unused() == ("a",))

# ---------------------------------------------------------------- 6. 可拔插
print("\n【6. 可拔插：不装载 = 零行为】")
check("空表：render 返回 key（调用方零改动可用）", TextTable().render("k") == "k")
check("空表：validate / audit 空",
      TextTable().validate() == [] and TextTable().audit()["total"] == 0)
check("模块导入本身无副作用（无全局单例被自动装载）", TextTable().missing() == ())


# ====================================================================== 审计 L2296
# `on_miss` 是**唯一**的缺 key 诊断通道；原 `except: pass` 在回调抛错时静默降级，
# 玩家照样看到 key 本身而唯一能说清缘由的日志一条不留。
# 判据钉**性质**（有诊断 / 行为不变），不钉源码形态 —— 把 except 删掉同样能过这组。
def _l2296_capture():
    """装一个会记到 logging 上的处理器，返回 (记录列表, 还原函数)。"""
    recs = []

    class _H(logging.Handler):
        def emit(self, record):
            recs.append(record)

    h = _H(level=logging.DEBUG)
    lg = logging.getLogger("saintess_engine.text.template")
    lg.addHandler(h)
    old_level, old_prop = lg.level, lg.propagate
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    return recs, lambda: (lg.removeHandler(h), lg.setLevel(old_level),
                          setattr(lg, "propagate", old_prop))


def _l2296_boom(key, slots):
    raise RuntimeError("宿主日志通道炸了（探针）")


# ① 回调抛错 ⇒ 必须留下诊断（异常级 + 栈），这是本条的核心不变式
_recs, _restore = _l2296_capture()
try:
    _t = TextTable({}, name="l2296-boom", on_miss=_l2296_boom)
    _out = _t.render("L2296_MISSING", n=1)
finally:
    _restore()
_errs = [r for r in _recs if r.levelno >= logging.ERROR and r.exc_info]
check("L2296：on_miss 抛错 ⇒ 留下带栈的 ERROR 诊断（不再静默吞掉）",
      len(_errs) >= 1, "ERROR+exc_info=%d / 全部记录 %d" % (len(_errs), len(_recs)))

# ② 诊断必须点名「是哪个 key / 哪张表」，否则运维拿到一行日志查不下去
_msgs = " ".join(r.getMessage() for r in _errs)
check("L2296：诊断点名缺 key 与表名（可定位）",
      "L2296_MISSING" in _msgs and "l2296-boom" in _msgs, _msgs[:120])

# ③ ★ 守住「记诊断**而不抛**」这半边：玩家可见文案不因日志句柄故障而整条消失。
#    反向护栏 —— 若有人改成直接 raise，这一格会红（提醒他同时改这一条口径）。
_recs2, _restore2 = _l2296_capture()
try:
    _t2 = TextTable({}, name="l2296-boom2", on_miss=_l2296_boom)
    _out2 = _t2.render("L2296_MISSING2")
    _no_raise = True
except Exception as _e:                                          # noqa: BLE001
    _out2, _no_raise = repr(_e), False
finally:
    _restore2()
check("L2296：回调炸了仍回落出文案（不抛，玩家面不空）",
      _no_raise and _out2 == "L2296_MISSING2", "raised=%s out=%r" % (not _no_raise, _out2))

# ④ 回落语义与改前逐字节相同：走 fallback 那一格（回调没给出替代文案 ⇒ got=None）
_t3 = TextTable({"A": "甲{tag}"}, name="l2296-fb", fallback="缺：{tag}", on_miss=_l2296_boom)
_recs3, _restore3 = _l2296_capture()
try:
    _out3 = _t3.render("L2296_NO_SUCH", tag="剑")
finally:
    _restore3()
check("L2296：回调炸时 fallback 串照常渲染（既有兜底未丢）",
      _out3 == "缺：剑", _out3)

# ⑤ ★ 不许把「回调正常」也打成异常级 —— 正常协议是「回调返回 None ⇒ 走兜底」，
#    那是**约定**不是故障。若有人把 except 删在 try 外面并误报，这格会红。
_recs4, _restore4 = _l2296_capture()
try:
    _t4 = TextTable({"A": "甲"}, name="l2296-ok", fallback="F", on_miss=lambda k, s: None)
    _out4 = _t4.render("L2296_NOT_DEFINED")
finally:
    _restore4()
check("L2296：回调返回 None（合法协议）不产生任何诊断",
      not [r for r in _recs4 if r.levelno >= logging.ERROR] and _out4 == "F",
      "err=%d out=%r" % (len([r for r in _recs4 if r.levelno >= logging.ERROR]), _out4))

# ⑥ 反证锚点（防空转恒绿）：本组引用的异常类名必须真的出现在探针里
check("L2296：探针自锚点非空（避免判据空转恒绿）",
      bool(_errs) and "l2296-boom" in _msgs, "errs=%d" % len(_errs))

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
