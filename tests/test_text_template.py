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
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)

from saintess_engine.text import TextSpec, TextTable, extract_params, safe_format  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


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

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
