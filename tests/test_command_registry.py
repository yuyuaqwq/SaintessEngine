#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：指令声明注册表（saintess_engine.command.registry）。

三条不变量：
  1. **声明即形状**：装载/查询/匹配/派生 都由声明驱动，`{key: 正则}` 派生结果
     单条时**逐字等于**原声明（既有静态表可无痛换成派生）。
  2. **漂移可测**：`audit_handlers()` 两个方向都报（漏登记 / 死声明）——
     它替代「手工镜像表 + 再加一个同步测试」那套做法。
  3. **可拔插**：不装载 = 零行为；空注册表不命中任何文本、不产出任何正则。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)

from saintess_engine.command import CommandRegistry, CommandSpec, combine_patterns  # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


print("== 指令声明注册表门禁 ==")

# ---------------------------------------------------------------- 1. 装载
print("\n【1. 装载：dict / list / 简写三种形态】")
reg = CommandRegistry(name="t")
reg.load({
    "go": r"^go(?:\s+(\w+))?$",
    "look": {"patterns": [r"^look$", r"^l$"], "desc": "看", "category": "移动",
             "guards": ["player"], "order": 1},
    "help": {"pattern": r"^help$"},
    "hidden": {"regex": r"^secret$", "visible": False},
})
check("装载 4 条", len(reg) == 4, len(reg))
check("简写形态（key→正则）解析成 patterns", reg.get("go").patterns == (r"^go(?:\s+(\w+))?$",),
      reg.get("go").patterns)
check("别名键 pattern / regex 都认",
      reg.get("help").pattern == "^help$" and reg.get("hidden").pattern == "^secret$")
check("list 形态装载", len(CommandRegistry.from_data([{"key": "a", "pattern": "^a$"},
                                                     {"key": "b", "pattern": "^b$"}])) == 2)

try:
    reg.register(CommandSpec(key="go", patterns=(r"^x$",)))
    check("同 key 重复 → 抛错（防静默覆盖）", False, "没抛")
except ValueError:
    check("同 key 重复 → 抛错（防静默覆盖）", True)
reg.register(CommandSpec(key="go", patterns=(r"^go2$",)), replace=True)
check("replace=True 可覆盖", reg.get("go").pattern == "^go2$")

# ---------------------------------------------------------------- 2. 查询
print("\n【2. 查询：分类 / 可见性 / 排序】")
reg2 = CommandRegistry.from_data([
    {"key": "b", "pattern": "^b$", "category": "移动", "order": 2},
    {"key": "a", "pattern": "^a$", "category": "移动", "order": 1},
    {"key": "c", "pattern": "^c$", "category": "", "order": 0},
    {"key": "d", "pattern": "^d$", "visible": False},
])
check("by_category 分组", set(reg2.by_category()) == {"移动", ""},
      list(reg2.by_category()))
check("分类内保持注册序", [s.key for s in reg2.by_category()["移动"]] == ["b", "a"])
check("visible 按 order 升序", [s.key for s in reg2.visible()] == ["c", "a", "b"],
      [s.key for s in reg2.visible()])
check("visible 排除 visible=False", "d" not in [s.key for s in reg2.visible()])
check("contains / keys / 迭代", "a" in reg2 and reg2.keys()[1] == "a"
      and [s.key for s in reg2] == ["b", "a", "c", "d"])

# ---------------------------------------------------------------- 3. 匹配
print("\n【3. 匹配：命中全量 / 首条 / 三种模式】")
# 独立表（免受上面 replace 影响）
mreg = CommandRegistry.from_data([
    {"key": "go", "pattern": r"^go(?:\s+(\w+))?$"},
    {"key": "look", "patterns": [r"^look$", r"^l$"]},
])
check("hits 命中全部", [s.key for s in mreg.hits("go north")] == ["go"],
      [s.key for s in mreg.hits("go north")])
check("hit 取首条", mreg.hit("l").key == "look")
check("无命中 → None", mreg.hit("zzz") is None)
check("别名第二条正则也命中", mreg.hit("look").key == "look")

# 三种模式的区别（用无锚点/有锚点两条正则做区分）
mr = CommandRegistry.from_data([{"key": "sub", "pattern": "x"},
                                {"key": "pre", "pattern": "^x"}])
check("search（默认，宿主 filter 语义）：子串命中",
      [s.key for s in mr.hits("axb")] == ["sub"], [s.key for s in mr.hits("axb")])
check("match：需行首，'axb' 两条都不命中", mr.hits("axb", mode="match") == (),
      [s.key for s in mr.hits("axb", mode="match")])
# `re.match` 只锚**行首**：模式 "x" 在 "xyz" 上也命中（第 0 位）→ 两条都算
check("match：'xyz' 两条都命中（均自行首起匹配）",
      [s.key for s in mr.hits("xyz", mode="match")] == ["sub", "pre"],
      [s.key for s in mr.hits("xyz", mode="match")])
check("fullmatch：'xyz' 无满匹配", mr.hits("xyz", mode="fullmatch") == (),
      [s.key for s in mr.hits("xyz", mode="fullmatch")])
check("fullmatch：'x' 两条都满匹配",
      [s.key for s in mr.hits("x", mode="fullmatch")] == ["sub", "pre"],
      [s.key for s in mr.hits("x", mode="fullmatch")])

# 互斥矩阵：一条文本命中 ≥2 条要能查出来
dup = CommandRegistry.from_data([{"key": "p", "pattern": "^foo"},
                                 {"key": "q", "pattern": "^foo bar$"}])
check("互斥矩阵可发现一文本命中多条", len(dup.hits("foo bar")) == 2,
      [s.key for s in dup.hits("foo bar")])

# ---------------------------------------------------------------- 4. 派生
print("\n【4. 派生：正则池 / {key: 正则} 表 / 回写】")
check("patterns 去重保序", CommandRegistry.from_data([
    {"key": "a", "patterns": ["^a$", "^aa$"]},
    {"key": "b", "patterns": ["^aa$"]},
]).patterns() == ("^a$", "^aa$"))
pm = reg.pattern_map()
# 注：go 上面被 replace=True 覆盖成 ^go2$ —— 这里要证明的是「派生逐字保真」
check("pattern_map 单条 → 逐字等于原声明", pm["go"] == "^go2$", pm.get("go"))
check("pattern_map 多条 → 非捕获组交替", pm["look"] == r"(?:^look$)|(?:^l$)", pm.get("look"))
check("combine_patterns 单条原样 / 空 → 空串",
      combine_patterns(["^a$"]) == "^a$" and combine_patterns([]) == ""
      and combine_patterns(["^a$", "^b$"]) == "(?:^a$)|(?:^b$)")
round_trip = CommandRegistry.from_data(reg2.to_data())
check("to_data → 重载 round-trip 稳定（key/可见/排序保真）",
      [s.key for s in round_trip.visible()] == [s.key for s in reg2.visible()]
      and round_trip.get("d").visible is False)

# ---------------------------------------------------------------- 5. 自检
print("\n【5. 自检：validate（声明自身）+ audit_handlers（漂移两向）】")
bad = CommandRegistry.from_data([{"key": "ok", "pattern": "^ok$"},
                                 {"key": "nopat", "pattern": ""},
                                 {"key": "badre", "pattern": "([("}])
probs = bad.validate()
check("报告「未声明正则」", any("nopat" in p and "未声明" in p for p in probs), probs)
check("报告「正则非法」", any("badre" in p and "非法" in p for p in probs), probs)
check("正常表 validate 为空", reg2.validate() == [], reg2.validate())
shared = CommandRegistry.from_data([{"key": "a", "pattern": "^same$"},
                                    {"key": "b", "pattern": "^same$"}])
check("报告「正则被多条共用」（互斥隐患）",
      any("共用" in p for p in shared.validate()), shared.validate())

au = reg2.audit_handlers(["b", "a", "c", "d"])
check("audit：全对齐 → ok", au["ok"] is True, au)
au2 = reg2.audit_handlers(["b", "a", "c", "d", "extra_handler"])
check("audit：有 handler 无声明 → missing_spec", au2["missing_spec"] == ["extra_handler"], au2)
au3 = reg2.audit_handlers(["b", "a"])
check("audit：有声明无 handler → missing_handler",
      au3["missing_handler"] == ["c", "d"] and au3["ok"] is False, au3)

# ---------------------------------------------------------------- 6. 可拔插
print("\n【6. 可拔插：不装载 = 零行为】")
empty = CommandRegistry()
check("空表：不命中任何文本", empty.hit("anything") is None and empty.hits("x") == ())
check("空表：不产出任何正则", empty.patterns() == () and empty.pattern_map() == {})
check("空表：validate / audit 均无告警",
      empty.validate() == [] and empty.audit_handlers([])["ok"] is True)
check("模块导入本身不注册任何东西（无全局副作用）",
      CommandRegistry().patterns() == ())

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
